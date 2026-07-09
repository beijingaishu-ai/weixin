"""mp_manager 业务逻辑:公众号档案 CRUD + AppSecret 加密 + 运营分配 + 内部凭据。

约定:
- 数据权限只走 apply_mp_scope(deps 唯一出口);本层不自造可见性判断。
- 所有出参绝不含 app_secret / app_secret_cipher;台账仅回显固定占位。
- 写操作由本层 commit(审计 write_audit 只 flush,commit 责任在调用链此处收口)。
"""
import json

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.crypto import (
    CryptoConfigError,
    current_key_version,
    decrypt_secret,
    encrypt_secret,
)
from app.core.exceptions import AppError
from app.models.mp_account import MpAccount, MpAccountAssign
from app.models.user import SysUser
from app.modules.auth_rbac.deps import apply_mp_scope
from app.modules.mp_manager import schemas


# ---------------------------------------------------------------------------
# 序列化助手(集中把 ORM -> 出参 dict,确保永不带出 secret 列)
# ---------------------------------------------------------------------------
def _to_item(acc: MpAccount) -> dict:
    return {
        "id": acc.id,
        "mp_name": acc.mp_name,
        "wx_original_id": acc.wx_original_id,
        "app_id": acc.app_id,
        "account_type": acc.account_type,
        "is_verified": acc.is_verified,
        "need_review": acc.need_review,
        "ip_whitelist_ok": acc.ip_whitelist_ok,
        "status": acc.status,
        "last_verified_at": acc.last_verified_at,
        "remark": acc.remark,
        "created_at": acc.created_at,
        "app_secret_masked": "****",
    }


async def _load_assignees(db: AsyncSession, mp_id: int) -> list[dict]:
    """该号有效分配人(deleted_flag=0),联表取 real_name。"""
    rows = await db.execute(
        select(
            MpAccountAssign.user_id,
            SysUser.real_name,
            MpAccountAssign.perm_level,
            MpAccountAssign.created_at,
        )
        .join(SysUser, SysUser.id == MpAccountAssign.user_id)
        .where(
            MpAccountAssign.mp_account_id == mp_id,
            MpAccountAssign.deleted_flag == 0,
        )
        .order_by(MpAccountAssign.user_id)
    )
    return [
        {
            "user_id": r.user_id,
            "real_name": r.real_name,
            "perm_level": r.perm_level,
            "assigned_at": r.created_at,
        }
        for r in rows.all()
    ]


async def _get_account_or_404(db: AsyncSession, mp_id: int) -> MpAccount:
    acc = await db.get(MpAccount, mp_id)
    if acc is None or acc.is_deleted:
        raise AppError("公众号不存在", status_code=404)
    return acc


# ---------------------------------------------------------------------------
# 11 分页台账
# ---------------------------------------------------------------------------
async def list_accounts(
    db: AsyncSession,
    *,
    visible: set[int] | None,
    page: int,
    page_size: int,
    keyword: str | None,
    status: int | None,
) -> dict:
    base = select(MpAccount).where(MpAccount.is_deleted == 0)
    base = apply_mp_scope(base, MpAccount.id, visible)

    if keyword:
        like = f"%{keyword.strip()}%"
        base = base.where(
            or_(
                MpAccount.mp_name.like(like),
                MpAccount.app_id.like(like),
                MpAccount.wx_original_id.like(like),
            )
        )
    if status is not None:
        base = base.where(MpAccount.status == status)

    total = await db.scalar(
        select(func.count()).select_from(base.order_by(None).subquery())
    )

    rows = await db.scalars(
        base.order_by(MpAccount.id.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    items = [_to_item(acc) for acc in rows.all()]
    return {"items": items, "total": total or 0, "page": page, "page_size": page_size}


# ---------------------------------------------------------------------------
# 12 创建
# ---------------------------------------------------------------------------
async def create_account(
    db: AsyncSession, *, payload: schemas.MpAccountCreate, current_id: int
) -> dict:
    # app_id 唯一(仅看未删行;已删占位不冲突)
    exists = await db.scalar(
        select(MpAccount.id).where(
            MpAccount.app_id == payload.app_id, MpAccount.is_deleted == 0
        )
    )
    if exists:
        raise AppError("该 app_id 已存在", status_code=400)

    ver = current_key_version()
    try:
        cipher = encrypt_secret(payload.app_id, payload.app_secret, ver)
    except CryptoConfigError as e:
        raise AppError(f"加密配置异常: {e}", status_code=500) from e

    acc = MpAccount(
        mp_name=payload.mp_name,
        wx_original_id=payload.wx_original_id or "",
        app_id=payload.app_id,
        app_secret_cipher=cipher,
        key_version=ver,
        account_type=payload.account_type,
        is_verified=payload.is_verified or 0,
        remark=payload.remark or "",
        created_by=current_id,
    )
    db.add(acc)
    await db.flush()  # 取 acc.id

    await write_audit(
        db,
        action="mp.create",
        biz_type="mp_account",
        biz_id=acc.id,
        auditor_id=current_id,
        opinion=f"创建公众号 {payload.mp_name}({payload.app_id})",
    )
    await db.commit()
    return {"id": acc.id}


# ---------------------------------------------------------------------------
# 13 详情
# ---------------------------------------------------------------------------
async def get_account_detail(db: AsyncSession, *, mp_id: int) -> dict:
    acc = await _get_account_or_404(db, mp_id)
    data = _to_item(acc)
    data["assignees"] = await _load_assignees(db, mp_id)
    return data


# ---------------------------------------------------------------------------
# 14 更新
# ---------------------------------------------------------------------------
async def update_account(
    db: AsyncSession,
    *,
    mp_id: int,
    payload: schemas.MpAccountUpdate,
    current,
    redis=None,
) -> None:
    acc = await _get_account_or_404(db, mp_id)

    # need_review 变更收紧:仅持有 system:config:manage(super_admin)可改
    if payload.need_review is not None and not current.has("system:config:manage"):
        raise AppError("无权修改审核开关(need_review)", status_code=403)

    changed_fields: list[str] = []

    if payload.mp_name is not None:
        acc.mp_name = payload.mp_name
        changed_fields.append("mp_name")
    if payload.status is not None:
        acc.status = payload.status
        changed_fields.append("status")
    if payload.need_review is not None:
        acc.need_review = payload.need_review
        changed_fields.append("need_review")
    if payload.remark is not None:
        acc.remark = payload.remark
        changed_fields.append("remark")
    if payload.is_verified is not None:
        acc.is_verified = payload.is_verified
        changed_fields.append("is_verified")

    if payload.app_secret is not None:
        ver = current_key_version()
        try:
            acc.app_secret_cipher = encrypt_secret(acc.app_id, payload.app_secret, ver)
        except CryptoConfigError as e:
            raise AppError(f"加密配置异常: {e}", status_code=500) from e
        acc.key_version = ver
        changed_fields.append("app_secret")
        # 换密后清理 M2 wx-gateway 的 access_token 缓存(有则删,无则忽略)
        if redis is not None:
            try:
                await redis.delete(f"wx:token:{acc.app_id}")
            except Exception:  # noqa: BLE001 —— 缓存清理失败不阻断换密主流程
                pass

    await write_audit(
        db,
        action="mp.update",
        biz_type="mp_account",
        biz_id=acc.id,
        auditor_id=current.id,
        opinion=f"更新字段: {', '.join(changed_fields) or '无'}",
    )
    await db.commit()


# ---------------------------------------------------------------------------
# 15 校验(M1:密文自检,不真调微信)
# ---------------------------------------------------------------------------
async def verify_account(db: AsyncSession, *, mp_id: int, current_id: int) -> dict:
    acc = await _get_account_or_404(db, mp_id)

    try:
        decrypt_secret(acc.app_id, acc.app_secret_cipher, acc.key_version)
        ok_flag = True
        hint = (
            "密文可正常解密; 真实 access_token 校验将在 M2 接入 wx-gateway 后生效"
            "(届时校验 40164 IP 白名单)"
        )
        if acc.account_type == 3:
            hint += "; 该测试/模拟号(account_type=3)将走 MockChannel"
    except Exception:  # noqa: BLE001 —— 解密失败即密钥/密文异常
        ok_flag = False
        hint = "密文解密失败, 密钥或密文异常, 请重新录入 AppSecret"

    await write_audit(
        db,
        action="mp.verify",
        biz_type="mp_account",
        biz_id=acc.id,
        auditor_id=current_id,
        opinion=f"密文自检: {'通过' if ok_flag else '失败'}",
    )
    await db.commit()
    return {"ok": ok_flag, "checked": "cipher", "hint": hint}


# ---------------------------------------------------------------------------
# 浏览器发布登录态授权:状态查询 + 手动吊销(续扫入口一期)
# ---------------------------------------------------------------------------
async def login_auth_status(db: AsyncSession, *, mp_id: int) -> dict:
    """返回该号浏览器发布登录态授权状态 + 续扫指引。测试/模拟号无需授权。"""
    acc = await _get_account_or_404(db, mp_id)
    is_mock = acc.account_type == 3
    return {
        "mp_id": acc.id,
        "mp_name": acc.mp_name,
        "is_mock": is_mock,
        "wx_login_status": "MOCK" if is_mock else acc.wx_login_status,
        "wx_login_captured_at": acc.wx_login_captured_at,
        "wx_login_expires_at": acc.wx_login_expires_at,
        "wx_login_ttl_hours": acc.wx_login_ttl_hours,
        # 一期续扫保底:在部署机执行该命令有头扫码续期(详见设计文档第 4 章)
        "reauth_cmd": None if is_mock else f"python scripts/wx_login.py {acc.app_id}",
    }


async def mark_login_revoked(db: AsyncSession, *, mp_id: int, current_id: int) -> dict:
    """管理员手动吊销该号登录态(强制下次发布前重新扫码)。仅对授权窗口内的号有意义。"""
    from app.core.states import WxLoginStatus, ensure_transition

    acc = await _get_account_or_404(db, mp_id)
    if acc.account_type == 3:
        return {"ok": False, "hint": "测试/模拟号(account_type=3)无需登录态授权"}
    if acc.wx_login_status not in (WxLoginStatus.AUTHORIZED, WxLoginStatus.EXPIRING):
        return {"ok": True, "wx_login_status": acc.wx_login_status, "hint": "该号本就未在授权窗口内"}
    ensure_transition("mp_account_login", acc.wx_login_status, WxLoginStatus.REVOKED)
    acc.wx_login_status = WxLoginStatus.REVOKED
    acc.wx_login_alerted_at = None
    await write_audit(
        db, action="mp.login_revoke", biz_type="mp_account",
        biz_id=acc.id, auditor_id=current_id, opinion="手动吊销浏览器发布登录态,需重新扫码续期",
    )
    await db.commit()
    return {"ok": True, "wx_login_status": acc.wx_login_status}


# ---------------------------------------------------------------------------
# 16 分配人清单
# ---------------------------------------------------------------------------
async def list_assignees(db: AsyncSession, *, mp_id: int) -> list[dict]:
    await _get_account_or_404(db, mp_id)
    return await _load_assignees(db, mp_id)


# ---------------------------------------------------------------------------
# 17 全量覆盖式分配
# ---------------------------------------------------------------------------
async def set_assignees(
    db: AsyncSession,
    *,
    mp_id: int,
    payload: schemas.AssigneesUpdate,
    current_id: int,
) -> dict:
    await _get_account_or_404(db, mp_id)

    # 去重:同一 user_id 以最后一次 perm_level 为准
    desired: dict[int, int] = {a.user_id: a.perm_level for a in payload.assignments}

    # 校验目标用户存在且未删
    if desired:
        valid_ids = set(
            await db.scalars(
                select(SysUser.id).where(
                    SysUser.id.in_(desired.keys()), SysUser.is_deleted == 0
                )
            )
        )
        missing = set(desired.keys()) - valid_ids
        if missing:
            raise AppError(
                f"用户不存在或已删除: {sorted(missing)}", status_code=400
            )

    # 现有有效分配
    existing_rows = (
        await db.execute(
            select(MpAccountAssign).where(
                MpAccountAssign.mp_account_id == mp_id,
                MpAccountAssign.deleted_flag == 0,
            )
        )
    ).scalars().all()
    existing: dict[int, MpAccountAssign] = {r.user_id: r for r in existing_rows}

    added: list[int] = []
    removed: list[int] = []
    changed: list[int] = []

    # 移除:现有里不在 desired 的 -> 软删(deleted_flag = 本行 id)
    for uid, row in existing.items():
        if uid not in desired:
            row.deleted_flag = row.id
            removed.append(uid)

    # 新增 / 变更
    for uid, level in desired.items():
        if uid in existing:
            row = existing[uid]
            if row.perm_level != level:
                row.perm_level = level
                changed.append(uid)
        else:
            # 曾被软删的 (user,mp) 因唯一键含 deleted_flag 可再次 insert
            db.add(
                MpAccountAssign(
                    user_id=uid,
                    mp_account_id=mp_id,
                    perm_level=level,
                    assigned_by=current_id,
                    deleted_flag=0,
                )
            )
            added.append(uid)

    summary = json.dumps(
        {"added": sorted(added), "removed": sorted(removed), "changed": sorted(changed)},
        ensure_ascii=False,
    )
    await write_audit(
        db,
        action="mp.assign",
        biz_type="mp_account_assign",
        biz_id=mp_id,
        auditor_id=current_id,
        opinion=summary,
    )
    await db.commit()
    return {"added": sorted(added), "removed": sorted(removed), "changed": sorted(changed)}


# ---------------------------------------------------------------------------
# 20 内部凭据(明文 secret;仅内网 wx-gateway 调用)
# ---------------------------------------------------------------------------
async def get_credential(db: AsyncSession, *, app_id: str) -> dict:
    acc = await db.scalar(
        select(MpAccount).where(
            MpAccount.app_id == app_id, MpAccount.is_deleted == 0
        )
    )
    if acc is None:
        raise AppError("公众号不存在", status_code=404)
    try:
        plain = decrypt_secret(acc.app_id, acc.app_secret_cipher, acc.key_version)
    except Exception as e:  # noqa: BLE001
        raise AppError("凭据解密失败", status_code=500) from e
    return {"app_id": acc.app_id, "app_secret": plain}
