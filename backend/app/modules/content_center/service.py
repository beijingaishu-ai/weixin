"""content-center 业务逻辑:素材库 / 样式模板 / 图文编排 / 版本 / 提审 / 审核 / 多图文组。

约定(对齐 M1/M2 地基):
- 状态迁移一律经 states.ensure_transition("content_article", frm, to);IllegalTransition→422。
- 数据权限:列表用 apply_mp_scope(deps 唯一出口);单号写操作由 router 的 require_mp_access 守卫,
  body 带 mp_account_id 的接口(建文章 / 建组)在本层用 _assert_mp_edit 手工校验 operator 级别。
- 审核相关审计走 core.audit.write_audit;本层负责 commit(write_audit 只 flush)。
- 素材图转存复用 core.wx_material.ensure_material_on_wx(kind='uploadimg'),不在本层另写去重。
"""
from __future__ import annotations

import re

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.audit import write_audit
from app.core.config import settings
from app.core.exceptions import AppError
from app.core.states import ArticleStatus, GroupStatus, IllegalTransition, ensure_transition
from app.core.wx_material import UPLOADIMG, ensure_material_on_wx
from app.models.content import (
    ContentArticle,
    ContentArticleVersion,
    ContentDraftGroup,
    ContentMaterial,
    ContentStyleTemplate,
)
from app.models.mp_account import MpAccount, MpAccountAssign
from app.modules.auth_rbac.deps import apply_mp_scope
from app.modules.content_center import html_pipeline, schemas

MAX_GROUP_SIZE = 8
# 可编辑状态(提审前草稿态);APPROVED/DRAFT_CREATED/PENDING_REVIEW 均不可再改正文
EDITABLE_STATUSES = {ArticleStatus.TRANSFORMED, ArticleStatus.REJECTED}


# ===========================================================================
# 通用助手
# ===========================================================================
async def _get_article_or_404(db: AsyncSession, article_id: int) -> ContentArticle:
    art = await db.get(ContentArticle, article_id)
    if art is None or art.is_deleted:
        raise AppError("图文不存在", code=1, status_code=404)
    return art


async def _get_mp_or_404(db: AsyncSession, mp_id: int) -> MpAccount:
    mp = await db.get(MpAccount, mp_id)
    if mp is None or mp.is_deleted:
        raise AppError("公众号不存在", code=1, status_code=404)
    return mp


async def _get_group_or_404(db: AsyncSession, group_id: int) -> ContentDraftGroup:
    grp = await db.get(ContentDraftGroup, group_id)
    if grp is None or grp.is_deleted:
        raise AppError("图文组不存在", code=1, status_code=404)
    return grp


async def _assert_mp_edit(
    db: AsyncSession, *, current, mp_id: int, need_level: int = 2
) -> None:
    """body 带 mp_account_id 的写操作:全权角色放行;operator 须对该号 perm_level>=need_level。

    与 deps.require_mp_access 语义一致,但用于路径无 id 的场景(建文章 / 建组)。
    """
    if getattr(current, "is_full_access", False):
        return
    perm_level = await db.scalar(
        select(MpAccountAssign.perm_level).where(
            MpAccountAssign.user_id == current.id,
            MpAccountAssign.mp_account_id == mp_id,
            MpAccountAssign.deleted_flag == 0,
        )
    )
    if perm_level is None or perm_level < need_level:
        raise AppError("无权操作该公众号", code=1, status_code=403)


def _transition(art: ContentArticle, to: str) -> str:
    """安全迁移 content_article.status;非法迁移转 422 结构化错误。返回 from_status。"""
    frm = art.status
    try:
        ensure_transition("content_article", frm, to)
    except IllegalTransition as e:
        raise AppError(
            f"非法状态迁移: {frm} → {to}",
            code=1,
            status_code=422,
        ) from e
    art.status = to
    return frm


async def _next_version_no(db: AsyncSession, article_id: int) -> int:
    cur = await db.scalar(
        select(func.max(ContentArticleVersion.version_no)).where(
            ContentArticleVersion.content_article_id == article_id
        )
    )
    return (cur or 0) + 1


async def _snapshot_version(
    db: AsyncSession, art: ContentArticle, *, created_by: int, change_note: str = ""
) -> ContentArticleVersion:
    """把当前正文快照为一条版本记录(version_no 自增)。"""
    ver = ContentArticleVersion(
        content_article_id=art.id,
        version_no=await _next_version_no(db, art.id),
        title=art.title,
        digest=art.digest,
        content_html=art.content_html,
        change_note=change_note,
        created_by=created_by,
    )
    db.add(ver)
    await db.flush()
    return ver


# ===========================================================================
# 素材库
# ===========================================================================
async def upload_material(
    db: AsyncSession,
    *,
    filename: str,
    data: bytes,
    material_type: str,
    current_id: int,
) -> dict:
    """落盘 + 按 (file_hash, material_type) 去重入库(命中即复用,秒传)。"""
    if not data:
        raise AppError("上传文件为空", code=1, status_code=422)

    ext = storage.guess_ext(filename)
    file_hash, rel_path, size = storage.save_bytes(data, ext)

    existing = await db.scalar(
        select(ContentMaterial).where(
            ContentMaterial.file_hash == file_hash,
            ContentMaterial.material_type == material_type,
        )
    )
    if existing is not None:
        return {
            "id": existing.id,
            "file_hash": existing.file_hash,
            "file_path": existing.file_path,
            "file_size": existing.file_size,
            "url": existing.file_path,
        }

    mat = ContentMaterial(
        material_type=material_type,
        file_hash=file_hash,
        file_size=size,
        file_path=rel_path,
        origin_url="",
        created_by=current_id,
    )
    db.add(mat)
    await db.flush()
    await db.commit()
    return {
        "id": mat.id,
        "file_hash": file_hash,
        "file_path": rel_path,
        "file_size": size,
        "url": rel_path,
    }


async def list_materials(
    db: AsyncSession,
    *,
    page: int,
    page_size: int,
    material_type: str | None,
    keyword: str | None,
) -> dict:
    base = select(ContentMaterial)
    if material_type:
        base = base.where(ContentMaterial.material_type == material_type)
    if keyword:
        like = f"%{keyword.strip()}%"
        base = base.where(
            or_(
                ContentMaterial.file_hash.like(like),
                ContentMaterial.file_path.like(like),
                ContentMaterial.origin_url.like(like),
            )
        )
    total = await db.scalar(
        select(func.count()).select_from(base.order_by(None).subquery())
    )
    rows = await db.scalars(
        base.order_by(ContentMaterial.id.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    items = []
    for m in rows.all():
        items.append(
            {
                "id": m.id,
                "material_type": m.material_type,
                "file_hash": m.file_hash,
                "file_size": m.file_size,
                "file_path": m.file_path,
                "origin_url": m.origin_url,
                "created_by": m.created_by,
                "created_at": m.created_at,
                "url": m.file_path,
            }
        )
    return {"items": items, "total": total or 0, "page": page, "page_size": page_size}


async def delete_material(db: AsyncSession, *, material_id: int) -> None:
    mat = await db.get(ContentMaterial, material_id)
    if mat is None:
        raise AppError("素材不存在", code=1, status_code=404)
    # 被任一图文引用为封面则拒绝删除
    ref = await db.scalar(
        select(ContentArticle.id).where(
            ContentArticle.cover_material_id == material_id,
            ContentArticle.is_deleted == 0,
        )
    )
    if ref is not None:
        raise AppError(
            "素材已被图文用作封面,无法删除",
            code=1,
            status_code=422,
        )
    await db.delete(mat)
    await db.commit()


# ===========================================================================
# 样式模板
# ===========================================================================
async def list_style_templates(db: AsyncSession, *, category: str | None) -> list[dict]:
    stmt = select(ContentStyleTemplate).where(
        ContentStyleTemplate.enabled == 1,
        ContentStyleTemplate.is_deleted == 0,
    )
    if category:
        stmt = stmt.where(ContentStyleTemplate.category == category)
    rows = await db.scalars(stmt.order_by(ContentStyleTemplate.id.desc()))
    return [
        {
            "id": t.id,
            "template_name": t.template_name,
            "description": t.description,
            "style_json": t.style_json,
            "header_html": t.header_html,
            "footer_html": t.footer_html,
            "category": t.category,
            "is_builtin": t.is_builtin,
            "enabled": t.enabled,
            "created_at": t.created_at,
        }
        for t in rows.all()
    ]


async def create_style_template(
    db: AsyncSession, *, payload: schemas.StyleTemplateCreate, current_id: int
) -> dict:
    exists = await db.scalar(
        select(ContentStyleTemplate.id).where(
            ContentStyleTemplate.template_name == payload.template_name,
            ContentStyleTemplate.is_deleted == 0,
        )
    )
    if exists is not None:
        raise AppError("模板名已存在", code=1, status_code=422)
    tpl = ContentStyleTemplate(
        template_name=payload.template_name,
        description=payload.description,
        style_json=payload.style_json,
        header_html=payload.header_html,
        footer_html=payload.footer_html,
        category=payload.category,
        is_builtin=0,
        enabled=1,
        created_by=current_id,
    )
    db.add(tpl)
    await db.flush()
    await db.commit()
    return {"id": tpl.id}


# ===========================================================================
# 图文文章
# ===========================================================================
async def create_article(
    db: AsyncSession, *, payload: schemas.ArticleCreate, current
) -> dict:
    await _get_mp_or_404(db, payload.mp_account_id)
    await _assert_mp_edit(db, current=current, mp_id=payload.mp_account_id, need_level=2)

    # 校验封面素材存在(若指定)
    if payload.cover_material_id is not None:
        cover = await db.get(ContentMaterial, payload.cover_material_id)
        if cover is None:
            raise AppError("封面素材不存在", code=1, status_code=422)

    # 建稿即跑 SAVE 管道清洗正文(白名单去 script、链接降级、外链识别)
    cleaned = html_pipeline.process_article_html(payload.content_html, stage="SAVE")

    art = ContentArticle(
        mp_account_id=payload.mp_account_id,
        title=payload.title,
        author=payload.author or "",
        digest=payload.digest or "",
        content_html=cleaned.cleaned_html,
        cover_material_id=payload.cover_material_id,
        style_template_id=payload.style_template_id,
        content_source_url=payload.content_source_url or "",
        need_open_comment=payload.need_open_comment,
        only_fans_can_comment=payload.only_fans_can_comment,
        status=ArticleStatus.TRANSFORMED,
        created_by=current.id,
    )
    db.add(art)
    await db.flush()  # 取 art.id

    await _snapshot_version(db, art, created_by=current.id, change_note="初稿")
    await db.commit()
    return {"id": art.id}


async def list_articles(
    db: AsyncSession,
    *,
    visible: set[int] | None,
    page: int,
    page_size: int,
    mp_account_id: int | None,
    status: str | None,
    keyword: str | None,
) -> dict:
    base = select(ContentArticle).where(ContentArticle.is_deleted == 0)
    base = apply_mp_scope(base, ContentArticle.mp_account_id, visible)
    if mp_account_id is not None:
        base = base.where(ContentArticle.mp_account_id == mp_account_id)
    if status:
        base = base.where(ContentArticle.status == status)
    if keyword:
        like = f"%{keyword.strip()}%"
        base = base.where(
            or_(
                ContentArticle.title.like(like),
                ContentArticle.digest.like(like),
                ContentArticle.author.like(like),
            )
        )
    total = await db.scalar(
        select(func.count()).select_from(base.order_by(None).subquery())
    )
    rows = await db.scalars(
        base.order_by(ContentArticle.id.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    items = [_article_item(a) for a in rows.all()]
    return {"items": items, "total": total or 0, "page": page, "page_size": page_size}


def _article_item(a: ContentArticle) -> dict:
    return {
        "id": a.id,
        "mp_account_id": a.mp_account_id,
        "title": a.title,
        "author": a.author,
        "digest": a.digest,
        "status": a.status,
        "cover_material_id": a.cover_material_id,
        "draft_group_id": a.draft_group_id,
        "group_position": a.group_position,
        "created_by": a.created_by,
        "created_at": a.created_at,
        "updated_at": a.updated_at,
    }


async def get_article_detail(db: AsyncSession, *, article_id: int) -> dict:
    art = await _get_article_or_404(db, article_id)
    data = _article_item(art)
    data.update(
        {
            "content_html": art.content_html,
            "style_template_id": art.style_template_id,
            "content_source_url": art.content_source_url,
            "need_open_comment": art.need_open_comment,
            "only_fans_can_comment": art.only_fans_can_comment,
            "thumb_media_id": art.thumb_media_id,
            "draft_media_id": art.draft_media_id,
        }
    )
    return data


async def update_article(
    db: AsyncSession, *, article_id: int, payload: schemas.ArticleUpdate, current
) -> None:
    art = await _get_article_or_404(db, article_id)
    if art.status not in EDITABLE_STATUSES:
        raise AppError(
            f"当前状态({art.status})不可编辑,仅 TRANSFORMED/REJECTED 可改",
            code=1,
            status_code=422,
        )

    if payload.cover_material_id is not None:
        cover = await db.get(ContentMaterial, payload.cover_material_id)
        if cover is None:
            raise AppError("封面素材不存在", code=1, status_code=422)

    if payload.title is not None:
        art.title = payload.title
    if payload.author is not None:
        art.author = payload.author
    if payload.digest is not None:
        art.digest = payload.digest
    if payload.cover_material_id is not None:
        art.cover_material_id = payload.cover_material_id
    if payload.style_template_id is not None:
        art.style_template_id = payload.style_template_id
    if payload.content_source_url is not None:
        art.content_source_url = payload.content_source_url
    if payload.need_open_comment is not None:
        art.need_open_comment = payload.need_open_comment
    if payload.only_fans_can_comment is not None:
        art.only_fans_can_comment = payload.only_fans_can_comment

    # 正文变更:跑 SAVE 管道清洗后落库,并追加版本
    if payload.content_html is not None:
        result = html_pipeline.process_article_html(payload.content_html, stage="SAVE")
        art.content_html = result.cleaned_html
        await _snapshot_version(db, art, created_by=current.id, change_note="编辑保存")

    await db.commit()


# ===========================================================================
# 版本
# ===========================================================================
async def create_version(
    db: AsyncSession, *, article_id: int, payload: schemas.VersionCreate, current_id: int
) -> dict:
    art = await _get_article_or_404(db, article_id)
    ver = await _snapshot_version(
        db, art, created_by=current_id, change_note=payload.change_note or "手动存版本"
    )
    await db.commit()
    return {"id": ver.id, "version_no": ver.version_no}


async def list_versions(db: AsyncSession, *, article_id: int) -> list[dict]:
    await _get_article_or_404(db, article_id)
    rows = await db.scalars(
        select(ContentArticleVersion)
        .where(ContentArticleVersion.content_article_id == article_id)
        .order_by(ContentArticleVersion.version_no.desc())
    )
    return [
        {
            "id": v.id,
            "content_article_id": v.content_article_id,
            "version_no": v.version_no,
            "title": v.title,
            "digest": v.digest,
            "change_note": v.change_note,
            "created_by": v.created_by,
            "created_at": v.created_at,
        }
        for v in rows.all()
    ]


async def rollback_article(
    db: AsyncSession, *, article_id: int, version_no: int, current
) -> dict:
    art = await _get_article_or_404(db, article_id)
    if art.status not in EDITABLE_STATUSES:
        raise AppError(
            f"当前状态({art.status})不可回滚,仅 TRANSFORMED/REJECTED 可改",
            code=1,
            status_code=422,
        )
    ver = await db.scalar(
        select(ContentArticleVersion).where(
            ContentArticleVersion.content_article_id == article_id,
            ContentArticleVersion.version_no == version_no,
        )
    )
    if ver is None:
        raise AppError("指定版本不存在", code=1, status_code=404)

    art.title = ver.title
    art.digest = ver.digest
    art.content_html = ver.content_html
    # 回滚也留痕:把回滚后内容作为新版本快照
    new_ver = await _snapshot_version(
        db, art, created_by=current.id, change_note=f"回滚至 v{version_no}"
    )
    await db.commit()
    return {"id": art.id, "version_no": new_ver.version_no, "rolled_back_from": version_no}


# ===========================================================================
# 提审(HTML 管道 + 正文图转存 + 双层审核开关决定去向)
# ===========================================================================
_IMG_SRC_RE = re.compile(r"(<img\b[^>]*?\bsrc=)([\"'])(.*?)\2", re.IGNORECASE)


def _replace_img_src(html: str, old_src: str, new_url: str) -> str:
    """把正文中 src == old_src 的 <img> 替换为 new_url(精确匹配,避免误伤)。"""
    if not old_src or not new_url:
        return html
    return html.replace(f'src="{old_src}"', f'src="{new_url}"').replace(
        f"src='{old_src}'", f"src='{new_url}'"
    )


async def submit_article(
    db: AsyncSession, *, article_id: int, gateway, current
) -> dict:
    """提审:清洗正文 -> 转存站内素材库图片 -> 按双层开关决定 PENDING_REVIEW / 自动过审。

    教学期不实现站外抓取:仅转存 data-material-id 指向已入库素材的图片;
    无 data-material-id 的外链图跳过并记 issue。
    """
    art = await _get_article_or_404(db, article_id)
    if art.status not in EDITABLE_STATUSES:
        raise AppError(
            f"当前状态({art.status})不可提审,仅 TRANSFORMED/REJECTED 可提审",
            code=1,
            status_code=422,
        )

    mp = await _get_mp_or_404(db, art.mp_account_id)

    # 1) 跑 SAVE 管道得清洗后 html 与外链清单
    result = html_pipeline.process_article_html(art.content_html, stage="SAVE")
    cleaned = result.cleaned_html
    issues = list(result.issues)
    transferred = 0

    # 2) 对每个非微信域 img:若 data-material-id 指向已入库素材 -> 转存换 wx_url;否则跳过记 issue
    for ext_img in result.external_imgs:
        if ext_img.data_material_id is None:
            # 管道已记 issue,此处不重复
            continue
        material = await db.get(ContentMaterial, ext_img.data_material_id)
        if material is None:
            issues.append(
                f"data-material-id={ext_img.data_material_id} 素材不存在,跳过转存"
            )
            continue
        ref = await ensure_material_on_wx(db, gateway, mp, material, kind=UPLOADIMG)
        if ref.wx_url:
            cleaned = _replace_img_src(cleaned, ext_img.src, ref.wx_url)
            transferred += 1
        else:
            issues.append(f"素材 {material.id} 转存未返回微信 URL,已保留原 src")

    art.content_html = cleaned

    # 3) 双层审核开关:全局 + 号级都为真 -> 走人工审核;否则自动过审
    review_on = bool(settings.PUBLISH_REVIEW_ENABLED) and bool(mp.need_review)

    if review_on:
        frm = _transition(art, ArticleStatus.PENDING_REVIEW)
        await write_audit(
            db,
            action="SUBMIT",
            biz_type="content_article",
            biz_id=art.id,
            auditor_id=current.id,
            from_status=frm,
            to_status=art.status,
            opinion="; ".join(issues)[:512],
        )
        auto_approved = False
    else:
        frm = _transition(art, ArticleStatus.APPROVED)
        await write_audit(
            db,
            action="AUTO_APPROVE",
            biz_type="content_article",
            biz_id=art.id,
            auditor_id=0,
            from_status=frm,
            to_status=art.status,
            opinion="双层审核开关关闭,自动过审",
        )
        auto_approved = True

    await db.commit()
    return {
        "id": art.id,
        "status": art.status,
        "auto_approved": auto_approved,
        "issues": issues,
        "transferred_imgs": transferred,
    }


# ===========================================================================
# 审核(全系统唯一审核接口)
# ===========================================================================
async def audit_article(
    db: AsyncSession, *, article_id: int, result: str, opinion: str, current
) -> dict:
    art = await _get_article_or_404(db, article_id)
    if art.status != ArticleStatus.PENDING_REVIEW:
        raise AppError(
            f"当前状态({art.status})不可审核,仅 PENDING_REVIEW 可审",
            code=1,
            status_code=422,
        )

    if result == "pass":
        frm = _transition(art, ArticleStatus.APPROVED)
        action = "APPROVE"
    else:
        frm = _transition(art, ArticleStatus.REJECTED)
        action = "REJECT"

    await write_audit(
        db,
        action=action,
        biz_type="content_article",
        biz_id=art.id,
        auditor_id=current.id,
        from_status=frm,
        to_status=art.status,
        opinion=opinion or "",
    )
    await db.commit()
    return {"id": art.id, "status": art.status}


# ===========================================================================
# 多图文组
# ===========================================================================
async def create_draft_group(
    db: AsyncSession, *, payload: schemas.DraftGroupCreate, current
) -> dict:
    await _get_mp_or_404(db, payload.mp_account_id)
    await _assert_mp_edit(db, current=current, mp_id=payload.mp_account_id, need_level=2)
    grp = ContentDraftGroup(
        mp_account_id=payload.mp_account_id,
        group_name=payload.group_name or "",
        status=GroupStatus.EDITING,
        created_by=current.id,
    )
    db.add(grp)
    await db.flush()
    await db.commit()
    return {"id": grp.id}


async def _group_members(db: AsyncSession, group_id: int) -> list[ContentArticle]:
    rows = await db.scalars(
        select(ContentArticle)
        .where(
            ContentArticle.draft_group_id == group_id,
            ContentArticle.is_deleted == 0,
        )
        .order_by(ContentArticle.group_position.asc(), ContentArticle.id.asc())
    )
    return list(rows.all())


async def add_article_to_group(
    db: AsyncSession, *, group_id: int, article_id: int, current
) -> dict:
    grp = await _get_group_or_404(db, group_id)
    await _assert_mp_edit(db, current=current, mp_id=grp.mp_account_id, need_level=2)
    art = await _get_article_or_404(db, article_id)

    # 同号校验
    if art.mp_account_id != grp.mp_account_id:
        raise AppError(
            "图文与组不属于同一公众号",
            code=1,
            status_code=422,
        )
    # 已在别的组?
    if art.draft_group_id is not None and art.draft_group_id != group_id:
        raise AppError("该图文已属于其它组", code=1, status_code=422)

    members = await _group_members(db, group_id)
    if any(m.id == article_id for m in members):
        raise AppError("图文已在组内", code=1, status_code=422)
    if len(members) >= MAX_GROUP_SIZE:
        raise AppError("组内图文已达上限(8 篇)", code=2, status_code=422)

    next_pos = (max((m.group_position for m in members), default=-1)) + 1
    art.draft_group_id = group_id
    art.group_position = next_pos
    await db.commit()
    return {"group_id": group_id, "article_id": article_id, "group_position": next_pos}


async def reorder_group(
    db: AsyncSession, *, group_id: int, article_ids: list[int], current
) -> dict:
    grp = await _get_group_or_404(db, group_id)
    await _assert_mp_edit(db, current=current, mp_id=grp.mp_account_id, need_level=2)
    members = await _group_members(db, group_id)
    member_ids = {m.id for m in members}

    if set(article_ids) != member_ids:
        raise AppError(
            "重排列表须与组成员完全一致",
            code=1,
            status_code=422,
        )
    by_id = {m.id: m for m in members}
    for pos, aid in enumerate(article_ids):
        by_id[aid].group_position = pos
    await db.commit()
    return {"group_id": group_id, "order": article_ids}


async def remove_article_from_group(
    db: AsyncSession, *, group_id: int, article_id: int, current
) -> dict:
    grp = await _get_group_or_404(db, group_id)
    await _assert_mp_edit(db, current=current, mp_id=grp.mp_account_id, need_level=2)
    art = await _get_article_or_404(db, article_id)
    if art.draft_group_id != group_id:
        raise AppError("该图文不在此组", code=1, status_code=422)

    art.draft_group_id = None
    art.group_position = 0
    await db.flush()

    # 剩余成员重排 group_position(0..n-1)
    remaining = await _group_members(db, group_id)
    for pos, m in enumerate(remaining):
        m.group_position = pos
    await db.commit()
    return {"group_id": group_id, "removed": article_id}


async def get_draft_group_detail(db: AsyncSession, *, group_id: int) -> dict:
    grp = await _get_group_or_404(db, group_id)
    members = await _group_members(db, group_id)
    all_approved = bool(members) and all(
        m.status == ArticleStatus.APPROVED for m in members
    )
    # 组内全部 APPROVED -> 前端可置 READY(此处按当前成员状态派生展示状态,不落库改写)
    display_status = grp.status
    if grp.status == GroupStatus.EDITING and all_approved:
        display_status = GroupStatus.READY

    return {
        "id": grp.id,
        "mp_account_id": grp.mp_account_id,
        "group_name": grp.group_name,
        "status": display_status,
        "all_approved": all_approved,
        "members": [
            {
                "id": m.id,
                "title": m.title,
                "status": m.status,
                "group_position": m.group_position,
                "cover_material_id": m.cover_material_id,
            }
            for m in members
        ],
        "created_at": grp.created_at,
    }
