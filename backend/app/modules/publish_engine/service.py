"""publish_engine 业务逻辑:发布任务创建/查询/取消/重试/日志/统计 + Mock 配置。

约定:
  - 数据权限:列表走 apply_mp_scope(deps 唯一出口);单号访问走 _assert_mp_access
    (因 /publish/tasks/{id} 的路径参数 id 是任务 id,而非公众号 id,故不能直接用
    deps.require_mp_access,改为解析任务归属号后手工校验,语义与其一致)。
  - 状态迁移一律 ensure_transition;写操作由本层 commit。
  - 发文执行内联:创建/重试后立即 execute_publish(内部含 poll_once)。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.states import ArticleStatus, TaskStatus, ensure_transition
from app.models.content import ContentArticle, ContentDraftGroup
from app.models.mp_account import MpAccount, MpAccountAssign
from app.models.publish import PublishLog, PublishTask
from app.modules.auth_rbac.deps import UserCtx, apply_mp_scope
from app.modules.publish_engine import executor, schemas
from app.modules.wx_gateway import mock_channel

# 未终结(仍可能占用 biz_key)的任务状态
_LIVE_STATUSES = (TaskStatus.SCHEDULED, TaskStatus.PUBLISHING)


# ---------------------------------------------------------------------------
# 权限:任务归属号访问校验(等价 deps.require_mp_access,但入参是 mp_account_id)
# ---------------------------------------------------------------------------
async def _assert_mp_access(
    db: AsyncSession, user: UserCtx, mp_account_id: int, need_level: int
) -> None:
    """角色特权直通;operator 须对该号 perm_level>=need_level,否则 403。"""
    if user.is_full_access:
        return
    perm_level = await db.scalar(
        select(MpAccountAssign.perm_level).where(
            MpAccountAssign.user_id == user.id,
            MpAccountAssign.mp_account_id == mp_account_id,
            MpAccountAssign.deleted_flag == 0,
        )
    )
    if perm_level is None or perm_level < need_level:
        raise AppError("无权访问该公众号", status_code=403)


def _to_item(task: PublishTask) -> dict:
    return {
        "id": task.id,
        "biz_key": task.biz_key,
        "content_article_id": task.content_article_id,
        "draft_group_id": task.draft_group_id,
        "mp_account_id": task.mp_account_id,
        "publish_type": task.publish_type,
        "scheduled_at": task.scheduled_at,
        "status": task.status,
        "publish_id": task.publish_id,
        "published_article_id": task.published_article_id,
        "published_url": task.published_url,
        "retry_count": task.retry_count,
        "max_retry": task.max_retry,
        "next_retry_at": task.next_retry_at,
        "last_errcode": task.last_errcode,
        "last_errmsg": task.last_errmsg,
        "created_by": task.created_by,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


async def _get_task_or_404(db: AsyncSession, task_id: int) -> PublishTask:
    task = await db.get(PublishTask, task_id)
    if task is None or task.is_deleted:
        raise AppError("发布任务不存在", status_code=404)
    return task


# ---------------------------------------------------------------------------
# 目标校验:文章/组须全部 APPROVED 且归属号一致,返回 (biz_key, mp_account_id)
# ---------------------------------------------------------------------------
async def _validate_target(
    db: AsyncSession, payload: schemas.PublishTaskCreate
) -> tuple[str, list[ContentArticle]]:
    if payload.content_article_id is not None:
        art = await db.get(ContentArticle, payload.content_article_id)
        if art is None or art.is_deleted:
            raise AppError("文章不存在", status_code=404)
        if art.mp_account_id != payload.mp_account_id:
            raise AppError("文章归属公众号与 mp_account_id 不一致", status_code=422)
        if art.status != ArticleStatus.APPROVED:
            raise AppError("文章未过审(须 APPROVED)", status_code=422)
        return f"article:{art.id}", [art]

    grp = await db.get(ContentDraftGroup, payload.draft_group_id)
    if grp is None or grp.is_deleted:
        raise AppError("图文组不存在", status_code=404)
    if grp.mp_account_id != payload.mp_account_id:
        raise AppError("图文组归属公众号与 mp_account_id 不一致", status_code=422)
    rows = await db.scalars(
        select(ContentArticle)
        .where(
            ContentArticle.draft_group_id == grp.id,
            ContentArticle.is_deleted == 0,
        )
        .order_by(ContentArticle.group_position.asc(), ContentArticle.id.asc())
    )
    articles = list(rows)
    if not articles:
        raise AppError("图文组为空", status_code=422)
    bad = [a.id for a in articles if a.status != ArticleStatus.APPROVED]
    if bad:
        raise AppError(f"组内存在未过审文章: {bad}", status_code=422)
    if any(a.mp_account_id != payload.mp_account_id for a in articles):
        raise AppError("组内文章归属公众号不一致", status_code=422)
    return f"group:{grp.id}", articles


# ---------------------------------------------------------------------------
# 创建 + 内联执行
# ---------------------------------------------------------------------------
async def create_task(
    db: AsyncSession,
    gateway,
    *,
    payload: schemas.PublishTaskCreate,
    user: UserCtx,
) -> dict:
    # 单号访问守卫(发布级 4)
    await _assert_mp_access(db, user, payload.mp_account_id, need_level=4)

    # 公众号存在性
    mp = await db.get(MpAccount, payload.mp_account_id)
    if mp is None or mp.is_deleted:
        raise AppError("公众号不存在", status_code=404)

    # biz_key 由目标 id 直接推导;先做重复未完成任务拒绝(同 biz_key 存在
    # SCHEDULED/PUBLISHING 未删任务),再校验目标状态,使 409「已在进行」语义优先。
    if payload.content_article_id is not None:
        biz_key = f"article:{payload.content_article_id}"
    else:
        biz_key = f"group:{payload.draft_group_id}"

    dup = await db.scalar(
        select(PublishTask.id).where(
            PublishTask.biz_key == biz_key,
            PublishTask.is_deleted == 0,
            PublishTask.status.in_(_LIVE_STATUSES),
        )
    )
    if dup:
        raise AppError("该目标已有进行中的发布任务", status_code=409)

    # 目标存在/归属/全部 APPROVED 校验
    await _validate_target(db, payload)

    task = PublishTask(
        biz_key=biz_key,
        content_article_id=payload.content_article_id,
        draft_group_id=payload.draft_group_id,
        mp_account_id=payload.mp_account_id,
        publish_type=payload.publish_type,
        scheduled_at=payload.scheduled_at or datetime.utcnow(),
        status=TaskStatus.SCHEDULED,
        created_by=user.id,
    )
    db.add(task)
    await db.flush()  # 取 task.id

    # M2 手动发文:创建后立即内联执行(内部含 poll_once)
    await executor.execute_publish(db, gateway, task)
    await db.commit()
    await db.refresh(task)
    return _to_item(task)


# ---------------------------------------------------------------------------
# 分页列表(数据权限)
# ---------------------------------------------------------------------------
async def list_tasks(
    db: AsyncSession,
    *,
    visible: set[int] | None,
    page: int,
    page_size: int,
    mp_account_id: int | None,
    status: str | None,
) -> dict:
    base = select(PublishTask).where(PublishTask.is_deleted == 0)
    base = apply_mp_scope(base, PublishTask.mp_account_id, visible)
    if mp_account_id is not None:
        base = base.where(PublishTask.mp_account_id == mp_account_id)
    if status:
        base = base.where(PublishTask.status == status)

    total = await db.scalar(
        select(func.count()).select_from(base.order_by(None).subquery())
    )
    rows = await db.scalars(
        base.order_by(PublishTask.id.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    items = [_to_item(t) for t in rows.all()]
    return {"items": items, "total": total or 0, "page": page, "page_size": page_size}


# ---------------------------------------------------------------------------
# 详情(单号访问守卫,只读级 1)
# ---------------------------------------------------------------------------
async def get_task(db: AsyncSession, *, task_id: int, user: UserCtx) -> dict:
    task = await _get_task_or_404(db, task_id)
    await _assert_mp_access(db, user, task.mp_account_id, need_level=1)
    return _to_item(task)


# ---------------------------------------------------------------------------
# 一键下架(仅 PUBLISHED:模拟在后台删除文章)
# ---------------------------------------------------------------------------
async def takedown_task(db: AsyncSession, gateway, *, task_id: int, user: UserCtx) -> dict:
    task = await _get_task_or_404(db, task_id)
    await _assert_mp_access(db, user, task.mp_account_id, need_level=4)
    if task.status != TaskStatus.PUBLISHED:
        raise AppError("仅已发布任务可下架", status_code=422)
    await executor.takedown(db, gateway, task)
    await db.commit()
    await db.refresh(task)
    return _to_item(task)


# ---------------------------------------------------------------------------
# 取消(仅 SCHEDULED,软删)
# ---------------------------------------------------------------------------
async def cancel_task(db: AsyncSession, *, task_id: int, user: UserCtx) -> dict:
    task = await _get_task_or_404(db, task_id)
    await _assert_mp_access(db, user, task.mp_account_id, need_level=4)
    if task.status != TaskStatus.SCHEDULED:
        raise AppError("仅 SCHEDULED 任务可取消", status_code=422)
    task.is_deleted = 1
    await db.commit()
    return {"id": task.id, "cancelled": True}


# ---------------------------------------------------------------------------
# 重试(仅 FAILED:FAILED→SCHEDULED,retry_count+1,清 err,立即执行)
# ---------------------------------------------------------------------------
async def retry_task(db: AsyncSession, gateway, *, task_id: int, user: UserCtx) -> dict:
    task = await _get_task_or_404(db, task_id)
    await _assert_mp_access(db, user, task.mp_account_id, need_level=4)
    if task.status != TaskStatus.FAILED:
        raise AppError("仅 FAILED 任务可重试", status_code=422)

    ensure_transition("publish_task", task.status, TaskStatus.SCHEDULED)
    task.status = TaskStatus.SCHEDULED
    task.retry_count += 1
    task.dispatched = 0
    task.last_errcode = None
    task.last_errmsg = ""
    task.next_retry_at = None
    await db.flush()

    await executor.execute_publish(db, gateway, task)
    await db.commit()
    await db.refresh(task)
    return _to_item(task)


# ---------------------------------------------------------------------------
# 任务日志明细
# ---------------------------------------------------------------------------
async def list_logs(db: AsyncSession, *, task_id: int, user: UserCtx) -> list[dict]:
    task = await _get_task_or_404(db, task_id)
    await _assert_mp_access(db, user, task.mp_account_id, need_level=1)
    rows = await db.scalars(
        select(PublishLog)
        .where(PublishLog.publish_task_id == task_id)
        .order_by(PublishLog.id.asc())
    )
    return [
        {
            "id": r.id,
            "publish_task_id": r.publish_task_id,
            "phase": r.phase,
            "from_status": r.from_status,
            "to_status": r.to_status,
            "wx_api": r.wx_api,
            "request_digest": r.request_digest,
            "errcode": r.errcode,
            "errmsg": r.errmsg,
            "cost_ms": r.cost_ms,
            "created_at": r.created_at,
        }
        for r in rows.all()
    ]


# ---------------------------------------------------------------------------
# 统计(各状态计数 + 成功率)
# ---------------------------------------------------------------------------
async def stats(
    db: AsyncSession, *, visible: set[int] | None, mp_account_id: int | None
) -> dict:
    base = select(PublishTask.status, func.count()).where(PublishTask.is_deleted == 0)
    base = apply_mp_scope(base, PublishTask.mp_account_id, visible)
    if mp_account_id is not None:
        base = base.where(PublishTask.mp_account_id == mp_account_id)
    rows = await db.execute(base.group_by(PublishTask.status))
    counts = {status: cnt for status, cnt in rows.all()}

    scheduled = counts.get(TaskStatus.SCHEDULED, 0)
    publishing = counts.get(TaskStatus.PUBLISHING, 0)
    published = counts.get(TaskStatus.PUBLISHED, 0)
    failed = counts.get(TaskStatus.FAILED, 0)
    total = scheduled + publishing + published + failed
    # 成功率基数取已终态(PUBLISHED + FAILED),避免进行中任务拉低
    terminal = published + failed
    success_rate = round(published / terminal * 100, 2) if terminal else 0.0
    return {
        "total": total,
        "scheduled": scheduled,
        "publishing": publishing,
        "published": published,
        "failed": failed,
        "success_rate": success_rate,
    }


# ---------------------------------------------------------------------------
# Mock 配置(课堂演练失败/重试用)
# ---------------------------------------------------------------------------
def set_mock(app_id: str, payload: schemas.MockOutcomeIn) -> dict:
    mock_channel.set_mock_outcome(
        app_id,
        publish_status=payload.publish_status,
        submit_errcode=payload.submit_errcode,
    )
    return {
        "app_id": app_id,
        "publish_status": payload.publish_status,
        "submit_errcode": payload.submit_errcode,
    }
