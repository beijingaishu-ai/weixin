"""内容清洗管道(对齐设计 5.6)。

纯函数 clean_html(raw_html) -> (clean_html, text):
- 删除 script/style/iframe/form/link/meta 整节点(去脚本、去外链样式、去跟踪像素);
- 剥离 on* 事件属性与 javascript: 协议;
- 标签白名单(strip 非白名单标签但保留其文字);
- 产出清洗后 HTML 与纯文本(供 simhash 指纹)。

图片本地化为可选 best-effort 扩展点(localize_images),教学期默认关闭、不触网、不调微信接口。
"""
from __future__ import annotations

from bs4 import BeautifulSoup, Comment

from app.core.simhash import html_to_text

# 允许保留的标签(其余标签 unwrap 保留文字)
ALLOW_TAGS = {
    "p", "br", "h1", "h2", "h3", "h4", "strong", "em", "u", "s", "blockquote",
    "ul", "ol", "li", "a", "img", "table", "thead", "tbody", "tr", "th", "td",
    "figure", "figcaption", "span", "div", "hr", "code", "pre",
}
# 直接整节点删除的危险/噪声标签
DROP_TAGS = {"script", "style", "iframe", "form", "link", "meta", "input", "noscript", "svg"}
# 各标签允许保留的属性(其余属性一律移除)
ALLOW_ATTRS = {
    "a": {"href", "title"},
    "img": {"src", "alt", "width", "height"},
}


def _clean_attrs(tag) -> None:
    allowed = ALLOW_ATTRS.get(tag.name, set())
    for attr in list(tag.attrs.keys()):
        val = tag.attrs.get(attr, "")
        # 去事件属性与危险协议
        if attr.lower().startswith("on"):
            del tag.attrs[attr]
            continue
        if attr in ("href", "src") and isinstance(val, str) and val.strip().lower().startswith(
            ("javascript:", "vbscript:", "data:text/html")
        ):
            del tag.attrs[attr]
            continue
        if attr not in allowed:
            del tag.attrs[attr]


def clean_html(raw_html: str) -> tuple[str, str]:
    """返回 (clean_html, text)。"""
    soup = BeautifulSoup(raw_html or "", "html.parser")

    # 删注释
    for c in soup.find_all(string=lambda s: isinstance(s, Comment)):
        c.extract()
    # 删危险/噪声整节点
    for tag in soup.find_all(DROP_TAGS):
        tag.decompose()
    # 逐标签:白名单外 unwrap(保留文字);白名单内净化属性
    for tag in soup.find_all(True):
        if tag.name in DROP_TAGS:
            tag.decompose()
            continue
        if tag.name not in ALLOW_TAGS:
            tag.unwrap()
        else:
            _clean_attrs(tag)

    cleaned = str(soup).strip()
    text = html_to_text(cleaned)
    return cleaned, text


def localize_images(clean_html_str: str, article_id: int) -> str:
    """图片本地化扩展点(教学期默认不启用,直接原样返回)。

    生产/需要时:逐张下载正文外链图片→落本地素材→改写 <img src>;不调微信接口。
    """
    return clean_html_str
