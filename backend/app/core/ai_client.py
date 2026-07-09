"""火山方舟 Coding Plan AI 客户端:封装 OpenAI 兼容协议调用。

使用方式:
    from app.core.ai_client import get_ai_client
    client = get_ai_client()
    response = await client.chat_completion(messages, model="glm-4.7")
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, AsyncGenerator, List, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class AIClient:
    """火山方舟 Coding Plan 客户端封装。"""

    def __init__(self, api_key: str, base_url: str, model: str, timeout: int) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._model = model
        self._timeout = timeout
        self._async_client = httpx.AsyncClient(
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}"},
            follow_redirects=True,
        )

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def chat_completion(
        self,
        messages: List[dict[str, Any]],
        model: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """调用 Chat Completion API。

        Args:
            messages: 消息列表,每条格式 {"role": "user"|"assistant"|"system", "content": "..."}
            model: 模型名称,默认使用配置中的 VOLC_ARK_MODEL
            max_tokens: 最大输出 token 数
            temperature: 温度参数,0-2 之间,越高越随机
            kwargs: 其他 OpenAI API 参数

        Returns:
            API 响应字典,包含 choices、usage 等字段

        Raises:
            ValueError: 未配置 API Key
            httpx.HTTPError: 连接失败或 API 调用异常
        """
        if not self.is_configured:
            raise ValueError("火山方舟 Coding Plan 未配置 API Key")

        target_model = model or self._model
        payload = {
            "model": target_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            **kwargs,
        }

        try:
            response = await self._async_client.post(
                f"{self._base_url}/chat/completions",
                json=payload,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error("AI chat completion failed: %s", str(e))
            raise

    async def chat_completion_stream(
        self,
        messages: List[dict[str, Any]],
        model: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """流式调用 Chat Completion API。

        Args:
            messages: 消息列表
            model: 模型名称
            max_tokens: 最大输出 token 数
            temperature: 温度参数
            kwargs: 其他 OpenAI API 参数

        Yields:
            每个流消息的字典,包含 delta、finish_reason 等字段
        """
        if not self.is_configured:
            raise ValueError("火山方舟 Coding Plan 未配置 API Key")

        target_model = model or self._model
        payload = {
            "model": target_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
            **kwargs,
        }

        try:
            async with self._async_client.stream(
                "POST",
                f"{self._base_url}/chat/completions",
                json=payload,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("data: "):
                        line = line[6:]
                    if line == "[DONE]":
                        break
                    import json

                    yield json.loads(line)
        except httpx.HTTPError as e:
            logger.error("AI chat completion stream failed: %s", str(e))
            raise

    async def embeddings(
        self,
        input_data: List[str],
        model: Optional[str] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """调用 Embeddings API。

        Args:
            input_data: 文本列表,每个元素为要向量化的文本
            model: Embedding 模型名称

        Returns:
            API 响应字典,包含 data 字段(每个元素含 embedding 向量)
        """
        if not self.is_configured:
            raise ValueError("火山方舟 Coding Plan 未配置 API Key")

        target_model = model or "doubao-embedding-vision"
        payload = {
            "model": target_model,
            "input": input_data,
            **kwargs,
        }

        try:
            response = await self._async_client.post(
                f"{self._base_url}/embeddings",
                json=payload,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error("AI embeddings failed: %s", str(e))
            raise

    def get_available_models(self) -> List[str]:
        """获取 Coding Plan 支持的模型列表。"""
        return [
            "ark-code-latest",
            "doubao-seed-2.0-code",
            "doubao-seed-2.0-pro",
            "doubao-seed-2.0-lite",
            "doubao-seed-code",
            "minimax-m2.5",
            "glm-4.7",
            "deepseek-v3.2",
            "kimi-k2.5",
        ]


@lru_cache
def get_ai_client() -> AIClient:
    """获取 AI 客户端单例。"""
    return AIClient(
        api_key=settings.VOLC_ARK_API_KEY,
        base_url=settings.VOLC_ARK_BASE_URL,
        model=settings.VOLC_ARK_MODEL,
        timeout=settings.VOLC_ARK_TIMEOUT_SECONDS,
    )


ai_client = get_ai_client()
