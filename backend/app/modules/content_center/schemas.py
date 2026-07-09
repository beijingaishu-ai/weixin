"""content-center 出入参模型(Pydantic v2)。

约定:
- 长度红线随 schema:title<=64、digest<=120、author<=64。
- 出参 from_attributes=True 便于直接由 ORM 装配。
- 分页统一 {items,total,page,page_size}。
"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# 素材库
# ---------------------------------------------------------------------------
class MaterialItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    material_type: str
    file_hash: str
    file_size: int
    file_path: str
    origin_url: str = ""
    created_by: int
    created_at: datetime | None = None
    # 本地可访问相对路径(前端拼 /media/ 前缀访问)
    url: str = ""


class MaterialUploadResult(BaseModel):
    id: int
    file_hash: str
    file_path: str
    file_size: int
    url: str


class MaterialPage(BaseModel):
    items: list[MaterialItem]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------
# 样式模板
# ---------------------------------------------------------------------------
class StyleTemplateItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    template_name: str
    description: str = ""
    style_json: str | None = None
    header_html: str | None = None
    footer_html: str | None = None
    category: str
    is_builtin: int
    enabled: int
    created_at: datetime | None = None


class StyleTemplateCreate(BaseModel):
    template_name: str = Field(..., min_length=1, max_length=64)
    description: str = Field("", max_length=255)
    style_json: str | None = None
    header_html: str | None = None
    footer_html: str | None = None
    category: str = Field("card", max_length=16)


# ---------------------------------------------------------------------------
# 图文文章
# ---------------------------------------------------------------------------
class ArticleCreate(BaseModel):
    mp_account_id: int = Field(..., ge=1)
    title: str = Field(..., min_length=1, max_length=64)
    author: str = Field("", max_length=64)
    digest: str = Field("", max_length=120)
    content_html: str = Field(..., min_length=1)
    cover_material_id: int | None = None
    style_template_id: int | None = None
    content_source_url: str = Field("", max_length=512)
    need_open_comment: int = Field(0, ge=0, le=1)
    only_fans_can_comment: int = Field(0, ge=0, le=1)


class ArticleUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=64)
    author: str | None = Field(None, max_length=64)
    digest: str | None = Field(None, max_length=120)
    content_html: str | None = Field(None, min_length=1)
    cover_material_id: int | None = None
    style_template_id: int | None = None
    content_source_url: str | None = Field(None, max_length=512)
    need_open_comment: int | None = Field(None, ge=0, le=1)
    only_fans_can_comment: int | None = Field(None, ge=0, le=1)


class ArticleItem(BaseModel):
    """列表项(不含正文,减负)。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    mp_account_id: int
    title: str
    author: str = ""
    digest: str = ""
    status: str
    cover_material_id: int | None = None
    draft_group_id: int | None = None
    group_position: int = 0
    created_by: int
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ArticleDetail(ArticleItem):
    """详情:含正文与提审辅助字段。"""

    content_html: str
    style_template_id: int | None = None
    content_source_url: str = ""
    need_open_comment: int = 0
    only_fans_can_comment: int = 0
    thumb_media_id: str = ""
    draft_media_id: str = ""


class ArticlePage(BaseModel):
    items: list[ArticleItem]
    total: int
    page: int
    page_size: int


class IdResult(BaseModel):
    id: int


# ---------------------------------------------------------------------------
# 版本
# ---------------------------------------------------------------------------
class VersionItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    content_article_id: int
    version_no: int
    title: str
    digest: str = ""
    change_note: str = ""
    created_by: int
    created_at: datetime | None = None


class VersionCreate(BaseModel):
    change_note: str = Field("", max_length=255)


class RollbackIn(BaseModel):
    version_no: int = Field(..., ge=1)


# ---------------------------------------------------------------------------
# 提审 / 审核
# ---------------------------------------------------------------------------
class SubmitResult(BaseModel):
    id: int
    status: str
    auto_approved: bool
    issues: list[str] = Field(default_factory=list)
    transferred_imgs: int = 0


class AuditIn(BaseModel):
    result: str = Field(..., pattern="^(pass|reject)$")
    opinion: str = Field("", max_length=512)


# ---------------------------------------------------------------------------
# 多图文组
# ---------------------------------------------------------------------------
class DraftGroupCreate(BaseModel):
    mp_account_id: int = Field(..., ge=1)
    group_name: str = Field("", max_length=64)


class GroupAddArticleIn(BaseModel):
    article_id: int = Field(..., ge=1)


class GroupReorderIn(BaseModel):
    article_ids: list[int] = Field(..., min_length=1)


class GroupMemberItem(BaseModel):
    id: int
    title: str
    status: str
    group_position: int
    cover_material_id: int | None = None


class DraftGroupDetail(BaseModel):
    id: int
    mp_account_id: int
    group_name: str = ""
    status: str
    all_approved: bool
    members: list[GroupMemberItem] = Field(default_factory=list)
    created_at: datetime | None = None
