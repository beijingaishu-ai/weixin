"""publish_engine 路由:发布任务 + 内联执行 + 轮询 + 重试 + 日志 + 统计 + Mock 配置。

前缀 /api/v1 由 main include_router 追加;本文件挂 /publish/*。
- 数据权限:列表/统计走 get_visible_mp_ids + apply_mp_scope;
  单号写/读守卫因路径参数 id 是「任务 id」而非「公众号 id」,不能直接用 deps.require_mp_access,
  改由 service 解析任务归属号后手工校验(POST /publish/tasks 用 body.mp_account_id 同理)。
- 发文执行内联(M2 手动发文):创建/重试后立即 execute_publish(内部含 poll_once),
  gateway 用 Depends(get_gateway) 注入。
- 所有业务路由 return ok(...)。
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.response import ok
from app.modules.auth_rbac.deps import (
    UserCtx,
    get_current_user,
    get_visible_mp_ids,
    require_perm,
)
from app.modules.publish_engine import schemas, service
from app.modules.wx_gateway.gateway import WxGateway, get_gateway

router = APIRouter(tags=["publish"])


# ---------------------------------------------------------------------------
# 创建发布任务(内联执行:建稿 → 提交 → 立即 poll)
# ---------------------------------------------------------------------------
@router.post("/publish/tasks")
async def create_publish_task(
    payload: schemas.PublishTaskCreate,
    current: UserCtx = Depends(require_perm("publish:task:manage")),
    gateway: WxGateway = Depends(get_gateway),
    db: AsyncSession = Depends(get_db),
):
    data = await service.create_task(db, gateway, payload=payload, user=current)
    return ok(data)


# ---------------------------------------------------------------------------
# 分页列表(数据权限过滤)
# ---------------------------------------------------------------------------
@router.get("/publish/tasks")
async def list_publish_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    mp_account_id: int | None = Query(None),
    status: str | None = Query(None),
    _: UserCtx = Depends(require_perm("publish:task:view")),
    visible: set[int] | None = Depends(get_visible_mp_ids),
    db: AsyncSession = Depends(get_db),
):
    data = await service.list_tasks(
        db,
        visible=visible,
        page=page,
        page_size=page_size,
        mp_account_id=mp_account_id,
        status=status,
    )
    return ok(data)


# ---------------------------------------------------------------------------
# 详情(含 publish_id / published_url;service 内做单号访问校验)
# ---------------------------------------------------------------------------
@router.get("/publish/tasks/{id}")
async def get_publish_task(
    id: int,
    current: UserCtx = Depends(require_perm("publish:task:view")),
    db: AsyncSession = Depends(get_db),
):
    data = await service.get_task(db, task_id=id, user=current)
    return ok(data)


# ---------------------------------------------------------------------------
# 一键下架(仅 PUBLISHED:模拟在后台删除文章)
# ---------------------------------------------------------------------------
@router.post("/publish/tasks/{id}/takedown")
async def takedown_publish_task(
    id: int,
    current: UserCtx = Depends(require_perm("publish:task:manage")),
    gateway: WxGateway = Depends(get_gateway),
    db: AsyncSession = Depends(get_db),
):
    data = await service.takedown_task(db, gateway, task_id=id, user=current)
    return ok(data)


# ---------------------------------------------------------------------------
# 取消(仅 SCHEDULED,软删)
# ---------------------------------------------------------------------------
@router.post("/publish/tasks/{id}/cancel")
async def cancel_publish_task(
    id: int,
    current: UserCtx = Depends(require_perm("publish:task:manage")),
    db: AsyncSession = Depends(get_db),
):
    data = await service.cancel_task(db, task_id=id, user=current)
    return ok(data)


# ---------------------------------------------------------------------------
# 重试(仅 FAILED:FAILED→SCHEDULED,retry_count+1,清 err,立即执行)
# ---------------------------------------------------------------------------
@router.post("/publish/tasks/{id}/retry")
async def retry_publish_task(
    id: int,
    current: UserCtx = Depends(require_perm("publish:task:manage")),
    gateway: WxGateway = Depends(get_gateway),
    db: AsyncSession = Depends(get_db),
):
    data = await service.retry_task(db, gateway, task_id=id, user=current)
    return ok(data)


# ---------------------------------------------------------------------------
# 任务日志明细
# ---------------------------------------------------------------------------
@router.get("/publish/tasks/{id}/logs")
async def list_publish_logs(
    id: int,
    current: UserCtx = Depends(require_perm("publish:log:view")),
    db: AsyncSession = Depends(get_db),
):
    data = await service.list_logs(db, task_id=id, user=current)
    return ok(data)


# ---------------------------------------------------------------------------
# 统计(各状态计数 + 成功率;数据权限)
# ---------------------------------------------------------------------------
@router.get("/publish/stats")
async def publish_stats(
    mp_account_id: int | None = Query(None),
    _: UserCtx = Depends(require_perm("publish:task:view")),
    visible: set[int] | None = Depends(get_visible_mp_ids),
    db: AsyncSession = Depends(get_db),
):
    data = await service.stats(db, visible=visible, mp_account_id=mp_account_id)
    return ok(data)


# ---------------------------------------------------------------------------
# Mock 配置(课堂演练失败/重试用;仅 system:config:manage)
# ---------------------------------------------------------------------------
@router.post("/publish/mock/{app_id}")
async def set_publish_mock(
    app_id: str,
    payload: schemas.MockOutcomeIn,
    _: UserCtx = Depends(require_perm("system:config:manage")),
):
    data = service.set_mock(app_id, payload)
    return ok(data)
