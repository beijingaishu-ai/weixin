"""数据库:异步引擎 + 会话工厂 + 声明式 Base。

说明:表结构的**唯一 DDL 事实源是 deploy/mysql/init/01_schema.sql**(对齐设计第 2 章)。
本层 ORM 模型仅用于查询/写入,列名与 schema.sql 严格一致;字段类型选用可移植类型
(Integer/String/LargeBinary...),以便测试可用 create_all() 在 SQLite 内存库跑通同一套模型。
"""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


# 注意:SQLAlchemy 2.0.36 + aiomysql 0.2.0 下 pool_pre_ping=True 会触发
# AsyncAdapt_aiomysql_connection.ping() 签名不匹配(缺 reconnect 位参)而 500。
# 改用 pool_recycle 定期回收连接,规避该坏路径,同时防 MySQL 空闲断连。
engine = create_async_engine(
    settings.sqlalchemy_database_uri,
    pool_pre_ping=False,
    pool_recycle=3600,
    future=True,
    echo=False,
)

SessionLocal = async_sessionmaker(
    engine, expire_on_commit=False, class_=AsyncSession, autoflush=False
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖:每请求一个会话,退出时自动关闭。

    测试通过 app.dependency_overrides[get_db] 注入 SQLite 会话。
    """
    async with SessionLocal() as session:
        yield session
