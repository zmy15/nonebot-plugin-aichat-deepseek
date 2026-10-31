"""DeepSeek Chat Completions API 客户端。

直接使用 httpx 调用 ``POST /chat/completions``，不依赖 OpenAI SDK 的版本，
请求/响应格式与 DeepSeek 官方文档保持一致。

参考：https://api-docs.deepseek.com/zh-cn/api/create-chat-completion
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, Literal, TypedDict

import httpx
from nonebot import logger

ToolRunner = Callable[[str, str], Awaitable[str]]


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
    """一个最小的 DeepSeek 对话客户端，支持非流式对话与工具调用。"""

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
        image_expire_seconds: int = 86400,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._api_base = api_base
        self._model = model
        self._timeout = timeout
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._thinking = thinking
        self._image_expire_seconds = image_expire_seconds
        self._transport = transport

    @property
    def configured(self) -> bool:
        """是否配置了 API Key。"""
        return bool(self._api_key)

    def _build_payload(
        self,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [dict(message) for message in messages],
            "stream": False,
            "temperature": self._temperature,
        }
        if self._max_tokens is not None:
            payload["max_tokens"] = self._max_tokens
        if self._thinking is not None:
            payload["thinking"] = {
                "type": "enabled" if self._thinking else "disabled"
            }
        if tools:
            payload["tools"] = list(tools)
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
    def _extract_message(data: Any) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise DeepSeekError("DeepSeek 返回了无法解析的响应")

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise DeepSeekError("DeepSeek 返回了空回复")

        first = choices[0]
        message = first.get("message") if isinstance(first, dict) else None
        if not isinstance(message, dict):
            raise DeepSeekError("DeepSeek 返回了无法解析的回复")
        return message

    @classmethod
    def _content_from_message(cls, message: Mapping[str, Any]) -> str:
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise DeepSeekError("DeepSeek 返回了空回复")
        return content.strip()

    @classmethod
    def _extract_content(cls, data: Any) -> str:
        return cls._content_from_message(cls._extract_message(data))

    async def _request(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        tools: Sequence[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if not self._api_key:
            raise DeepSeekError("未配置 DEEPSEEK_API_KEY")

        url = f"{self._api_base.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = self._build_payload(messages, tools)

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
        if not isinstance(data, dict):
            raise DeepSeekError("DeepSeek 返回了无法解析的响应")

        usage = data.get("usage")
        if usage:
            logger.debug(f"DeepSeek token 用量：{usage}")
        return data

    async def chat(self, messages: Sequence[Mapping[str, Any]]) -> str:
        """发送对话消息并返回模型回复文本。"""
        data = await self._request(messages)
        return self._extract_content(data)

    async def upload_image(
        self,
        image_data: bytes,
        filename: str,
        content_type: str,
    ) -> str:
        """通过 Files API 上传图片，返回可引用到对话中的 file_id。"""
        if not self._api_key:
            raise DeepSeekError("未配置 DEEPSEEK_API_KEY")

        url = f"{self._api_base.rstrip('/')}/files"
        headers = {"Authorization": f"Bearer {self._api_key}"}
        form: dict[str, str] = {"purpose": "user_data"}
        if self._image_expire_seconds > 0:
            if not 3600 <= self._image_expire_seconds <= 2592000:
                raise DeepSeekError(
                    "图片文件有效期必须为 0 或 3600-2592000 秒"
                )
            form["expires_after[anchor]"] = "created_at"
            form["expires_after[seconds]"] = str(self._image_expire_seconds)

        try:
            async with httpx.AsyncClient(
                timeout=max(self._timeout, 300.0),
                transport=self._transport,
            ) as client:
                response = await client.post(
                    url,
                    headers=headers,
                    data=form,
                    files={
                        "file": (filename, image_data, content_type),
                    },
                )
        except httpx.TimeoutException as exc:
            raise DeepSeekError("上传图片到 DeepSeek 超时") from exc
        except httpx.HTTPError as exc:
            raise DeepSeekError(
                f"上传图片失败：{exc.__class__.__name__}"
            ) from exc

        data = self._parse_json(response)
        if response.status_code >= 400:
            raise DeepSeekError(
                self._error_detail(response, data),
                status_code=response.status_code,
            )
        file_id = data.get("id") if isinstance(data, dict) else None
        if not isinstance(file_id, str) or not file_id:
            raise DeepSeekError("DeepSeek Files API 没有返回 file_id")
        return file_id

    async def chat_with_tools(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        tools: Sequence[Mapping[str, Any]],
        tool_runner: ToolRunner,
        max_tool_rounds: int = 3,
    ) -> str:
        """自动执行模型请求的工具，直到模型给出最终文本回复。"""
        working: list[dict[str, Any]] = [dict(message) for message in messages]
        rounds = max(1, max_tool_rounds)

        for _ in range(rounds):
            data = await self._request(working, tools=tools)
            message = self._extract_message(data)
            tool_calls = message.get("tool_calls")
            if not tool_calls:
                return self._content_from_message(message)
            if not isinstance(tool_calls, list):
                raise DeepSeekError("DeepSeek 返回了无法解析的工具调用")

            working.append(
                {
                    "role": "assistant",
                    "content": message.get("content"),
                    "tool_calls": tool_calls,
                }
            )

            for call in tool_calls:
                if not isinstance(call, dict):
                    raise DeepSeekError("DeepSeek 返回了无法解析的工具调用")
                function = call.get("function")
                if not isinstance(function, dict):
                    raise DeepSeekError("DeepSeek 返回了无法解析的工具调用")

                name = function.get("name")
                arguments = function.get("arguments") or "{}"
                if not isinstance(name, str) or not name:
                    raise DeepSeekError("DeepSeek 返回了无效的工具名称")
                if not isinstance(arguments, str):
                    arguments = json.dumps(arguments, ensure_ascii=False)

                try:
                    result = await tool_runner(name, arguments)
                except Exception:
                    logger.exception(f"工具 {name} 执行失败")
                    result = json.dumps(
                        {"error": f"工具 {name} 执行失败"},
                        ensure_ascii=False,
                    )

                tool_call_id = call.get("id")
                if not isinstance(tool_call_id, str) or not tool_call_id:
                    tool_call_id = f"call_{len(working)}"

                working.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": (
                            result
                            if isinstance(result, str)
                            else json.dumps(result, ensure_ascii=False)
                        ),
                    }
                )

        # 工具调用次数达到上限后，强制模型给出普通文本回复
        data = await self._request(working)
        return self._extract_content(data)
