"""审计记录模型。列名对齐 schema.sql(设计第 2 章 audit_record)。

M1 复用本表记录操作审计:登录/登出、用户与角色变更、公众号分配变更等
(biz_type 取 sys_user / mp_account / mp_account_assign,action 为短码)。
M4 起同表承载内容审核动作(SUBMIT/APPROVE/REJECT/AUTO_APPROVE)。
"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AuditRecord(Base):
    __tablename__ = "audit_record"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    biz_type: Mapped[str] = mapped_column(String(32), nullable=False, default="content_article")
    biz_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # 短码,≤16 字符,如 auth.login / user.create / mp.assign
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    from_status: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    to_status: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    # 操作人;0=系统自动动作
    auditor_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    opinion: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
