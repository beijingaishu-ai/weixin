"""审计写入助手:统一写 audit_record(操作留痕)。

M1 用于登录/登出、用户与角色变更、公众号分配变更等操作审计。
action 为短码(≤16 字符),biz_type 标识业务对象。调用方负责 commit。
"""
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditRecord


async def write_audit(
    db: AsyncSession,
    *,
    action: str,
    biz_type: str,
    biz_id: int,
    auditor_id: int | None,
    opinion: str = "",
    from_status: str = "",
    to_status: str = "",
) -> AuditRecord:
    rec = AuditRecord(
        biz_type=biz_type,
        biz_id=biz_id,
        action=action[:16],
        from_status=from_status,
        to_status=to_status,
        auditor_id=auditor_id,
        opinion=opinion[:512],
    )
    db.add(rec)
    await db.flush()
    return rec
