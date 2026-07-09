"""HTML 处理管道:正文白名单清洗 / 样式保留 / 链接降级 / 外链图片识别 / 体检。

设计对齐 4.3(图文编排 HTML 管道)。本模块**纯函数**:不触网、不查库、不写盘。
真正的正文图转存(uploadimg 换微信域 URL)在 service.submit_article 里做,本模块只负责:
  1) 按白名单删除危险/不支持标签(script/style/iframe/form/input/video 等);
  2) 抹掉所有 on* 事件属性与 javascript: 协议(防 XSS);
  3) 保留内联 style(公众号正文靠内联样式呈现);
  4) 非微信域(非 mmbiz.qpic.cn)的 <a> 链接降级为纯文本(公众号正文禁外链跳转);
  5) 识别外链图片清单 external_imgs(每项含 src 与 data-material-id),供 service 决定转存;
  6) 产出体检 issues(空正文、外链图无对应素材等),前端据此提示。

stage:
  "SAVE" —— 保存/提审前的清洗与体检(当前唯一实现)。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Comment

# 微信正文允许的标签白名单(其余标签"脱壳"保留文字,危险标签整体删除)
ALLOWED_TAGS: set[str] = {
    "p", "br", "hr", "span", "strong", "em", "u", "s", "sup", "sub",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "blockquote", "section", "ul", "ol", "li",
    "img", "table", "tr", "td", "th", "a",
}

# 直接整棵子树删除的危险/不支持标签(连同内部文字一并去掉)
DANGEROUS_TAGS: set[str] = {"script", "style", "iframe", "form", "input", "video"}

# 每类标签允许保留的属性(白名单;其余属性一律删除)
ALLOWED_ATTRS: dict[str, set[str]] = {
    "*": {"style"},  # 所有标签都可保留内联样式
    "img": {"src", "alt", "data-src", "data-material-id", "width", "height", "style"},
    "a": {"href", "style"},
    "td": {"colspan", "rowspan", "style"},
    "th": {"colspan", "rowspan", "style"},
    "table": {"border", "cellpadding", "cellspacing", "style"},
    "section": {"style", "class"},
    "span": {"style", "class"},
}

# 微信正文图允许的域(已转存到微信侧的 URL 均落此域)
WX_IMG_HOST = "mmbiz.qpic.cn"


@dataclass
class ExternalImg:
    """一条待转存的外链图片。"""

    src: str
    data_material_id: int | None = None


@dataclass
class PipelineResult:
    """管道处理结果。"""

    cleaned_html: str
    external_imgs: list[ExternalImg] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)


def _is_wx_img(src: str) -> bool:
    """图片 src 是否已是微信域(无需再转存)。"""
    if not src:
        return False
    return WX_IMG_HOST in src


def _is_wx_link(href: str) -> bool:
    """<a> 链接是否指向微信域(mp.weixin.qq.com / mmbiz.qpic.cn)——仅此类保留跳转。"""
    if not href:
        return False
    low = href.lower()
    return "mp.weixin.qq.com" in low or WX_IMG_HOST in low


def _strip_dangerous_attrs(tag) -> None:
    """删除 on* 事件属性、javascript: 协议;按白名单裁剪属性。"""
    allowed = ALLOWED_ATTRS.get(tag.name, set()) | ALLOWED_ATTRS["*"]
    for attr in list(tag.attrs.keys()):
        low = attr.lower()
        # 事件属性(onclick/onerror/onload...)一律删除
        if low.startswith("on"):
            del tag.attrs[attr]
            continue
        # 不在白名单的属性删除
        if low not in allowed:
            del tag.attrs[attr]
            continue
        # javascript:/vbscript:/data: 协议的 href/src 清空(防脚本注入)
        if low in ("href", "src"):
            val = str(tag.attrs.get(attr, "")).strip().lower()
            if val.startswith(("javascript:", "vbscript:")):
                del tag.attrs[attr]


def _int_or_none(val) -> int | None:
    try:
        return int(str(val).strip())
    except (TypeError, ValueError):
        return None


def process_article_html(raw_html: str, stage: str = "SAVE") -> PipelineResult:
    """清洗正文 HTML 并产出外链图清单与体检结果(纯函数,不触网不查库)。

    参数:
        raw_html: 原始正文 HTML(可能来自富文本编辑器或采集转换)。
        stage:    处理阶段;当前仅 "SAVE" 有实现(清洗 + 体检 + 外链识别)。
    返回:
        PipelineResult(cleaned_html, external_imgs, issues)。
    """
    issues: list[str] = []
    external_imgs: list[ExternalImg] = []

    if not raw_html or not raw_html.strip():
        return PipelineResult(cleaned_html="", external_imgs=[], issues=["正文为空"])

    soup = BeautifulSoup(raw_html, "html.parser")

    # 1) 删除 HTML 注释(可能藏条件注释脚本)
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()

    # 2) 删除危险/不支持标签(连同子树)
    for tag in soup.find_all(DANGEROUS_TAGS):
        tag.decompose()

    # 3) 遍历剩余标签:白名单裁剪 + 属性净化;非白名单标签脱壳(保留文字)
    for tag in soup.find_all(True):
        # decompose 后可能已从树上摘除,跳过
        if tag.name is None:
            continue
        if tag.name not in ALLOWED_TAGS:
            tag.unwrap()  # 脱壳:删标签保留其内部内容
            continue
        _strip_dangerous_attrs(tag)

    # 4) 图片:识别外链图清单(非微信域需转存);微信域直接放行
    for img in soup.find_all("img"):
        src = (img.get("src") or img.get("data-src") or "").strip()
        mat_id = _int_or_none(img.get("data-material-id"))
        if _is_wx_img(src):
            continue
        if not src and mat_id is None:
            issues.append("存在无 src 且无 data-material-id 的图片,已跳过")
            continue
        external_imgs.append(ExternalImg(src=src, data_material_id=mat_id))
        if mat_id is None:
            issues.append(
                f"外链图片未绑定素材库(data-material-id 缺失),提审时将跳过转存: {src[:80]}"
            )

    # 5) 链接:非微信域 <a> 降级为纯文本(unwrap 保留锚文本)
    for a in soup.find_all("a"):
        href = (a.get("href") or "").strip()
        if not _is_wx_link(href):
            a.unwrap()

    cleaned_html = str(soup)

    # 6) 体检:清洗后纯文本为空
    if not soup.get_text(strip=True) and not soup.find("img"):
        issues.append("清洗后正文无有效文字与图片")

    return PipelineResult(
        cleaned_html=cleaned_html,
        external_imgs=external_imgs,
        issues=issues,
    )
