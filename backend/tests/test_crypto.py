"""AppSecret 加密层测试(app.core.crypto)。

覆盖:
- encrypt/decrypt 往返正确;
- 布局约定(nonce 12B 前缀, 密文含 16B tag, 每次 nonce 随机);
- AAD 绑定: 用错误 app_id / 错误 key_version 解密必败(防跨记录/跨版本搬移);
- 篡改密文触发 GCM 校验失败;
- mask_secret 脱敏规则(仅末 4 位可见, 空串安全)。

本文件不依赖 FastAPI app, 即使 auth_rbac / mp_manager router 尚未实现也能独立运行。
"""
import pytest
from cryptography.exceptions import InvalidTag

from app.core.crypto import (
    current_key_version,
    decrypt_secret,
    encrypt_secret,
    mask_secret,
)

APP_ID = "wx1234567890abcdef"
SECRET = "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6"  # 32 位形似真实 AppSecret


def test_encrypt_decrypt_roundtrip():
    ver = current_key_version()
    blob = encrypt_secret(APP_ID, SECRET, ver)
    assert isinstance(blob, (bytes, bytearray))
    assert decrypt_secret(APP_ID, blob, ver) == SECRET


def test_encrypt_default_version_matches_current():
    """不传 ver 时应使用当前 key_version, 可用该版本解回。"""
    ver = current_key_version()
    blob = encrypt_secret(APP_ID, SECRET)
    assert decrypt_secret(APP_ID, blob, ver) == SECRET


def test_layout_nonce_prefix_and_tag_length():
    """存储布局: nonce(12B) || ciphertext || tag(16B)。

    明文长度 L -> 总长 = 12(nonce) + L(密文, GCM 为流式等长) + 16(tag)。
    """
    ver = current_key_version()
    blob = encrypt_secret(APP_ID, SECRET, ver)
    assert len(blob) == 12 + len(SECRET.encode("utf-8")) + 16


def test_nonce_is_random_each_call():
    """相同明文两次加密应产生不同密文(nonce 随机), 但都能解回原文。"""
    ver = current_key_version()
    b1 = encrypt_secret(APP_ID, SECRET, ver)
    b2 = encrypt_secret(APP_ID, SECRET, ver)
    assert b1 != b2
    assert decrypt_secret(APP_ID, b1, ver) == SECRET
    assert decrypt_secret(APP_ID, b2, ver) == SECRET


def test_aad_binding_wrong_app_id_fails():
    """AAD 绑定 app_id: 换一个 app_id 解密必败(密文不能被搬到别的号)。"""
    ver = current_key_version()
    blob = encrypt_secret(APP_ID, SECRET, ver)
    with pytest.raises(InvalidTag):
        decrypt_secret("wxOTHERAPPID000000", blob, ver)


def test_aad_binding_wrong_version_fails():
    """AAD 绑定 key_version: 用错误版本号解密必败(防跨版本重放)。

    注意: 当前只登记了一个版本的密钥, 用不存在的版本会先触发 KeyError;
    故本用例断言"抛异常"即可, 不限定具体异常类型。
    """
    ver = current_key_version()
    blob = encrypt_secret(APP_ID, SECRET, ver)
    with pytest.raises(Exception):  # noqa: B017 —— KeyError 或 InvalidTag 均可
        decrypt_secret(APP_ID, blob, ver + 999)


def test_tampered_ciphertext_fails():
    """篡改任意一字节 -> GCM 认证失败。"""
    ver = current_key_version()
    blob = bytearray(encrypt_secret(APP_ID, SECRET, ver))
    blob[-1] ^= 0xFF  # 翻转 tag 末字节
    with pytest.raises(InvalidTag):
        decrypt_secret(APP_ID, bytes(blob), ver)


def test_mask_secret_keeps_last_four():
    assert mask_secret("abcdefgh") == "****efgh"
    assert mask_secret("1234567890") == "******7890"


def test_mask_secret_short_and_empty():
    # 空串 -> 空串(不泄露任何信息)
    assert mask_secret("") == ""
    # 长度 <=4 时无可掩位, 直接回显该短串(len-4 取 max(0,..))
    assert mask_secret("ab") == "ab"
    assert mask_secret("abcd") == "abcd"


def test_mask_secret_never_reveals_full_body():
    plain = "supersecretvalue1234"
    masked = mask_secret(plain)
    # 掩码后除末 4 位外不得包含原文前缀
    assert masked.endswith(plain[-4:])
    assert plain[:-4] not in masked
