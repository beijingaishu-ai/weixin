"""发布引擎模型(2 张表)。列名严格对齐 schema(设计第 2、7 章)。"""
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
from app.core.states import TaskStatus


class PublishTask(Base):
    __tablename__ = "publish_task"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 幂等键:article:{id} / group:{id}(改期重发追加序号)
    biz_key: Mapped[str] = mapped_column(String(64), nullable=False)
    content_article_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    draft_group_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    mp_account_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # 1=freepublish(发布到主页,不推送) 2=mass(群发,仅认证号)
    publish_type: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    dispatched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=TaskStatus.SCHEDULED)
    # freepublish/submit 回执;任务不存 draft_media_id(归 content_article)
    publish_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    published_article_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    published_url: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retry: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_errcode: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_errmsg: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    is_deleted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (UniqueConstraint("biz_key", name="uk_biz_key"),)


class PublishLog(Base):
    __tablename__ = "publish_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    publish_task_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # DRAFT_ADD / FREEPUBLISH_SUBMIT / FREEPUBLISH_POLL / MATERIAL / RESULT / RETRY / ALERT
    phase: Mapped[str] = mapped_column(String(32), nullable=False)
    from_status: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    to_status: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    wx_api: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    request_digest: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    errcode: Mapped[int | None] = mapped_column(Integer, nullable=True)
    errmsg: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    cost_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
