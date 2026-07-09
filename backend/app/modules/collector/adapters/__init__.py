"""采集适配器包:三内置适配器(mock / rss / manual)+ 注册表。

导入本包即触发三适配器 @register 到 ADAPTER_REGISTRY(供 service 按 adapter_type 实例化)。
"""
from app.modules.collector.adapters.base import (
    ADAPTER_REGISTRY,
    ArticleDetail,
    ArticleMeta,
    SourceAdapter,
    register,
)

# 导入三适配器模块以触发注册(副作用导入,勿删)
from app.modules.collector.adapters import mock, rss, manual  # noqa: E402,F401

__all__ = [
    "ADAPTER_REGISTRY",
    "ArticleDetail",
    "ArticleMeta",
    "SourceAdapter",
    "register",
]
