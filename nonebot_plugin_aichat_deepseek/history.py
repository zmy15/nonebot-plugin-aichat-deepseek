"""进程内的对话上下文存储。

上下文只保存在内存中，机器人重启后会丢失；按会话（私聊用户）隔离，
每个会话最多保留最近 ``max_turns`` 轮问答。
"""

from __future__ import annotations

import asyncio
from collections import deque

from .data_source import ChatMessage

Turn = tuple[str, str]


class ConversationStore:
    def __init__(self, max_turns: int = 5) -> None:
        self._max_turns = max(0, max_turns)
        self._turns: dict[str, deque[Turn]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def lock(self, key: str) -> asyncio.Lock:
        """获取某个会话的锁，避免同一用户并发消息打乱上下文。"""
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    def build_messages(self, key: str) -> list[ChatMessage]:
        """把历史轮次转换为 API 需要的 messages 列表。"""
        messages: list[ChatMessage] = []
        for user_text, assistant_text in self._turns.get(key, ()):
            messages.append({"role": "user", "content": user_text})
            messages.append({"role": "assistant", "content": assistant_text})
        return messages

    def add_turn(self, key: str, user_text: str, assistant_text: str) -> None:
        if self._max_turns == 0:
            return
        turns = self._turns.get(key)
        if turns is None:
            turns = deque(maxlen=self._max_turns)
            self._turns[key] = turns
        turns.append((user_text, assistant_text))

    def clear(self, key: str) -> None:
        self._turns.pop(key, None)
