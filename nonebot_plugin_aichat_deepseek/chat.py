"""私聊对话逻辑。

只处理私聊消息，不需要任何命令前缀；群里发送的消息不会触发。
"""

from __future__ import annotations

import asyncio
import random
import re
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import datetime
from typing import Any

from nonebot import get_driver, logger, on_command, on_message, on_notice
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupMessageEvent,
    PokeNotifyEvent,
    PrivateMessageEvent,
)
from nonebot.matcher import Matcher
from nonebot.rule import Rule

from .aggregator import MessageAggregator
from .config import plugin_config
from .data_source import ChatMessage, DeepSeekClient, DeepSeekError
from .formatting import split_reply, strip_markdown
from .history import (
    STICKER_LIBRARY_KEY,
    UTC8,
    ConversationStore,
)
from .images import ImageError, fetch_image
from .scheduled_tasks import (
    cancel_followup,
    get_scheduler,
    schedule_followup,
)
from .stickers import (
    build_sticker_prompt_note,
    is_sticker_image,
    save_sticker_payload,
)
from .tools import (
    MEMORY_CATEGORY_LABELS,
    build_group_tool_definitions,
    build_tool_definitions,
    execute_tool,
)

Sender = Callable[[str], Awaitable[None]]

MISSING_API_KEY_TIP = "还没有配置 DEEPSEEK_API_KEY，请先在 .env 中填写后再试。"
IMAGE_DISABLED_TIP = "图片理解功能还没有开启。"
EMPTY_REPLY_TIP = "……"
POKE_PROMPT = "（对方戳了你一下，请用一句简短自然的话回应）"
POKE_BACK_PROMPT = (
    "（对方戳了你一下，请用一句简短自然的话回应；"
    "也可以调用 poke_user 戳回去。）"
)
COMPLETENESS_SYSTEM_PROMPT = (
    "你是一个消息完整性判断器。用户可能把同一句话拆成多条发送。\n"
    "下面会给出最近对话和当前拼接后的用户消息。"
    "请结合上下文判断当前消息是否已经表达完整、可以正常回答。\n"
    "如果明显还没说完，例如只有开场白、句子中断、以“然后/因为/我想问”等结尾，"
    "只输出 INCOMPLETE。\n"
    "否则只输出 COMPLETE。\n"
    "不要回答用户的问题，不要解释。"
)
SUMMARY_SYSTEM_PROMPT = (
    "你是一个对话摘要助手。请把用户与 AI 的对话压缩成一段简洁的中文摘要，"
    "保留关键事实、用户偏好、约定和未完成事项；不要编造，不要使用 Markdown。"
)

client = DeepSeekClient(
    api_key=plugin_config.deepseek_api_key,
    api_base=plugin_config.deepseek_api_base,
    model=plugin_config.deepseek_model,
    timeout=plugin_config.deepseek_timeout,
    temperature=plugin_config.deepseek_temperature,
    max_tokens=plugin_config.deepseek_max_tokens,
    thinking=plugin_config.deepseek_thinking,
    image_expire_seconds=plugin_config.deepseek_image_expire_seconds,
)

store = ConversationStore(
    db_path=plugin_config.deepseek_db_path,
    max_turns=plugin_config.deepseek_history_turns,
    trigger_turns=plugin_config.deepseek_compression_trigger_turns,
    batch_messages=plugin_config.deepseek_compression_batch_messages,
)


async def _is_private_message(event: Event) -> bool:
    """响应规则：只匹配 OneBot V11 的私聊消息。"""
    return isinstance(event, PrivateMessageEvent)


private_chat = on_message(rule=Rule(_is_private_message), priority=100, block=True)


def _is_private_poke(event: Event) -> bool:
    """只响应私聊里戳机器人本人的事件。"""
    return (
        plugin_config.deepseek_poke_enabled
        and isinstance(event, PokeNotifyEvent)
        and not event.group_id
        and event.target_id == event.self_id
        and event.user_id != event.self_id
    )


private_poke = on_notice(rule=Rule(_is_private_poke), priority=5, block=True)


def _is_group_poke(event: Event) -> bool:
    """群聊里戳机器人本人的事件。"""
    return (
        plugin_config.deepseek_group_enabled
        and plugin_config.deepseek_poke_enabled
        and isinstance(event, PokeNotifyEvent)
        and event.group_id is not None
        and _group_allowed(event.group_id)
        and event.target_id == event.self_id
        and event.user_id != event.self_id
    )


group_poke = on_notice(rule=Rule(_is_group_poke), priority=5, block=True)


def _session_key(event: PrivateMessageEvent | PokeNotifyEvent) -> str:
    """同一机器人下按用户隔离上下文。"""
    return f"{event.self_id}:{event.user_id}"


_GROUP_LAST_REPLY: dict[str, float] = {}


def _group_ids() -> set[int] | None:
    """空配置表示不限制群号，返回 ``None``。"""
    raw = plugin_config.deepseek_group_ids.strip()
    if not raw:
        return None
    return {int(part) for part in re.findall(r"\d+", raw)}


def _group_session_key(event: GroupMessageEvent) -> str:
    return f"group:{event.self_id}:{event.group_id}"


def _group_allowed(group_id: int) -> bool:
    ids = _group_ids()
    return ids is None or group_id in ids


def _is_group_message(event: Event) -> bool:
    return (
        plugin_config.deepseek_group_enabled
        and isinstance(event, GroupMessageEvent)
        and _group_allowed(event.group_id)
    )


group_chat = on_message(rule=Rule(_is_group_message), priority=100, block=True)


def _has_at_bot(event: GroupMessageEvent) -> bool:
    return any(
        segment.type == "at"
        and str(segment.data.get("qq")) == str(event.self_id)
        for segment in event.message
    )


def _group_sender_name(event: GroupMessageEvent) -> str:
    sender = event.sender
    return sender.card or sender.nickname or str(event.user_id)


def _mark_group_reply(session_key: str) -> None:
    _GROUP_LAST_REPLY[session_key] = time.monotonic()


def _should_group_reply(session_key: str) -> bool:
    probability = plugin_config.deepseek_group_reply_probability
    if probability <= 0:
        return False
    last = _GROUP_LAST_REPLY.get(session_key, 0.0)
    if time.monotonic() - last < plugin_config.deepseek_group_reply_cooldown:
        return False
    return random.random() < probability


def _starts_with_command(text: str) -> bool:
    """以命令前缀开头的消息交给命令响应器，避免和 /ping 等命令冲突。"""
    command_start = get_driver().config.command_start or set()
    return any(prefix and text.startswith(prefix) for prefix in command_start)


def next_reply_interval() -> float:
    """计算两条消息之间的等待秒数，带随机抖动，避免机械感。"""
    interval = plugin_config.deepseek_reply_interval
    jitter = plugin_config.deepseek_reply_interval_jitter
    if interval <= 0 and jitter <= 0:
        return 0.0
    return max(0.0, interval + random.uniform(-jitter, jitter))


def next_initial_delay() -> float:
    """首次回复前的随机延迟，模拟真人看到消息后停顿一下。"""
    delay = plugin_config.deepseek_reply_delay
    jitter = plugin_config.deepseek_reply_delay_jitter
    if delay <= 0 and jitter <= 0:
        return 0.0
    return max(0.0, delay + random.uniform(-jitter, jitter))


def _usage_numbers(usage: Mapping[str, Any]) -> tuple[int, int, int, int]:
    """返回 cache_hit / cache_miss / prompt_tokens / completion_tokens。"""
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    details = usage.get("prompt_tokens_details")
    cached = details.get("cached_tokens") if isinstance(details, dict) else None

    cache_hit = usage.get("prompt_cache_hit_tokens", cached)
    cache_hit = int(cache_hit or 0)
    cache_miss = usage.get("prompt_cache_miss_tokens")
    cache_miss = (
        int(cache_miss)
        if cache_miss is not None
        else max(0, prompt_tokens - cache_hit)
    )
    completion_tokens = int(usage.get("completion_tokens") or 0)
    return cache_hit, cache_miss, prompt_tokens, completion_tokens


def _merge_usage(total: dict[str, int], usage: Mapping[str, Any]) -> None:
    cache_hit, cache_miss, prompt_tokens, completion_tokens = _usage_numbers(
        usage
    )
    total["calls"] = total.get("calls", 0) + 1
    total["cache_hit"] = total.get("cache_hit", 0) + cache_hit
    total["cache_miss"] = total.get("cache_miss", 0) + cache_miss
    total["prompt_tokens"] = total.get("prompt_tokens", 0) + prompt_tokens
    total["completion_tokens"] = (
        total.get("completion_tokens", 0) + completion_tokens
    )


def _log_api_usage(
    session_key: str,
    phase: str,
    usage: Mapping[str, Any],
) -> None:
    cache_hit, cache_miss, prompt_tokens, completion_tokens = _usage_numbers(
        usage
    )
    logger.info(
        f"[deepseek] session={session_key} phase={phase} "
        f"cache_hit={cache_hit} cache_miss={cache_miss} "
        f"prompt_tokens={prompt_tokens} "
        f"completion_tokens={completion_tokens}"
    )


def _log_reply(
    qid: str,
    session_key: str,
    replied: bool,
    reason: str,
    usage: dict[str, int],
    segments: int = 0,
) -> None:
    logger.info(
        f"[chat] reply qid={qid} session={session_key} "
        f"replied={str(replied).lower()} reason={reason} "
        f"segments={segments} api_calls={usage.get('calls', 0)} "
        f"cache_hit={usage.get('cache_hit', 0)} "
        f"cache_miss={usage.get('cache_miss', 0)} "
        f"prompt_tokens={usage.get('prompt_tokens', 0)} "
        f"completion_tokens={usage.get('completion_tokens', 0)}"
    )


def _format_error(exc: DeepSeekError) -> str:
    if exc.status_code == 401:
        return "DeepSeek API Key 无效，请检查 DEEPSEEK_API_KEY。"
    if exc.status_code == 402:
        return "DeepSeek 账户余额不足，请充值后再试。"
    if exc.status_code == 429:
        return "请求太频繁了，请稍后再试。"
    if exc.status_code is not None and exc.status_code >= 500:
        return "DeepSeek 服务暂时不可用，请稍后再试。"

    detail = exc.message.strip()
    if len(detail) > 200:
        detail = f"{detail[:200]}…"
    return f"DeepSeek 请求失败：{detail}"


_QUESTION_MARKERS = (
    "怎么样",
    "好不好",
    "要不要",
    "是不是",
    "有没有",
    "在吗",
    "忙吗",
    "吃了吗",
)


def _looks_like_question(text: str) -> bool:
    text = text.strip()
    if not text:
        return False
    if "?" in text or "？" in text:
        return True
    if text.endswith(("吗", "呢", "嘛", "么")):
        return True
    return any(marker in text for marker in _QUESTION_MARKERS)


def _cancel_pending_followup(session_key: str) -> None:
    cancel_followup(get_scheduler(), session_key)


def _maybe_schedule_followup(session_key: str, answer: str) -> None:
    if not (
        plugin_config.deepseek_scheduler_enabled
        and plugin_config.deepseek_followup_enabled
    ):
        return

    scheduler = get_scheduler()
    if scheduler is None:
        return

    if not _looks_like_question(answer):
        cancel_followup(scheduler, session_key)
        return

    self_id, separator, user_id = session_key.partition(":")
    if not separator or not self_id or not user_id:
        return
    try:
        target_id = int(user_id)
    except ValueError:
        return

    token = uuid.uuid4().hex
    try:
        schedule_followup(
            scheduler,
            session_key=session_key,
            self_id=self_id,
            user_id=target_id,
            delay_seconds=plugin_config.deepseek_followup_delay_seconds,
            token=token,
        )
        logger.info(
            f"[chat] followup scheduled session={session_key} "
            f"delay={plugin_config.deepseek_followup_delay_seconds}"
        )
    except Exception:
        logger.exception("安排未回复追问失败")


def _memory_lines(memories: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    used_chars = 0
    for memory in memories:
        label = MEMORY_CATEGORY_LABELS.get(
            memory["category"], memory["category"]
        )
        line = f"- #{memory['id']} [{label}] {memory['content']}"
        max_chars = plugin_config.deepseek_memory_max_chars
        if used_chars + len(line) + 1 > max_chars:
            break
        lines.append(line)
        used_chars += len(line) + 1
    return lines


def _build_system_prompt(
    summary: str = "",
    memories: list[dict[str, Any]] | None = None,
    user_prompt: str = "",
    *,
    group: bool = False,
) -> str:
    """在用户配置的人设之后追加输出约束、自定义指令、摘要和长期记忆。"""
    persona = plugin_config.deepseek_system_prompt.strip()
    delimiter = plugin_config.deepseek_split_delimiter.strip() or "|||"
    rules = (
        "输出要求：\n"
        "1. 只输出纯文本，不要使用任何 Markdown 格式"
        "（标题、加粗、斜体、代码块、引用、列表、表格、链接等）。\n"
        "2. 优先分成多条短消息发送，每条都像真人随口聊天："
        "一句话不要太长，句末可以不带标点，不要写成一大段。\n"
        f"3. 多条消息之间用 {delimiter} 分隔；"
        "不要在回复中解释或提到分隔符。\n"
    )
    if group:
        today = datetime.now(UTC8).strftime("%Y-%m-%d")
        rules += (
            f"\n群聊规则：当前日期是 {today}（UTC+8）。"
            "你会看到“昵称(QQ)：内容”格式的群消息；"
            "像群成员一样自然地参与聊天，不要复述所有人的话，"
            "不要假装知道未提供的信息；需要称呼某人时直接写昵称。"
        )
        if (
            plugin_config.deepseek_tools_enabled
            and plugin_config.deepseek_memory_enabled
        ):
            rules += (
                "\n群聊记忆：当前发言人的个人信息用 save_user_memory 保存，"
                "整个群共享的信息用 save_group_memory 保存；"
                "需要回忆时用 search_user_memory 或 search_group_memory；"
                "删除时用 delete_user_memory 或 delete_group_memory。"
                "不要把单个成员的私人信息写进群聊记忆。"
            )
        if (
            plugin_config.deepseek_tools_enabled
            and plugin_config.deepseek_search_enabled
        ):
            rules += (
                "\n群里聊到实时信息、新闻、价格、天气或你不确定的内容时，"
                "可以调用 web_search 查询，不要凭记忆编造。"
            )
        if (
            plugin_config.deepseek_tools_enabled
            and plugin_config.deepseek_poke_enabled
        ):
            rules += (
                "\n群里可以用 poke_user 戳一戳当前发言人，"
                "表达提醒、调侃或互动；不要连续频繁戳同一个人。"
            )
        if (
            plugin_config.deepseek_tools_enabled
            and plugin_config.deepseek_sticker_enabled
        ):
            rules += (
                "\n所有私聊和群聊共用同一个表情库，不按用户或群隔离。"
                "本轮收到表情包时，消息里会给出表情包 ID；"
                "如果用户说明了含义，调用 describe_sticker 记录，"
                "没有说明就不要凭空猜测。聊天中可以根据气氛主动调用 "
                "send_sticker 发送合适的表情包；不确定有哪些可选时，"
                "先调用 search_stickers 查看。"
            )
        prompt = f"{persona}\n\n{rules}" if persona else rules
        if summary:
            prompt = f"{prompt}\n\n【历史对话摘要】\n{summary}"
        return prompt

    if plugin_config.deepseek_tools_enabled:
        now = datetime.now(UTC8).strftime("%Y-%m-%d")
        rules += (
            f"\n4. 当前日期是 {now}（UTC+8）。"
            "用户询问以前聊过什么、回忆之前的内容时，"
            "调用 query_chat_history 工具查询；"
            "提到“昨天”等相对时间时先换算成日期，不要编造。"
        )

    if (
        plugin_config.deepseek_tools_enabled
        and plugin_config.deepseek_memory_enabled
    ):
        rules += (
            "\n5. 当用户提到长期稳定的个人信息、偏好、习惯、关系或重要事实"
            "（例如“我叫…”“我喜欢…”“我住在…”“记住…”），"
            "或明确要求你记住时，必须调用 save_user_memory 保存；"
            "不要保存一次性、临时的内容。"
            "\n6. 用户要求忘记某条记忆时调用 delete_user_memory；"
            "需要查找更早的记忆时调用 search_user_memory。"
        )

    if (
        plugin_config.deepseek_tools_enabled
        and plugin_config.deepseek_search_enabled
    ):
        rules += (
            "\n当用户询问实时信息、新闻、价格、天气、最近发生的事件，"
            "或你不确定、需要最新资料时，调用 web_search 搜索网页；"
            "不要凭记忆编造实时信息。"
        )

    if (
        plugin_config.deepseek_tools_enabled
        and plugin_config.deepseek_scheduler_enabled
    ):
        rules += (
            "\n每次回复时都主动判断：是否适合在稍后找用户聊天或戳一戳，"
            "不需要用户提出“定时”或“提醒我”的要求。"
            "例如用户说要去忙、吃饭、睡觉、出门，"
            "或聊天告一段落时，可以调用 schedule_task "
            "安排稍后关心或问候；"
            "不要每次对话都安排，也不要连续安排多个。"
            "到点后由你根据上下文、人设和记忆主动生成消息，"
            "不是发送固定文本。只作用于当前私聊用户，"
            "不要编造任务已创建，任务保存在内存中，"
            "机器人重启后会丢失。"
            "用户要查看、取消或修改定时任务时，分别调用 "
            "list_scheduled_tasks、cancel_scheduled_task、"
            "update_scheduled_task；只能操作当前用户自己的任务。"
        )

    if (
        plugin_config.deepseek_tools_enabled
        and plugin_config.deepseek_scheduler_enabled
        and plugin_config.deepseek_followup_enabled
    ):
        rules += (
            "\n当你向用户提问后，如果用户一段时间没有回复，"
            "插件会自动让你再补一句；追问由插件自动处理，"
            "不需要你调用 schedule_task 另外安排。"
        )

    if (
        plugin_config.deepseek_tools_enabled
        and plugin_config.deepseek_custom_prompt_enabled
    ):
        rules += (
            "\n用户明确要求改变人设、语气、回复风格或记住专属设定时，"
            "调用 set_user_system_prompt 保存；"
            "询问当前设定时调用 get_user_system_prompt；"
            "要求恢复默认时调用 clear_user_system_prompt。"
        )

    if (
        plugin_config.deepseek_tools_enabled
        and plugin_config.deepseek_poke_enabled
    ):
        rules += (
            "\n用户要求你戳一戳、提醒或互动时，调用 poke_user；"
            "不要等用户开口，聊天气氛合适时主动戳一戳；"
            "用户戳你时，也可以戳回去。"
        )

    if (
        plugin_config.deepseek_tools_enabled
        and plugin_config.deepseek_sticker_enabled
    ):
        rules += (
            "\n用户发送表情包时，插件会把它存入表情库并在消息中给出"
            "表情包 ID。如果你能根据图片判断它表达的情绪或含义，"
            "调用 describe_sticker 记录一两个词的简短含义；"
            "用户说明了含义时以用户说明为准。"
            "不要等用户明确要求，聊天中可以根据情绪主动调用 "
            "send_sticker 发送合适的表情包，"
            "把表情包当成日常表达方式之一；"
            "不确定有哪些表情可选时，先调用 search_stickers 查看。"
        )

    prompt = f"{persona}\n\n{rules}" if persona else rules
    custom = user_prompt.strip()
    if plugin_config.deepseek_custom_prompt_enabled and custom:
        prompt = (
            f"{prompt}\n\n【用户自定义指令】\n{custom}\n"
            "请在不违反上面的输出格式要求的前提下优先遵守这些指令。"
        )
    if summary:
        prompt = f"{prompt}\n\n【历史对话摘要】\n{summary}"

    if memories:
        lines = _memory_lines(memories)
        if lines:
            prompt = f"{prompt}\n\n【用户长期记忆】\n" + "\n".join(lines)

    return prompt


def _build_request_messages(
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


def _build_group_request_messages(
    bot_id: int,
    group_id: int,
    sender_id: int,
    sender_name: str,
    history_limit: int,
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


async def compress_if_needed(session_key: str) -> None:
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


async def _generate_reply_locked(
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


async def _generate_group_reply_locked(
    bot_id: int,
    group_id: int,
    sender_id: int,
    sender_name: str,
    session_key: str,
    usage: dict[str, int] | None = None,
) -> str:
    usage_total = usage if usage is not None else {}

    def record_usage(usage_data: Mapping[str, Any]) -> None:
        _merge_usage(usage_total, usage_data)
        _log_api_usage(session_key, "group_reply", usage_data)

    messages = _build_group_request_messages(
        bot_id,
        group_id,
        sender_id,
        sender_name,
        plugin_config.deepseek_group_history_messages,
    )

    group_tools = build_group_tool_definitions()
    if plugin_config.deepseek_tools_enabled and group_tools:

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
            tools=group_tools,
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

    store.add_group_message(bot_id, group_id, "assistant", answer)
    return answer


async def generate_reply(
    session_key: str,
    text: str,
    images: Sequence[Mapping[str, Any]] | None = None,
    *,
    history_user_text: str | None = None,
    group: bool = False,
    history_limit: int | None = None,
) -> str:
    """携带上下文请求模型，成功后把本轮问答写入历史。"""
    async with store.lock(session_key):
        return await _generate_reply_locked(
            session_key,
            text,
            images,
            history_user_text=history_user_text,
            group=group,
            history_limit=history_limit,
        )


async def reply(
    session_key: str,
    text: str,
    send: Sender,
    images: Sequence[Mapping[str, Any]] | None = None,
    *,
    history_user_text: str | None = None,
    allow_followup: bool = True,
    group: bool = False,
    history_limit: int | None = None,
    bot_id: int | None = None,
    group_id: int | None = None,
    sender_id: int | None = None,
    sender_name: str = "",
) -> None:
    """生成回复并发送；出错时回复一条可读的错误提示。"""
    qid = uuid.uuid4().hex[:8]
    usage: dict[str, int] = {}
    logger.info(
        f"[chat] question qid={qid} session={session_key} "
        f"text_len={len(text)} images={len(images or [])}"
    )

    if not client.configured:
        _log_reply(qid, session_key, False, "no_api_key", usage)
        await send(MISSING_API_KEY_TIP)
        return

    async with store.lock(session_key):
        try:
            if group:
                if (
                    bot_id is None
                    or group_id is None
                    or sender_id is None
                ):
                    raise ValueError("群聊回复缺少必要的会话信息")
                answer = await _generate_group_reply_locked(
                    bot_id,
                    group_id,
                    sender_id,
                    sender_name,
                    session_key,
                    usage,
                )
            else:
                answer = await _generate_reply_locked(
                    session_key,
                    text,
                    images,
                    usage,
                    history_user_text=history_user_text,
                    history_limit=history_limit,
                )
        except ImageError as exc:
            logger.warning(f"图片处理失败：{exc}")
            _log_reply(qid, session_key, False, "image_error", usage)
            await send(f"图片处理失败：{exc}")
            return
        except DeepSeekError as exc:
            logger.warning(
                f"DeepSeek 调用失败（status={exc.status_code}）：{exc.message}"
            )
            reason = (
                "api_error"
                if exc.status_code is None
                else f"api_error_{exc.status_code}"
            )
            _log_reply(
                qid,
                session_key,
                False,
                reason,
                usage,
            )
            await send(_format_error(exc))
            return
        except Exception:
            logger.exception("DeepSeek 对话处理出现未预期异常")
            _log_reply(qid, session_key, False, "exception", usage)
            await send("处理对话时出错了，请稍后再试。")
            return

        messages = split_reply(
            answer,
            delimiter=plugin_config.deepseek_split_delimiter,
            max_segments=plugin_config.deepseek_reply_max_segments,
            max_length=plugin_config.deepseek_reply_max_length,
            split_paragraphs=plugin_config.deepseek_split_paragraphs,
        )
        if not messages:
            messages = [EMPTY_REPLY_TIP]

        initial_delay = next_initial_delay()
        if initial_delay > 0:
            await asyncio.sleep(initial_delay)

        try:
            for index, message in enumerate(messages):
                if index:
                    delay = next_reply_interval()
                    if delay > 0:
                        await asyncio.sleep(delay)
                await send(message)
        except Exception:
            logger.exception("发送回复失败")
            _log_reply(
                qid,
                session_key,
                False,
                "send_error",
                usage,
                len(messages),
            )
            return

        _log_reply(
            qid,
            session_key,
            True,
            "ok",
            usage,
            len(messages),
        )

        if allow_followup and not group:
            _maybe_schedule_followup(session_key, answer)

        if not group:
            try:
                await compress_if_needed(session_key)
            except Exception:
                logger.exception("上下文压缩处理失败")


async def proactive_reply(
    session_key: str,
    topic: str,
    send: Sender,
) -> None:
    """到点后由模型主动生成一条消息，像真人一样开启话题。"""
    prompt = (
        "（现在是主动找用户聊天的时间。像真人一样自然地发一条消息开启话题，"
        "可以问候、关心、分享或接着之前的话题；"
        "直接输出你要发给用户的内容，不要提到这是定时任务，"
        "不要解释，也不要说“有什么可以帮你”。"
    )
    if topic:
        prompt += f"这次想聊：{topic}。"
    prompt += "）"

    await reply(
        session_key,
        prompt,
        send,
        history_user_text="（AI 主动找用户聊天）",
    )


async def followup_reply(
    session_key: str,
    send: Sender,
) -> None:
    """用户一段时间没回复时，由模型再补一句自然追问。"""
    prompt = (
        "（你刚才问了用户一个问题，但用户一段时间没有回复。"
        "现在像真人一样再发一句，轻轻追问或关心；"
        "不要提到定时任务，不要重复原问题，不要连续追问；"
        "直接输出你要发给用户的内容。）"
    )
    await reply(
        session_key,
        prompt,
        send,
        history_user_text="（AI 追问未回复的用户）",
        allow_followup=False,
    )


async def _is_message_complete(
    session_key: str,
    text: str,
    images: list[dict[str, Any]],
) -> bool:
    """判断聚合后的消息是否已经完整，可以交给正式对话处理。"""
    if images:
        return True
    if not text.strip():
        return True
    if not plugin_config.deepseek_completeness_check or not client.configured:
        return True

    try:
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": COMPLETENESS_SYSTEM_PROMPT,
            }
        ]
        messages.extend(store.build_messages(session_key)[-6:])
        messages.append({"role": "user", "content": text})
        answer = await client.chat(
            messages,
            on_usage=lambda usage: _log_api_usage(
                session_key, "completeness", usage
            ),
            session_key=session_key,
            phase="completeness",
        )
    except Exception:
        logger.exception("消息完整性判断失败，按完整处理")
        return True

    upper = answer.strip().upper()
    if "INCOMPLETE" in upper or "不完整" in answer:
        logger.info(
            f"[chat] no_reply session={session_key} reason=incomplete "
            f"text_len={len(text)}"
        )
        return False
    return True


async def _handle_aggregated(
    session_key: str,
    text: str,
    images: list[dict[str, Any]],
    send: Sender,
) -> None:
    logger.info(
        f"[chat] aggregated session={session_key} "
        f"text_len={len(text)} images={len(images)}"
    )
    await reply(session_key, text, send, images=images)


message_aggregator = MessageAggregator(
    debounce_seconds=plugin_config.deepseek_debounce_seconds,
    debounce_jitter=plugin_config.deepseek_debounce_jitter,
    is_complete=_is_message_complete,
    handler=_handle_aggregated,
)


async def process_private_poke(event: PokeNotifyEvent, send: Sender) -> None:
    session_key = _session_key(event)
    logger.info(
        f"[chat] poke session={session_key} target={event.target_id}"
    )
    _cancel_pending_followup(session_key)
    prompt = (
        POKE_BACK_PROMPT
        if plugin_config.deepseek_tools_enabled
        and plugin_config.deepseek_poke_enabled
        else POKE_PROMPT
    )
    await reply(session_key, prompt, send)


async def process_group_poke(
    event: PokeNotifyEvent, send: Sender
) -> None:
    if event.group_id is None:
        return
    session_key = f"group:{event.self_id}:{event.group_id}"
    sender_name = f"用户{event.user_id}"
    store.add_group_message(
        event.self_id,
        event.group_id,
        "user",
        "（对方戳了你一下，想引起你的注意）",
        sender_id=event.user_id,
        sender_name=sender_name,
    )
    logger.info(
        f"[group] poke session={session_key} "
        f"target={event.target_id} user={event.user_id}"
    )
    prompt = (
        POKE_BACK_PROMPT
        if plugin_config.deepseek_tools_enabled
        and plugin_config.deepseek_poke_enabled
        else POKE_PROMPT
    )
    await reply(
        session_key,
        prompt,
        send,
        group=True,
        history_limit=plugin_config.deepseek_group_history_messages,
        allow_followup=False,
        bot_id=event.self_id,
        group_id=event.group_id,
        sender_id=event.user_id,
        sender_name=sender_name,
    )


async def clear_user_context(session_key: str) -> None:
    """清空当前用户的消息、摘要和长期记忆，保留自定义提示词。"""
    await message_aggregator.discard(session_key)
    async with store.lock(session_key):
        store.clear_context(session_key)
    logger.info(f"[chat] clear_context session={session_key}")


clear_context_command = on_command(
    "清空",
    aliases={
        "清除",
        "重置",
        "清空上下文",
        "清除上下文",
        "重置上下文",
        "clear",
        "reset",
    },
    rule=Rule(_is_private_message),
    priority=5,
    block=True,
)


@clear_context_command.handle()
async def handle_clear_context(event: PrivateMessageEvent) -> None:
    await clear_user_context(_session_key(event))
    await clear_context_command.finish("已清空当前用户的全部对话上下文。")


def _group_sticker_note(records: list[dict[str, Any]]) -> str:
    ids = "、".join(f"#{record['id']}" for record in records)
    note = (
        f"（本轮收到 {len(records)} 个表情包，"
        f"已存入全局表情库（私聊和所有群共用）：{ids}。"
    )
    if plugin_config.deepseek_tools_enabled:
        note += (
            "如果用户说明了含义，调用 describe_sticker 记录；"
            "没有说明就不要猜。需要发表情包时调用 send_sticker。）"
        )
    else:
        note += "）"
    return note


async def process_group_message(
    event: GroupMessageEvent, send: Sender
) -> None:
    session_key = _group_session_key(event)
    if event.user_id == event.self_id:
        return

    text = event.get_plaintext().strip()
    sender = _group_sender_name(event)
    to_me = event.to_me or _has_at_bot(event)
    logger.info(
        f"[group] incoming session={session_key} user={event.user_id} "
        f"text_len={len(text)} to_me={str(to_me).lower()} "
        f"probability={plugin_config.deepseek_group_reply_probability}"
    )

    if text and _starts_with_command(text):
        return

    images = [
        segment for segment in event.message if segment.type == "image"
    ]
    sticker_records: list[dict[str, Any]] = []
    if images and plugin_config.deepseek_sticker_enabled:
        for segment in images:
            if (
                len(sticker_records)
                >= plugin_config.deepseek_sticker_max_count
            ):
                break
            if not is_sticker_image(segment.data, text):
                continue
            try:
                payload = await fetch_image(
                    segment.data,
                    timeout=plugin_config.deepseek_image_timeout,
                    max_bytes=plugin_config.deepseek_image_max_bytes,
                )
                sticker_records.append(
                    save_sticker_payload(
                        store,
                        STICKER_LIBRARY_KEY,
                        payload,
                    )
                )
            except Exception:
                logger.exception("群聊表情包保存失败，跳过本次收藏")

    content = text if text else ("[图片]" if images else "[非文本消息]")
    if sticker_records:
        content = f"{content}\n{_group_sticker_note(sticker_records)}"
    elif images and text:
        content = f"{content}\n（发送了 {len(images)} 张图片）"

    store.add_group_message(
        event.self_id,
        event.group_id,
        "user",
        content,
        sender_id=event.user_id,
        sender_name=sender,
    )

    if not text and not to_me:
        return

    if to_me:
        _mark_group_reply(session_key)
        await reply(
            session_key,
            text,
            send,
            group=True,
            history_limit=plugin_config.deepseek_group_history_messages,
            allow_followup=False,
            bot_id=event.self_id,
            group_id=event.group_id,
            sender_id=event.user_id,
            sender_name=sender,
        )
        return

    if _should_group_reply(session_key):
        _mark_group_reply(session_key)
        await reply(
            session_key,
            text,
            send,
            group=True,
            history_limit=plugin_config.deepseek_group_history_messages,
            allow_followup=False,
            bot_id=event.self_id,
            group_id=event.group_id,
            sender_id=event.user_id,
            sender_name=sender,
        )


async def process_private_message(event: PrivateMessageEvent, send: Sender) -> None:
    text = event.get_plaintext().strip()
    images = [
        segment.data for segment in event.message if segment.type == "image"
    ]
    session_key = _session_key(event)
    logger.info(
        f"[chat] incoming session={session_key} text_len={len(text)} "
        f"images={len(images)} "
        f"aggregate={plugin_config.deepseek_aggregate_messages}"
    )
    _cancel_pending_followup(session_key)

    if images and not plugin_config.deepseek_image_enabled:
        if not text:
            logger.info(
                f"[chat] reply session={session_key} "
                f"replied=true reason=image_disabled tip_sent=true"
            )
            await send(IMAGE_DISABLED_TIP)
            return
        images = []

    if not text and not images:
        logger.debug(f"[chat] ignored session={session_key} reason=empty")
        return
    if event.user_id == event.self_id:
        logger.debug(f"[chat] ignored session={session_key} reason=self")
        return
    if text and _starts_with_command(text):
        logger.debug(f"[chat] ignored session={session_key} reason=command")
        return

    if plugin_config.deepseek_aggregate_messages:
        await message_aggregator.add(session_key, text, images, send)
    else:
        await reply(session_key, text, send, images=images)


@private_chat.handle()
async def handle_private_chat(event: PrivateMessageEvent, matcher: Matcher) -> None:
    async def send(message: str) -> None:
        await matcher.send(message)

    await process_private_message(event, send)


@group_chat.handle()
async def handle_group_chat(bot: Bot, event: GroupMessageEvent) -> None:
    async def send(message: str) -> None:
        await bot.call_api(
            "send_group_msg",
            group_id=event.group_id,
            message=message,
        )

    await process_group_message(event, send)


@group_poke.handle()
async def handle_group_poke(bot: Bot, event: PokeNotifyEvent) -> None:
    async def send(message: str) -> None:
        await bot.call_api(
            "send_group_msg",
            group_id=event.group_id,
            message=message,
        )

    await process_group_poke(event, send)


@private_poke.handle()
async def handle_private_poke(bot: Bot, event: PokeNotifyEvent) -> None:
    async def send(message: str) -> None:
        await bot.call_api(
            "send_private_msg",
            user_id=event.user_id,
            message=message,
        )

    await process_private_poke(event, send)
