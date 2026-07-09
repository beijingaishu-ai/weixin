"""认证 & 数据权限依赖(对齐设计 3.6.2)。

- get_current_user:解析 JWT → 查库校验 status(即时封禁)→ 装配角色/权限(以 DB 为准,
  角色变更无需重登即生效)。
- require_perm:功能权限守卫(缺权限 → 403)。
- get_visible_mp_ids / apply_mp_scope:数据权限唯一出口(operator 只见被分配号)。
- require_mp_access(need_level):详情/写操作守卫,叠加 perm_level 分级校验,防 IDOR 水平越权。
"""
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Path
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.redis import get_redis
from app.core.security import ACCESS, decode_token
from app.models.mp_account import MpAccountAssign
from app.models.user import SysRole, SysUser, SysUserRole
from app.modules.auth_rbac.permissions import (
    FULL_ACCESS_ROLES,
    perms_of,
    primary_role,
)

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class UserCtx:
    id: int
    roles: frozenset[str]
    perms: frozenset[str]

    @property
    def role(self) -> str:
        """展示用主角色。"""
        return primary_role(set(self.roles))

    @property
    def is_full_access(self) -> bool:
        return bool(self.roles & FULL_ACCESS_ROLES)

    def has(self, perm: str) -> bool:
        return perm in self.perms


async def load_roles(db: AsyncSession, user_id: int) -> set[str]:
    rows = await db.scalars(
        select(SysRole.role_code)
        .join(SysUserRole, SysUserRole.role_id == SysRole.id)
        .where(SysUserRole.user_id == user_id)
    )
    return set(rows)


async def get_current_user(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> UserCtx:
    if cred is None or not cred.credentials:
        raise HTTPException(401, "未提供访问令牌")
    try:
        payload = decode_token(cred.credentials)
    except jwt.PyJWTError:
        raise HTTPException(401, "令牌无效或已过期")
    if payload.get("typ") != ACCESS:
        raise HTTPException(401, "令牌类型错误")

    jti = payload.get("jti")
    if jti and await redis.get(f"jwt:block:{jti}"):
        raise HTTPException(401, "令牌已失效,请重新登录")

    try:
        uid = int(payload["sub"])
    except (KeyError, ValueError):
        raise HTTPException(401, "令牌载荷异常")

    user = await db.get(SysUser, uid)
    if user is None or user.status != 1 or user.is_deleted:
        raise HTTPException(401, "账号不存在或已停用")

    roles = await load_roles(db, uid)
    return UserCtx(id=uid, roles=frozenset(roles), perms=frozenset(perms_of(roles)))


def require_perm(*required: str):
    """功能权限守卫(依赖工厂):须持有全部 required 权限点。"""

    async def _guard(user: UserCtx = Depends(get_current_user)) -> UserCtx:
        missing = [p for p in required if p not in user.perms]
        if missing:
            raise HTTPException(403, f"缺少权限: {', '.join(missing)}")
        return user

    return _guard


async def get_visible_mp_ids(
    user: UserCtx = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> set[int] | None:
    """None=全量可见(角色特权);集合=仅可见集合内公众号(可能为空集)。"""
    if user.is_full_access:
        return None
    rows = await db.scalars(
        select(MpAccountAssign.mp_account_id).where(
            MpAccountAssign.user_id == user.id,
            MpAccountAssign.deleted_flag == 0,
        )
    )
    return set(rows)


def apply_mp_scope(stmt, mp_col, visible: set[int] | None):
    """数据权限唯一出口:None 放行全量;否则限定在可见集合内(空集 → IN (-1) 得空结果)。"""
    if visible is None:
        return stmt
    return stmt.where(mp_col.in_(visible or {-1}))


def require_mp_access(need_level: int = 1):
    """单号访问守卫(依赖工厂):路径参数 id 为公众号 id。
    角色特权直通;operator 须 perm_level >= need_level,否则 403(不泄露该号是否存在)。
    need_level:1=只读 2=编辑 3=提审 4=发布。
    """

    async def _guard(
        id: int = Path(..., description="公众号 id"),
        user: UserCtx = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> int:
        if user.is_full_access:
            return id
        perm_level = await db.scalar(
            select(MpAccountAssign.perm_level).where(
                MpAccountAssign.user_id == user.id,
                MpAccountAssign.mp_account_id == id,
                MpAccountAssign.deleted_flag == 0,
            )
        )
        if perm_level is None or perm_level < need_level:
            raise HTTPException(403, "无权访问该公众号")
        return id

    return _guard
