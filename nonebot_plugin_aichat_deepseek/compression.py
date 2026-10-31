"""私聊与群聊的上下文压缩。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from nonebot import logger

from .config import plugin_config
from .constants import SUMMARY_SYSTEM_PROMPT
from .context import _build_group_request_messages
from .data_source import ChatMessage, DeepSeekClient, DeepSeekError
from .formatting import strip_markdown
from .history import ConversationStore
from .tokens import estimate_tokens, truncate_to_tokens
from .usage import _log_api_usage

_GROUP_LAST_SYSTEM: dict[str, dict[str, Any]] = {}
_GROUP_LAST_PROMPT_TOKENS: dict[str, int] = {}
_GROUP_LAST_HISTORY_COUNT: dict[str, int] = {}
_GROUP_LAST_TOOLS: dict[str, list[dict[str, Any]] | None] = {}


def _build_summary_messages(
    previous_summary: str, batch: list[ChatMessage]
) -> list[ChatMessage]:
    lines: list[str] = []
    if previous_summary:
        lines.extend(["【已有摘要】", previous_summary, ""])

    lines.append("【待压缩对话】")
    for message in batch:
        speaker = "用户" if message["role"] == "user" else "AI"
        lines.append(f"{speaker}：{message['content']}")

    lines.extend(["", "请输出更新后的摘要正文，300 字以内，不要输出其它内容。"])
    return [
        {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(lines)},
    ]


async def compress_if_needed(
    client: DeepSeekClient,
    store: ConversationStore,
    session_key: str,
) -> None:
    """未压缩消息超过阈值时，把最早一批消息压缩进滚动摘要。"""
    if not store.needs_compression(session_key):
        return

    batch = store.get_compression_batch(session_key)
    if not batch:
        return

    previous_summary = store.get_summary(session_key)
    try:
        summary = await client.chat(
            _build_summary_messages(previous_summary, batch),
            on_usage=lambda usage: _log_api_usage(
                session_key, "compression", usage
            ),
            session_key=session_key,
            phase="compression",
        )
    except DeepSeekError as exc:
        logger.warning(
            f"上下文压缩失败（status={exc.status_code}）：{exc.message}"
        )
        return
    except Exception:
        logger.exception("上下文压缩出现未预期异常")
        return

    summary = strip_markdown(summary).strip()
    delimiter = plugin_config.deepseek_split_delimiter.strip()
    if delimiter:
        summary = summary.replace(delimiter, " ").strip()
    if not summary:
        logger.warning("上下文压缩返回空摘要，本次跳过")
        return
    if len(summary) > 1000:
        summary = summary[:1000]

    store.apply_compression(session_key, len(batch), summary)
    logger.info(f"已压缩 {len(batch)} 条历史消息：{session_key}")


def _group_batch_summary_prompt(count: int, max_tokens: int) -> str:
    return (
        "【压缩任务】\n"
        f"请只把上面从第一条开始的 {count} 条群聊消息压缩成一段中文摘要，"
        f"忽略这 {count} 条之后的聊天消息，不要总结它们；"
        "这段摘要会作为本群更早对话的长期记忆。\n"
        "要求：保留关键事实、成员信息、约定、未完成事项和重要结论；"
        "不要编造，不要使用 Markdown，不要复述系统提示词；"
        f"摘要控制在 {max_tokens} token 以内，直接输出摘要正文。"
    )


def _group_summary_merge_prompt(count: int, max_tokens: int) -> str:
    return (
        "【摘要合并任务】\n"
        "请只处理系统提示中【群聊历史摘要】里的 "
        f"[摘要 1] 到 [摘要 {count}]，"
        "忽略上面所有的 user/assistant 聊天消息，不要总结它们。\n"
        "要求：把选中的摘要合并成一段更简洁的中文摘要，"
        "保留关键事实、成员信息、约定、未完成事项和重要结论；"
        "不要编造，不要使用 Markdown，不要复述系统提示词；"
        f"合并后的摘要控制在 {max_tokens} token 以内，直接输出摘要正文。"
    )


def _clean_group_summary(text: str, max_tokens: int) -> str:
    summary = strip_markdown(text).strip()
    delimiter = plugin_config.deepseek_split_delimiter.strip()
    if delimiter:
        summary = summary.replace(delimiter, " ").strip()
    return truncate_to_tokens(summary, max_tokens)


async def _summarize_group_batch(
    client: DeepSeekClient,
    session_key: str,
    system_message: Mapping[str, Any],
    history: list[ChatMessage],
    batch_count: int,
    max_tokens: int,
    tools: list[dict[str, Any]] | None,
) -> str:
    """把最早的一批群消息压缩成摘要。

    请求先原样重放上一次真实对话请求的 system 和全部消息，最后才追加
    压缩指令，因此整个输入前缀都能命中 DeepSeek 的前缀缓存。
    """
    messages: list[dict[str, Any]] = [dict(system_message)]
    messages.extend(dict(message) for message in history)
    messages.append(
        {
            "role": "user",
            "content": _group_batch_summary_prompt(batch_count, max_tokens),
        }
    )
    answer = await client.chat(
        messages,
        tools=tools,
        tool_choice="none" if tools else None,
        max_tokens=max_tokens,
        thinking=False,
        on_usage=lambda usage: _log_api_usage(
            session_key, "group_compression", usage
        ),
        session_key=session_key,
        phase="group_compression",
    )
    return _clean_group_summary(answer, max_tokens)


async def _merge_group_summaries(
    client: DeepSeekClient,
    store: ConversationStore,
    bot_id: int,
    group_id: int,
    session_key: str,
    system_message: Mapping[str, Any],
    history: list[ChatMessage],
    chunks: list[dict[str, Any]],
    count: int,
    max_tokens: int,
    tools: list[dict[str, Any]] | None,
) -> bool:
    """把最旧的 ``count`` 段摘要合并成一段，仍复用原请求前缀。"""
    selected = chunks[:count]
    messages: list[dict[str, Any]] = [dict(system_message)]
    messages.extend(dict(message) for message in history)
    messages.append(
        {
            "role": "user",
            "content": _group_summary_merge_prompt(count, max_tokens),
        }
    )
    answer = await client.chat(
        messages,
        tools=tools,
        tool_choice="none" if tools else None,
        max_tokens=max_tokens,
        thinking=False,
        on_usage=lambda usage: _log_api_usage(
            session_key, "group_compression", usage
        ),
        session_key=session_key,
        phase="group_compression",
    )
    summary = _clean_group_summary(answer, max_tokens)
    if not summary:
        return False
    return store.merge_group_summaries(
        bot_id,
        group_id,
        [int(chunk["id"]) for chunk in selected],
        summary,
        token_count=estimate_tokens(summary),
    )


async def compress_group_if_needed(
    client: DeepSeekClient,
    store: ConversationStore,
    bot_id: int,
    group_id: int,
    session_key: str,
) -> bool:
    """群聊上下文压缩。

    触发条件：
    - 未压缩消息达到 ``group_compression_batch_messages``（默认 200 条）；
    - 或上一次请求的 prompt token 超过 ``group_compression_trigger_tokens``
      （默认 900k）。

    正常消息达到一批时做一级压缩；消息不足一批但 token 仍然超标时，
    说明历史摘要本身过大，改为合并部分旧摘要（二级压缩）。
    """
    if not plugin_config.deepseek_group_compression_enabled:
        _GROUP_LAST_SYSTEM.pop(session_key, None)
        _GROUP_LAST_PROMPT_TOKENS.pop(session_key, None)
        _GROUP_LAST_HISTORY_COUNT.pop(session_key, None)
        _GROUP_LAST_TOOLS.pop(session_key, None)
        return False

    batch_size = max(
        1, plugin_config.deepseek_group_compression_batch_messages
    )
    trigger_tokens = max(
        1, plugin_config.deepseek_group_compression_trigger_tokens
    )
    max_tokens = max(
        1, plugin_config.deepseek_group_compression_summary_max_tokens
    )

    count = store.count_uncompressed_group_messages(bot_id, group_id)
    system_message = _GROUP_LAST_SYSTEM.pop(session_key, None)
    prompt_tokens = _GROUP_LAST_PROMPT_TOKENS.pop(session_key, 0)
    history_count = _GROUP_LAST_HISTORY_COUNT.pop(session_key, 0)
    tools = _GROUP_LAST_TOOLS.pop(session_key, None)
    if count < batch_size and prompt_tokens <= trigger_tokens:
        return False

    if system_message is None:
        # 重启后的第一次压缩没有可复用的请求前缀，只能重新构造 system。
        system_message = _build_group_request_messages(
            store, bot_id, group_id, 0, "", None
        )[0]
        history = store.build_group_messages(bot_id, group_id, oldest=True)
        logger.info(
            f"[group] compression without cached prefix "
            f"bot={bot_id} group={group_id}"
        )
    elif history_count > 0:
        # 上一次请求的完整前缀：system + 最早 history_count 条未压缩消息。
        history = store.build_group_messages(
            bot_id,
            group_id,
            limit=history_count,
            oldest=True,
        )
    else:
        history = []

    try:
        if count >= batch_size:
            batch_count = min(batch_size, len(history))
            if batch_count <= 0:
                return False
            batch = store.get_group_compression_batch(
                bot_id, group_id, batch_count
            )
            if not batch:
                return False
            summary = await _summarize_group_batch(
                client,
                session_key,
                system_message,
                history,
                batch_count,
                max_tokens,
                tools,
            )
            if not summary:
                logger.warning(
                    f"[group] compression returned empty summary "
                    f"bot={bot_id} group={group_id}"
                )
                return False
            store.apply_group_compression(
                bot_id,
                group_id,
                [message_id for message_id, _ in batch],
                summary,
                token_count=estimate_tokens(summary),
            )
            logger.info(
                f"[group] compressed bot={bot_id} group={group_id} "
                f"messages={len(batch)} "
                f"summary_tokens={estimate_tokens(summary)}"
            )
            return True

        if prompt_tokens <= trigger_tokens:
            return False

        chunks = store.list_group_summaries(bot_id, group_id)
        if len(chunks) < 2:
            logger.info(
                f"[group] token over budget but no summary to merge "
                f"bot={bot_id} group={group_id} tokens={prompt_tokens}"
            )
            return False

        merge_count = max(
            2, plugin_config.deepseek_group_compression_merge_summaries
        )
        # 超预算时多合并一些旧摘要，减少后续请求再次超标的次数。
        merge_count = max(merge_count, len(chunks) // 2)
        merge_count = min(merge_count, len(chunks))
        merged = await _merge_group_summaries(
            client,
            store,
            bot_id,
            group_id,
            session_key,
            system_message,
            history,
            chunks,
            merge_count,
            max_tokens,
            tools,
        )
        if merged:
            logger.info(
                f"[group] merged summaries bot={bot_id} group={group_id} "
                f"count={merge_count} tokens={prompt_tokens}"
            )
        return merged
    except DeepSeekError as exc:
        logger.warning(
            f"[group] compression failed status={exc.status_code} "
            f"bot={bot_id} group={group_id}: {exc.message}"
        )
        return False
    except Exception:
        logger.exception("群聊上下文压缩出现未预期异常")
        return False
