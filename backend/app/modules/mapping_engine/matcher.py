"""条件匹配器(纯函数,无 DB 依赖,便于 dry-run 与单测)。

match_condition_json 约定字段(全部可选,缺省即不限):
- keywords_exclude: list[str]  命中任一 → 直接 False(排除优先,短路第一步)
- keywords_include: list[str]  包含词
- keywords_include_mode: "ANY" | "ALL"  默认 ANY(含任一即可);ALL 须全含
- match_field: "title" | "content" | "title_and_content"  默认 title_and_content
    取值文本:title→仅标题;content→html_to_text(clean_html);title_and_content→两者拼接
- min_word_count: int  纯文本(html_to_text(clean_html))长度下限
- categories / tags: list[str]  collect_article 无对应字段 → 视为不限(直接跳过)

短路顺序:排除词 → 包含词 → 字数。任一关卡不过即 False。
"""
from __future__ import annotations

from app.core.simhash import html_to_text

_DEFAULT_FIELD = "title_and_content"


def _as_list(value) -> list[str]:
    """把配置里的关键词字段规整成非空字符串列表(容忍 None / 单个字符串 / 混杂类型)。"""
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    out: list[str] = []
    for v in value:
        if v is None:
            continue
        s = str(v).strip()
        if s:
            out.append(s)
    return out


def _plain_text(article) -> str:
    """采集正文纯文本(去标签)。"""
    return html_to_text(getattr(article, "clean_html", "") or "")


def _match_text(article, field: str) -> str:
    """按 match_field 组装用于关键词匹配的文本(统一小写)。"""
    title = getattr(article, "title", "") or ""
    if field == "title":
        text = title
    elif field == "content":
        text = _plain_text(article)
    else:  # title_and_content(默认)
        text = f"{title} {_plain_text(article)}"
    return text.lower()


def evaluate(cond: dict | None, article) -> bool:
    """条件是否命中(纯函数)。cond 为空 → 视为无条件命中(True)。"""
    if not cond:
        return True

    field = cond.get("match_field") or _DEFAULT_FIELD
    text = _match_text(article, field)

    # 1) 排除词优先:命中任一 → False
    excludes = _as_list(cond.get("keywords_exclude"))
    if excludes and any(kw.lower() in text for kw in excludes):
        return False

    # 2) 包含词
    includes = _as_list(cond.get("keywords_include"))
    if includes:
        mode = (cond.get("keywords_include_mode") or "ANY").upper()
        lowered = [kw.lower() for kw in includes]
        if mode == "ALL":
            if not all(kw in text for kw in lowered):
                return False
        else:  # ANY
            if not any(kw in text for kw in lowered):
                return False

    # 3) 字数(按纯文本长度)
    min_wc = cond.get("min_word_count")
    if isinstance(min_wc, int) and min_wc > 0:
        if len(_plain_text(article)) < min_wc:
            return False

    # categories / tags:collect_article 无该字段 → 不限(跳过)

    return True


def evaluate_detail(cond: dict | None, article) -> dict:
    """逐条件判定明细(供 dry-run 展示):每关卡 {name, applicable, passed, detail}。

    返回 {matched: bool, checks: [...]}。matched 与 evaluate() 语义等价。
    """
    checks: list[dict] = []
    matched = True

    if not cond:
        return {"matched": True, "checks": checks}

    field = cond.get("match_field") or _DEFAULT_FIELD
    text = _match_text(article, field)
    plain = _plain_text(article)

    # 1) 排除词
    excludes = _as_list(cond.get("keywords_exclude"))
    if excludes:
        hit = [kw for kw in excludes if kw.lower() in text]
        passed = len(hit) == 0
        matched = matched and passed
        checks.append({
            "name": "keywords_exclude",
            "applicable": True,
            "passed": passed,
            "detail": f"命中排除词 {hit}" if hit else "未命中任何排除词",
        })
    else:
        checks.append({
            "name": "keywords_exclude",
            "applicable": False,
            "passed": True,
            "detail": "未配置排除词",
        })

    # 2) 包含词
    includes = _as_list(cond.get("keywords_include"))
    if includes:
        mode = (cond.get("keywords_include_mode") or "ANY").upper()
        lowered = {kw: kw.lower() in text for kw in includes}
        hit = [kw for kw, ok in lowered.items() if ok]
        if mode == "ALL":
            passed = all(lowered.values())
            detail = f"ALL 模式,已含 {hit} / 需全含 {includes}"
        else:
            passed = any(lowered.values())
            detail = f"ANY 模式,命中 {hit} / 候选 {includes}"
        matched = matched and passed
        checks.append({
            "name": "keywords_include",
            "applicable": True,
            "passed": passed,
            "detail": detail,
        })
    else:
        checks.append({
            "name": "keywords_include",
            "applicable": False,
            "passed": True,
            "detail": "未配置包含词",
        })

    # 3) 字数
    min_wc = cond.get("min_word_count")
    if isinstance(min_wc, int) and min_wc > 0:
        actual = len(plain)
        passed = actual >= min_wc
        matched = matched and passed
        checks.append({
            "name": "min_word_count",
            "applicable": True,
            "passed": passed,
            "detail": f"纯文本 {actual} 字 / 下限 {min_wc}",
        })
    else:
        checks.append({
            "name": "min_word_count",
            "applicable": False,
            "passed": True,
            "detail": "未配置字数下限",
        })

    # categories / tags:采集文章无该字段 → 不限
    for extra in ("categories", "tags"):
        if _as_list(cond.get(extra)):
            checks.append({
                "name": extra,
                "applicable": False,
                "passed": True,
                "detail": "采集文章无该字段,视为不限",
            })

    return {"matched": matched, "checks": checks}
