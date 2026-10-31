"""把对话历史、摘要和记忆拼装成 API 请求消息。"""

from __future__ import annotations

from typing import Any

from .config import plugin_config
from .history import ConversationStore
from .prompts import _build_system_prompt, _memory_lines
from .tokens import estimate_tokens


def _build_request_messages(
    store: ConversationStore,
    session_key: str,
    user_content: str | list[dict[str, Any]],
    *,
    group: bool = False,
    history_limit: int | None = None,
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [
        dict(message)
        for message in store.build_messages(
            session_key, limit=history_limit
        )
    ]
    summary = store.get_summary(session_key)
    memories: list[dict[str, Any]] = []
    if plugin_config.deepseek_memory_enabled and not group:
        memories = store.list_memories(
            session_key,
            limit=plugin_config.deepseek_memory_max_items,
        )
    user_prompt = (
        store.get_user_prompt(session_key)
        if plugin_config.deepseek_custom_prompt_enabled and not group
        else ""
    )
    messages.insert(
        0,
        {
            "role": "system",
            "content": _build_system_prompt(
                summary,
                memories,
                user_prompt,
                group=group,
            ),
        },
    )
    messages.append({"role": "user", "content": user_content})
    return messages


def _format_group_summaries(
    chunks: list[dict[str, Any]],
) -> str:
    """把摘要片段拼成 system 中的历史摘要区块。"""
    return "\n\n".join(
        f"[摘要 {index}]\n{chunk['content']}"
        for index, chunk in enumerate(chunks, 1)
    )


def _build_group_request_messages(
    store: ConversationStore,
    bot_id: int,
    group_id: int,
    sender_id: int,
    sender_name: str,
    history_limit: int | None = None,
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [
        dict(message)
        for message in store.build_group_messages(
            bot_id,
            group_id,
            limit=history_limit,
        )
    ]
    system = _build_system_prompt(group=True)

    summary_text = _format_group_summaries(
        store.list_group_summaries(bot_id, group_id)
    )
    if summary_text:
        system = f"{system}\n\n【群聊历史摘要】\n{summary_text}"

    if plugin_config.deepseek_memory_enabled:
        group_memories = store.list_group_memories(
            bot_id,
            group_id,
            "group",
            limit=plugin_config.deepseek_memory_max_items,
        )
        group_lines = _memory_lines(group_memories)
        if group_lines:
            system = (
                f"{system}\n\n【群聊记忆】\n" + "\n".join(group_lines)
            )

        member_memories = store.list_group_memories(
            bot_id,
            group_id,
            "member",
            user_id=sender_id,
            limit=plugin_config.deepseek_memory_max_items,
        )
        member_lines = _memory_lines(member_memories)
        if member_lines:
            label = f"{sender_name}({sender_id})"
            system = (
                f"{system}\n\n【当前成员记忆：{label}】\n"
                + "\n".join(member_lines)
            )

    return [{"role": "system", "content": system}, *messages]


def _estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    """估算一组请求消息的 token 数，作为 API 未返回用量时的兜底。"""
    total = 0
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            total += estimate_tokens(content) + 4
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    text = part.get("text")
                    if isinstance(text, str):
                        total += estimate_tokens(text)
            total += 4
    return total
