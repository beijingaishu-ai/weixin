"""Celery 应用与 Beat 调度(M4,docker 下启用 worker/beat)。

本地零依赖模式 / 测试不运行 Celery——同一套 tick 逻辑改由 POST /scheduler/tick 手动触发。
docker-compose 的 worker/beat 服务加载本模块:Beat 每分钟投递 pipeline_tick,worker 执行。

任务体复用 app.modules.scheduler.service.tick(与手动触发完全一致),保证两种触发路径行为一致。
"""
from __future__ import annotations

import asyncio

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "wx_mp",
    broker=settings.redis_url,
    backend=settings.redis_url,
)
celery_app.conf.update(
    task_default_queue="default",
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    beat_schedule={
        # 每分钟推进一次全自动流水线(采集到期源→映射→建任务→发表→重试→告警)
        "pipeline-tick-every-minute": {
            "task": "app.celery_app.pipeline_tick",
            "schedule": crontab(minute="*"),
        },
    },
)


async def _run_tick() -> dict:
    from app.core.db import SessionLocal
    from app.core.redis import get_redis
    from app.modules.scheduler.service import tick
    from app.modules.wx_gateway.gateway import WxGateway

    redis = await get_redis()
    async with SessionLocal() as db:
        return await tick(db, WxGateway(redis))


@celery_app.task(name="app.celery_app.pipeline_tick")
def pipeline_tick() -> dict:
    """Beat 周期任务:执行一次流水线 tick。"""
    return asyncio.run(_run_tick())
