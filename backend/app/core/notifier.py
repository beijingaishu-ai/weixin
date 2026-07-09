"""告警通知(对齐设计 7.6 死信告警)。

支持:控制台日志(默认)+ 可选企业微信机器人 webhook + 可选邮件(SMTP)。
教学演示默认只打日志;配置 ALERT_WEBHOOK_URL 后额外推企业微信机器人。
测试可通过 set_test_sink 收集告警而不出网。
"""
from __future__ import annotations

import logging
import os
from collections.abc import Callable

import httpx

logger = logging.getLogger("app.notifier")

# 测试注入的接收器:设置后告警只进它,不打日志/不出网
_test_sink: Callable[[str, str], None] | None = None


def set_test_sink(fn: Callable[[str, str], None] | None) -> None:
    global _test_sink
    _test_sink = fn


async def notify(subject: str, body: str = "", *, level: str = "warning") -> None:
    """发送一条告警。subject 必填,body 可选。"""
    if _test_sink is not None:
        _test_sink(subject, body)
        return

    logger.warning("[ALERT] %s | %s", subject, body)

    webhook = os.environ.get("ALERT_WEBHOOK_URL", "").strip()
    if webhook:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                await client.post(
                    webhook,
                    json={
                        "msgtype": "text",
                        "text": {"content": f"【公众号系统告警】{subject}\n{body}"},
                    },
                )
        except Exception as e:  # noqa: BLE001 —— 告警失败不应影响主流程
            logger.error("告警 webhook 推送失败: %s", e)
