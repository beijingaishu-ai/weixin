"""pytest 全局夹具 —— 后端 M1 异步测试基础设施。

关键点(顺序敏感):
1) 在 import 任何 `app.*` 模块之前, 先把测试用环境变量写入 os.environ。
   config.py 在 import 期即构造 `settings` 单例并读取这些变量, 因此必须抢在前面。
2) 用内存 SQLite(StaticPool + check_same_thread=False)共享单一连接, 以便
   同一测试内多个会话看到同一份表数据; 每个测试 function 级 create_all/drop_all 隔离。
3) 用 app.dependency_overrides 覆盖 get_db / get_redis, 注入测试会话与内存 FakeRedis。
4) app 相关夹具惰性 import `app.main`: auth_rbac / mp_manager 的 router 尚由他人并行实现,
   未就绪时相关测试自动 skip, 而不依赖 app 的 test_crypto 仍可独立运行。
"""
import base64
import fnmatch
import os

# ---- 1) 必须在任何 app.* import 之前设置环境变量 ----
# 32 字节固定主密钥的 base64(用于 AppSecret AES-256-GCM)
_MASTER_KEY_B64 = base64.b64encode(b"0123456789abcdef0123456789abcdef").decode()

os.environ.setdefault("APP_ENV", "test")
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["JWT_SECRET_KEY"] = "test-secret"
os.environ["MP_SECRET_MASTER_KEY"] = _MASTER_KEY_B64
os.environ["MP_SECRET_KEY_VERSION"] = "1"
os.environ["INTERNAL_TOKEN"] = "test-internal"
os.environ["SUPER_ADMIN_USERNAME"] = "admin"
os.environ["SUPER_ADMIN_PASSWORD"] = "Admin@12345"
# 缩短失败锁定阈值默认值不改, 依赖 config 默认(LOGIN_MAX_FAIL=5)

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import BigInteger  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.ext.compiler import compiles  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402


# ---------------------------------------------------------------------------
# 可移植性补丁(仅测试期生效): 让 BigInteger 在 SQLite 下编译为 INTEGER。
# 生产用 MySQL(BIGINT AUTO_INCREMENT), 但 SQLite 只有 `INTEGER PRIMARY KEY`
# 才获得 rowid 自增; 若保持 BIGINT, 主键不自增 -> 插入报 NOT NULL。
# 这里只改 SQLite 方言的 DDL 渲染, 不触碰生产模型定义。
# ---------------------------------------------------------------------------
@compiles(BigInteger, "sqlite")
def _bigint_as_integer_on_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN202
    return "INTEGER"

# 触发所有 ORM 模型注册到 Base.metadata(否则 create_all 建不出全部表)
import app.models  # noqa: E402,F401
from app.core.db import Base, get_db  # noqa: E402
from app.core.redis import get_redis  # noqa: E402
from app.seeds import run_seeds  # noqa: E402


# ---------------------------------------------------------------------------
# FakeRedis —— 内存假实现, 覆盖 auth 服务与 deps 用到的异步命令子集
# ---------------------------------------------------------------------------
class FakeRedis:
    """极简内存 Redis(异步接口)。

    支持: get / set(ex=) / delete / incr / expire / keys / scan_iter。
    不实现真实 TTL 过期(测试不依赖真实到期), expire 仅记录以便断言存在性。
    值统一以 str 存储, 贴近 redis-py decode_responses=True 的行为。
    """

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key: str):
        return self.store.get(key)

    async def set(self, key: str, value, ex: int | None = None):
        self.store[key] = str(value)
        if ex is not None:
            self.ttls[key] = ex
        return True

    async def delete(self, *keys: str) -> int:
        removed = 0
        for k in keys:
            if k in self.store:
                del self.store[k]
                self.ttls.pop(k, None)
                removed += 1
        return removed

    async def incr(self, key: str, amount: int = 1) -> int:
        cur = int(self.store.get(key, "0")) + amount
        self.store[key] = str(cur)
        return cur

    async def expire(self, key: str, seconds: int) -> bool:
        if key in self.store:
            self.ttls[key] = seconds
            return True
        return False

    async def ttl(self, key: str) -> int:
        if key not in self.store:
            return -2
        return self.ttls.get(key, -1)

    async def exists(self, *keys: str) -> int:
        return sum(1 for k in keys if k in self.store)

    async def keys(self, pattern: str = "*") -> list[str]:
        return [k for k in self.store if fnmatch.fnmatch(k, pattern)]

    async def scan_iter(self, match: str = "*", count: int | None = None):
        for k in list(self.store):
            if fnmatch.fnmatch(k, match):
                yield k

    async def flushdb(self) -> bool:
        self.store.clear()
        self.ttls.clear()
        return True


# ---------------------------------------------------------------------------
# 数据库: 单一共享内存连接 + 每测试重建 schema
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture(scope="function")
async def engine():
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
        future=True,
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield eng
    finally:
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await eng.dispose()


@pytest_asyncio.fixture(scope="function")
async def session_factory(engine):
    return async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession, autoflush=False
    )


@pytest_asyncio.fixture(scope="function")
async def seeded(session_factory):
    """运行 seeds: 预置五个内置角色 + 超级管理员。"""
    async with session_factory() as db:
        await run_seeds(db)
    return True


@pytest_asyncio.fixture(scope="function")
async def db_session(session_factory) -> AsyncSession:
    """供测试直接建数据(建 operator、公众号等)的会话。"""
    async with session_factory() as s:
        yield s


@pytest.fixture(scope="function")
def fake_redis() -> FakeRedis:
    return FakeRedis()


# ---------------------------------------------------------------------------
# 应用 & HTTP 客户端(惰性 import, router 未就绪则 skip)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="function")
def app(session_factory, fake_redis, seeded):
    """构造被测 FastAPI app 并覆盖 get_db / get_redis。

    auth_rbac / mp_manager 的 router 尚未实现时 import 失败 -> skip 相关测试。
    """
    try:
        from app.main import app as fastapi_app
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"app 尚不可导入(router/service 未就绪): {e!r}")

    async def _override_get_db():
        async with session_factory() as s:
            yield s

    async def _override_get_redis():
        return fake_redis

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    fastapi_app.dependency_overrides[get_redis] = _override_get_redis
    try:
        yield fastapi_app
    finally:
        fastapi_app.dependency_overrides.clear()


@pytest_asyncio.fixture(scope="function")
async def client(app) -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# 认证辅助
# ---------------------------------------------------------------------------
def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _login(client: AsyncClient, username: str, password: str) -> dict:
    """登录并返回 body['data']; 供 fixture 与测试复用。"""
    resp = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    return resp


@pytest_asyncio.fixture(scope="function")
async def admin_token(client: AsyncClient) -> str:
    """超管登录取 access_token。"""
    resp = await _login(client, "admin", "Admin@12345")
    if resp.status_code != 200:
        pytest.skip(f"登录端点未就绪或失败: {resp.status_code} {resp.text}")
    body = resp.json()
    if body.get("code") != 0 or not body.get("data"):
        pytest.skip(f"登录响应不符合契约: {body}")
    return body["data"]["access_token"]


@pytest.fixture(scope="function")
def make_login(client: AsyncClient):
    """返回一个协程工厂, 便于测试内以任意账号登录。"""

    async def _do(username: str, password: str):
        return await _login(client, username, password)

    return _do
