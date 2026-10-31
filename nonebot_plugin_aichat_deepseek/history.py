"""基于 SQLite 的对话上下文存储。

- 每条用户消息、AI 回复都会写入本地数据库
- 启动时把未压缩的历史消息和摘要加载进内存，后续读写走内存 + 写穿
- 未压缩消息超过阈值时，把最早的一批消息标记为已压缩，并生成滚动摘要
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

from .data_source import ChatMessage

UTC = timezone.utc
UTC8 = timezone(timedelta(hours=8), name="UTC+8")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_key TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    compressed INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_messages_session
    ON messages (session_key, compressed, id);

CREATE TABLE IF NOT EXISTS summaries (
    session_key TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_key TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'fact',
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (session_key, content)
);

CREATE INDEX IF NOT EXISTS idx_memories_session
    ON memories (session_key, updated_at, id);
"""


def _utc_text(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, tz=UTC).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def _utc_to_utc8(value: str) -> str:
    moment = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    return moment.replace(tzinfo=UTC).astimezone(UTC8).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


class ConversationStore:
    def __init__(
        self,
        db_path: str | Path = ":memory:",
        max_turns: int = 30,
        trigger_turns: int = 30,
        batch_messages: int = 20,
    ) -> None:
        self._max_turns = max(0, max_turns)
        self._trigger_turns = max(0, trigger_turns)
        self._batch_messages = max(1, batch_messages)
        self._messages: dict[str, list[ChatMessage]] = {}
        self._summaries: dict[str, str] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._conn = self._connect(db_path)
        self._init_schema()
        self._load_all()

    @staticmethod
    def _connect(db_path: str | Path) -> sqlite3.Connection:
        if str(db_path) == ":memory:":
            target = ":memory:"
        else:
            path = Path(db_path).expanduser()
            if not path.is_absolute():
                path = Path.cwd() / path
            path.parent.mkdir(parents=True, exist_ok=True)
            target = str(path)

        conn = sqlite3.connect(target, timeout=5.0)
        if target != ":memory:":
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.executescript(_SCHEMA)

    def _load_all(self) -> None:
        for session_key, role, content in self._conn.execute(
            "SELECT session_key, role, content FROM messages "
            "WHERE compressed = 0 ORDER BY id"
        ):
            self._messages.setdefault(session_key, []).append(
                cast(ChatMessage, {"role": role, "content": content})
            )
        for session_key, content in self._conn.execute(
            "SELECT session_key, content FROM summaries"
        ):
            self._summaries[session_key] = content

    def lock(self, key: str) -> asyncio.Lock:
        """获取某个会话的锁，避免同一用户并发消息打乱上下文。"""
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    def build_messages(self, key: str) -> list[ChatMessage]:
        """把最近的历史消息转换为 API 需要的 messages 列表。"""
        if self._max_turns == 0:
            return []
        messages = self._messages.get(key, [])
        limit = self._max_turns * 2
        if len(messages) > limit:
            messages = messages[-limit:]
        return [
            cast(ChatMessage, dict(message)) for message in messages
        ]

    def add_turn(
        self,
        key: str,
        user_text: str,
        assistant_text: str,
        *,
        when: datetime | None = None,
    ) -> None:
        """持久化一轮完整问答，并同步到内存。"""
        moment = when or datetime.now(UTC)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC8)
        created_at = moment.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")

        with self._conn:
            self._conn.executemany(
                "INSERT INTO messages "
                "(session_key, role, content, created_at) "
                "VALUES (?, ?, ?, ?)",
                [
                    (key, "user", user_text, created_at),
                    (key, "assistant", assistant_text, created_at),
                ],
            )
        self._messages.setdefault(key, []).extend(
            [
                {"role": "user", "content": user_text},
                {"role": "assistant", "content": assistant_text},
            ]
        )

    def get_summary(self, key: str) -> str:
        return self._summaries.get(key, "")

    def add_memory(
        self,
        key: str,
        content: str,
        category: str = "fact",
    ) -> int:
        """保存一条长期记忆；相同内容会更新分类和时间。"""
        content = content.strip()
        if not content:
            raise ValueError("记忆内容不能为空")

        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        with self._conn:
            self._conn.execute(
                "INSERT INTO memories "
                "(session_key, category, content, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(session_key, content) DO UPDATE SET "
                "category = excluded.category, "
                "updated_at = excluded.updated_at",
                (key, category, content, now, now),
            )
            row = self._conn.execute(
                "SELECT id FROM memories "
                "WHERE session_key = ? AND content = ?",
                (key, content),
            ).fetchone()
        return int(row[0]) if row else 0

    def list_memories(self, key: str, limit: int = 20) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 50))
        rows = self._conn.execute(
            "SELECT id, category, content FROM memories "
            "WHERE session_key = ? "
            "ORDER BY updated_at DESC, id DESC LIMIT ?",
            (key, limit),
        ).fetchall()
        return [
            {"id": int(memory_id), "category": category, "content": content}
            for memory_id, category, content in rows
        ]

    def search_memories(
        self,
        key: str,
        keyword: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 50))
        clauses = ["session_key = ?"]
        params: list[Any] = [key]

        if keyword:
            escaped = (
                keyword.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            clauses.append("content LIKE ? ESCAPE '\\'")
            params.append(f"%{escaped}%")

        params.append(limit)
        rows = self._conn.execute(
            "SELECT id, category, content FROM memories "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY updated_at DESC, id DESC LIMIT ?",
            params,
        ).fetchall()
        return [
            {"id": int(memory_id), "category": category, "content": content}
            for memory_id, category, content in rows
        ]

    def delete_memory(self, key: str, memory_id: int) -> bool:
        with self._conn:
            cursor = self._conn.execute(
                "DELETE FROM memories WHERE id = ? AND session_key = ?",
                (memory_id, key),
            )
        return cursor.rowcount > 0

    def needs_compression(self, key: str) -> bool:
        if self._max_turns == 0 or self._trigger_turns == 0:
            return False
        return len(self._messages.get(key, [])) > self._trigger_turns * 2

    def get_compression_batch(self, key: str) -> list[ChatMessage]:
        messages = self._messages.get(key, [])
        return [
            cast(ChatMessage, dict(message))
            for message in messages[: self._batch_messages]
        ]

    def apply_compression(self, key: str, count: int, summary: str) -> None:
        """把最早 ``count`` 条消息标记为已压缩，并保存摘要。"""
        messages = self._messages.get(key, [])
        count = max(0, min(count, len(messages)))
        if count == 0:
            return

        with self._conn:
            self._conn.execute(
                """
                UPDATE messages SET compressed = 1
                WHERE id IN (
                    SELECT id FROM messages
                    WHERE session_key = ? AND compressed = 0
                    ORDER BY id
                    LIMIT ?
                )
                """,
                (key, count),
            )
            self._conn.execute(
                """
                INSERT INTO summaries (session_key, content, updated_at)
                VALUES (?, ?, datetime('now'))
                ON CONFLICT(session_key) DO UPDATE SET
                    content = excluded.content,
                    updated_at = excluded.updated_at
                """,
                (key, summary),
            )

        self._messages[key] = messages[count:]
        self._summaries[key] = summary

    def query_history(
        self,
        key: str,
        *,
        start_ts: int | None = None,
        end_ts: int | None = None,
        keyword: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """把 messages 中的 user/assistant 配对成轮次后查询。"""
        clauses = ["u.session_key = ?", "u.role = 'user'"]
        params: list[Any] = [key]

        if start_ts is not None:
            clauses.append("u.created_at >= ?")
            params.append(_utc_text(start_ts))
        if end_ts is not None:
            clauses.append("u.created_at <= ?")
            params.append(_utc_text(end_ts))
        if keyword:
            escaped = (
                keyword.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            clauses.append(
                "(u.content LIKE ? ESCAPE '\\' "
                "OR a.content LIKE ? ESCAPE '\\')"
            )
            params.extend([f"%{escaped}%", f"%{escaped}%"])

        limit = max(1, min(int(limit), 50))
        params.append(limit)

        rows = self._conn.execute(
            "SELECT u.created_at, u.content, a.content "
            "FROM messages AS u "
            "JOIN messages AS a ON a.id = ("
            "    SELECT MIN(a2.id) FROM messages AS a2 "
            "    WHERE a2.session_key = u.session_key "
            "      AND a2.role = 'assistant' "
            "      AND a2.id > u.id"
            ") "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY u.id DESC LIMIT ?",
            params,
        ).fetchall()
        rows.reverse()

        return [
            {
                "time": _utc_to_utc8(created_at),
                "user": user_content,
                "assistant": assistant_content,
            }
            for created_at, user_content, assistant_content in rows
        ]

    def clear(self, key: str) -> None:
        with self._conn:
            self._conn.execute(
                "DELETE FROM messages WHERE session_key = ?", (key,)
            )
            self._conn.execute(
                "DELETE FROM summaries WHERE session_key = ?", (key,)
            )
            self._conn.execute(
                "DELETE FROM memories WHERE session_key = ?", (key,)
            )
        self._messages.pop(key, None)
        self._summaries.pop(key, None)

    def close(self) -> None:
        self._conn.close()
