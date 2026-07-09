"""转换算子(纯函数,无 DB 依赖)。

transform_action_json 约定字段(全部可选):
- title_template: str  标题模板,占位 {title}{source_name}{category}{date},渲染后超 64 截断
- pipeline: list[dict]  正文流水线,每步 {op: <算子名>, ...参数}
    支持算子(PIPELINE_OPS):
      regex_replace     : {pattern, repl, count?}      正则替换 clean_html
      remove_paragraph  : {mode: contains|regex, value} 删除命中的 <p>…</p> 段落
      strip_external_links: {}                          去 <a> 标签保留其文字
      rehost_images     : {mode: mark_only}             mark_only 只扫外链图,不上传(标注数量)
      append_block      : {position: head|tail, html}   头/尾追加版权/来源块
                          占位 {source_name}{title}{publish_time}{author}{url}

apply_transform(transform_action, art, source_name) -> (title, content_html)
"""
from __future__ import annotations

import re
from datetime import datetime

TITLE_MAX = 64

# 外链图正则(http/https 开头的 src);data:/ 相对路径视为已内联,不计外链
_IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.I)
_IMG_SRC_RE = re.compile(r'src\s*=\s*["\']?\s*(https?://[^"\'\s>]+)', re.I)
# <a ...>inner</a> → inner(去链接留文字)
_A_TAG_RE = re.compile(r"<a\b[^>]*>(.*?)</a>", re.I | re.S)
# 段落分割(用于 remove_paragraph)
_P_BLOCK_RE = re.compile(r"<p\b[^>]*>.*?</p>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")


# ---------------------------------------------------------------------------
# 标题渲染
# ---------------------------------------------------------------------------
def render_title(template: str | None, art, source_name: str = "") -> str:
    """渲染标题模板,占位 {title}{source_name}{category}{date};超 64 截断。

    template 为空 → 直接用采集标题(同样截断)。
    """
    raw_title = getattr(art, "title", "") or ""
    if not template:
        return raw_title[:TITLE_MAX]

    ctx = {
        "title": raw_title,
        "source_name": source_name or "",
        "category": "",  # 采集文章无分类字段,占位置空
        "date": datetime.now().strftime("%Y-%m-%d"),
    }
    try:
        rendered = template.format_map(_SafeDict(ctx))
    except (ValueError, IndexError):
        # 模板含非法花括号 → 退化为原模板文本
        rendered = template
    return rendered[:TITLE_MAX]


class _SafeDict(dict):
    """format_map 兜底:未知占位符原样保留 {key} 而非抛 KeyError。"""

    def __missing__(self, key):  # noqa: D401
        return "{" + key + "}"


# ---------------------------------------------------------------------------
# 正文算子
# ---------------------------------------------------------------------------
def op_regex_replace(html: str, step: dict, ctx: dict) -> str:
    pattern = step.get("pattern")
    if not pattern:
        return html
    repl = step.get("repl", "")
    count = step.get("count", 0)
    try:
        return re.sub(pattern, repl, html, count=count if isinstance(count, int) else 0)
    except re.error:
        return html


def op_remove_paragraph(html: str, step: dict, ctx: dict) -> str:
    mode = (step.get("mode") or "contains").lower()
    value = step.get("value")
    if not value:
        return html

    if mode == "regex":
        try:
            needle = re.compile(value, re.I | re.S)
        except re.error:
            return html
    else:
        needle = None  # contains 模式

    def _keep(match: re.Match) -> str:
        block = match.group(0)
        inner_text = _TAG_RE.sub("", block)
        if mode == "regex":
            return "" if needle.search(inner_text) or needle.search(block) else block
        return "" if value in inner_text else block

    return _P_BLOCK_RE.sub(_keep, html)


def op_strip_external_links(html: str, step: dict, ctx: dict) -> str:
    """去 <a> 标签,仅保留其可见文字。"""
    return _A_TAG_RE.sub(lambda m: m.group(1), html)


def op_rehost_images(html: str, step: dict, ctx: dict) -> str:
    """mode=mark_only:只扫描外链图数量并记入 ctx,不上传、不改 HTML。

    (真正转存图片留待 M2 提审阶段 ensure_material_on_wx;此处仅做静态标注。)
    """
    mode = (step.get("mode") or "mark_only").lower()
    ext_imgs = [
        m.group(1)
        for tag in _IMG_TAG_RE.findall(html)
        for m in [_IMG_SRC_RE.search(tag)]
        if m
    ]
    ctx["external_images"] = ext_imgs
    ctx["external_image_count"] = len(ext_imgs)
    # mark_only(及未知模式)一律不改 HTML
    return html


def op_append_block(html: str, step: dict, ctx: dict) -> str:
    """头/尾追加来源版权块;占位 {source_name}{title}{publish_time}{author}{url}。"""
    tpl = step.get("html")
    if not tpl:
        return html
    position = (step.get("position") or "tail").lower()
    art = ctx.get("_article")
    publish_time = ""
    if art is not None and getattr(art, "source_publish_time", None):
        publish_time = art.source_publish_time.strftime("%Y-%m-%d %H:%M")
    block_ctx = {
        "source_name": ctx.get("source_name", ""),
        "title": getattr(art, "title", "") if art is not None else "",
        "publish_time": publish_time,
        "author": getattr(art, "author", "") if art is not None else "",
        "url": getattr(art, "url", "") if art is not None else "",
    }
    try:
        block = tpl.format_map(_SafeDict(block_ctx))
    except (ValueError, IndexError):
        block = tpl
    return block + html if position == "head" else html + block


PIPELINE_OPS = {
    "regex_replace": op_regex_replace,
    "remove_paragraph": op_remove_paragraph,
    "strip_external_links": op_strip_external_links,
    "rehost_images": op_rehost_images,
    "append_block": op_append_block,
}


def apply_transform(
    transform_action: dict | None, art, source_name: str = ""
) -> tuple[str, str]:
    """套用转换动作,返回 (title, content_html)。transform_action 为空 → 原样透传。"""
    transform_action = transform_action or {}

    title = render_title(transform_action.get("title_template"), art, source_name)

    html = getattr(art, "clean_html", "") or ""
    ctx: dict = {"_article": art, "source_name": source_name}
    for step in transform_action.get("pipeline") or []:
        if not isinstance(step, dict):
            continue
        op_name = step.get("op")
        fn = PIPELINE_OPS.get(op_name)
        if fn is None:
            continue
        html = fn(html, step, ctx)

    return title, html
