"""采集去重工具:URL 规范化指纹 + 正文 SimHash 近似指纹(对齐设计 5.7)。

- url_hash:SHA-256(规范化 URL),精确去重(collect_article.url_hash 唯一约束)。
- simhash:64 位 SimHash,存为 16 位十六进制字符串;切 4 段各 16 位建索引,
  按鸽笼原理"任一段相等"召回候选再算 Hamming 距离,≤3 判近似重复。
- 分词用字符级 2-gram(中文友好、无需 jieba/词典,教学足够);可替换为 jieba 提升精度。
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACK_PARAMS = re.compile(r"^(utm_|chksm|scene|from|isappinstalled|clicktime|wechat_)", re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def normalize_url(url: str) -> str:
    """小写 host、去跟踪参数、去尾部斜杠。空 URL 原样返回(ManualAdapter 粘贴正文场景)。"""
    if not url:
        return ""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    host = parts.netloc.lower()
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not _TRACK_PARAMS.match(k)]
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), host, path, urlencode(query), ""))


def url_hash(url: str, fallback: str = "") -> str:
    """规范化 URL 的 SHA-256;URL 为空时用 fallback(如标题+正文)兜底成键。"""
    key = normalize_url(url) or fallback
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def html_to_text(html: str) -> str:
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", html or "")).strip()


def _tokens(text: str) -> list[str]:
    """字符级 2-gram(去空白)。"""
    chars = re.sub(r"\s+", "", text)
    if len(chars) < 2:
        return [chars] if chars else []
    return [chars[i:i + 2] for i in range(len(chars) - 1)]


def simhash64(text: str) -> int:
    """返回 64 位 SimHash 整数。"""
    bits = [0] * 64
    toks = _tokens(text)
    if not toks:
        return 0
    for tok in toks:
        h = int.from_bytes(hashlib.md5(tok.encode("utf-8")).digest()[:8], "big")
        for i in range(64):
            bits[i] += 1 if (h >> i) & 1 else -1
    out = 0
    for i in range(64):
        if bits[i] > 0:
            out |= 1 << i
    return out


def simhash_hex(value: int) -> str:
    return f"{value & 0xFFFFFFFFFFFFFFFF:016x}"


def bands(value: int) -> tuple[int, int, int, int]:
    """把 64 位切成 4 段各 16 位,用于分段索引召回。"""
    return (
        (value >> 48) & 0xFFFF,
        (value >> 32) & 0xFFFF,
        (value >> 16) & 0xFFFF,
        value & 0xFFFF,
    )


def hamming(a: int, b: int) -> int:
    return bin((a ^ b) & 0xFFFFFFFFFFFFFFFF).count("1")


def normalize_title(title: str) -> str:
    """标题归一:去空白/标点/统一小写,用于标题相似预判。"""
    return re.sub(r"[\s\W_]+", "", (title or "").lower())
