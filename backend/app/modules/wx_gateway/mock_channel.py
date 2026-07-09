"""MockChannel:测试/模拟号(account_type=3)的本地模拟通道(对齐设计 7.1.5)。

所有 draft/freepublish/material 调用不出网,由本地实现返回可配置结果。
默认全部成功;可通过 set_mock_outcome 为某个 app_id 注入失败(errcode)或指定
publish_status(如 3 常规失败 / 4 审核不通过),用于课堂演练失败重试与告警分支。

上层 publish-engine / content-center 代码零改动——状态机、日志、轮询链路真实走通。
"""
from __future__ import annotations

import hashlib
import threading

from app.modules.wx_gateway.errors import WxApiError

_WX_IMG_DOMAIN = "https://mmbiz.qpic.cn"


class _MockState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.seq = 0
        # app_id -> {"submit_errcode": int|None, "publish_status": int}
        self.outcomes: dict[str, dict] = {}

    def next_id(self, prefix: str) -> str:
        with self.lock:
            self.seq += 1
            return f"{prefix}_{self.seq:06d}"


_state = _MockState()


def set_mock_outcome(app_id: str, *, publish_status: int | None = None,
                     submit_errcode: int | None = None) -> None:
    """配置某模拟号的下一次结果。publish_status 默认 0(成功)。"""
    cfg = _state.outcomes.setdefault(app_id, {})
    if publish_status is not None:
        cfg["publish_status"] = publish_status
    if submit_errcode is not None:
        cfg["submit_errcode"] = submit_errcode


def reset_mock_outcomes() -> None:
    _state.outcomes.clear()


def _cfg(app_id: str) -> dict:
    return _state.outcomes.get(app_id, {})


def get_outcome(app_id: str) -> dict:
    """公开访问某模拟号已配置的结果(供 MockBrowserChannel 读取)。"""
    return _cfg(app_id)


def next_seq(prefix: str = "seq") -> int:
    """自增序号(供 MockBrowserChannel 生成确定性的模拟发表 id)。"""
    with _state.lock:
        _state.seq += 1
        return _state.seq


def _hash8(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


async def upload_image(app_id: str, data: bytes) -> str:
    return f"{_WX_IMG_DOMAIN}/mock/{_hash8(data)}.jpg"


async def add_permanent_material(app_id: str, data: bytes, material_type: str = "image") -> dict:
    h = _hash8(data)
    return {"media_id": f"mockmedia_{h}", "url": f"{_WX_IMG_DOMAIN}/mockmat/{h}.jpg"}


async def add_draft(app_id: str, articles: list[dict]) -> str:
    cfg = _cfg(app_id)
    if cfg.get("submit_errcode"):
        raise WxApiError(cfg["submit_errcode"], "MockChannel 注入的建草稿失败")
    return _state.next_id("mockdraft")


async def submit_publish(app_id: str, draft_media_id: str) -> str:
    cfg = _cfg(app_id)
    if cfg.get("submit_errcode"):
        raise WxApiError(cfg["submit_errcode"], "MockChannel 注入的提交发布失败")
    return _state.next_id("mockpub")


async def get_publish_result(app_id: str, publish_id: str) -> dict:
    status = _cfg(app_id).get("publish_status", 0)
    result: dict = {"publish_status": status}
    if status == 0:
        result["article_id"] = f"mockart_{publish_id}"
        result["article_url"] = f"https://mp.weixin.qq.com/s/MOCK_{publish_id}"
    return result
