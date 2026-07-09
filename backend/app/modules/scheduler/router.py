"""调度中心路由(前缀 /api/v1 由 main 添加)。

- POST /scheduler/tick:手动触发一次全自动流水线推进(本地演示 / 无 Celery 时用;
  docker 下由 Celery Beat 周期调用同一 tick)。仅 system:config:manage。
- GET  /scheduler/dashboard:全局看板聚合(各引擎状态计数 + 发布成功率)。
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.response import ok
from app.modules.auth_rbac.deps import UserCtx, require_perm
from app.modules.scheduler import service
from app.modules.wx_gateway.gateway import WxGateway, get_gateway

router = APIRouter(prefix="/scheduler", tags=["scheduler"])


@router.post("/tick")
async def run_tick(
    _: UserCtx = Depends(require_perm("system:config:manage")),
    gateway: WxGateway = Depends(get_gateway),
    db: AsyncSession = Depends(get_db),
):
    return ok(await service.tick(db, gateway))


@router.get("/dashboard")
async def dashboard(
    _: UserCtx = Depends(require_perm("publish:task:view")),
    db: AsyncSession = Depends(get_db),
):
    return ok(await service.dashboard(db))
