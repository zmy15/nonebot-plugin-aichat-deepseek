"""私聊对话逻辑。

只处理私聊消息，不需要任何命令前缀；群里发送的消息不会触发。
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable

from nonebot import get_driver, logger, on_message
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import PrivateMessageEvent
from nonebot.matcher import Matcher
from nonebot.rule import Rule

from .config import plugin_config
from .data_source import ChatMessage, DeepSeekClient, DeepSeekError
from .formatting import split_reply
from .history import ConversationStore

Sender = Callable[[str], Awaitable[None]]

MISSING_API_KEY_TIP = "还没有配置 DEEPSEEK_API_KEY，请先在 .env 中填写后再试。"
EMPTY_REPLY_TIP = "……"

client = DeepSeekClient(
    api_key=plugin_config.deepseek_api_key,
    api_base=plugin_config.deepseek_api_base,
    model=plugin_config.deepseek_model,
    timeout=plugin_config.deepseek_timeout,
    temperature=plugin_config.deepseek_temperature,
    max_tokens=plugin_config.deepseek_max_tokens,
    thinking=plugin_config.deepseek_thinking,
)

store = ConversationStore(plugin_config.deepseek_history_turns)


async def _is_private_message(event: Event) -> bool:
    """响应规则：只匹配 OneBot V11 的私聊消息。"""
    return isinstance(event, PrivateMessageEvent)


private_chat = on_message(rule=Rule(_is_private_message), priority=100, block=True)


def _session_key(event: PrivateMessageEvent) -> str:
    """同一机器人下按用户隔离上下文。"""
    return f"{event.self_id}:{event.user_id}"


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


def _build_system_prompt() -> str:
    """在用户配置的人设之后追加纯文本、分隔符等输出约束。"""
    persona = plugin_config.deepseek_system_prompt.strip()
    delimiter = plugin_config.deepseek_split_delimiter.strip() or "|||"
    rules = (
        "输出要求：\n"
        "1. 只输出纯文本，不要使用任何 Markdown 格式"
        "（标题、加粗、斜体、代码块、引用、列表、表格、链接等）。\n"
        f"2. 需要分成多条消息时，用 {delimiter} 分隔；"
        "每条消息简短自然，像真人聊天。\n"
        "3. 不要在回复中解释或提到分隔符。"
    )
    return f"{persona}\n\n{rules}" if persona else rules


def _build_request_messages(session_key: str, text: str) -> list[ChatMessage]:
    messages = store.build_messages(session_key)
    messages.insert(0, {"role": "system", "content": _build_system_prompt()})
    messages.append({"role": "user", "content": text})
    return messages


async def _generate_reply_locked(session_key: str, text: str) -> str:
    messages = _build_request_messages(session_key, text)
    answer = await client.chat(messages)
    store.add_turn(session_key, text, answer)
    return answer


async def generate_reply(session_key: str, text: str) -> str:
    """携带上下文请求模型，成功后把本轮问答写入历史。"""
    async with store.lock(session_key):
        return await _generate_reply_locked(session_key, text)


async def reply(session_key: str, text: str, send: Sender) -> None:
    """生成回复并发送；出错时回复一条可读的错误提示。"""
    if not client.configured:
        await send(MISSING_API_KEY_TIP)
        return

    async with store.lock(session_key):
        try:
            answer = await _generate_reply_locked(session_key, text)
        except DeepSeekError as exc:
            logger.warning(
                f"DeepSeek 调用失败（status={exc.status_code}）：{exc.message}"
            )
            await send(_format_error(exc))
            return
        except Exception:
            logger.exception("DeepSeek 对话处理出现未预期异常")
            await send("处理对话时出错了，请稍后再试。")
            return

        messages = split_reply(
            answer,
            delimiter=plugin_config.deepseek_split_delimiter,
            max_segments=plugin_config.deepseek_reply_max_segments,
            max_length=plugin_config.deepseek_reply_max_length,
        )
        if not messages:
            messages = [EMPTY_REPLY_TIP]

        for index, message in enumerate(messages):
            if index:
                delay = next_reply_interval()
                if delay > 0:
                    await asyncio.sleep(delay)
            await send(message)


async def process_private_message(event: PrivateMessageEvent, send: Sender) -> None:
    text = event.get_plaintext().strip()
    if not text or event.user_id == event.self_id:
        return
    if _starts_with_command(text):
        return
    await reply(_session_key(event), text, send)


@private_chat.handle()
async def handle_private_chat(event: PrivateMessageEvent, matcher: Matcher) -> None:
    async def send(message: str) -> None:
        await matcher.send(message)

    await process_private_message(event, send)
