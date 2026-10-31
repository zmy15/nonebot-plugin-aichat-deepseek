"""私聊对话逻辑。

只处理私聊消息，不需要任何命令前缀；群里发送的消息不会触发。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from nonebot import get_driver, logger, on_message
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import PrivateMessageEvent
from nonebot.matcher import Matcher
from nonebot.rule import Rule

from .config import plugin_config
from .data_source import ChatMessage, DeepSeekClient, DeepSeekError
from .history import ConversationStore

Sender = Callable[[str], Awaitable[None]]

MISSING_API_KEY_TIP = "还没有配置 DEEPSEEK_API_KEY，请先在 .env 中填写后再试。"

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


def split_text(text: str, limit: int) -> list[str]:
    """把过长回复按换行或定长切分，尽量不切断单词行。"""
    text = text.strip()
    if not text:
        return []
    if limit <= 0:
        return [text]

    chunks: list[str] = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunk = text[:cut].strip()
        if chunk:
            chunks.append(chunk)
        text = text[cut:].lstrip("\n")
    if text.strip():
        chunks.append(text.strip())
    return chunks


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


def _build_request_messages(session_key: str, text: str) -> list[ChatMessage]:
    messages = store.build_messages(session_key)
    system_prompt = plugin_config.deepseek_system_prompt.strip()
    if system_prompt:
        messages.insert(0, {"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": text})
    return messages


async def generate_reply(session_key: str, text: str) -> str:
    """携带上下文请求模型，成功后把本轮问答写入历史。"""
    async with store.lock(session_key):
        messages = _build_request_messages(session_key, text)
        answer = await client.chat(messages)
        store.add_turn(session_key, text, answer)
        return answer


async def reply(session_key: str, text: str, send: Sender) -> None:
    """生成回复并发送；出错时回复一条可读的错误提示。"""
    if not client.configured:
        await send(MISSING_API_KEY_TIP)
        return

    try:
        answer = await generate_reply(session_key, text)
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

    for chunk in split_text(answer, plugin_config.deepseek_reply_max_length):
        await send(chunk)


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
