"""content-center 路由:素材库 / 样式模板 / 图文编排 / 版本 / 提审 / 审核 / 多图文组。

前缀 /api/v1 由 main include_router 追加;本文件挂 /materials、/style-templates、
/articles、/draft-groups。

数据权限:
- 列表走 get_visible_mp_ids + apply_mp_scope(service 内)。
- 单号写操作:因路径参数是 article/group 的 id(非公众号 id),deps.require_mp_access 不直接适用,
  故用本文件的 _require_article_mp_access / _require_group_mp_access 解析归属公众号后按 perm_level 校验
  (语义等同 require_mp_access,防水平越权)。
- body 带 mp_account_id 的接口(建文章/建组)在 service._assert_mp_edit 里手工校验。
审核接口对全部号可见角色放行,不叠加单号守卫。
"""
from fastapi import APIRouter, Depends, File, HTTPException, Path, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.response import ok
from app.models.content import ContentArticle, ContentDraftGroup
from app.models.mp_account import MpAccountAssign
from app.modules.auth_rbac.deps import (
    UserCtx,
    get_current_user,
    get_visible_mp_ids,
    require_perm,
)
from app.modules.content_center import schemas, service
from app.modules.wx_gateway.gateway import WxGateway, get_gateway

router = APIRouter(tags=["content-center"])


# ---------------------------------------------------------------------------
# 单号数据权限:解析 article / group 归属公众号后按 perm_level 校验(防 IDOR 水平越权)
# ---------------------------------------------------------------------------
async def _assert_perm_level(
    db: AsyncSession, *, user: UserCtx, mp_id: int, need_level: int
) -> None:
    if user.is_full_access:
        return
    perm_level = await db.scalar(
        select(MpAccountAssign.perm_level).where(
            MpAccountAssign.user_id == user.id,
            MpAccountAssign.mp_account_id == mp_id,
            MpAccountAssign.deleted_flag == 0,
        )
    )
    if perm_level is None or perm_level < need_level:
        raise HTTPException(403, "无权访问该公众号")


def _require_article_mp_access(need_level: int):
    """依赖工厂:路径参数 id = 图文 id;解析其 mp_account_id 后按 perm_level 守卫。"""

    async def _guard(
        id: int = Path(..., description="图文 id"),
        user: UserCtx = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> int:
        art = await db.get(ContentArticle, id)
        if art is None or art.is_deleted:
            raise HTTPException(404, "图文不存在")
        await _assert_perm_level(db, user=user, mp_id=art.mp_account_id, need_level=need_level)
        return id

    return _guard


def _require_group_mp_access(need_level: int):
    """依赖工厂:路径参数 id = 图文组 id;解析其 mp_account_id 后按 perm_level 守卫。"""

    async def _guard(
        id: int = Path(..., description="图文组 id"),
        user: UserCtx = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> int:
        grp = await db.get(ContentDraftGroup, id)
        if grp is None or grp.is_deleted:
            raise HTTPException(404, "图文组不存在")
        await _assert_perm_level(db, user=user, mp_id=grp.mp_account_id, need_level=need_level)
        return id

    return _guard


# ===========================================================================
# 素材库
# ===========================================================================
@router.post("/materials")
async def upload_material(
    file: UploadFile = File(...),
    material_type: str = Query("image"),
    current: UserCtx = Depends(require_perm("content:material:upload")),
    db: AsyncSession = Depends(get_db),
):
    data = await file.read()
    result = await service.upload_material(
        db,
        filename=file.filename or "upload.jpg",
        data=data,
        material_type=material_type,
        current_id=current.id,
    )
    return ok(result)


@router.get("/materials")
async def list_materials(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    material_type: str | None = Query(None),
    keyword: str | None = Query(None),
    _: UserCtx = Depends(require_perm("content:material:view")),
    db: AsyncSession = Depends(get_db),
):
    data = await service.list_materials(
        db,
        page=page,
        page_size=page_size,
        material_type=material_type,
        keyword=keyword,
    )
    return ok(data)


@router.delete("/materials/{id}")
async def delete_material(
    id: int,
    _: UserCtx = Depends(require_perm("content:material:upload")),
    db: AsyncSession = Depends(get_db),
):
    await service.delete_material(db, material_id=id)
    return ok()


# ===========================================================================
# 样式模板
# ===========================================================================
@router.get("/style-templates")
async def list_style_templates(
    category: str | None = Query(None),
    _: UserCtx = Depends(require_perm("content:article:edit")),
    db: AsyncSession = Depends(get_db),
):
    data = await service.list_style_templates(db, category=category)
    return ok(data)


@router.post("/style-templates")
async def create_style_template(
    payload: schemas.StyleTemplateCreate,
    current: UserCtx = Depends(require_perm("content:template:manage")),
    db: AsyncSession = Depends(get_db),
):
    data = await service.create_style_template(db, payload=payload, current_id=current.id)
    return ok(data)


# ===========================================================================
# 图文文章
# ===========================================================================
@router.post("/articles")
async def create_article(
    payload: schemas.ArticleCreate,
    current: UserCtx = Depends(require_perm("content:article:edit")),
    db: AsyncSession = Depends(get_db),
):
    data = await service.create_article(db, payload=payload, current=current)
    return ok(data)


@router.get("/articles")
async def list_articles(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    mp_account_id: int | None = Query(None),
    status: str | None = Query(None),
    keyword: str | None = Query(None),
    _: UserCtx = Depends(require_perm("content:article:view")),
    visible: set[int] | None = Depends(get_visible_mp_ids),
    db: AsyncSession = Depends(get_db),
):
    data = await service.list_articles(
        db,
        visible=visible,
        page=page,
        page_size=page_size,
        mp_account_id=mp_account_id,
        status=status,
        keyword=keyword,
    )
    return ok(data)


@router.get("/articles/{id}")
async def get_article(
    _: UserCtx = Depends(require_perm("content:article:view")),
    article_id: int = Depends(_require_article_mp_access(need_level=1)),
    db: AsyncSession = Depends(get_db),
):
    data = await service.get_article_detail(db, article_id=article_id)
    return ok(data)


@router.put("/articles/{id}")
async def update_article(
    payload: schemas.ArticleUpdate,
    current: UserCtx = Depends(require_perm("content:article:edit")),
    article_id: int = Depends(_require_article_mp_access(need_level=2)),
    db: AsyncSession = Depends(get_db),
):
    await service.update_article(
        db, article_id=article_id, payload=payload, current=current
    )
    return ok()


# ---- 版本 ----
@router.post("/articles/{id}/versions")
async def create_version(
    payload: schemas.VersionCreate,
    current: UserCtx = Depends(require_perm("content:article:edit")),
    article_id: int = Depends(_require_article_mp_access(need_level=2)),
    db: AsyncSession = Depends(get_db),
):
    data = await service.create_version(
        db, article_id=article_id, payload=payload, current_id=current.id
    )
    return ok(data)


@router.get("/articles/{id}/versions")
async def list_versions(
    _: UserCtx = Depends(require_perm("content:article:view")),
    article_id: int = Depends(_require_article_mp_access(need_level=1)),
    db: AsyncSession = Depends(get_db),
):
    data = await service.list_versions(db, article_id=article_id)
    return ok(data)


@router.post("/articles/{id}/rollback")
async def rollback_article(
    payload: schemas.RollbackIn,
    current: UserCtx = Depends(require_perm("content:article:edit")),
    article_id: int = Depends(_require_article_mp_access(need_level=2)),
    db: AsyncSession = Depends(get_db),
):
    data = await service.rollback_article(
        db, article_id=article_id, version_no=payload.version_no, current=current
    )
    return ok(data)


# ---- 提审 ----
@router.post("/articles/{id}/submit")
async def submit_article(
    current: UserCtx = Depends(require_perm("content:article:submit")),
    article_id: int = Depends(_require_article_mp_access(need_level=3)),
    db: AsyncSession = Depends(get_db),
    gateway: WxGateway = Depends(get_gateway),
):
    data = await service.submit_article(
        db, article_id=article_id, gateway=gateway, current=current
    )
    return ok(data)


# ---- 审核(全系统唯一审核接口;对全部号可见角色放行,不叠加单号守卫)----
@router.post("/articles/{id}/audit")
async def audit_article(
    id: int,
    payload: schemas.AuditIn,
    current: UserCtx = Depends(require_perm("content:article:audit")),
    db: AsyncSession = Depends(get_db),
):
    data = await service.audit_article(
        db,
        article_id=id,
        result=payload.result,
        opinion=payload.opinion,
        current=current,
    )
    return ok(data)


# ===========================================================================
# 多图文组
# ===========================================================================
@router.post("/draft-groups")
async def create_draft_group(
    payload: schemas.DraftGroupCreate,
    current: UserCtx = Depends(require_perm("content:article:edit")),
    db: AsyncSession = Depends(get_db),
):
    data = await service.create_draft_group(db, payload=payload, current=current)
    return ok(data)


@router.post("/draft-groups/{id}/articles")
async def add_article_to_group(
    payload: schemas.GroupAddArticleIn,
    current: UserCtx = Depends(require_perm("content:article:edit")),
    group_id: int = Depends(_require_group_mp_access(need_level=2)),
    db: AsyncSession = Depends(get_db),
):
    data = await service.add_article_to_group(
        db, group_id=group_id, article_id=payload.article_id, current=current
    )
    return ok(data)


@router.patch("/draft-groups/{id}/reorder")
async def reorder_group(
    payload: schemas.GroupReorderIn,
    current: UserCtx = Depends(require_perm("content:article:edit")),
    group_id: int = Depends(_require_group_mp_access(need_level=2)),
    db: AsyncSession = Depends(get_db),
):
    data = await service.reorder_group(
        db, group_id=group_id, article_ids=payload.article_ids, current=current
    )
    return ok(data)


@router.delete("/draft-groups/{id}/articles/{aid}")
async def remove_article_from_group(
    aid: int,
    current: UserCtx = Depends(require_perm("content:article:edit")),
    group_id: int = Depends(_require_group_mp_access(need_level=2)),
    db: AsyncSession = Depends(get_db),
):
    data = await service.remove_article_from_group(
        db, group_id=group_id, article_id=aid, current=current
    )
    return ok(data)


@router.get("/draft-groups/{id}")
async def get_draft_group(
    _: UserCtx = Depends(require_perm("content:article:view")),
    group_id: int = Depends(_require_group_mp_access(need_level=1)),
    db: AsyncSession = Depends(get_db),
):
    data = await service.get_draft_group_detail(db, group_id=group_id)
    return ok(data)
