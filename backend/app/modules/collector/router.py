"""collector 路由(前缀 /api/v1/collect 由 main 添加)。"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.response import ok
from app.modules.auth_rbac.deps import UserCtx, require_perm
from app.modules.collector import schemas, service

router = APIRouter(prefix="/collect", tags=["collector"])


# --------------------------- 采集源 ---------------------------
@router.get("/sources")
async def list_sources(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    adapter_type: str | None = None,
    status: str | None = None,
    keyword: str | None = None,
    _: UserCtx = Depends(require_perm("collect:source:view")),
    db: AsyncSession = Depends(get_db),
):
    return ok(await service.list_sources(
        db, page=page, page_size=page_size,
        adapter_type=adapter_type, status=status, keyword=keyword,
    ))


@router.post("/sources")
async def create_source(
    payload: schemas.SourceCreate,
    user: UserCtx = Depends(require_perm("collect:source:manage")),
    db: AsyncSession = Depends(get_db),
):
    return ok(await service.create_source(db, payload=payload, current_id=user.id))


@router.get("/sources/{id}")
async def get_source(
    id: int,
    _: UserCtx = Depends(require_perm("collect:source:view")),
    db: AsyncSession = Depends(get_db),
):
    return ok(await service.get_source(db, source_id=id))


@router.put("/sources/{id}")
async def update_source(
    id: int,
    payload: schemas.SourceUpdate,
    _: UserCtx = Depends(require_perm("collect:source:manage")),
    db: AsyncSession = Depends(get_db),
):
    await service.update_source(db, source_id=id, payload=payload)
    return ok()


@router.delete("/sources/{id}")
async def delete_source(
    id: int,
    _: UserCtx = Depends(require_perm("collect:source:manage")),
    db: AsyncSession = Depends(get_db),
):
    await service.delete_source(db, source_id=id)
    return ok()


@router.post("/sources/{id}/enable")
async def enable_source(
    id: int,
    _: UserCtx = Depends(require_perm("collect:source:manage")),
    db: AsyncSession = Depends(get_db),
):
    await service.set_enabled(db, source_id=id, enabled=True)
    return ok()


@router.post("/sources/{id}/disable")
async def disable_source(
    id: int,
    _: UserCtx = Depends(require_perm("collect:source:manage")),
    db: AsyncSession = Depends(get_db),
):
    await service.set_enabled(db, source_id=id, enabled=False)
    return ok()


@router.post("/sources/{id}/test-run")
async def test_run(
    id: int,
    _: UserCtx = Depends(require_perm("collect:source:manage")),
    db: AsyncSession = Depends(get_db),
):
    return ok(await service.test_run(db, source_id=id))


@router.post("/sources/{id}/run-now")
async def run_now(
    id: int,
    _: UserCtx = Depends(require_perm("collect:source:manage")),
    db: AsyncSession = Depends(get_db),
):
    return ok(await service.run_now(db, source_id=id))


@router.post("/manual-import")
async def manual_import(
    payload: schemas.ManualImportIn,
    user: UserCtx = Depends(require_perm("collect:source:manage")),
    db: AsyncSession = Depends(get_db),
):
    return ok(await service.manual_import(db, payload=payload, current_id=user.id))


# --------------------------- 采集文章 ---------------------------
@router.get("/articles")
async def list_articles(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    source_id: int | None = None,
    status: str | None = None,
    keyword: str | None = None,
    _: UserCtx = Depends(require_perm("collect:article:view")),
    db: AsyncSession = Depends(get_db),
):
    data = await service.list_articles(
        db, page=page, page_size=page_size,
        source_id=source_id, status=status, keyword=keyword,
    )
    data["items"] = [schemas.ArticleItem.model_validate(a).model_dump() for a in data["items"]]
    return ok(data)


@router.get("/articles/{id}")
async def get_article(
    id: int,
    _: UserCtx = Depends(require_perm("collect:article:view")),
    db: AsyncSession = Depends(get_db),
):
    art = await service.get_article(db, article_id=id)
    return ok(schemas.ArticleDetail.model_validate(art).model_dump())


@router.get("/articles/{id}/dedup-info")
async def dedup_info(
    id: int,
    _: UserCtx = Depends(require_perm("collect:article:view")),
    db: AsyncSession = Depends(get_db),
):
    return ok(await service.dedup_info(db, article_id=id))


@router.post("/articles/{id}/reclean")
async def reclean(
    id: int,
    _: UserCtx = Depends(require_perm("collect:source:manage")),
    db: AsyncSession = Depends(get_db),
):
    await service.reclean(db, article_id=id)
    return ok()


@router.delete("/articles/{id}")
async def delete_article(
    id: int,
    _: UserCtx = Depends(require_perm("collect:source:manage")),
    db: AsyncSession = Depends(get_db),
):
    await service.delete_article(db, article_id=id)
    return ok()


@router.get("/stats/overview")
async def stats_overview(
    _: UserCtx = Depends(require_perm("collect:source:view")),
    db: AsyncSession = Depends(get_db),
):
    return ok(await service.stats_overview(db))
