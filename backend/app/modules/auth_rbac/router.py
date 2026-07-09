"""auth_rbac 路由(APIRouter,变量名 router;不含 /api/v1 前缀,main.py 统一加)。

覆盖:登录/刷新/登出/me、用户与角色管理、审计查询。
所有成功返回统一 ok(data);分页 data={items,total,page,page_size}。
写操作在路由层统一 commit(service 只 flush + write_audit)。
"""
from datetime import datetime

import jwt
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.audit import write_audit
from app.core.redis import get_redis
from app.core.response import ok
from app.core.security import (
    ACCESS,
    REFRESH,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from app.modules.auth_rbac import service
from app.modules.auth_rbac.deps import (
    UserCtx,
    get_current_user,
    get_visible_mp_ids,
    require_perm,
)
from app.modules.auth_rbac.permissions import (
    BUILTIN_ROLES,
    ROLE_PERMISSIONS,
    perms_of,
    primary_role,
)
from app.modules.auth_rbac.schemas import (
    AuditPage,
    LoginReq,
    LoginUser,
    MeResp,
    RefreshReq,
    RoleItem,
    TokenPair,
    UserCreateReq,
    UserCreateResp,
    UserMpItem,
    UserPage,
    UserPasswordReq,
    UserRolesReq,
    UserUpdateReq,
)

router = APIRouter(tags=["auth_rbac"])

_bearer = HTTPBearer(auto_error=False)


# ==================== 认证 ====================
@router.post("/auth/login")
async def login(
    body: LoginReq,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    user, role_codes = await service.authenticate(db, redis, body.username, body.password)

    role_for_token = primary_role(set(role_codes))
    access, _ = create_access_token(user.id, role_for_token)
    refresh, r_jti = create_refresh_token(user.id)
    await service.add_refresh_whitelist(redis, user.id, r_jti)

    await service.touch_last_login(db, user)
    await write_audit(
        db,
        action="auth.login",
        biz_type="sys_user",
        biz_id=user.id,
        auditor_id=user.id,
    )
    await db.commit()

    perms = sorted(perms_of(set(role_codes)))
    payload = TokenPair(
        access_token=access,
        refresh_token=refresh,
        token_type="bearer",
        user=LoginUser(
            id=user.id, real_name=user.real_name, role=role_for_token, perms=perms
        ),
    )
    return ok(payload.model_dump())


@router.post("/auth/refresh")
async def refresh_token(
    body: RefreshReq,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    try:
        payload = decode_token(body.refresh_token)
    except jwt.PyJWTError:
        raise HTTPException(401, "刷新令牌无效或已过期")
    if payload.get("typ") != REFRESH:
        raise HTTPException(401, "令牌类型错误")

    try:
        uid = int(payload["sub"])
    except (KeyError, ValueError):
        raise HTTPException(401, "令牌载荷异常")
    old_jti = payload.get("jti")
    if not old_jti or not await service.is_refresh_whitelisted(redis, uid, old_jti):
        raise HTTPException(401, "刷新令牌已失效,请重新登录")

    # 账号即时校验(停用/软删则拒绝)
    role_codes = await service.load_role_codes(db, uid)
    from app.models.user import SysUser  # 局部导入避免顶层循环

    user = await db.get(SysUser, uid)
    if user is None or user.status != 1 or user.is_deleted:
        # 顺手清掉这条失效白名单
        await service.remove_refresh_token(redis, uid, old_jti)
        raise HTTPException(401, "账号不存在或已停用")

    # 旋转:删旧、签发新对、新 refresh 入白名单
    await service.remove_refresh_token(redis, uid, old_jti)
    role_for_token = primary_role(set(role_codes))
    access, _ = create_access_token(uid, role_for_token)
    new_refresh, new_jti = create_refresh_token(uid)
    await service.add_refresh_whitelist(redis, uid, new_jti)

    payload_out = TokenPair(
        access_token=access, refresh_token=new_refresh, token_type="bearer", user=None
    )
    return ok(payload_out.model_dump(exclude_none=True))


@router.post("/auth/logout")
async def logout(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    user: UserCtx = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    # get_current_user 不返回 jti,这里再 decode 一次当前 access token 取 jti 入黑名单
    if cred and cred.credentials:
        try:
            payload = decode_token(cred.credentials)
            jti = payload.get("jti")
            if jti:
                await service.block_access_jti(redis, jti)
        except jwt.PyJWTError:
            pass  # 令牌已不可用则无需拉黑

    # 删除该用户全部刷新令牌白名单
    await service.revoke_all_refresh(redis, user.id)

    await write_audit(
        db,
        action="auth.logout",
        biz_type="sys_user",
        biz_id=user.id,
        auditor_id=user.id,
    )
    await db.commit()
    return ok({"logout": True})


@router.get("/auth/me")
async def me(
    user: UserCtx = Depends(get_current_user),
    visible: set[int] | None = Depends(get_visible_mp_ids),
    db: AsyncSession = Depends(get_db),
):
    data = await service.build_me(
        db, user.id, list(user.roles), list(user.perms), visible
    )
    return ok(MeResp(**data).model_dump())


# ==================== 用户管理 ====================
@router.get("/users")
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None),
    role: str | None = Query(None),
    status: int | None = Query(None, ge=0, le=1),
    user: UserCtx = Depends(require_perm("user:manage")),
    db: AsyncSession = Depends(get_db),
):
    data = await service.list_users(
        db,
        page=page,
        page_size=page_size,
        keyword=keyword,
        role=role,
        status=status,
    )
    return ok(UserPage(**data).model_dump())


@router.post("/users")
async def create_user(
    body: UserCreateReq,
    user: UserCtx = Depends(require_perm("user:manage")),
    db: AsyncSession = Depends(get_db),
):
    new_id = await service.create_user(
        db,
        username=body.username,
        real_name=body.real_name,
        password=body.password,
        role_code=body.role_code,
        phone=body.phone,
        operator_id=user.id,
    )
    await db.commit()
    return ok(UserCreateResp(id=new_id).model_dump())


@router.put("/users/{id}")
async def update_user(
    body: UserUpdateReq,
    id: int = Path(..., ge=1),
    user: UserCtx = Depends(require_perm("user:manage")),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    await service.update_user(
        db,
        redis,
        user_id=id,
        real_name=body.real_name,
        phone=body.phone,
        status=body.status,
        operator_id=user.id,
    )
    await db.commit()
    return ok({"updated": True})


@router.put("/users/{id}/roles")
async def update_user_roles(
    body: UserRolesReq,
    id: int = Path(..., ge=1),
    user: UserCtx = Depends(require_perm("user:manage")),
    db: AsyncSession = Depends(get_db),
):
    await service.set_user_roles(
        db,
        user_id=id,
        role_codes=body.role_codes,
        operator_id=user.id,
    )
    await db.commit()
    return ok({"updated": True})


@router.put("/users/{id}/password")
async def update_user_password(
    body: UserPasswordReq,
    id: int = Path(..., ge=1),
    user: UserCtx = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    # user:manage 或本人可改
    if id != user.id and not user.has("user:manage"):
        raise HTTPException(403, "无权修改该用户密码")
    await service.change_password(
        db,
        redis,
        user_id=id,
        new_password=body.new_password,
        operator_id=user.id,
    )
    await db.commit()
    return ok({"updated": True})


@router.get("/users/{id}/mp-accounts")
async def list_user_mp(
    id: int = Path(..., ge=1),
    user: UserCtx = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # user:assign 或本人可查
    if id != user.id and not user.has("user:assign"):
        raise HTTPException(403, "无权查看该用户的公众号分配")
    items = await service.list_user_mp_accounts(db, id)
    return ok([UserMpItem(**it).model_dump() for it in items])


# ==================== 角色 ====================
@router.get("/roles")
async def list_roles(
    user: UserCtx = Depends(get_current_user),
):
    items = [
        RoleItem(
            role_code=code,
            role_name=name,
            perms=sorted(ROLE_PERMISSIONS.get(code, set())),
        ).model_dump()
        for code, name in BUILTIN_ROLES
    ]
    return ok(items)


# ==================== 审计查询 ====================
@router.get("/audit-records")
async def list_audit_records(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    action: str | None = Query(None),
    user_id: int | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    user: UserCtx = Depends(require_perm("user:manage")),
    db: AsyncSession = Depends(get_db),
):
    data = await service.list_audit_records(
        db,
        page=page,
        page_size=page_size,
        action=action,
        user_id=user_id,
        date_from=date_from,
        date_to=date_to,
    )
    return ok(AuditPage(**data).model_dump())
