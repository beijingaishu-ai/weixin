"""auth_rbac 纯业务函数(不含 FastAPI 依赖)。

入参为 db(AsyncSession)/ redis(异步客户端)与已解析的数据,返回 ORM/dict/基本类型。
Redis key 约定:
  登录失败计数  login:fail:{username}      TTL=锁定期
  访问令牌黑名单 jwt:block:{jti}            TTL=access 剩余
  刷新令牌白名单 jwt:refresh:{user_id}:{jti} TTL=7d
所有写操作由调用方(router)统一 commit;审计写入用 core.audit.write_audit(内部 flush)。
"""
from datetime import datetime, timezone

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.config import settings
from app.core.exceptions import AppError
from app.core.security import (
    access_ttl_seconds,
    hash_password,
    refresh_ttl_seconds,
    verify_password,
)
from app.models.mp_account import MpAccount, MpAccountAssign
from app.models.audit import AuditRecord
from app.models.user import SysRole, SysUser, SysUserRole
from app.modules.auth_rbac.permissions import (
    is_valid_role,
    perms_of,
    primary_role,
)


# ==================== Redis key helpers ====================
def _fail_key(username: str) -> str:
    return f"login:fail:{username}"


def _block_key(jti: str) -> str:
    return f"jwt:block:{jti}"


def _refresh_key(user_id: int, jti: str) -> str:
    return f"jwt:refresh:{user_id}:{jti}"


async def add_refresh_whitelist(redis: Redis, user_id: int, jti: str) -> None:
    await redis.set(_refresh_key(user_id, jti), "1", ex=refresh_ttl_seconds())


async def is_refresh_whitelisted(redis: Redis, user_id: int, jti: str) -> bool:
    return bool(await redis.get(_refresh_key(user_id, jti)))


async def remove_refresh_token(redis: Redis, user_id: int, jti: str) -> None:
    await redis.delete(_refresh_key(user_id, jti))


async def revoke_all_refresh(redis: Redis, user_id: int) -> None:
    """删除某用户的全部刷新令牌白名单(强制下线 / 改密后重登)。"""
    pattern = f"jwt:refresh:{user_id}:*"
    keys = [k async for k in redis.scan_iter(match=pattern, count=100)]
    if keys:
        await redis.delete(*keys)


async def block_access_jti(redis: Redis, jti: str) -> None:
    await redis.set(_block_key(jti), "1", ex=access_ttl_seconds())


# ==================== 角色装配 ====================
async def load_role_codes(db: AsyncSession, user_id: int) -> list[str]:
    rows = await db.scalars(
        select(SysRole.role_code)
        .join(SysUserRole, SysUserRole.role_id == SysRole.id)
        .where(SysUserRole.user_id == user_id)
    )
    return list(rows)


async def _role_id_map(db: AsyncSession, role_codes: set[str]) -> dict[str, int]:
    """role_code -> role_id;缺失角色由调用方先做 is_valid_role 校验。"""
    rows = await db.execute(
        select(SysRole.role_code, SysRole.id).where(SysRole.role_code.in_(role_codes))
    )
    return {code: rid for code, rid in rows.all()}


async def _count_active_super_admins(db: AsyncSession, exclude_user_id: int | None = None) -> int:
    """统计启用状态(status=1、未软删)且拥有 super_admin 角色的用户数。"""
    stmt = (
        select(func.count(func.distinct(SysUser.id)))
        .select_from(SysUser)
        .join(SysUserRole, SysUserRole.user_id == SysUser.id)
        .join(SysRole, SysRole.id == SysUserRole.role_id)
        .where(
            SysRole.role_code == "super_admin",
            SysUser.status == 1,
            SysUser.is_deleted == 0,
        )
    )
    if exclude_user_id is not None:
        stmt = stmt.where(SysUser.id != exclude_user_id)
    return int(await db.scalar(stmt) or 0)


# ==================== 登录 / 令牌 ====================
async def authenticate(
    db: AsyncSession, redis: Redis, username: str, password: str
) -> tuple[SysUser, list[str]]:
    """校验账号密码(含失败锁定)。返回 (user, role_codes)。

    锁定期内 -> AppError(423);账号密码错误 -> AppError(401,含剩余次数);
    账号停用/软删 -> AppError(403)。成功清除失败计数。
    """
    fail_key = _fail_key(username)
    fails = await redis.get(fail_key)
    fails = int(fails) if fails else 0
    if fails >= settings.LOGIN_MAX_FAIL:
        raise AppError(
            f"账号已锁定,请 {settings.LOGIN_LOCK_MINUTES} 分钟后重试", status_code=423
        )

    user = await db.scalar(
        select(SysUser).where(SysUser.username == username, SysUser.is_deleted == 0)
    )
    if user is None or not verify_password(password, user.password_hash):
        new_fails = await redis.incr(fail_key)
        if new_fails == 1:
            await redis.expire(fail_key, settings.LOGIN_LOCK_MINUTES * 60)
        if new_fails >= settings.LOGIN_MAX_FAIL:
            raise AppError(
                f"用户名或密码错误次数过多,账号已锁定 {settings.LOGIN_LOCK_MINUTES} 分钟",
                status_code=423,
            )
        remaining = settings.LOGIN_MAX_FAIL - new_fails
        raise AppError(f"用户名或密码错误(还可尝试 {remaining} 次)", status_code=401)

    if user.status != 1:
        raise AppError("账号已停用", status_code=403)

    await redis.delete(fail_key)
    role_codes = await load_role_codes(db, user.id)
    return user, role_codes


async def touch_last_login(db: AsyncSession, user: SysUser) -> None:
    user.last_login_at = datetime.now(timezone.utc)
    await db.flush()


# ==================== /auth/me ====================
async def build_me(
    db: AsyncSession, user_id: int, roles: list[str], perms: list[str], visible: set[int] | None
) -> dict:
    """装配 /auth/me 载荷。visible=None 表示全量可见(perm_level=None)。"""
    user = await db.get(SysUser, user_id)

    visible_mp: list[dict] = []
    if visible is None:
        rows = await db.execute(
            select(MpAccount.id, MpAccount.mp_name)
            .where(MpAccount.status == 1, MpAccount.is_deleted == 0)
            .order_by(MpAccount.id)
        )
        for mp_id, mp_name in rows.all():
            visible_mp.append({"id": mp_id, "mp_name": mp_name, "perm_level": None})
    elif visible:
        rows = await db.execute(
            select(MpAccount.id, MpAccount.mp_name, MpAccountAssign.perm_level)
            .join(MpAccountAssign, MpAccountAssign.mp_account_id == MpAccount.id)
            .where(
                MpAccountAssign.user_id == user_id,
                MpAccountAssign.deleted_flag == 0,
                MpAccount.id.in_(visible),
                MpAccount.is_deleted == 0,
            )
            .order_by(MpAccount.id)
        )
        for mp_id, mp_name, perm_level in rows.all():
            visible_mp.append({"id": mp_id, "mp_name": mp_name, "perm_level": perm_level})

    return {
        "id": user_id,
        "username": user.username if user else "",
        "real_name": user.real_name if user else "",
        "role": primary_role(set(roles)),
        "roles": sorted(roles),
        "perms": sorted(perms),
        "visible_mp": visible_mp,
    }


# ==================== 用户管理 ====================
async def list_users(
    db: AsyncSession,
    *,
    page: int,
    page_size: int,
    keyword: str | None = None,
    role: str | None = None,
    status: int | None = None,
) -> dict:
    conds = [SysUser.is_deleted == 0]
    if keyword:
        like = f"%{keyword}%"
        conds.append((SysUser.username.like(like)) | (SysUser.real_name.like(like)))
    if status is not None:
        conds.append(SysUser.status == status)

    user_ids_by_role = None
    if role:
        rows = await db.scalars(
            select(SysUserRole.user_id)
            .join(SysRole, SysRole.id == SysUserRole.role_id)
            .where(SysRole.role_code == role)
        )
        user_ids_by_role = set(rows)
        if not user_ids_by_role:
            return {"items": [], "total": 0, "page": page, "page_size": page_size}
        conds.append(SysUser.id.in_(user_ids_by_role))

    total = int(await db.scalar(select(func.count()).select_from(SysUser).where(*conds)) or 0)

    rows = await db.scalars(
        select(SysUser)
        .where(*conds)
        .order_by(SysUser.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    users = list(rows)

    # 批量装配角色
    role_map: dict[int, list[str]] = {}
    if users:
        uid_list = [u.id for u in users]
        rrows = await db.execute(
            select(SysUserRole.user_id, SysRole.role_code)
            .join(SysRole, SysRole.id == SysUserRole.role_id)
            .where(SysUserRole.user_id.in_(uid_list))
        )
        for uid, code in rrows.all():
            role_map.setdefault(uid, []).append(code)

    items = []
    for u in users:
        items.append(
            {
                "id": u.id,
                "username": u.username,
                "real_name": u.real_name,
                "phone": u.phone,
                "status": u.status,
                "roles": sorted(role_map.get(u.id, [])),
                "created_at": u.created_at,
                "last_login_at": u.last_login_at,
            }
        )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


async def create_user(
    db: AsyncSession,
    *,
    username: str,
    real_name: str,
    password: str,
    role_code: str,
    phone: str | None,
    operator_id: int,
) -> int:
    if not is_valid_role(role_code):
        raise AppError(f"非法角色: {role_code}", status_code=400)

    # username 唯一(含已软删占用):软删时 username 被改写为 username#id,故直接查原名即可判活跃占用;
    # 但为稳妥,任何 username 完全相等(未软删)都算冲突。
    exists = await db.scalar(select(SysUser.id).where(SysUser.username == username))
    if exists:
        raise AppError("用户名已被占用", status_code=400)

    user = SysUser(
        username=username,
        password_hash=hash_password(password),
        real_name=real_name,
        phone=phone or "",
        status=1,
    )
    db.add(user)
    await db.flush()

    role_id = (await _role_id_map(db, {role_code})).get(role_code)
    if role_id is None:
        raise AppError("角色不存在(请检查角色初始化)", status_code=400)
    db.add(SysUserRole(user_id=user.id, role_id=role_id))
    await db.flush()

    await write_audit(
        db,
        action="user.create",
        biz_type="sys_user",
        biz_id=user.id,
        auditor_id=operator_id,
        opinion=f"create user {username} role={role_code}",
    )
    return user.id


async def update_user(
    db: AsyncSession,
    redis: Redis,
    *,
    user_id: int,
    real_name: str | None,
    phone: str | None,
    status: int | None,
    operator_id: int,
) -> None:
    user = await db.get(SysUser, user_id)
    if user is None or user.is_deleted:
        raise AppError("用户不存在", status_code=404)

    disabling = status is not None and status == 0 and user.status != 0
    if disabling:
        # 禁止停用最后一个启用的 super_admin
        remaining = await _count_active_super_admins(db, exclude_user_id=user.id)
        if remaining == 0 and await _has_role(db, user.id, "super_admin"):
            raise AppError("不能停用最后一个超级管理员", status_code=400)

    if real_name is not None:
        user.real_name = real_name
    if phone is not None:
        user.phone = phone
    if status is not None:
        user.status = status
    await db.flush()

    if disabling:
        await revoke_all_refresh(redis, user.id)

    await write_audit(
        db,
        action="user.update",
        biz_type="sys_user",
        biz_id=user.id,
        auditor_id=operator_id,
        opinion=f"update user status={status}",
    )


async def _has_role(db: AsyncSession, user_id: int, role_code: str) -> bool:
    hit = await db.scalar(
        select(SysUserRole.id)
        .join(SysRole, SysRole.id == SysUserRole.role_id)
        .where(SysUserRole.user_id == user_id, SysRole.role_code == role_code)
    )
    return hit is not None


async def set_user_roles(
    db: AsyncSession,
    *,
    user_id: int,
    role_codes: list[str],
    operator_id: int,
) -> None:
    user = await db.get(SysUser, user_id)
    if user is None or user.is_deleted:
        raise AppError("用户不存在", status_code=404)

    codes = list(dict.fromkeys(role_codes))  # 去重保序
    for c in codes:
        if not is_valid_role(c):
            raise AppError(f"非法角色: {c}", status_code=400)

    # 不允许把最后一个启用的 super_admin 降级
    losing_super = await _has_role(db, user_id, "super_admin") and "super_admin" not in codes
    if losing_super:
        remaining = await _count_active_super_admins(db, exclude_user_id=user_id)
        if remaining == 0:
            raise AppError("不能降级最后一个超级管理员", status_code=400)

    id_map = await _role_id_map(db, set(codes))
    missing = [c for c in codes if c not in id_map]
    if missing:
        raise AppError(f"角色未初始化: {', '.join(missing)}", status_code=400)

    # 全量替换
    existing = await db.scalars(select(SysUserRole).where(SysUserRole.user_id == user_id))
    for row in existing:
        await db.delete(row)
    await db.flush()
    for c in codes:
        db.add(SysUserRole(user_id=user_id, role_id=id_map[c]))
    await db.flush()

    await write_audit(
        db,
        action="user.role",
        biz_type="sys_user",
        biz_id=user_id,
        auditor_id=operator_id,
        opinion=f"roles -> {','.join(codes)}",
    )


async def change_password(
    db: AsyncSession,
    redis: Redis,
    *,
    user_id: int,
    new_password: str,
    operator_id: int,
) -> None:
    user = await db.get(SysUser, user_id)
    if user is None or user.is_deleted:
        raise AppError("用户不存在", status_code=404)
    user.password_hash = hash_password(new_password)
    await db.flush()

    # 改密后强制该用户重新登录(清刷新令牌白名单)
    await revoke_all_refresh(redis, user_id)

    await write_audit(
        db,
        action="user.passwd",
        biz_type="sys_user",
        biz_id=user_id,
        auditor_id=operator_id,
        opinion="password changed",
    )


async def list_user_mp_accounts(db: AsyncSession, user_id: int) -> list[dict]:
    rows = await db.execute(
        select(
            MpAccountAssign.mp_account_id,
            MpAccount.mp_name,
            MpAccountAssign.perm_level,
            MpAccountAssign.created_at,
        )
        .join(MpAccount, MpAccount.id == MpAccountAssign.mp_account_id)
        .where(MpAccountAssign.user_id == user_id, MpAccountAssign.deleted_flag == 0)
        .order_by(MpAccountAssign.mp_account_id)
    )
    return [
        {
            "mp_account_id": mp_id,
            "mp_name": mp_name,
            "perm_level": perm_level,
            "assigned_at": created_at,
        }
        for mp_id, mp_name, perm_level, created_at in rows.all()
    ]


# ==================== 审计查询 ====================
async def list_audit_records(
    db: AsyncSession,
    *,
    page: int,
    page_size: int,
    action: str | None = None,
    user_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict:
    conds = []
    if action:
        conds.append(AuditRecord.action == action)
    if user_id is not None:
        conds.append(AuditRecord.auditor_id == user_id)
    if date_from is not None:
        conds.append(AuditRecord.created_at >= date_from)
    if date_to is not None:
        conds.append(AuditRecord.created_at <= date_to)

    total = int(
        await db.scalar(select(func.count()).select_from(AuditRecord).where(*conds)) or 0
    )
    rows = await db.scalars(
        select(AuditRecord)
        .where(*conds)
        .order_by(AuditRecord.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = list(rows)
    return {"items": items, "total": total, "page": page, "page_size": page_size}
