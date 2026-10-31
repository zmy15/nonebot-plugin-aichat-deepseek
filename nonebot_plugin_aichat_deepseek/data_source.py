"""DeepSeek Chat Completions API 客户端。

直接使用 httpx 调用 ``POST /chat/completions``，不依赖 OpenAI SDK 的版本，
请求/响应格式与 DeepSeek 官方文档保持一致。

参考：https://api-docs.deepseek.com/zh-cn/api/create-chat-completion
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal, TypedDict

import httpx
from nonebot import logger


class ChatMessage(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


class DeepSeekError(RuntimeError):
    """调用 DeepSeek API 失败。

    ``status_code`` 为 HTTP 状态码；网络错误、未配置 Key 等场景为 ``None``。
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class DeepSeekClient:
    """一个最小的 DeepSeek 对话客户端，只实现非流式对话。"""

    def __init__(
        self,
        *,
        api_key: str | None,
        api_base: str,
        model: str,
        timeout: float = 60.0,
        temperature: float = 1.0,
        max_tokens: int | None = None,
        thinking: bool | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._api_base = api_base
        self._model = model
        self._timeout = timeout
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._thinking = thinking
        self._transport = transport

    @property
    def configured(self) -> bool:
        """是否配置了 API Key。"""
        return bool(self._api_key)

    def _build_payload(self, messages: Sequence[ChatMessage]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": list(messages),
            "stream": False,
            "temperature": self._temperature,
        }
        if self._max_tokens is not None:
            payload["max_tokens"] = self._max_tokens
        if self._thinking is not None:
            payload["thinking"] = {
                "type": "enabled" if self._thinking else "disabled"
            }
        return payload

    @staticmethod
    def _parse_json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return None

    @staticmethod
    def _error_detail(response: httpx.Response, data: Any) -> str:
        if isinstance(data, dict):
            error = data.get("error")
            if isinstance(error, dict):
                message = error.get("message")
                if isinstance(message, str) and message.strip():
                    return message.strip()
            if isinstance(error, str) and error.strip():
                return error.strip()

        text = response.text.strip()
        if text:
            detail = text.replace("\n", " ")[:300]
            return f"HTTP {response.status_code}: {detail}"
        return f"HTTP {response.status_code}"

    @staticmethod
    def _extract_content(data: Any) -> str:
        if not isinstance(data, dict):
            raise DeepSeekError("DeepSeek 返回了无法解析的响应")

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise DeepSeekError("DeepSeek 返回了空回复")

        first = choices[0]
        message = first.get("message") if isinstance(first, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise DeepSeekError("DeepSeek 返回了空回复")

        return content.strip()

    async def chat(self, messages: Sequence[ChatMessage]) -> str:
        """发送对话消息并返回模型回复文本。"""
        if not self._api_key:
            raise DeepSeekError("未配置 DEEPSEEK_API_KEY")

        url = f"{self._api_base.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = self._build_payload(messages)

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                response = await client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise DeepSeekError("请求 DeepSeek API 超时") from exc
        except httpx.HTTPError as exc:
            raise DeepSeekError(
                f"请求 DeepSeek API 失败：{exc.__class__.__name__}"
            ) from exc

        data = self._parse_json(response)
        if response.status_code >= 400:
            raise DeepSeekError(
                self._error_detail(response, data),
                status_code=response.status_code,
            )

        content = self._extract_content(data)
        if isinstance(data, dict):
            usage = data.get("usage")
            if usage:
                logger.debug(f"DeepSeek token 用量：{usage}")
        return content
