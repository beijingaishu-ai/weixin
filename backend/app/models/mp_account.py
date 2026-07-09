"""公众号档案 / 运营分配 模型。列名严格对齐 schema.sql(设计第 2、3 章)。

app_secret_cipher 用 LargeBinary(映射 MySQL VARBINARY(512)),存 AES-256-GCM 密文;
任何序列化模型都不得包含该列(secret 零回显)。
"""
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class MpAccount(Base):
    __tablename__ = "mp_account"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    mp_name: Mapped[str] = mapped_column(String(64), nullable=False)
    wx_original_id: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    app_id: Mapped[str] = mapped_column(String(32), nullable=False)
    app_secret_cipher: Mapped[bytes] = mapped_column(LargeBinary(512), nullable=False)
    # 1=开发者密钥直连 2=第三方平台授权(预留)
    auth_mode: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    key_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    # 1=订阅号 2=服务号 3=测试/模拟号(=3 走 MockChannel)
    account_type: Mapped[int] = mapped_column(Integer, nullable=False)
    is_verified: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 号级审核开关(默认开),仅 super_admin 可改
    need_review: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    avatar_url: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    qrcode_url: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    # 出口 IP 是否已加入该号后台白名单(校验凭据时更新;40164 置 0)
    ip_whitelist_ok: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # ---- 浏览器发布登录态授权(扫码授权 + 可配有效期);详见 docs/浏览器发布登录态授权设计.md ----
    # 最近一次扫码成功、storage_state 落盘时刻(仅续扫回写)
    wx_login_captured_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # = captured_at + ttl_hours;发布前置与巡检的唯一时间判据
    wx_login_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 行级有效期(小时),覆盖全局 WX_LOGIN_TTL_HOURS
    wx_login_ttl_hours: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=48)
    # WxLoginStatus 枚举快照
    wx_login_status: Mapped[str] = mapped_column(String(16), nullable=False, default="UNAUTHORIZED")
    # 续扫告警去重戳:告警后置时间,续扫成功清空
    wx_login_alerted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 1=正常 2=凭据异常 0=停用
    status: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    remark: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    is_deleted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (UniqueConstraint("app_id", name="uk_app_id"),)


class MpAccountAssign(Base):
    __tablename__ = "mp_account_assign"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mp_account_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # 号内权限级别:1=只读 2=可编辑 3=可提审 4=可发布(逐级包含)
    perm_level: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    assigned_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # 软删占位:0=有效;取消分配时 UPDATE 为本行 id,使唯一键可被重新占用
    deleted_flag: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user_id", "mp_account_id", "deleted_flag", name="uk_user_mp"),
    )
