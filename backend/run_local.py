"""本地零依赖开发启动器 —— 无需 Docker / MySQL / Redis。

用途:在只装了 Python 的机器上一键把后端跑起来,方便开发和课堂演示。
  - 数据库:SQLite 文件 dev_local.db(首次自动建表 + 预置角色与超管)
  - Redis :fakeredis 内存替身(进程内,重启即清空)

⚠️ 仅供本地开发!生产/验收请用 docker compose(真 MySQL + Redis),见 README。

运行:
  cd backend
  .venv/Scripts/python run_local.py          # 默认 127.0.0.1:8000
  .venv/Scripts/python run_local.py --port 8001

登录:超管 admin / Admin@12345(可用环境变量 SUPER_ADMIN_PASSWORD 覆盖)。
配合前端:另开终端 `cd frontend && npm run dev`,浏览器开 http://localhost:5173
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import os

# ---- 必须在导入 app 之前,固定"本地开发"的环境 ----------------------------
# 用可解释的固定 DEV 密钥,保证重启后 dev_local.db 里的 AppSecret 仍可解密。
# 这些值仅用于本地演示,绝不可用于生产(生产走 .env / docker)。
_DEV_DIR = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_DEV_DIR}/dev_local.db")
os.environ.setdefault("DEBUG", "false")  # 关掉 SQL echo,日志清爽
os.environ.setdefault("JWT_SECRET_KEY", "LOCAL-DEV-ONLY-jwt-secret-do-not-use-in-prod")
os.environ.setdefault(
    "MP_SECRET_MASTER_KEY",
    base64.b64encode(b"LOCAL_DEV_ONLY_master_key_32byte").decode(),  # 恰好 32 字节
)
os.environ.setdefault("INTERNAL_TOKEN", "LOCAL-DEV-internal-token")

import fakeredis.aioredis  # noqa: E402
from sqlalchemy import BigInteger  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402


# SQLite 不支持 BIGINT 自增主键 —— 开发期把 BigInteger 编译成 INTEGER(仅 sqlite 方言)。
# 生产是 MySQL,不受影响。
@compiles(BigInteger, "sqlite")
def _bigint_as_integer_on_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN202
    return "INTEGER"


async def _init_db() -> None:
    """建表(若不存在)。预置数据由 app 的 lifespan seeds 完成。"""
    import app.models  # noqa: F401  —— 触发全部模型注册到 Base.metadata
    from app.core.db import Base, engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()  # 释放本事件循环的连接,交给 uvicorn 重新建池


def main() -> None:
    parser = argparse.ArgumentParser(description="本地零依赖开发启动器")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    asyncio.run(_init_db())

    import uvicorn

    from app.core.redis import get_redis
    from app.main import app

    # 用内存 Redis 替身覆盖依赖(登录锁定、JWT 黑/白名单均走它)
    _fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    app.dependency_overrides[get_redis] = lambda: _fake

    print("=" * 68)
    print("  本地开发模式(SQLite + 内存Redis,无需 Docker)")
    print(f"  API   : http://{args.host}:{args.port}")
    print(f"  文档  : http://{args.host}:{args.port}/docs")
    print("  超管  : admin / Admin@12345")
    print("  数据库: dev_local.db(删除该文件即可重置)")
    print("=" * 68)

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
