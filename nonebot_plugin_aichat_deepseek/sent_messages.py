"""记录机器人最近发送的消息，供撤回工具使用。

只保存在内存里：进程重启后记录会丢失，但撤回本身也只对刚发送不久
的消息有意义。记录按会话隔离，最多保留 20 条，2 分钟后过期。
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

MAX_SENT_MESSAGES = 20
SENT_MESSAGE_TTL = 2 * 60.0

_BUCKETS: dict[str, list["SentMessage"]] = {}


@dataclass(frozen=True, slots=True)
class SentMessage:
    message_id: int
    content: str
    created_at: float


def extract_message_id(result: Any) -> int | None:
    """从 OneBot 发送接口的返回值里取出 message_id。"""
    if isinstance(result, bool):
        return None
    if isinstance(result, int):
        return result
    if isinstance(result, Mapping):
        value = result.get("message_id")
    else:
        value = getattr(result, "message_id", None)
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def record(
    session_key: str,
    message_id: int,
    content: str = "",
    *,
    when: float | None = None,
) -> None:
    """记录一条机器人发送的消息，重复 ID 会被替换。"""
    current = time.monotonic()
    created_at = current if when is None else when
    if current - created_at > SENT_MESSAGE_TTL:
        return
    bucket = [
        item
        for item in _BUCKETS.get(session_key, [])
        if current - item.created_at <= SENT_MESSAGE_TTL
        and item.message_id != message_id
    ]
    bucket.append(SentMessage(int(message_id), content, created_at))
    _BUCKETS[session_key] = bucket[-MAX_SENT_MESSAGES:]


def record_result(
    session_key: str,
    result: Any,
    content: str = "",
) -> int | None:
    """从发送结果中提取 ID 并记录，返回记录到的 ID。"""
    message_id = extract_message_id(result)
    if message_id is None:
        return None
    record(session_key, message_id, content)
    return message_id


def recent(session_key: str, count: int = 1) -> list[SentMessage]:
    """返回最近 ``count`` 条记录，按发送时间从旧到新排列。"""
    now = time.monotonic()
    bucket = [
        item
        for item in _BUCKETS.get(session_key, [])
        if now - item.created_at <= SENT_MESSAGE_TTL
    ]
    if bucket:
        _BUCKETS[session_key] = bucket[-MAX_SENT_MESSAGES:]
    else:
        _BUCKETS.pop(session_key, None)
    count = max(1, int(count))
    return bucket[-count:]


def remove(session_key: str, message_id: int) -> None:
    bucket = [
        item
        for item in _BUCKETS.get(session_key, [])
        if item.message_id != message_id
    ]
    if bucket:
        _BUCKETS[session_key] = bucket
    else:
        _BUCKETS.pop(session_key, None)


def clear(session_key: str | None = None) -> None:
    if session_key is None:
        _BUCKETS.clear()
    else:
        _BUCKETS.pop(session_key, None)
