"""DeepSeek Chat Completions API 客户端。

直接使用 httpx 调用 ``POST /chat/completions``，不依赖 OpenAI SDK 的版本，
请求/响应格式与 DeepSeek 官方文档保持一致。

参考：https://api-docs.deepseek.com/zh-cn/api/create-chat-completion
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, Literal, TypedDict

import httpx
from nonebot import logger

ToolRunner = Callable[[str, str], Awaitable[str]]
UsageCallback = Callable[[Mapping[str, Any]], None]


def _elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


def _usage_numbers(usage: Mapping[str, Any]) -> tuple[int, int, int, int]:
    """返回 cache_hit / cache_miss / prompt_tokens / completion_tokens。"""
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    details = usage.get("prompt_tokens_details")
    cached = details.get("cached_tokens") if isinstance(details, dict) else None
    cache_hit = int(usage.get("prompt_cache_hit_tokens", cached) or 0)
    cache_miss = usage.get("prompt_cache_miss_tokens")
    cache_miss = (
        int(cache_miss)
        if cache_miss is not None
        else max(0, prompt_tokens - cache_hit)
    )
    completion_tokens = int(usage.get("completion_tokens") or 0)
    return cache_hit, cache_miss, prompt_tokens, completion_tokens


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
        on_usage: UsageCallback | None = None,
        session_key: str = "",
        phase: str = "chat",
    ) -> dict[str, Any]:
        started = time.perf_counter()
        label = f"session={session_key or '-'} phase={phase}"
        logger.info(
            f"[deepseek-api] start {label} model={self._model} "
            f"messages={len(messages)} tools={len(tools or [])}"
        )

        try:
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
                    response = await client.post(
                        url, headers=headers, json=payload
                    )
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
            usage_data: Mapping[str, Any] = (
                usage if isinstance(usage, dict) else {}
            )
            if usage_data:
                logger.debug(f"DeepSeek token 用量：{usage_data}")
                if on_usage is not None:
                    try:
                        on_usage(usage_data)
                    except Exception:
                        logger.exception("DeepSeek usage 回调执行失败")

            cache_hit, cache_miss, prompt_tokens, completion_tokens = (
                _usage_numbers(usage_data)
            )
            logger.info(
                f"[deepseek-api] ok {label} status={response.status_code} "
                f"duration_ms={_elapsed_ms(started)} "
                f"cache_hit={cache_hit} cache_miss={cache_miss} "
                f"prompt_tokens={prompt_tokens} "
                f"completion_tokens={completion_tokens}"
            )
            return data
        except DeepSeekError as exc:
            logger.warning(
                f"[deepseek-api] error {label} status={exc.status_code} "
                f"duration_ms={_elapsed_ms(started)} message={exc.message}"
            )
            raise
        except Exception:
            logger.exception(
                f"[deepseek-api] error {label} status=None "
                f"duration_ms={_elapsed_ms(started)}"
            )
            raise

    async def chat(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        on_usage: UsageCallback | None = None,
        session_key: str = "",
        phase: str = "chat",
    ) -> str:
        """发送对话消息并返回模型回复文本。"""
        data = await self._request(
            messages,
            on_usage=on_usage,
            session_key=session_key,
            phase=phase,
        )
        return self._extract_content(data)

    def _search_url(self) -> str:
        base = self._api_base.rstrip("/")
        if base.endswith("/v1"):
            return f"{base}/tools/search"
        return f"{base}/v1/tools/search"

    async def search(
        self,
        query: str,
        *,
        count: int = 5,
        need_content: bool = False,
        ori_question: str | None = None,
        session_key: str = "",
    ) -> dict[str, Any]:
        """调用 DeepSeek 网页搜索接口，返回原始 JSON 结果。"""
        started = time.perf_counter()
        label = f"session={session_key or '-'} phase=web_search"
        logger.info(
            f"[deepseek-api] start {label} api=search count={count} "
            f"need_content={str(need_content).lower()}"
        )

        if not self._api_key:
            logger.warning(
                f"[deepseek-api] error {label} api=search status=None "
                f"duration_ms={_elapsed_ms(started)} "
                "message=未配置 DEEPSEEK_API_KEY"
            )
            raise DeepSeekError("未配置 DEEPSEEK_API_KEY")

        payload: dict[str, Any] = {
            "query": query,
            "count": count,
            "need_content": need_content,
        }
        if ori_question:
            payload["ori_question"] = ori_question

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                response = await client.post(
                    self._search_url(),
                    headers=headers,
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            logger.warning(
                f"[deepseek-api] error {label} api=search status=None "
                f"duration_ms={_elapsed_ms(started)} message=timeout"
            )
            raise DeepSeekError("请求网页搜索超时") from exc
        except httpx.HTTPError as exc:
            logger.warning(
                f"[deepseek-api] error {label} api=search status=None "
                f"duration_ms={_elapsed_ms(started)} "
                f"message={exc.__class__.__name__}"
            )
            raise DeepSeekError(
                f"请求网页搜索失败：{exc.__class__.__name__}"
            ) from exc

        data = self._parse_json(response)
        if response.status_code >= 400:
            detail = self._error_detail(response, data)
            logger.warning(
                f"[deepseek-api] error {label} api=search "
                f"status={response.status_code} "
                f"duration_ms={_elapsed_ms(started)} message={detail}"
            )
            raise DeepSeekError(detail, status_code=response.status_code)

        if not isinstance(data, dict):
            logger.warning(
                f"[deepseek-api] error {label} api=search status=200 "
                f"duration_ms={_elapsed_ms(started)} "
                "message=无法解析响应"
            )
            raise DeepSeekError("网页搜索返回了无法解析的响应")
        results = data.get("results")
        if not isinstance(results, list):
            raise DeepSeekError("网页搜索返回了无法解析的结果")

        logger.info(
            f"[deepseek-api] ok {label} api=search status=200 "
            f"duration_ms={_elapsed_ms(started)} results={len(results)}"
        )
        return data

    async def upload_image(
        self,
        image_data: bytes,
        filename: str,
        content_type: str,
        *,
        session_key: str = "",
    ) -> str:
        """通过 Files API 上传图片，返回可引用到对话中的 file_id。"""
        started = time.perf_counter()
        label = f"session={session_key or '-'} phase=image_upload"
        logger.info(
            f"[deepseek-api] start {label} api=files filename={filename} "
            f"bytes={len(image_data)} content_type={content_type}"
        )

        if not self._api_key:
            logger.warning(
                f"[deepseek-api] error {label} api=files status=None "
                f"duration_ms={_elapsed_ms(started)} "
                "message=未配置 DEEPSEEK_API_KEY"
            )
            raise DeepSeekError("未配置 DEEPSEEK_API_KEY")

        url = f"{self._api_base.rstrip('/')}/files"
        headers = {"Authorization": f"Bearer {self._api_key}"}
        form: dict[str, str] = {"purpose": "user_data"}
        if self._image_expire_seconds > 0:
            if not 3600 <= self._image_expire_seconds <= 2592000:
                logger.warning(
                    f"[deepseek-api] error {label} api=files status=None "
                    f"duration_ms={_elapsed_ms(started)} "
                    "message=图片文件有效期配置无效"
                )
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
            logger.warning(
                f"[deepseek-api] error {label} api=files status=None "
                f"duration_ms={_elapsed_ms(started)} message=timeout"
            )
            raise DeepSeekError("上传图片到 DeepSeek 超时") from exc
        except httpx.HTTPError as exc:
            logger.warning(
                f"[deepseek-api] error {label} api=files status=None "
                f"duration_ms={_elapsed_ms(started)} "
                f"message={exc.__class__.__name__}"
            )
            raise DeepSeekError(
                f"上传图片失败：{exc.__class__.__name__}"
            ) from exc

        data = self._parse_json(response)
        if response.status_code >= 400:
            detail = self._error_detail(response, data)
            logger.warning(
                f"[deepseek-api] error {label} api=files "
                f"status={response.status_code} "
                f"duration_ms={_elapsed_ms(started)} message={detail}"
            )
            raise DeepSeekError(
                detail,
                status_code=response.status_code,
            )
        file_id = data.get("id") if isinstance(data, dict) else None
        if not isinstance(file_id, str) or not file_id:
            logger.warning(
                f"[deepseek-api] error {label} api=files "
                f"status={response.status_code} "
                f"duration_ms={_elapsed_ms(started)} "
                "message=Files API 没有返回 file_id"
            )
            raise DeepSeekError("DeepSeek Files API 没有返回 file_id")

        logger.info(
            f"[deepseek-api] ok {label} api=files "
            f"status={response.status_code} "
            f"duration_ms={_elapsed_ms(started)} file_id={file_id}"
        )
        return file_id

    async def chat_with_tools(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        tools: Sequence[Mapping[str, Any]],
        tool_runner: ToolRunner,
        max_tool_rounds: int = 3,
        on_usage: UsageCallback | None = None,
        session_key: str = "",
        phase: str = "chat",
    ) -> str:
        """自动执行模型请求的工具，直到模型给出最终文本回复。"""
        working: list[dict[str, Any]] = [dict(message) for message in messages]
        rounds = max(1, max_tool_rounds)

        for _ in range(rounds):
            data = await self._request(
                working,
                tools=tools,
                on_usage=on_usage,
                session_key=session_key,
                phase=phase,
            )
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
        data = await self._request(
            working,
            on_usage=on_usage,
            session_key=session_key,
            phase=phase,
        )
        return self._extract_content(data)
