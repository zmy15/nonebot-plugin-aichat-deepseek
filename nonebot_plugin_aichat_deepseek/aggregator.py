"""把用户连续发送的多条消息合并成一次完整提问。

用户可能把一句话拆成几次发送。``MessageAggregator`` 在每次新消息到达时
重置一个抖动等待窗口；窗口结束后调用完整性判断，只有判断为完整才交给
后续对话处理。判断为不完整时保留缓冲区，等待用户继续发送。
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

Sender = Callable[[str], Awaitable[None]]
CompletenessChecker = Callable[
    [str, str, list[dict[str, Any]]], Awaitable[bool]
]
BatchHandler = Callable[
    [str, str, list[dict[str, Any]], Sender], Awaitable[None]
]


@dataclass
class _PendingBatch:
    texts: list[str] = field(default_factory=list)
    images: list[dict[str, Any]] = field(default_factory=list)
    send: Sender | None = None


class MessageAggregator:
    def __init__(
        self,
        *,
        debounce_seconds: float,
        debounce_jitter: float,
        is_complete: CompletenessChecker,
        handler: BatchHandler,
    ) -> None:
        self._debounce_seconds = max(0.0, debounce_seconds)
        self._debounce_jitter = max(0.0, debounce_jitter)
        self._is_complete = is_complete
        self._handler = handler
        self._pending: dict[str, _PendingBatch] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._versions: dict[str, int] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, key: str) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    def _delay(self) -> float:
        jitter = random.uniform(
            -self._debounce_jitter, self._debounce_jitter
        )
        return max(0.0, self._debounce_seconds + jitter)

    def _clear_task(self, key: str) -> None:
        current = asyncio.current_task()
        if self._tasks.get(key) is current:
            self._tasks.pop(key, None)

    async def add(
        self,
        session_key: str,
        text: str,
        images: list[dict[str, Any]],
        send: Sender,
    ) -> None:
        async with self._lock_for(session_key):
            batch = self._pending.get(session_key)
            if batch is None:
                batch = _PendingBatch()
                self._pending[session_key] = batch

            if text:
                batch.texts.append(text)
            if images:
                batch.images.extend(images)
            batch.send = send

            version = self._versions.get(session_key, 0) + 1
            self._versions[session_key] = version
            self._tasks[session_key] = asyncio.create_task(
                self._flush_after(session_key, version)
            )

    async def discard(self, session_key: str) -> None:
        """丢弃某个会话尚未处理的消息，用于清空上下文命令。"""
        self._versions[session_key] = (
            self._versions.get(session_key, 0) + 1
        )
        async with self._lock_for(session_key):
            self._pending.pop(session_key, None)
            self._versions[session_key] = (
                self._versions.get(session_key, 0) + 1
            )
            task = self._tasks.pop(session_key, None)
            if task is not None and task is not asyncio.current_task():
                task.cancel()

    async def _flush_after(self, key: str, version: int) -> None:
        await asyncio.sleep(self._delay())

        async with self._lock_for(key):
            if self._versions.get(key) != version:
                return

            batch = self._pending.get(key)
            if batch is None:
                return

            text = "\n".join(batch.texts).strip()
            images = list(batch.images)
            if not text and not images:
                self._pending.pop(key, None)
                self._clear_task(key)
                return

            complete = True
            try:
                complete = await self._is_complete(key, text, images)
            except Exception:
                logger.exception("消息完整性判断失败，按完整处理")

            if self._versions.get(key) != version:
                return

            if not complete:
                self._clear_task(key)
                return

            self._pending.pop(key, None)
            self._clear_task(key)
            send = batch.send

        if send is not None:
            try:
                await self._handler(key, text, images, send)
            except Exception:
                logger.exception("聚合消息处理失败")
