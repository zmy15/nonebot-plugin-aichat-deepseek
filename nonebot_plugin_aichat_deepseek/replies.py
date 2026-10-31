"""携带上下文请求模型并持久化本轮问答。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from nonebot import logger

from .compression import (
    _GROUP_LAST_HISTORY_COUNT,
    _GROUP_LAST_PROMPT_TOKENS,
    _GROUP_LAST_SYSTEM,
    _GROUP_LAST_TOOLS,
)
from .config import plugin_config
from .context import (
    _build_group_request_messages,
    _build_request_messages,
    _estimate_messages_tokens,
)
from .history import STICKER_LIBRARY_KEY, ConversationStore
from .images import ImageError
from .stickers import (
    build_sticker_prompt_note,
    is_sticker_image,
    save_sticker_payload,
)
from .tools import (
    build_group_tool_definitions,
    build_tool_definitions,
    execute_tool,
)
from .usage import _log_api_usage, _merge_usage


async def generate_private_reply(
    client: Any,
    store: ConversationStore,
    fetch_image: Any,
    get_scheduler: Any,
    session_key: str,
    text: str,
    images: Sequence[Mapping[str, Any]] | None = None,
    usage: dict[str, int] | None = None,
    history_user_text: str | None = None,
    *,
    group: bool = False,
    history_limit: int | None = None,
) -> str:
    usage_total = usage if usage is not None else {}

    def record_usage(usage_data: Mapping[str, Any]) -> None:
        _merge_usage(usage_total, usage_data)
        _log_api_usage(session_key, "reply", usage_data)

    history_text = text

    if images:
        if len(images) > plugin_config.deepseek_image_max_count:
            raise ImageError(
                f"一次最多发送 {plugin_config.deepseek_image_max_count} 张图片"
            )

        payloads = []
        for segment in images:
            payloads.append(
                await fetch_image(
                    segment,
                    timeout=plugin_config.deepseek_image_timeout,
                    max_bytes=plugin_config.deepseek_image_max_bytes,
                )
            )

        sticker_records: list[dict[str, Any]] = []
        if plugin_config.deepseek_sticker_enabled:
            for segment, payload in zip(images, payloads):
                if (
                    len(sticker_records)
                    >= plugin_config.deepseek_sticker_max_count
                ):
                    break
                if not is_sticker_image(segment, text):
                    continue
                try:
                    sticker_records.append(
                        save_sticker_payload(
                            store, STICKER_LIBRARY_KEY, payload
                        )
                    )
                except Exception:
                    logger.exception("保存表情包失败，跳过本次收藏")

        file_ids = []
        for payload in payloads:
            file_ids.append(
                await client.upload_image(
                    payload.data,
                    payload.filename,
                    payload.content_type,
                    session_key=session_key,
                )
            )

        prompt = text or (
            "请描述这张图片。" if len(payloads) == 1 else "请描述这些图片。"
        )
        sticker_note = (
            build_sticker_prompt_note(sticker_records)
            if plugin_config.deepseek_tools_enabled
            else ""
        )
        if sticker_note:
            prompt = f"{prompt}\n{sticker_note}"

        user_content: list[dict[str, Any]] = [
            {"type": "text", "text": prompt}
        ]
        user_content.extend(
            {"type": "file", "file_id": file_id} for file_id in file_ids
        )
        messages = _build_request_messages(
            store,
            session_key,
            user_content,
            group=group,
            history_limit=history_limit,
        )

        image_count = len(payloads) - len(sticker_records)
        markers: list[str] = []
        if image_count:
            markers.append(f"（用户发送了 {image_count} 张图片）")
        if sticker_records:
            markers.append(
                f"（用户发送了 {len(sticker_records)} 个表情包）"
            )
        marker = "".join(markers)
        history_text = f"{text}\n{marker}".strip() if text else marker
    else:
        messages = _build_request_messages(
            store,
            session_key,
            text,
            group=group,
            history_limit=history_limit,
        )

    if history_user_text is not None:
        history_text = history_user_text

    if plugin_config.deepseek_tools_enabled and not group:

        async def run_tool(name: str, arguments: str) -> str:
            return await execute_tool(
                name,
                arguments,
                session_key,
                store,
                search_web=getattr(client, "search", None),
                get_scheduler=get_scheduler,
            )

        answer = await client.chat_with_tools(
            messages,
            tools=build_tool_definitions(
                include_memory=plugin_config.deepseek_memory_enabled,
                include_custom_prompt=(
                    plugin_config.deepseek_custom_prompt_enabled
                ),
                include_poke=plugin_config.deepseek_poke_enabled,
                include_recall=plugin_config.deepseek_recall_enabled,
                include_stickers=plugin_config.deepseek_sticker_enabled,
                include_search=plugin_config.deepseek_search_enabled,
                include_scheduler=plugin_config.deepseek_scheduler_enabled,
            ),
            tool_runner=run_tool,
            max_tool_rounds=plugin_config.deepseek_tool_max_rounds,
            on_usage=record_usage,
            session_key=session_key,
            phase="reply",
        )
    else:
        answer = await client.chat(
            messages,
            on_usage=record_usage,
            session_key=session_key,
            phase="reply",
        )

    store.add_turn(session_key, history_text, answer)
    return answer


async def generate_group_reply(
    client: Any,
    store: ConversationStore,
    get_scheduler: Any,
    bot_id: int,
    group_id: int,
    sender_id: int,
    sender_name: str,
    session_key: str,
    usage: dict[str, int] | None = None,
) -> str:
    usage_total = usage if usage is not None else {}
    last_prompt_tokens = 0

    def record_usage(usage_data: Mapping[str, Any]) -> None:
        nonlocal last_prompt_tokens
        last_prompt_tokens = int(usage_data.get("prompt_tokens") or 0)
        _merge_usage(usage_total, usage_data)
        _log_api_usage(session_key, "group_reply", usage_data)

    history_limit: int | None = (
        None
        if plugin_config.deepseek_group_compression_enabled
        else plugin_config.deepseek_group_history_messages
    )
    messages = _build_group_request_messages(
        store,
        bot_id,
        group_id,
        sender_id,
        sender_name,
        history_limit,
    )

    group_tools = build_group_tool_definitions()
    request_tools = (
        group_tools
        if plugin_config.deepseek_tools_enabled and group_tools
        else None
    )
    if request_tools:

        async def run_tool(name: str, arguments: str) -> str:
            return await execute_tool(
                name,
                arguments,
                session_key,
                store,
                search_web=getattr(client, "search", None),
                get_scheduler=get_scheduler,
                chat_type="group",
                bot_id=bot_id,
                group_id=group_id,
                sender_id=sender_id,
                sender_name=sender_name,
            )

        answer = await client.chat_with_tools(
            messages,
            tools=request_tools,
            tool_runner=run_tool,
            max_tool_rounds=plugin_config.deepseek_tool_max_rounds,
            on_usage=record_usage,
            session_key=session_key,
            phase="group_reply",
        )
    else:
        answer = await client.chat(
            messages,
            on_usage=record_usage,
            session_key=session_key,
            phase="group_reply",
        )

    if plugin_config.deepseek_group_compression_enabled:
        # 记录本次请求的精确前缀，下一次压缩直接复用它来命中前缀缓存。
        _GROUP_LAST_SYSTEM[session_key] = dict(messages[0])
        _GROUP_LAST_HISTORY_COUNT[session_key] = len(messages) - 1
        _GROUP_LAST_TOOLS[session_key] = request_tools
        _GROUP_LAST_PROMPT_TOKENS[session_key] = (
            last_prompt_tokens or _estimate_messages_tokens(messages)
        )

    store.add_group_message(bot_id, group_id, "assistant", answer)
    return answer
