"""ManualAdapter:运营手工导入(URL 导入或粘贴正文)。

手工源不自动拉取清单(fetch_list 返回空),主要经 service 的 manual-import 端点直接入库;
保留适配器身份以统一注册与校验。
"""
from __future__ import annotations

from typing import Any

from app.modules.collector.adapters.base import (
    ArticleDetail,
    ArticleMeta,
    SourceAdapter,
    register,
)


@register
class ManualAdapter(SourceAdapter):
    adapter_type = "manual"

    async def fetch_list(
        self, cursor: dict[str, Any]
    ) -> tuple[list[ArticleMeta], dict[str, Any]]:
        # 手工源不做自动增量拉取;内容由 manual-import 端点直接提交
        return [], dict(cursor or {})

    async def fetch_detail(self, meta: ArticleMeta) -> ArticleDetail:
        return ArticleDetail(
            url=meta.url,
            title=meta.title,
            pub_time=meta.pub_time,
            author=meta.author,
            source_mp_name=meta.source_mp_name,
            raw_html=str(meta.extra.get("raw_html", "")),
            cover_url=str(meta.extra.get("cover_url", "")),
            is_original_marked=bool(meta.extra.get("is_original_marked", False)),
        )

    async def healthcheck(self) -> bool:
        return True
