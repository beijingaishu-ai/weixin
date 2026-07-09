"""采集去重指纹单测(app.core.simhash)。

纯函数单测,不依赖 DB / HTTP / app 导入,始终可独立运行。
覆盖:
- normalize_url:去 utm/跟踪参数、host 小写、去尾斜杠后一致;
- url_hash:规范化等价的 URL 得到相同哈希;空 URL 走 fallback;
- simhash64:完全相同文本 hamming=0;明显不同文本 hamming 大(>10);
- bands:64 位切成 4 段各 16 位,拆分正确且可重组;
- normalize_title:去空白/标点/统一小写。
"""
from app.core.simhash import (
    bands,
    hamming,
    html_to_text,
    normalize_title,
    normalize_url,
    simhash64,
    simhash_hex,
    url_hash,
)


# ---------------------------------------------------------------------------
# normalize_url:去跟踪参数 + host 小写 + 去尾斜杠
# ---------------------------------------------------------------------------
def test_normalize_url_strips_tracking_params():
    """utm_* / scene / from / chksm / clicktime 等跟踪参数应被剥离,保留业务参数。"""
    dirty = (
        "https://mp.weixin.qq.com/s/abc"
        "?utm_source=x&utm_medium=y&scene=1&from=timeline"
        "&chksm=deadbeef&clicktime=123&id=42"
    )
    norm = normalize_url(dirty)
    assert "utm_source" not in norm
    assert "utm_medium" not in norm
    assert "scene=" not in norm
    assert "from=" not in norm
    assert "chksm" not in norm
    assert "clicktime" not in norm
    # 业务参数保留
    assert "id=42" in norm


def test_normalize_url_lowercases_host_only():
    """host 转小写;path 大小写保留(路径大小写敏感)。"""
    norm = normalize_url("HTTPS://MP.Weixin.QQ.com/S/AbC")
    assert norm.startswith("https://mp.weixin.qq.com")
    # path 未被强制小写
    assert "/S/AbC" in norm


def test_normalize_url_strips_trailing_slash():
    assert normalize_url("http://example.com/path/") == normalize_url(
        "http://example.com/path"
    )


def test_normalize_url_equivalent_after_normalization():
    """大小写 host + 尾斜杠 + 跟踪参数不同,但规范化后完全一致。"""
    a = "HTTPS://Example.COM/s/abc/?utm_source=weibo&foo=bar"
    b = "https://example.com/s/abc?foo=bar"
    assert normalize_url(a) == normalize_url(b)


def test_normalize_url_empty_returns_empty():
    """空 URL 原样返回空串(ManualAdapter 粘贴正文场景)。"""
    assert normalize_url("") == ""
    assert normalize_url("   ") == ""


# ---------------------------------------------------------------------------
# url_hash:规范化等价 → 同哈希;空 URL 走 fallback
# ---------------------------------------------------------------------------
def test_url_hash_same_for_equivalent_urls():
    a = "HTTPS://Example.COM/s/abc/?utm_source=weibo&foo=bar"
    b = "https://example.com/s/abc?foo=bar"
    assert url_hash(a) == url_hash(b)


def test_url_hash_differs_for_distinct_urls():
    assert url_hash("https://example.com/a") != url_hash("https://example.com/b")


def test_url_hash_empty_uses_fallback():
    """URL 为空时用 fallback(标题+正文)兜底成键;不同 fallback → 不同哈希。"""
    h1 = url_hash("", fallback="标题A|正文一")
    h2 = url_hash("", fallback="标题B|正文二")
    assert h1 != h2
    # 相同 fallback → 相同哈希(稳定)
    assert url_hash("", fallback="标题A|正文一") == h1


def test_url_hash_is_hex_sha256():
    h = url_hash("https://example.com/x")
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


# ---------------------------------------------------------------------------
# simhash64:相同文本 hamming=0;明显不同文本 hamming 大
# ---------------------------------------------------------------------------
def test_simhash_identical_text_hamming_zero():
    text = "这是一篇关于人工智能技术发展的深度报道内容详实数据翔实值得一读"
    assert hamming(simhash64(text), simhash64(text)) == 0


def test_simhash_distinct_text_hamming_large():
    """两段主题、用词完全不同的文本,Hamming 距离应明显大于近似阈值(设计取 3)。"""
    a = "人工智能大模型在自然语言处理与计算机视觉领域取得突破性进展引发行业关注"
    b = "周末去郊外露营烧烤钓鱼徒步爬山看日出拍照片心情愉悦身心放松惬意无比"
    dist = hamming(simhash64(a), simhash64(b))
    assert dist > 10, f"明显不同文本 Hamming 应大, 实为 {dist}"


def test_simhash_empty_text_is_zero():
    assert simhash64("") == 0
    assert simhash64("   ") == 0


def test_simhash_hex_is_16_chars():
    h = simhash_hex(simhash64("采集去重指纹测试文本"))
    assert len(h) == 16
    assert all(c in "0123456789abcdef" for c in h)


# ---------------------------------------------------------------------------
# bands:64 位切成 4 段各 16 位,拆分正确且可重组
# ---------------------------------------------------------------------------
def test_bands_split_known_value():
    v = 0x1234_5678_9ABC_DEF0
    assert bands(v) == (0x1234, 0x5678, 0x9ABC, 0xDEF0)


def test_bands_each_within_16_bits():
    v = simhash64("任意一段用于验证分段范围的文本内容")
    for seg in bands(v):
        assert 0 <= seg <= 0xFFFF


def test_bands_reconstruct_original():
    """4 段左移拼接应还原 64 位原值。"""
    v = simhash64("鸽笼原理分段索引召回候选测试")
    b0, b1, b2, b3 = bands(v)
    recon = (b0 << 48) | (b1 << 32) | (b2 << 16) | b3
    assert recon == (v & 0xFFFFFFFFFFFFFFFF)


# ---------------------------------------------------------------------------
# normalize_title:去空白/标点/统一小写
# ---------------------------------------------------------------------------
def test_normalize_title_strips_space_punct_and_lowercases():
    assert normalize_title("Foo Bar!!!") == normalize_title("foobar")


def test_normalize_title_keeps_cjk():
    """CJK 属于 \\w,不被剥离;仅去空白与标点。"""
    assert normalize_title("你好, 世界!") == "你好世界"


def test_normalize_title_empty():
    assert normalize_title("") == ""
    assert normalize_title(None) == ""


# ---------------------------------------------------------------------------
# html_to_text:去标签、折叠空白(辅助函数,附带覆盖)
# ---------------------------------------------------------------------------
def test_html_to_text_strips_tags_and_collapses_ws():
    assert html_to_text("<p>Hello</p>\n\n  <b>World</b>") == "Hello World"
