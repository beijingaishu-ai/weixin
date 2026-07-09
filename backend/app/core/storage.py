"""本地素材存储:按 SHA-256 内容寻址落盘,天然秒传去重(对齐设计 4.1)。

目录结构:{MEDIA_ROOT}/ab/cd/<sha256><ext>,前两级用哈希前缀分桶避免单目录过多文件。
生产可替换为对象存储(MinIO/OSS),接口保持不变。
"""
import hashlib
import os
from pathlib import Path

# 默认落在 backend/media(已 gitignore);可用环境变量覆盖
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", Path(__file__).resolve().parents[2] / "media"))

_EXT_BY_TYPE = {
    "image": ".jpg",
    "thumb": ".jpg",
}


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _path_for(file_hash: str, ext: str) -> Path:
    return MEDIA_ROOT / file_hash[:2] / file_hash[2:4] / f"{file_hash}{ext}"


def save_bytes(data: bytes, ext: str = ".jpg") -> tuple[str, str, int]:
    """写盘并返回 (file_hash, 相对路径, 字节数)。同哈希已存在则直接复用(秒传)。"""
    file_hash = sha256_hex(data)
    ext = ext if ext.startswith(".") else f".{ext}"
    dest = _path_for(file_hash, ext)
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    rel = str(dest.relative_to(MEDIA_ROOT)).replace("\\", "/")
    return file_hash, rel, len(data)


def read_bytes(rel_path: str) -> bytes:
    return (MEDIA_ROOT / rel_path).read_bytes()


def guess_ext(filename: str, default: str = ".jpg") -> str:
    suffix = Path(filename).suffix.lower()
    return suffix if suffix in {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"} else default
