"""私聊/群聊的响应规则、回复发送和 OneBot 事件入口。

system 提示词、上下文拼装、上下文压缩和模型调用分别放在
``prompts`` / ``context`` / ``compression`` / ``replies`` 中，
本模块只保留运行时依赖、发送逻辑和事件处理。
"""

from __future__ import annotations

import asyncio
import random
import re
import time
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from nonebot import logger, on_command, on_message, on_notice
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
from .compression import (
    _GROUP_LAST_HISTORY_COUNT,
    _GROUP_LAST_PROMPT_TOKENS,
    _GROUP_LAST_SYSTEM,
    _GROUP_LAST_TOOLS,
    compress_group_if_needed as _compress_group_if_needed,
    compress_if_needed as _compress_if_needed,
)
from .config import plugin_config
from .constants import (
    COMPLETENESS_SYSTEM_PROMPT,
    EMPTY_REPLY_TIP,
    IMAGE_DISABLED_TIP,
    MISSING_API_KEY_TIP,
    POKE_BACK_PROMPT,
    POKE_PROMPT,
    Sender,
)
from .context import (
    _build_group_request_messages as _context_build_group_request_messages,
    _build_request_messages as _context_build_request_messages,
)
from .data_source import DeepSeekClient, DeepSeekError
from .formatting import split_reply
from .history import STICKER_LIBRARY_KEY, ConversationStore
from .images import ImageError, fetch_image
from .prompts import _build_system_prompt
from .replies import generate_group_reply, generate_private_reply
from .scheduled_tasks import cancel_followup, get_scheduler, schedule_followup
from .stickers import is_sticker_image, save_sticker_payload
from .timing import (
    _looks_like_question,
    _starts_with_command,
    next_initial_delay,
    next_reply_interval,
)
from .usage import (
    _format_error,
    _log_api_usage,
    _log_reply,
    _merge_usage,
    _usage_numbers,
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


def _build_request_messages(
    session_key: str,
    user_content: str | list[dict[str, Any]],
    *,
    group: bool = False,
    history_limit: int | None = None,
) -> list[dict[str, Any]]:
    """兼容入口：使用当前 store 拼装私聊请求。"""
    return _context_build_request_messages(
        store,
        session_key,
        user_content,
        group=group,
        history_limit=history_limit,
    )


def _build_group_request_messages(
    bot_id: int,
    group_id: int,
    sender_id: int,
    sender_name: str,
    history_limit: int | None = None,
) -> list[dict[str, Any]]:
    """兼容入口：使用当前 store 拼装群聊请求。"""
    return _context_build_group_request_messages(
        store,
        bot_id,
        group_id,
        sender_id,
        sender_name,
        history_limit,
    )


async def compress_if_needed(session_key: str) -> None:
    """兼容入口：使用当前 client/store 压缩私聊上下文。"""
    await _compress_if_needed(client, store, session_key)


async def compress_group_if_needed(
    bot_id: int,
    group_id: int,
    session_key: str,
) -> bool:
    """兼容入口：使用当前 client/store 压缩群聊上下文。"""
    return await _compress_group_if_needed(
        client, store, bot_id, group_id, session_key
    )


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
    """兼容入口：注入当前运行时依赖后生成私聊回复。"""
    return await generate_private_reply(
        client,
        store,
        fetch_image,
        get_scheduler,
        session_key,
        text,
        images,
        usage,
        history_user_text,
        group=group,
        history_limit=history_limit,
    )


async def _generate_group_reply_locked(
    bot_id: int,
    group_id: int,
    sender_id: int,
    sender_name: str,
    session_key: str,
    usage: dict[str, int] | None = None,
) -> str:
    """兼容入口：注入当前运行时依赖后生成群聊回复。"""
    return await generate_group_reply(
        client,
        store,
        get_scheduler,
        bot_id,
        group_id,
        sender_id,
        sender_name,
        session_key,
        usage,
    )

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

        if group:
            if bot_id is not None and group_id is not None:
                try:
                    await compress_group_if_needed(
                        bot_id, group_id, session_key
                    )
                except Exception:
                    logger.exception("群聊上下文压缩处理失败")
        else:
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
