"""内容中心模型(6 张表)。列名严格对齐 schema(设计第 2、4 章)。

注:content_article 的 collect_article_id / mapping_rule_id 指向 M3 表,M2 阶段建为可空列、
暂不加物理外键(M3 建表时再补),因此本模型也不声明这两个关系。
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
from app.core.states import ArticleStatus, GroupStatus


class ContentMaterial(Base):
    __tablename__ = "content_material"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    material_type: Mapped[str] = mapped_column(String(16), nullable=False)  # image/thumb/...
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)      # SHA-256 全库去重
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    origin_url: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (UniqueConstraint("file_hash", "material_type", name="uk_hash_type"),)


class ContentMaterialWxRef(Base):
    __tablename__ = "content_material_wx_ref"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    material_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mp_account_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    media_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    wx_url: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (UniqueConstraint("material_id", "mp_account_id", name="uk_mat_mp"),)


class ContentStyleTemplate(Base):
    __tablename__ = "content_style_template"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    template_name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    style_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    header_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    footer_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    # category 归入 style_json 或 description;这里补一个显式列便于按类查询
    category: Mapped[str] = mapped_column(String(16), nullable=False, default="card")
    is_builtin: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    is_deleted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (UniqueConstraint("template_name", name="uk_name"),)


class ContentDraftGroup(Base):
    __tablename__ = "content_draft_group"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    mp_account_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    group_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    # EDITING / READY / PUBLISHED(组局部状态,非统一发文状态机)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=GroupStatus.EDITING)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    is_deleted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class ContentArticle(Base):
    __tablename__ = "content_article"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    mp_account_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # 指向 M3 表,M2 期为可空列、无物理外键
    collect_article_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    mapping_rule_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    draft_group_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    group_position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    style_template_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    title: Mapped[str] = mapped_column(String(64), nullable=False)
    author: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    digest: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    content_html: Mapped[str] = mapped_column(Text, nullable=False)
    thumb_media_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    # 封面本地素材(便于建草稿时定位封面文件);微信侧 media_id 存 thumb_media_id
    cover_material_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    draft_media_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    suggested_publish_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    need_open_comment: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    only_fans_can_comment: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_source_url: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    is_original_marked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ArticleStatus.TRANSFORMED
    )
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    is_deleted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("collect_article_id", "mp_account_id", name="uk_collect_mp"),
    )


class ContentArticleVersion(Base):
    __tablename__ = "content_article_version"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    content_article_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(64), nullable=False)
    digest: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    content_html: Mapped[str] = mapped_column(Text, nullable=False)
    change_note: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("content_article_id", "version_no", name="uk_art_ver"),
    )
