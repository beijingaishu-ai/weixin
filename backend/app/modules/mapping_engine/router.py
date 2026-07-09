"""mapping-engine 路由(前缀 /api/v1/mapping 由 main 添加)。"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.response import ok
from app.modules.auth_rbac.deps import UserCtx, require_perm
from app.modules.mapping_engine import schemas, service

router = APIRouter(prefix="/mapping", tags=["mapping-engine"])


# --------------------------- 规则 CRUD ---------------------------
@router.get("/rules")
async def list_rules(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    source_id: int | None = None,
    target_mp_account_id: int | None = None,
    enabled: int | None = None,
    keyword: str | None = None,
    _: UserCtx = Depends(require_perm("mapping:rule:view")),
    db: AsyncSession = Depends(get_db),
):
    return ok(await service.list_rules(
        db, page=page, page_size=page_size, source_id=source_id,
        target_mp_account_id=target_mp_account_id, enabled=enabled, keyword=keyword,
    ))


@router.post("/rules")
async def create_rule(
    payload: schemas.RuleCreate,
    user: UserCtx = Depends(require_perm("mapping:rule:manage")),
    db: AsyncSession = Depends(get_db),
):
    return ok(await service.create_rule(db, payload=payload, current_id=user.id))


@router.get("/rules/{id}")
async def get_rule(
    id: int,
    _: UserCtx = Depends(require_perm("mapping:rule:view")),
    db: AsyncSession = Depends(get_db),
):
    return ok(await service.get_rule(db, rule_id=id))


@router.put("/rules/{id}")
async def update_rule(
    id: int,
    payload: schemas.RuleUpdate,
    _: UserCtx = Depends(require_perm("mapping:rule:manage")),
    db: AsyncSession = Depends(get_db),
):
    await service.update_rule(db, rule_id=id, payload=payload)
    return ok()


@router.patch("/rules/{id}/status")
async def set_rule_status(
    id: int,
    payload: schemas.RuleStatusIn,
    _: UserCtx = Depends(require_perm("mapping:rule:manage")),
    db: AsyncSession = Depends(get_db),
):
    await service.set_rule_status(db, rule_id=id, enabled=payload.enabled)
    return ok()


@router.delete("/rules/{id}")
async def delete_rule(
    id: int,
    _: UserCtx = Depends(require_perm("mapping:rule:manage")),
    db: AsyncSession = Depends(get_db),
):
    await service.delete_rule(db, rule_id=id)
    return ok()


# --------------------------- dry-run / preview ---------------------------
@router.post("/rules/dry-run")
async def dry_run(
    payload: schemas.DryRunIn,
    _: UserCtx = Depends(require_perm("mapping:rule:view")),
    db: AsyncSession = Depends(get_db),
):
    return ok(await service.dry_run(db, payload=payload))


@router.post("/rules/{id}/preview")
async def preview(
    id: int,
    payload: schemas.PreviewIn,
    _: UserCtx = Depends(require_perm("mapping:rule:view")),
    db: AsyncSession = Depends(get_db),
):
    return ok(await service.preview(db, rule_id=id, collect_article_id=payload.collect_article_id))


# --------------------------- run-pending / executions ---------------------------
@router.post("/run-pending")
async def run_pending(
    limit: int = Query(500, ge=1, le=2000),
    _: UserCtx = Depends(require_perm("mapping:rule:manage")),
    db: AsyncSession = Depends(get_db),
):
    return ok(await service.run_pending(db, limit=limit))


@router.get("/executions")
async def list_executions(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    _: UserCtx = Depends(require_perm("mapping:rule:view")),
    db: AsyncSession = Depends(get_db),
):
    return ok(await service.list_executions(db, page=page, page_size=page_size))
