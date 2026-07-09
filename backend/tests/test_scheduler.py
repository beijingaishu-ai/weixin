"""M4 调度中心测试:一次 tick 跑通全自动流水线 + 死信告警 + 看板 + 一键下架。"""
import pytest
from sqlalchemy import select

from app.core import notifier
from app.core.crypto import current_key_version, encrypt_secret
from app.models.content import ContentArticle
from app.models.mp_account import MpAccount
from app.models.publish import PublishTask
from app.modules.wx_gateway import mock_channel
from tests.conftest import auth_headers

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset_mock_after():
    yield
    mock_channel.reset_mock_outcomes()
    notifier.set_test_sink(None)


async def _seed_mock_mp(session_factory, app_id, *, need_review=0, name="调度Mock号"):
    ver = current_key_version()
    async with session_factory() as db:
        acc = MpAccount(
            mp_name=name, app_id=app_id,
            app_secret_cipher=encrypt_secret(app_id, "sched-secret-000", ver),
            key_version=ver, account_type=3, need_review=need_review, created_by=1,
        )
        db.add(acc)
        await db.commit()
        return acc.id


async def _mk_source(client, token, *, dataset="tech", whitelist=1, name="调度源"):
    r = await client.post("/api/v1/collect/sources", headers=auth_headers(token), json={
        "source_name": name, "adapter_type": "mock", "config_json": {"dataset": dataset},
        "interval_minutes": 60, "whitelist_confirmed": whitelist,
    })
    assert r.json()["code"] == 0, r.text
    return r.json()["data"]["id"]


async def _mk_rule(client, token, src_id, mp_id, name="调度规则"):
    r = await client.post("/api/v1/mapping/rules", headers=auth_headers(token), json={
        "rule_name": name, "target_mp_account_id": mp_id, "source_ids": [src_id],
        "match_condition_json": {}, "transform_action_json": {"title_template": "【转】{title}"},
        "schedule_policy_json": {}, "priority": 100,
    })
    assert r.json()["code"] == 0, r.text


async def _tick(client, token):
    r = await client.post("/api/v1/scheduler/tick", headers=auth_headers(token))
    assert r.status_code == 200, r.text
    assert r.json()["code"] == 0, r.text
    return r.json()["data"]


async def test_full_auto_pipeline_review_off(client, admin_token, session_factory):
    """审核关(need_review=0):一次 tick 跑通 采集→映射→自动提审(自动过审)→建任务→发表。"""
    mp_id = await _seed_mock_mp(session_factory, "wxSCHED000001", need_review=0)
    src_id = await _mk_source(client, admin_token, dataset="tech", whitelist=1)
    await _mk_rule(client, admin_token, src_id, mp_id)

    data = await _tick(client, admin_token)
    # 采集 5 篇 → 映射产出 5 篇 → 自动提审自动过审 → 建 5 个任务 → 全部发表
    assert data["collected"] == 5, data
    assert data["mapped_transformed"] == 5, data
    assert data["auto_submitted"] == 5, data
    assert data["auto_created_tasks"] == 5, data
    assert data["published"] == 5, data

    # 落库校验:5 个任务 PUBLISHED,对应文章 DRAFT_CREATED
    async with session_factory() as db:
        tasks = (await db.scalars(
            select(PublishTask).where(PublishTask.mp_account_id == mp_id)
        )).all()
        assert len(tasks) == 5
        assert all(t.status == "PUBLISHED" and t.published_url for t in tasks)
        arts = (await db.scalars(
            select(ContentArticle).where(ContentArticle.mp_account_id == mp_id)
        )).all()
        assert all(a.status == "DRAFT_CREATED" for a in arts)


async def test_pipeline_stops_at_review_when_on(client, admin_token, session_factory):
    """审核开(need_review=1):tick 后文章停在 PENDING_REVIEW,不建任务、不发表。"""
    mp_id = await _seed_mock_mp(session_factory, "wxSCHED000002", need_review=1)
    src_id = await _mk_source(client, admin_token, dataset="campus", whitelist=1, name="审核源")
    await _mk_rule(client, admin_token, src_id, mp_id, name="审核规则")

    data = await _tick(client, admin_token)
    assert data["auto_submitted"] >= 1, data
    assert data["auto_created_tasks"] == 0, data  # 停在待审核,不建任务
    assert data["published"] == 0, data

    async with session_factory() as db:
        arts = (await db.scalars(
            select(ContentArticle.status).where(ContentArticle.mp_account_id == mp_id)
        )).all()
    assert any(s == "PENDING_REVIEW" for s in arts), arts


async def test_retry_and_dead_letter_alert(client, admin_token, session_factory):
    """注入发表失败:tick 后任务 FAILED;重试耗尽后死信告警(notifier sink 收到)。"""
    alerts: list[tuple[str, str]] = []
    notifier.set_test_sink(lambda s, b: alerts.append((s, b)))

    mp_id = await _seed_mock_mp(session_factory, "wxSCHED000003", need_review=0)
    # 该号 app_id 注入常规失败
    async with session_factory() as db:
        app_id = await db.scalar(select(MpAccount.app_id).where(MpAccount.id == mp_id))
    mock_channel.set_mock_outcome(app_id, publish_status=3)

    src_id = await _mk_source(client, admin_token, dataset="tech", whitelist=1, name="失败源")
    await _mk_rule(client, admin_token, src_id, mp_id, name="失败规则")

    # 首个 tick:采集→映射→建任务→发表失败(FAILED)
    d1 = await _tick(client, admin_token)
    assert d1["failed"] >= 1, d1

    # 把失败任务的 retry_count 顶到上限、next_retry_at 置到过去,促使死信告警
    from datetime import datetime, timedelta
    async with session_factory() as db:
        tasks = (await db.scalars(
            select(PublishTask).where(PublishTask.mp_account_id == mp_id)
        )).all()
        for t in tasks:
            t.retry_count = t.max_retry
            t.next_retry_at = None
        await db.commit()

    # 再 tick:重试耗尽 → 死信告警
    await _tick(client, admin_token)
    assert alerts, "应触发死信告警"
    assert "死信" in alerts[0][0]


async def test_dashboard_and_takedown(client, admin_token, session_factory):
    """看板聚合 + 一键下架。"""
    mp_id = await _seed_mock_mp(session_factory, "wxSCHED000004", need_review=0)
    src_id = await _mk_source(client, admin_token, dataset="tech", whitelist=1, name="看板源")
    await _mk_rule(client, admin_token, src_id, mp_id, name="看板规则")
    await _tick(client, admin_token)

    dash = (await client.get("/api/v1/scheduler/dashboard", headers=auth_headers(admin_token))).json()["data"]
    assert dash["mp_total"] >= 1
    assert dash["task_by_status"].get("PUBLISHED", 0) >= 1
    assert dash["publish_success_rate"] == 100.0

    # 一键下架一个已发布任务
    async with session_factory() as db:
        tid = await db.scalar(
            select(PublishTask.id).where(PublishTask.mp_account_id == mp_id, PublishTask.status == "PUBLISHED")
        )
    r = await client.post(f"/api/v1/publish/tasks/{tid}/takedown", headers=auth_headers(admin_token))
    assert r.json()["code"] == 0, r.text
    assert r.json()["data"]["last_errmsg"] == "已下架"
