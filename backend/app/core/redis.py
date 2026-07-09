"""Redis 异步客户端(JWT 黑/白名单、登录失败计数;M2+ 复用为 Celery broker)。

测试环境无 Redis 时,通过 app.dependency_overrides[get_redis] 注入内存假实现
(见 tests/conftest.py),故本模块不在 import 期建立真实连接。
"""
from redis.asyncio import Redis, from_url

from app.core.config import settings

_client: Redis | None = None


def _get_client() -> Redis:
    global _client
    if _client is None:
        _client = from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    return _client


async def get_redis() -> Redis:
    """FastAPI 依赖:返回共享的异步 Redis 客户端。"""
    return _get_client()
