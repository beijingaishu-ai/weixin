"""认证原语:bcrypt 密码哈希 + JWT 双令牌签发/校验(对齐设计 3.7)。

访问令牌 30 分钟、刷新令牌 7 天,HS256;载荷含 sub/role/jti/typ/exp。
令牌状态(黑名单/白名单)由 auth_rbac 服务借助 Redis 维护,本模块只做编解码。
"""
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings

ACCESS = "access"
REFRESH = "refresh"


# ---------------- 密码哈希 ----------------
def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ---------------- JWT ----------------
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _encode(payload: dict) -> str:
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_access_token(user_id: int, role: str, jti: str | None = None) -> tuple[str, str]:
    """返回 (token, jti)。"""
    jti = jti or uuid.uuid4().hex
    exp = _now() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    token = _encode(
        {"sub": str(user_id), "role": role, "jti": jti, "typ": ACCESS, "exp": exp, "iat": _now()}
    )
    return token, jti


def create_refresh_token(user_id: int, jti: str | None = None) -> tuple[str, str]:
    jti = jti or uuid.uuid4().hex
    exp = _now() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    token = _encode({"sub": str(user_id), "jti": jti, "typ": REFRESH, "exp": exp, "iat": _now()})
    return token, jti


def decode_token(token: str) -> dict:
    """解码并校验签名与过期;失败抛 jwt 异常,由调用方转 401。"""
    return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])


def access_ttl_seconds() -> int:
    return settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60


def refresh_ttl_seconds() -> int:
    return settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600
