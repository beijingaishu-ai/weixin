"""RSSAdapter:抓取公开 RSS2.0 / Atom feed,用标准库 ElementTree 解析(不引入 feedparser)。

- config_json.feed_url:必填,feed 地址。
- 解析 RSS2.0 的 <item>(title/link/pubDate/author|dc:creator/description)
  与 Atom 的 <entry>(title/link[@href]/updated|published/author>name/summary|content)。
- fetch_detail 教学期直接用清单里带回的 description/summary 作正文(不再抓 link 页,避免额外触网)。
- 增量游标 last_pub_time:记录本批最大发布时间字符串,下次只保留更新的项(尽力而为,
  时间不可比时退化为全量,由后续 url_hash / simhash 去重兜底)。

合规:仅 GET 公开 feed,默认 UA,无任何反爬对抗。
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

import httpx

from app.modules.collector.adapters.base import (
    ArticleDetail,
    ArticleMeta,
    SourceAdapter,
    register,
)

# 常见命名空间
_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "dc": "http://purl.org/dc/elements/1.1/",
    "content": "http://purl.org/rss/1.0/modules/content/",
}

_HTTP_TIMEOUT = 15.0


def _local(tag: str) -> str:
    """去命名空间前缀,取本地标签名(如 '{...}entry' -> 'entry')。"""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _text(el: ET.Element | None) -> str:
    return (el.text or "").strip() if el is not None else ""


def _find_first(item: ET.Element, *local_names: str) -> ET.Element | None:
    """按本地名(忽略命名空间)在直接子节点里找第一个匹配。"""
    wanted = set(local_names)
    for child in item:
        if _local(child.tag) in wanted:
            return child
    return None


def _atom_link(entry: ET.Element) -> str:
    """Atom <link href=...>:优先 rel=alternate 或无 rel 的 link。"""
    fallback = ""
    for child in entry:
        if _local(child.tag) != "link":
            continue
        rel = child.get("rel", "")
        href = child.get("href", "")
        if not href:
            continue
        if rel in ("", "alternate"):
            return href
        fallback = fallback or href
    return fallback


def _author(item: ET.Element) -> str:
    """RSS author / dc:creator,或 Atom author>name。"""
    a = _find_first(item, "author", "creator")
    if a is not None:
        # Atom author 是复合节点,取其 name 子节点
        name = _find_first(a, "name")
        if name is not None:
            return _text(name)
        return _text(a)
    return ""


def _parse_items(root: ET.Element) -> list[dict[str, str]]:
    """统一解析出 dict 列表(title/link/pub_time/author/description)。"""
    rows: list[dict[str, str]] = []
    root_local = _local(root.tag)

    # RSS2.0: <rss><channel><item>...   Atom: <feed><entry>...
    if root_local == "rss":
        channel = _find_first(root, "channel")
        items = list(channel) if channel is not None else []
        item_tag, title_tag, desc_tags = "item", "title", ("description",)
        link_from_atom = False
    else:
        # Atom(root 为 feed)或直接 channel
        items = list(root)
        item_tag, title_tag, desc_tags = "entry", "title", ("summary", "content")
        link_from_atom = True

    for el in items:
        if _local(el.tag) != item_tag:
            continue
        title = _text(_find_first(el, title_tag))
        if link_from_atom:
            link = _atom_link(el)
            if not link:
                link = _text(_find_first(el, "id"))
        else:
            link = _text(_find_first(el, "link"))
        pub = _text(_find_first(el, "pubDate", "published", "updated", "date"))
        desc_el = _find_first(el, *desc_tags)
        description = _text(desc_el)
        rows.append(
            {
                "title": title,
                "link": link,
                "pub_time": pub,
                "author": _author(el),
                "description": description,
            }
        )
    return rows


@register
class RSSAdapter(SourceAdapter):
    """标准库 RSS/Atom 适配器。"""

    adapter_type = "rss"

    def _feed_url(self) -> str:
        url = str(self.config.get("feed_url") or "").strip()
        if not url:
            raise ValueError("RSS 采集源缺少 config_json.feed_url")
        return url

    async def _download(self) -> str:
        async with httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT, follow_redirects=True
        ) as client:
            resp = await client.get(self._feed_url())
            resp.raise_for_status()
            return resp.text

    async def fetch_list(
        self, cursor: dict[str, Any]
    ) -> tuple[list[ArticleMeta], dict[str, Any]]:
        xml_text = await self._download()
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            raise ValueError(f"RSS/Atom 解析失败: {e}") from e

        rows = _parse_items(root)
        last_pub = str((cursor or {}).get("last_pub_time") or "")

        metas: list[ArticleMeta] = []
        max_pub = last_pub
        for r in rows:
            pub = r["pub_time"]
            # 增量:字符串可比时跳过 <= last_pub 的项(尽力而为)
            if last_pub and pub and pub <= last_pub:
                continue
            metas.append(
                ArticleMeta(
                    url=r["link"],
                    title=r["title"],
                    pub_time=pub,
                    author=r["author"],
                    source_mp_name="",
                    extra={"description": r["description"]},
                )
            )
            if pub and pub > max_pub:
                max_pub = pub

        new_cursor = dict(cursor or {})
        if max_pub:
            new_cursor["last_pub_time"] = max_pub
        return metas, new_cursor

    async def fetch_detail(self, meta: ArticleMeta) -> ArticleDetail:
        # 教学期:正文取清单 description/summary,不再二次抓 link 页
        raw_html = str(meta.extra.get("description", "")) if meta.extra else ""
        return ArticleDetail(
            url=meta.url,
            title=meta.title,
            pub_time=meta.pub_time,
            author=meta.author,
            source_mp_name=meta.source_mp_name,
            raw_html=raw_html,
            cover_url="",
            is_original_marked=False,
        )

    async def healthcheck(self) -> bool:
        xml_text = await self._download()
        try:
            ET.fromstring(xml_text)
        except ET.ParseError:
            return False
        return True
