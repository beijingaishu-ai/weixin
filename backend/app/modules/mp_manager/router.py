"""mp_manager 路由:公众号档案 CRUD / 校验 / 运营分配 / 内部凭据接口。

前缀 /api/v1 由 main include_router 追加;本文件挂 /mp-accounts 与 /internal/mp-accounts。
- 数据权限:列表走 get_visible_mp_ids + apply_mp_scope;单号走 require_mp_access(路径参数名必须叫 id)。
- 所有业务路由 return ok(...);机密红线由 schemas 出参模型兜底(零 secret 回显)。
- /internal 接口不挂任何用户鉴权依赖,手工校验 X-Internal-Token;Nginx 另在边缘 404 屏蔽。
"""
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.core.redis import get_redis
from app.core.response import ok
from app.modules.auth_rbac.deps import (
    UserCtx,
    get_visible_mp_ids,
    require_mp_access,
    require_perm,
)
from app.modules.mp_manager import schemas, service

router = APIRouter(tags=["mp-accounts"])


# ---------------------------------------------------------------------------
# 11 GET /mp-accounts —— 分页台账(数据权限过滤)
# ---------------------------------------------------------------------------
@router.get("/mp-accounts")
async def list_mp_accounts(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None),
    status: int | None = Query(None),
    _: UserCtx = Depends(require_perm("mp:account:view")),
    visible: set[int] | None = Depends(get_visible_mp_ids),
    db: AsyncSession = Depends(get_db),
):
    data = await service.list_accounts(
        db,
        visible=visible,
        page=page,
        page_size=page_size,
        keyword=keyword,
        status=status,
    )
    return ok(data)


# ---------------------------------------------------------------------------
# 12 POST /mp-accounts —— 创建
# ---------------------------------------------------------------------------
@router.post("/mp-accounts")
async def create_mp_account(
    payload: schemas.MpAccountCreate,
    current: UserCtx = Depends(require_perm("mp:account:manage")),
    db: AsyncSession = Depends(get_db),
):
    data = await service.create_account(db, payload=payload, current_id=current.id)
    return ok(data)


# ---------------------------------------------------------------------------
# 13 GET /mp-accounts/{id} —— 详情(单号访问守卫,路径参数名 = id)
# ---------------------------------------------------------------------------
@router.get("/mp-accounts/{id}")
async def get_mp_account(
    _: UserCtx = Depends(require_perm("mp:account:view")),
    mp_id: int = Depends(require_mp_access(need_level=1)),
    db: AsyncSession = Depends(get_db),
):
    data = await service.get_account_detail(db, mp_id=mp_id)
    return ok(data)


# ---------------------------------------------------------------------------
# 14 PUT /mp-accounts/{id} —— 更新
# ---------------------------------------------------------------------------
@router.put("/mp-accounts/{id}")
async def update_mp_account(
    id: int,
    payload: schemas.MpAccountUpdate,
    current: UserCtx = Depends(require_perm("mp:account:manage")),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    await service.update_account(
        db, mp_id=id, payload=payload, current=current, redis=redis
    )
    return ok()


# ---------------------------------------------------------------------------
# 15 POST /mp-accounts/{id}/verify —— 密文自检(M1 无 wx-gateway)
# ---------------------------------------------------------------------------
@router.post("/mp-accounts/{id}/verify")
async def verify_mp_account(
    id: int,
    current: UserCtx = Depends(require_perm("mp:account:manage")),
    db: AsyncSession = Depends(get_db),
):
    data = await service.verify_account(db, mp_id=id, current_id=current.id)
    return ok(data)


# ---------------------------------------------------------------------------
# 浏览器发布登录态授权:状态查询 + 手动吊销(续扫入口)
# ---------------------------------------------------------------------------
@router.get("/mp-accounts/{id}/login-auth")
async def get_login_auth(
    _: UserCtx = Depends(require_perm("mp:account:view")),
    mp_id: int = Depends(require_mp_access(need_level=1)),
    db: AsyncSession = Depends(get_db),
):
    return ok(await service.login_auth_status(db, mp_id=mp_id))


@router.post("/mp-accounts/{id}/login-revoke")
async def revoke_login_auth(
    current: UserCtx = Depends(require_perm("mp:account:manage")),
    mp_id: int = Depends(require_mp_access(need_level=4)),  # 需该号发布权
    db: AsyncSession = Depends(get_db),
):
    return ok(await service.mark_login_revoked(db, mp_id=mp_id, current_id=current.id))


# ---------------------------------------------------------------------------
# 16 GET /mp-accounts/{id}/assignees —— 分配人清单(单号访问守卫)
# ---------------------------------------------------------------------------
@router.get("/mp-accounts/{id}/assignees")
async def get_mp_assignees(
    _: UserCtx = Depends(require_perm("user:assign")),
    mp_id: int = Depends(require_mp_access(need_level=1)),
    db: AsyncSession = Depends(get_db),
):
    data = await service.list_assignees(db, mp_id=mp_id)
    return ok(data)


# ---------------------------------------------------------------------------
# 17 PUT /mp-accounts/{id}/assignees —— 全量覆盖式分配
# ---------------------------------------------------------------------------
@router.put("/mp-accounts/{id}/assignees")
async def set_mp_assignees(
    id: int,
    payload: schemas.AssigneesUpdate,
    current: UserCtx = Depends(require_perm("user:assign")),
    db: AsyncSession = Depends(get_db),
):
    data = await service.set_assignees(
        db, mp_id=id, payload=payload, current_id=current.id
    )
    return ok(data)


# ---------------------------------------------------------------------------
# 20 GET /internal/mp-accounts/{app_id}/credential —— 内部凭据(明文 secret)
#     不挂任何用户鉴权依赖;手工校验 X-Internal-Token == settings.INTERNAL_TOKEN。
#     仅供 wx-gateway 容器内网调用(Nginx 已 404 屏蔽 /api/v1/internal/)。
# ---------------------------------------------------------------------------
@router.get("/internal/mp-accounts/{app_id}/credential")
async def internal_get_credential(
    app_id: str,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
    db: AsyncSession = Depends(get_db),
):
    if not x_internal_token or x_internal_token != settings.INTERNAL_TOKEN:
        raise HTTPException(401, "内部令牌无效")
    data = await service.get_credential(db, app_id=app_id)
    return ok(data)
