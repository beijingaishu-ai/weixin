"""发文流水线核心(内联 async)。v1.1:发布走浏览器自动化,不走 API。

execute_publish(db, gateway, task) —— SCHEDULED 任务的一次完整推进:
    加载文章 → 校验全部 APPROVED → 组装 payload → gateway.publish()(浏览器模拟建稿+发表,
    一步完成)→ 逐页面步骤落 publish_log → 成功则文章 APPROVED→DRAFT_CREATED、任务 PUBLISHED;
    失败则 FAILED + 按退避排下次重试。

takedown(db, gateway, task) —— 一键下架:对已 PUBLISHED 任务模拟在后台删除文章。

约束:
  - 幂等:execute_publish 仅在 status=SCHEDULED 时推进。
  - 发布经 gateway.publish 门面(浏览器通道),不直接碰页面/httpx。
  - 状态迁移一律 ensure_transition。
  - 每个页面步骤落一条 publish_log(request_digest 脱敏)。
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.states import (
    ArticleStatus,
    IllegalTransition,
    TaskStatus,
    WxLoginStatus,
    ensure_transition,
)
from app.models.content import ContentArticle
from app.models.mp_account import MpAccount
from app.models.publish import PublishLog, PublishTask
from app.modules.wx_gateway.errors import WX_AUTH_EXPIRED, WxApiError
from app.modules.wx_gateway.gateway import login_valid

# 退避:60 * 2^retry_count,封顶 3600s
_BACKOFF_BASE = 60
_BACKOFF_CAP = 3600

PHASE_TAKEDOWN = "TAKEDOWN"


# ---------------------------------------------------------------------------
# 日志助手
# ---------------------------------------------------------------------------
async def _log(
    db: AsyncSession,
    task: PublishTask,
    *,
    phase: str,
    from_status: str = "",
    to_status: str = "",
    errcode: int | None = 0,
    errmsg: str = "",
    digest: str = "",
) -> None:
    db.add(
        PublishLog(
            publish_task_id=task.id,
            phase=phase,
            from_status=from_status,
            to_status=to_status,
            wx_api="browser://mp.weixin.qq.com",
            request_digest=digest[:1024],
            errcode=errcode,
            errmsg=errmsg[:512],
            cost_ms=0,
        )
    )
    await db.flush()


async def _fail(
    db: AsyncSession,
    task: PublishTask,
    *,
    phase: str,
    errcode: int | None,
    errmsg: str,
    schedule_retry: bool = True,
) -> None:
    """任务转 FAILED,写 last_err,按需排下次重试,落一条日志。"""
    frm = task.status
    if frm != TaskStatus.FAILED:
        try:
            ensure_transition("publish_task", frm, TaskStatus.FAILED)
            task.status = TaskStatus.FAILED
        except IllegalTransition:
            pass
    task.last_errcode = errcode
    task.last_errmsg = (errmsg or "")[:512]
    if schedule_retry and task.retry_count < task.max_retry:
        delay = min(_BACKOFF_BASE * (2 ** task.retry_count), _BACKOFF_CAP)
        task.next_retry_at = datetime.utcnow() + timedelta(seconds=delay)
    else:
        task.next_retry_at = None
    await _log(
        db, task, phase=phase, from_status=frm, to_status=task.status,
        errcode=errcode, errmsg=task.last_errmsg,
    )


# ---------------------------------------------------------------------------
# 加载
# ---------------------------------------------------------------------------
async def _load_articles(db: AsyncSession, task: PublishTask) -> list[ContentArticle]:
    if task.draft_group_id is not None:
        rows = await db.scalars(
            select(ContentArticle)
            .where(
                ContentArticle.draft_group_id == task.draft_group_id,
                ContentArticle.is_deleted == 0,
            )
            .order_by(ContentArticle.group_position.asc(), ContentArticle.id.asc())
        )
        return list(rows)
    art = await db.get(ContentArticle, task.content_article_id)
    if art is None or art.is_deleted:
        return []
    return [art]


async def _mp_of(db: AsyncSession, task: PublishTask) -> MpAccount | None:
    return await db.get(MpAccount, task.mp_account_id)


def _downgrade_login(mp: MpAccount) -> None:
    """运行时探测登录态失效 → 降级号状态(到期 EXPIRED / 被踢 REVOKED)并清告警戳以触发续扫。"""
    if mp.wx_login_status in (WxLoginStatus.EXPIRED, WxLoginStatus.REVOKED):
        return
    now = datetime.utcnow()
    expired_by_time = mp.wx_login_expires_at is None or now >= mp.wx_login_expires_at
    target = WxLoginStatus.EXPIRED if expired_by_time else WxLoginStatus.REVOKED
    try:
        ensure_transition("mp_account_login", mp.wx_login_status, target)
        mp.wx_login_status = target
    except IllegalTransition:
        pass
    mp.wx_login_alerted_at = None  # 让 _login_watch 重新告警续扫


def _to_payload(article: ContentArticle) -> dict:
    return {
        "id": article.id,
        "title": article.title,
        "author": article.author or "",
        "digest": article.digest or "",
        "content": article.content_html,
        "cover_material_id": article.cover_material_id,
        "need_open_comment": int(article.need_open_comment or 0),
        "only_fans_can_comment": int(article.only_fans_can_comment or 0),
    }


# ---------------------------------------------------------------------------
# 主流水线:浏览器模拟建稿 + 发表(一步)
# ---------------------------------------------------------------------------
async def execute_publish(db: AsyncSession, gateway, task: PublishTask) -> PublishTask:
    """推进一次 SCHEDULED 任务。幂等:非 SCHEDULED 直接返回。"""
    if task.status != TaskStatus.SCHEDULED:
        return task

    mp = await _mp_of(db, task)
    if mp is None:
        await _fail(db, task, phase="LOGIN", errcode=None,
                    errmsg="目标公众号不存在", schedule_retry=False)
        return task

    articles = await _load_articles(db, task)
    if not articles:
        await _fail(db, task, phase="NEW_DRAFT", errcode=None,
                    errmsg="未找到待发布文章", schedule_retry=False)
        return task

    # 全部须 APPROVED(重试时文章仍为 APPROVED——成功前不迁 DRAFT_CREATED)
    bad = [a.id for a in articles if a.status != ArticleStatus.APPROVED]
    if bad:
        await _fail(db, task, phase="NEW_DRAFT", errcode=None,
                    errmsg=f"文章状态不满足发布条件(须全部 APPROVED): {bad}",
                    schedule_retry=False)
        return task

    # 真实号发布前置:登录态未授权/过期 → 挂起(保持 SCHEDULED,不进 PUBLISHING、不进死信),
    # 续扫复位 AUTHORIZED 后由 scheduler 下一 tick 自然放行。主拦截在 scheduler 队列层,此为兜底。
    if not gateway.is_mock(mp) and not login_valid(mp):
        _downgrade_login(mp)
        task.last_errcode = WX_AUTH_EXPIRED
        task.last_errmsg = "登录态未授权/已过期,挂起等待管理员扫码续期"
        await _log(db, task, phase="LOGIN", from_status=task.status, to_status=task.status,
                   errcode=WX_AUTH_EXPIRED, errmsg=task.last_errmsg)
        return task  # 状态保持 SCHEDULED

    # SCHEDULED → PUBLISHING
    ensure_transition("publish_task", task.status, TaskStatus.PUBLISHING)
    task.status = TaskStatus.PUBLISHING
    task.dispatched = 1

    # 浏览器模拟发布(一步完成 登录→建稿→填充→上传图→保存→发表/群发→结果)
    payload = [_to_payload(a) for a in articles]
    try:
        outcome = await gateway.publish(mp, payload, publish_type=task.publish_type or 1)
    except WxApiError as e:
        if e.is_auth_expired:
            # 发布中途登录态失效:降级号 + FAILED 但不排退避、不进死信;续扫后由 _login_watch 重排
            _downgrade_login(mp)
            await _fail(db, task, phase="PUBLISH", errcode=e.errcode,
                        errmsg=e.errmsg, schedule_retry=False)
        else:
            await _fail(db, task, phase="PUBLISH", errcode=e.errcode, errmsg=e.errmsg)
        return task

    # 逐页面步骤落日志
    for step in outcome.steps:
        await _log(
            db, task, phase=step.phase,
            errcode=0 if step.ok else (outcome.errcode or 1),
            errmsg="" if step.ok else step.errmsg,
            digest=step.detail,
        )

    if outcome.ok:
        # 文章 APPROVED → DRAFT_CREATED(草稿已在后台建成并发表)
        for a in articles:
            ensure_transition("content_article", a.status, ArticleStatus.DRAFT_CREATED)
            a.status = ArticleStatus.DRAFT_CREATED
        frm = task.status
        ensure_transition("publish_task", frm, TaskStatus.PUBLISHED)
        task.status = TaskStatus.PUBLISHED
        task.published_url = (outcome.article_url or "")[:512]
        task.published_article_id = (outcome.article_id or "")[:64]
        task.last_errcode = None
        task.last_errmsg = ""
        task.next_retry_at = None
        await _log(
            db, task, phase="RESULT", from_status=frm, to_status=TaskStatus.PUBLISHED,
            errcode=0, digest=f"url={task.published_url}",
        )
    else:
        await _fail(db, task, phase="RESULT",
                    errcode=outcome.errcode, errmsg=outcome.errmsg or "发表失败")
    return task


async def takedown(db: AsyncSession, gateway, task: PublishTask) -> PublishTask:
    """一键下架:对已 PUBLISHED 任务模拟在后台删除文章。"""
    mp = await _mp_of(db, task)
    if mp is None:
        raise WxApiError(None, "目标公众号不存在")
    ok = await gateway.takedown(mp, task.published_url)
    await _log(
        db, task, phase=PHASE_TAKEDOWN, errcode=0 if ok else 1,
        errmsg="" if ok else "下架失败", digest=f"url={task.published_url}",
    )
    if ok:
        task.last_errmsg = "已下架"
    return task
