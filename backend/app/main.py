"""FastAPI 应用工厂。

挂载 auth_rbac、mp_manager 两个 M1 模块路由;注册统一异常处理;
启动时运行 seeds(预置角色 + 超级管理员)。
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.exceptions import register_exception_handlers
from app.core.response import ok
from app.modules.auth_rbac.router import router as auth_router
from app.modules.collector.router import router as collector_router
from app.modules.content_center.router import router as content_router
from app.modules.mapping_engine.router import router as mapping_router
from app.modules.mp_manager.router import router as mp_router
from app.modules.publish_engine.router import router as publish_router
from app.modules.scheduler.router import router as scheduler_router
from app.seeds import run_seeds

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        async with SessionLocal() as db:
            await run_seeds(db)
    except Exception as e:  # noqa: BLE001  —— 引导失败不应阻断启动(如 DB 尚未就绪),记录告警
        logger.warning("启动引导 seeds 未完成: %s", e)
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version="1.0.0-M1",
        description="微信公众号矩阵管理系统 —— M1(基础框架 + RBAC + 公众号管理)",
        lifespan=lifespan,
    )

    # 开发期允许前端本地跨域;生产由 Nginx 同源反代,可收紧
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.DEBUG else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    app.include_router(auth_router, prefix=settings.API_PREFIX)
    app.include_router(mp_router, prefix=settings.API_PREFIX)
    app.include_router(content_router, prefix=settings.API_PREFIX)
    app.include_router(publish_router, prefix=settings.API_PREFIX)
    app.include_router(collector_router, prefix=settings.API_PREFIX)
    app.include_router(mapping_router, prefix=settings.API_PREFIX)
    app.include_router(scheduler_router, prefix=settings.API_PREFIX)

    @app.get("/health", tags=["system"])
    async def health():
        return ok({"status": "up", "app": settings.APP_NAME})

    return app


app = create_app()
