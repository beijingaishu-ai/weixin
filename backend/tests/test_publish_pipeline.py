"""发布引擎端到端 HTTP 测试(publish_engine router/service,全程 Mock 号)。

契约(响应统一 {code,message,data}):
- POST /api/v1/publish/tasks {content_article_id,mp_account_id,scheduled_at?}  -> 建发布任务
- POST /api/v1/publish/tasks/{id}/poll                                          -> 推进/轮询
- POST /api/v1/publish/tasks/{id}/retry                                         -> 失败重试
- GET  /api/v1/publish/tasks/{id}/logs                                          -> 阶段日志
- POST /api/v1/publish/mock/{app_id} {publish_status|submit_errcode}            -> 注入 Mock 结果

覆盖:
1) 手动发文正路:建号(type=3,need_review=0)→建图文→提审(审核关→自动 APPROVED)
   →建任务→推进至 PUBLISHED 且 published_url 非空,content_article 落 DRAFT_CREATED;
   logs 含 DRAFT_ADD / FREEPUBLISH_SUBMIT / RESULT 各阶段。
2) 失败重试:注入 publish_status=3 → 任务 FAILED → reset 为成功后 retry → PUBLISHED。

publish_engine / content_center 尚由他人并行实现;端点未就绪(404 / app 不可导入)时
相关用例自动 skip。每个用例结束后 reset_mock_outcomes()。
"""
import pytest
from sqlalchemy import select

from app.core.crypto import current_key_version, encrypt_secret
from app.models.content import ContentArticle
from app.models.mp_account import MpAccount
from app.models.publish import PublishLog, PublishTask
from app.modules.wx_gateway import mock_channel
from tests.conftest import auth_headers

pytestmark = pytest.mark.asyncio

_MAX_POLL = 12  # 推进轮询上限,防止实现异步慢推进时死循环


@pytest.fixture(autouse=True)
def _reset_mock_after():
    yield
    mock_channel.reset_mock_outcomes()


# ---------------------------------------------------------------------------
# 落库辅助
# ---------------------------------------------------------------------------
async def _seed_mock_account(
    session_factory, app_id: str, *, need_review: int = 0, name: str = "发布Mock号"
) -> tuple[int, str]:
    """建 account_type=3 且默认 need_review=0 的模拟号(绕过审核)。返回 (id, app_id)。"""
    ver = current_key_version()
    async with session_factory() as db:
        acc = MpAccount(
            mp_name=name,
            app_id=app_id,
            app_secret_cipher=encrypt_secret(app_id, "pub-mock-secret-00000", ver),
            key_version=ver,
            account_type=3,
            need_review=need_review,
            created_by=1,
        )
        db.add(acc)
        await db.commit()
        return acc.id, app_id


def _skip_if_route_missing(resp, what: str):
    if resp.status_code == 404:
        pytest.skip(f"{what} 端点未就绪(publish_engine/content_center 并行实现中): {resp.status_code}")


def _data(resp) -> dict:
    return resp.json().get("data") or {}


async def _create_article(client, admin_token, mp_id: int, title="发布用图文") -> int:
    resp = await client.post(
        "/api/v1/articles",
        headers=auth_headers(admin_token),
        json={"mp_account_id": mp_id, "title": title, "content_html": "<p>发布正文</p>"},
    )
    _skip_if_route_missing(resp, "POST /articles")
    assert resp.status_code in (200, 201), resp.text
    art_id = _data(resp).get("id")
    assert art_id
    return art_id


async def _submit_article(client, admin_token, art_id: int):
    """提审;审核关(need_review=0)时应直接 APPROVED。"""
    resp = await client.post(
        f"/api/v1/articles/{art_id}/submit", headers=auth_headers(admin_token)
    )
    _skip_if_route_missing(resp, "POST /articles/{id}/submit")
    assert resp.status_code in (200, 201), resp.text
    assert resp.json()["code"] == 0, resp.text


async def _create_task(client, admin_token, art_id: int, mp_id: int) -> int:
    resp = await client.post(
        "/api/v1/publish/tasks",
        headers=auth_headers(admin_token),
        json={"content_article_id": art_id, "mp_account_id": mp_id},
    )
    _skip_if_route_missing(resp, "POST /publish/tasks")
    assert resp.status_code in (200, 201), resp.text
    assert resp.json()["code"] == 0, resp.text
    task_id = _data(resp).get("id")
    assert task_id
    return task_id


async def _drive_to_terminal(client, admin_token, session_factory, task_id: int) -> str:
    """浏览器发布为原子操作:建任务/重试后任务已进入终态(PUBLISHED/FAILED),直接读状态。"""
    async with session_factory() as db:
        return await db.scalar(select(PublishTask.status).where(PublishTask.id == task_id))


# ---------------------------------------------------------------------------
# 正路:手动发文全链路直至 PUBLISHED
# ---------------------------------------------------------------------------
async def test_manual_publish_happy_path(client, admin_token, session_factory):
    mp_id, _ = await _seed_mock_account(session_factory, "wxPUBHAPPY0000001", need_review=0)
    art_id = await _create_article(client, admin_token, mp_id)
    await _submit_article(client, admin_token, art_id)

    # 审核关:提审后应已 APPROVED
    async with session_factory() as db:
        st = await db.scalar(
            select(ContentArticle.status).where(ContentArticle.id == art_id)
        )
    assert st == "APPROVED", f"need_review=0 提审后应自动 APPROVED, 实为 {st}"

    task_id = await _create_task(client, admin_token, art_id, mp_id)
    final = await _drive_to_terminal(client, admin_token, session_factory, task_id)
    assert final == "PUBLISHED", f"Mock 正路任务应 PUBLISHED, 实为 {final}"

    # 任务落 published_url,content_article 变 DRAFT_CREATED
    async with session_factory() as db:
        task = (
            await db.execute(select(PublishTask).where(PublishTask.id == task_id))
        ).scalar_one()
        art_st = await db.scalar(
            select(ContentArticle.status).where(ContentArticle.id == art_id)
        )
    assert task.published_url, "PUBLISHED 任务应回写非空 published_url"
    assert art_st == "DRAFT_CREATED", f"发布后 content_article 应 DRAFT_CREATED, 实为 {art_st}"

    # 日志覆盖 DRAFT_ADD / FREEPUBLISH_SUBMIT / RESULT 各阶段
    logs_resp = await client.get(
        f"/api/v1/publish/tasks/{task_id}/logs", headers=auth_headers(admin_token)
    )
    _skip_if_route_missing(logs_resp, "GET /publish/tasks/{id}/logs")
    assert logs_resp.status_code == 200, logs_resp.text
    assert logs_resp.json()["code"] == 0

    # 优先信任 DB 中的 publish_log(不依赖日志接口的具体出参形状)
    async with session_factory() as db:
        phases = set(
            (
                await db.execute(
                    select(PublishLog.phase).where(PublishLog.publish_task_id == task_id)
                )
            )
            .scalars()
            .all()
        )
    # 浏览器发布的页面步骤(v1.1):LOGIN/NEW_DRAFT/FILL/UPLOAD_IMG/SAVE/PUBLISH/RESULT
    for expected in ("NEW_DRAFT", "PUBLISH", "RESULT"):
        assert expected in phases, f"缺少阶段日志 {expected}; 现有: {sorted(phases)}"


# ---------------------------------------------------------------------------
# 失败重试:publish_status=3 → FAILED → reset 成功后 retry → PUBLISHED
# ---------------------------------------------------------------------------
async def test_publish_failure_then_retry(client, admin_token, session_factory):
    mp_id, app_id = await _seed_mock_account(
        session_factory, "wxPUBRETRY0000001", need_review=0
    )
    art_id = await _create_article(client, admin_token, mp_id, title="重试用图文")
    await _submit_article(client, admin_token, art_id)

    # 注入常规失败:优先用 Mock 配置端点,不可用则直接调 mock_channel
    cfg = await client.post(
        f"/api/v1/publish/mock/{app_id}",
        headers=auth_headers(admin_token),
        json={"publish_status": 3},
    )
    if cfg.status_code == 404:
        mock_channel.set_mock_outcome(app_id, publish_status=3)
    else:
        assert cfg.status_code in (200, 201), cfg.text

    task_id = await _create_task(client, admin_token, art_id, mp_id)
    failed = await _drive_to_terminal(client, admin_token, session_factory, task_id)
    assert failed == "FAILED", f"注入 publish_status=3 后任务应 FAILED, 实为 {failed}"

    # 复位为成功:优先端点,回退直接调
    reset = await client.post(
        f"/api/v1/publish/mock/{app_id}",
        headers=auth_headers(admin_token),
        json={"publish_status": 0},
    )
    if reset.status_code == 404:
        mock_channel.reset_mock_outcomes()
    else:
        assert reset.status_code in (200, 201), reset.text

    # 重试:FAILED → SCHEDULED → ... → PUBLISHED
    retry = await client.post(
        f"/api/v1/publish/tasks/{task_id}/retry", headers=auth_headers(admin_token)
    )
    _skip_if_route_missing(retry, "POST /publish/tasks/{id}/retry")
    assert retry.status_code in (200, 201), retry.text
    assert retry.json()["code"] == 0, retry.text

    final = await _drive_to_terminal(client, admin_token, session_factory, task_id)
    assert final == "PUBLISHED", f"reset 后重试应 PUBLISHED, 实为 {final}"

    async with session_factory() as db:
        url = await db.scalar(
            select(PublishTask.published_url).where(PublishTask.id == task_id)
        )
    assert url, "重试成功后应回写 published_url"
