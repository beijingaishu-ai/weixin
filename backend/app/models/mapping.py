"""映射引擎模型(2 张表)。列名对齐 schema(设计第 2、6 章)。

多源→单目标:mapping_rule 一条一个 target_mp_account_id,采集源经 mapping_rule_source
关联(多对多),priority 数值越大越优先。
"""
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class MappingRule(Base):
    __tablename__ = "mapping_rule"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    rule_name: Mapped[str] = mapped_column(String(64), nullable=False)
    target_mp_account_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    match_condition_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    transform_action_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    schedule_policy_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 数值越大越优先,按 priority DESC 匹配,命中即停
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    is_deleted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class MappingRuleSource(Base):
    __tablename__ = "mapping_rule_source"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    rule_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (UniqueConstraint("rule_id", "source_id", name="uk_rule_source"),)
