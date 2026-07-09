"""浏览器发布登录态「扫码授权 + 可配有效期」机制测试。

验收铁律(docs/浏览器发布登录态授权设计.md 第 9 章):
  - 过期/未授权号的发布任务永不进死信、永不误发,原地挂起等续扫;
  - 续扫复位 AUTHORIZED 后任务自动恢复;
  - 窗口内(AUTHORIZED/EXPIRING 且未到期)判定为可发。
"""
from datetime import datetime, timedelta

import pytest

from app.core import notifier
from app.core.crypto import current_key_version, encrypt_secret
from app.core.states import WxLoginStatus
from app.models.content import ContentArticle
from app.models.mp_account import MpAccount
from app.models.publish import PublishTask
from app.modules.publish_engine import executor
from app.modules.scheduler import service as sched
from app.modules.wx_gateway.errors import WX_AUTH_EXPIRED, WxApiError
from app.modules.wx_gateway.gateway import login_valid

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset_sink():
    yield
    notifier.set_test_sink(None)


class _StubGateway:
    """真实号不应真正发布:一旦调 publish 即断言失败(证明被过期过滤/前置挡下)。"""

    @staticmethod
    def is_mock(mp):
        return mp.account_type == 3

    async def publish(self, *a, **k):
        raise AssertionError("过期/未授权号不应调用 gateway.publish")

    async def takedown(self, *a, **k):
        raise AssertionError


class _RaiseAuthGateway:
    """模拟发布中途登录态失效:publish 抛 WX_AUTH_EXPIRED。"""

    @staticmethod
    def is_mock(mp):
        return mp.account_type == 3

    async def publish(self, mp, articles, publish_type=1):
        raise WxApiError(WX_AUTH_EXPIRED, "发布中途登录态失效")


async def _seed_real_mp(session_factory, app_id, *, status, expires_in_h=None, ttl=48):
    ver = current_key_version()
    async with session_factory() as db:
        exp = None if expires_in_h is None else datetime.utcnow() + timedelta(hours=expires_in_h)
        acc = MpAccount(
            mp_name="真实订阅号", app_id=app_id,
            app_secret_cipher=encrypt_secret(app_id, "auth-secret-0001", ver),
            key_version=ver, account_type=1, created_by=1,
            wx_login_status=status, wx_login_expires_at=exp,
            wx_login_ttl_hours=ttl,
            wx_login_captured_at=(datetime.utcnow() if exp else None),
        )
        db.add(acc)
        await db.commit()
        return acc.id


async def _seed_task(session_factory, mp_id, *, status="SCHEDULED", errcode=None):
    async with session_factory() as db:
        art = ContentArticle(mp_account_id=mp_id, title="自检", content_html="<p>x</p>",
                             status="APPROVED", created_by=1)
        db.add(art)
        await db.flush()
        t = PublishTask(
            biz_key=f"article:{art.id}", content_article_id=art.id, mp_account_id=mp_id,
            publish_type=1, scheduled_at=datetime.utcnow() - timedelta(minutes=1),
            status=status, created_by=1, last_errcode=errcode,
        )
        db.add(t)
        await db.commit()
        return t.id


def _mk_mp(status, exp):
    m = MpAccount(mp_name="x", app_id="a", app_secret_cipher=b"", account_type=1, created_by=1)
    m.wx_login_status = status
    m.wx_login_expires_at = exp
    return m


async def test_login_valid_pure():
    now = datetime.utcnow()
    assert login_valid(_mk_mp(WxLoginStatus.AUTHORIZED, now + timedelta(hours=1)))
    assert login_valid(_mk_mp(WxLoginStatus.EXPIRING, now + timedelta(hours=1)))  # 临期仍可发
    assert not login_valid(_mk_mp(WxLoginStatus.AUTHORIZED, now - timedelta(hours=1)))  # 时间已过
    assert not login_valid(_mk_mp(WxLoginStatus.EXPIRED, now + timedelta(hours=1)))
    assert not login_valid(_mk_mp(WxLoginStatus.UNAUTHORIZED, None))


async def test_expired_account_task_suspended_not_dead_letter(session_factory):
    """过期真实号:_publish_due 直接跳过,任务原地挂起 SCHEDULED,不 FAILED、不死信。"""
    mp_id = await _seed_real_mp(session_factory, "wxAUTH0000001",
                                status=WxLoginStatus.EXPIRED, expires_in_h=-1)
    tid = await _seed_task(session_factory, mp_id)
    async with session_factory() as db:
        pub, failed = await sched._publish_due(db, _StubGateway(), datetime.utcnow())
        await db.commit()
    assert pub == 0 and failed == 0
    async with session_factory() as db:
        t = await db.get(PublishTask, tid)
        assert t.status == "SCHEDULED"  # 挂起,未动
        assert await sched._dead_letter_alerts(db) == 0  # 绝不进死信


async def test_executor_preguard_holds_scheduled(session_factory):
    """executor 兜底:过期号任务进 execute_publish 也不发,保持 SCHEDULED + 标记 WX_AUTH_EXPIRED。"""
    mp_id = await _seed_real_mp(session_factory, "wxAUTH0000002",
                                status=WxLoginStatus.UNAUTHORIZED, expires_in_h=None)
    tid = await _seed_task(session_factory, mp_id)
    async with session_factory() as db:
        t = await db.get(PublishTask, tid)
        await executor.execute_publish(db, _StubGateway(), t)  # 不应调 publish
        await db.commit()
    async with session_factory() as db:
        t = await db.get(PublishTask, tid)
        assert t.status == "SCHEDULED"
        assert t.last_errcode == WX_AUTH_EXPIRED
        assert t.retry_count == 0  # 不计重试


async def test_midpublish_auth_expiry_no_retry_no_deadletter(session_factory):
    """窗口内起发但中途登录态失效:任务 FAILED 但不排退避、不进死信,号降级 EXPIRED。"""
    mp_id = await _seed_real_mp(session_factory, "wxAUTH0000003",
                                status=WxLoginStatus.AUTHORIZED, expires_in_h=10)
    tid = await _seed_task(session_factory, mp_id)
    async with session_factory() as db:
        t = await db.get(PublishTask, tid)
        await executor.execute_publish(db, _RaiseAuthGateway(), t)
        await db.commit()
    async with session_factory() as db:
        t = await db.get(PublishTask, tid)
        mp = await db.get(MpAccount, mp_id)
        assert t.status == "FAILED"
        assert t.next_retry_at is None       # 不排退避重试
        assert t.retry_count == 0            # 不自增
        assert t.last_errcode == WX_AUTH_EXPIRED
        assert mp.wx_login_status in (WxLoginStatus.EXPIRED, WxLoginStatus.REVOKED)
        assert await sched._dead_letter_alerts(db) == 0


async def test_login_watch_transitions_and_alert_once(session_factory):
    """_login_watch:AUTHORIZED 过期 → EXPIRED 并号级一次告警(重复 tick 不重复告警)。"""
    alerts: list[tuple[str, str]] = []
    notifier.set_test_sink(lambda s, b: alerts.append((s, b)))
    mp_id = await _seed_real_mp(session_factory, "wxAUTH0000004",
                                status=WxLoginStatus.AUTHORIZED, expires_in_h=-1)
    async with session_factory() as db:
        r1 = await sched._login_watch(db, datetime.utcnow())
        await db.commit()
    assert r1["login_transitions"] == 1 and r1["login_alerts"] == 1
    async with session_factory() as db:
        mp = await db.get(MpAccount, mp_id)
        assert mp.wx_login_status == WxLoginStatus.EXPIRED
        r2 = await sched._login_watch(db, datetime.utcnow())  # 再巡检:已告警不重发
        await db.commit()
    assert r2["login_alerts"] == 0
    assert len(alerts) == 1


async def test_reauth_recovers_suspended_task(session_factory):
    """续扫复位 AUTHORIZED 后,_login_watch 把因过期挂起的 FAILED 任务重排回 SCHEDULED。"""
    mp_id = await _seed_real_mp(session_factory, "wxAUTH0000005",
                                status=WxLoginStatus.AUTHORIZED, expires_in_h=10)
    # 一个因登录态过期而 FAILED 的任务(last_errcode=WX_AUTH_EXPIRED,无 next_retry)
    tid = await _seed_task(session_factory, mp_id, status="FAILED", errcode=WX_AUTH_EXPIRED)
    async with session_factory() as db:
        r = await sched._login_watch(db, datetime.utcnow())  # 号在窗口内 → 恢复重排
        await db.commit()
    assert r["login_recovered"] == 1
    async with session_factory() as db:
        t = await db.get(PublishTask, tid)
        assert t.status == "SCHEDULED"
        assert t.last_errcode is None
