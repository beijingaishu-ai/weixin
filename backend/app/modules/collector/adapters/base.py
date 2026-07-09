"""采集适配器抽象层(对齐设计 5.x 采集中心)。

三方能力统一收敛到 SourceAdapter 接口,service 只依赖此协议、不感知具体来源:
- fetch_list(cursor)  -> (list[ArticleMeta], new_cursor)   增量拉取清单 + 回写游标
- fetch_detail(meta)  -> ArticleDetail                      拉正文/封面/原创标记
- healthcheck()       -> bool                               连通性自检(test-run 用)

约束(合规红线):
- 子类**禁止任何反爬对抗**(伪造 UA 绕验证码、破解加密、模拟登录抓私域等一律不做)。
- mock/manual 不触网,可被测试直接实例化调用;rss 仅用标准库解析公开 feed。

游标 cursor 为纯 dict(如 {"last_pub_time": "..."}),由 service 以 JSON 存 cursor_json。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ArticleMeta:
    """清单项(轻量元信息,不含正文)。"""

    url: str = ""
    title: str = ""
    pub_time: str = ""            # ISO8601 或来源原始时间字符串,service 负责解析
    author: str = ""
    source_mp_name: str = ""      # 原始来源公众号/站点名(留痕用)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ArticleDetail(ArticleMeta):
    """详情项:在清单元信息上补正文/封面/原创标记。"""

    raw_html: str = ""
    cover_url: str = ""
    is_original_marked: bool = False


class SourceAdapter(ABC):
    """采集源适配器基类。

    构造入参统一为 config(json.loads(source.config_json) 的结果),
    子类从 config 读取自身所需键(feed_url / dataset / ...)。
    """

    #: 适配器类型标识,子类必须覆盖(与 collect_source.adapter_type 对应)
    adapter_type: str = ""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config: dict[str, Any] = config or {}

    @abstractmethod
    async def fetch_list(self, cursor: dict[str, Any]) -> tuple[list[ArticleMeta], dict[str, Any]]:
        """拉取清单;返回 (metas, new_cursor)。cursor 为空 dict 表示首拉。"""
        raise NotImplementedError

    @abstractmethod
    async def fetch_detail(self, meta: ArticleMeta) -> ArticleDetail:
        """按清单项拉正文详情。"""
        raise NotImplementedError

    @abstractmethod
    async def healthcheck(self) -> bool:
        """连通性/配置自检:成功返回 True,失败返回 False 或抛异常。"""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# 适配器注册表:adapter_type -> SourceAdapter 子类
# ---------------------------------------------------------------------------
ADAPTER_REGISTRY: dict[str, type[SourceAdapter]] = {}


def register(cls: type[SourceAdapter]) -> type[SourceAdapter]:
    """类装饰器:把适配器登记到 ADAPTER_REGISTRY(键取类属性 adapter_type)。"""
    key = getattr(cls, "adapter_type", "")
    if not key:
        raise ValueError(f"{cls.__name__} 未定义 adapter_type,无法注册")
    ADAPTER_REGISTRY[key] = cls
    return cls


# 兼容以函数式方式获取,避免调用方直接 KeyError
def get_adapter_cls(adapter_type: str) -> type[SourceAdapter] | None:
    return ADAPTER_REGISTRY.get(adapter_type)


__all__ = [
    "ArticleMeta",
    "ArticleDetail",
    "SourceAdapter",
    "ADAPTER_REGISTRY",
    "register",
    "get_adapter_cls",
]
