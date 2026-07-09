"""采集中心模型(2 张表)。列名对齐 schema(设计第 2、5 章)。

simhash 存 16 位十六进制字符串(避开 MySQL 无符号 BIGINT 与 SQLite 兼容问题);
simhash_b0..b3 为 4 段各 16 位的普通索引列,由采集服务在写入前计算填充(非 MySQL 生成列,
以便同一套 ORM 在 SQLite 测试库跑通)。
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
from app.core.states import CollectStatus


class CollectSource(Base):
    __tablename__ = "collect_source"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_name: Mapped[str] = mapped_column(String(64), nullable=False)
    adapter_type: Mapped[str] = mapped_column(String(32), nullable=False)  # mock/rss/manual
    config_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    cursor_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=120)
    jitter_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 原创转载授权人工确认(微信无 API 可查他人白名单;线下取得授权后手工置位)
    whitelist_confirmed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    auth_proof_url: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    # ACTIVE / PAUSED / CIRCUIT_OPEN(源局部状态,非统一发文状态机)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    fail_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    is_deleted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class CollectArticle(Base):
    __tablename__ = "collect_article"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    author: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    url: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    url_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # 精确去重指纹(唯一)
    simhash: Mapped[str] = mapped_column(String(16), nullable=False, default="0")  # 16位hex
    simhash_b0: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    simhash_b1: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    simhash_b2: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    simhash_b3: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 近似去重命中时指向留存文章,本行置 UNMATCHED
    dedup_of: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    digest: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    raw_html: Mapped[str] = mapped_column(Text, nullable=False, default="")
    clean_html: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cover_url: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    is_original_marked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 无规则命中 / 去重 / 原创拦截时记录原因,便于运营复盘
    unmatched_reason: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    source_publish_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=CollectStatus.COLLECTED)
    collected_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    is_deleted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (UniqueConstraint("url_hash", name="uk_url_hash"),)
