"""AppSecret 加密存储:AES-256-GCM(对齐设计 3.3.2,全文唯一版本)。

- 存储布局:nonce(12B) || ciphertext || tag(16B),整体入 mp_account.app_secret_cipher。
- 主密钥仅存环境变量 MP_SECRET_MASTER_KEY(32 字节 base64),支持 key_version 轮换。
- AAD 绑定 app_id + key_version,防止密文被搬移到其他记录或跨版本重放。

数据库中绝不出现明文 secret;decrypt 仅供 wx-gateway 内部凭据接口与"校验凭据"动作调用。
"""
import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings


class CryptoConfigError(RuntimeError):
    """主密钥缺失或格式错误。"""


def _load_keys() -> dict[int, bytes]:
    """{key_version: 32字节密钥}。教学期只有一个版本;轮换时在此登记多版本。"""
    raw = settings.MP_SECRET_MASTER_KEY.strip()
    if not raw:
        raise CryptoConfigError(
            "未配置 MP_SECRET_MASTER_KEY,无法加解密 AppSecret。"
            "生成:python -c \"import os,base64;print(base64.b64encode(os.urandom(32)).decode())\""
        )
    try:
        key = base64.b64decode(raw)
    except Exception as e:  # noqa: BLE001
        raise CryptoConfigError("MP_SECRET_MASTER_KEY 不是合法 base64") from e
    if len(key) != 32:
        raise CryptoConfigError(f"MP_SECRET_MASTER_KEY 解码后需为 32 字节(实为 {len(key)})")
    return {settings.MP_SECRET_KEY_VERSION: key}


def _aad(app_id: str, ver: int) -> bytes:
    return f"{app_id}:{ver}".encode("utf-8")


def current_key_version() -> int:
    return settings.MP_SECRET_KEY_VERSION


def encrypt_secret(app_id: str, plain: str, ver: int | None = None) -> bytes:
    ver = ver or settings.MP_SECRET_KEY_VERSION
    key = _load_keys()[ver]
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, plain.encode("utf-8"), _aad(app_id, ver))
    return nonce + ct  # ct 已含 16B tag


def decrypt_secret(app_id: str, blob: bytes, ver: int) -> str:
    key = _load_keys()[ver]
    nonce, ct = blob[:12], blob[12:]
    return AESGCM(key).decrypt(nonce, ct, _aad(app_id, ver)).decode("utf-8")


def mask_secret(plain: str) -> str:
    """脱敏显示:仅保留末 4 位,其余以 * 代替(用于日志/前端提示,永不回显全文)。"""
    if not plain:
        return ""
    tail = plain[-4:]
    return "*" * max(0, len(plain) - 4) + tail
