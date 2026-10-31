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

# 所有私聊和群聊共用同一个表情库
STICKER_LIBRARY_KEY = "global"

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

CREATE TABLE IF NOT EXISTS user_prompts (
    session_key TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS stickers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_key TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    file_path TEXT NOT NULL,
    mime TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'user',
    use_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_used_at TEXT,
    UNIQUE (session_key, sha256)
);

CREATE INDEX IF NOT EXISTS idx_stickers_session
    ON stickers (session_key, updated_at, id);

CREATE TABLE IF NOT EXISTS group_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id INTEGER NOT NULL,
    group_id INTEGER NOT NULL,
    sender_id INTEGER,
    sender_name TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_group_messages
    ON group_messages (bot_id, group_id, id);

CREATE TABLE IF NOT EXISTS group_memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id INTEGER NOT NULL,
    group_id INTEGER NOT NULL,
    scope TEXT NOT NULL CHECK (scope IN ('group', 'member')),
    user_id INTEGER NOT NULL DEFAULT 0,
    category TEXT NOT NULL DEFAULT 'fact',
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (bot_id, group_id, scope, user_id, content)
);

CREATE INDEX IF NOT EXISTS idx_group_memories
    ON group_memories (bot_id, group_id, scope, user_id, updated_at, id);
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
        self._user_prompts: dict[str, str] = {}
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
        self._migrate_stickers_to_global()

    def _migrate_stickers_to_global(self) -> None:
        """把旧的按用户/群隔离的表情包合并到全局表情库。"""
        rows = self._conn.execute(
            "SELECT id, sha256, file_path, mime, description, tags, "
            "source, use_count, updated_at, last_used_at "
            "FROM stickers WHERE session_key <> ? ORDER BY id",
            (STICKER_LIBRARY_KEY,),
        ).fetchall()
        if not rows:
            return

        with self._conn:
            for (
                old_id,
                sha256,
                file_path,
                mime,
                description,
                tags,
                source,
                use_count,
                updated_at,
                last_used_at,
            ) in rows:
                existing = self._conn.execute(
                    "SELECT id, mime, description, tags, use_count, "
                    "updated_at, last_used_at FROM stickers "
                    "WHERE session_key = ? AND sha256 = ?",
                    (STICKER_LIBRARY_KEY, sha256),
                ).fetchone()
                if existing is None:
                    self._conn.execute(
                        "UPDATE stickers SET session_key = ? WHERE id = ?",
                        (STICKER_LIBRARY_KEY, old_id),
                    )
                    continue

                (
                    keep_id,
                    keep_mime,
                    keep_description,
                    keep_tags,
                    keep_use_count,
                    keep_updated_at,
                    keep_last_used_at,
                ) = existing
                merged_last_used = max(
                    filter(
                        None,
                        (keep_last_used_at, last_used_at),
                    ),
                    default=None,
                )
                self._conn.execute(
                    "UPDATE stickers SET mime = ?, description = ?, "
                    "tags = ?, source = ?, use_count = ?, updated_at = ?, "
                    "last_used_at = ? WHERE id = ?",
                    (
                        keep_mime or mime,
                        keep_description or description,
                        keep_tags or tags,
                        source,
                        int(keep_use_count) + int(use_count),
                        max(keep_updated_at, updated_at),
                        merged_last_used,
                        keep_id,
                    ),
                )
                self._conn.execute(
                    "DELETE FROM stickers WHERE id = ?",
                    (old_id,),
                )

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
        for session_key, content in self._conn.execute(
            "SELECT session_key, content FROM user_prompts"
        ):
            self._user_prompts[session_key] = content

    def lock(self, key: str) -> asyncio.Lock:
        """获取某个会话的锁，避免同一用户并发消息打乱上下文。"""
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    def build_messages(
        self,
        key: str,
        limit: int | None = None,
    ) -> list[ChatMessage]:
        """把最近的历史消息转换为 API 需要的 messages 列表。"""
        if limit is None:
            if self._max_turns == 0:
                return []
            limit = self._max_turns * 2
        if limit <= 0:
            return []
        messages = self._messages.get(key, [])
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

    def add_message(
        self,
        key: str,
        role: str,
        content: str,
        *,
        when: datetime | None = None,
    ) -> None:
        """追加一条单独的消息，用于群聊中未触发回复的消息。"""
        if role not in ("user", "assistant"):
            raise ValueError("role 必须是 user 或 assistant")

        moment = when or datetime.now(UTC)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC8)
        created_at = moment.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")

        with self._conn:
            self._conn.execute(
                "INSERT INTO messages "
                "(session_key, role, content, created_at) "
                "VALUES (?, ?, ?, ?)",
                (key, role, content, created_at),
            )
        self._messages.setdefault(key, []).append(
            {"role": role, "content": content}
        )

    def add_group_message(
        self,
        bot_id: int,
        group_id: int,
        role: str,
        content: str,
        *,
        sender_id: int | None = None,
        sender_name: str = "",
        when: datetime | None = None,
    ) -> int:
        """追加一条群聊消息，保留发送者 QQ 和昵称。"""
        if role not in ("user", "assistant"):
            raise ValueError("role 必须是 user 或 assistant")

        moment = when or datetime.now(UTC)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC8)
        created_at = moment.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")

        with self._conn:
            cursor = self._conn.execute(
                "INSERT INTO group_messages "
                "(bot_id, group_id, sender_id, sender_name, role, "
                "content, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    bot_id,
                    group_id,
                    sender_id,
                    sender_name,
                    role,
                    content,
                    created_at,
                ),
            )
        return int(cursor.lastrowid)

    def build_group_messages(
        self,
        bot_id: int,
        group_id: int,
        limit: int = 50,
    ) -> list[ChatMessage]:
        """加载群聊最近消息，并把发送者 QQ/昵称拼进 user 内容。"""
        if limit <= 0:
            return []
        rows = self._conn.execute(
            "SELECT role, sender_id, sender_name, content "
            "FROM group_messages "
            "WHERE bot_id = ? AND group_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (bot_id, group_id, limit),
        ).fetchall()

        messages: list[ChatMessage] = []
        for role, sender_id, sender_name, content in reversed(rows):
            if role == "user":
                name = sender_name or (
                    str(sender_id) if sender_id is not None else "未知成员"
                )
                label = (
                    f"{name}({sender_id})"
                    if sender_id is not None
                    else name
                )
                content = f"{label}：{content}"
            messages.append(
                cast(ChatMessage, {"role": role, "content": content})
            )
        return messages

    def clear_group_context(self, bot_id: int, group_id: int) -> None:
        with self._conn:
            self._conn.execute(
                "DELETE FROM group_messages "
                "WHERE bot_id = ? AND group_id = ?",
                (bot_id, group_id),
            )

    def get_summary(self, key: str) -> str:
        return self._summaries.get(key, "")

    def get_user_prompt(self, key: str) -> str:
        """返回当前用户自定义的 system 提示词，没有则为空字符串。"""
        return self._user_prompts.get(key, "")

    def set_user_prompt(self, key: str, content: str) -> None:
        """保存或覆盖某个私聊用户的自定义 system 提示词。"""
        content = content.strip()
        if not content:
            raise ValueError("自定义提示词不能为空")

        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        with self._conn:
            self._conn.execute(
                "INSERT INTO user_prompts (session_key, content, updated_at) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(session_key) DO UPDATE SET "
                "content = excluded.content, "
                "updated_at = excluded.updated_at",
                (key, content, now),
            )
        self._user_prompts[key] = content

    def clear_user_prompt(self, key: str) -> bool:
        """删除某个用户的自定义 system 提示词。"""
        with self._conn:
            cursor = self._conn.execute(
                "DELETE FROM user_prompts WHERE session_key = ?", (key,)
            )
        self._user_prompts.pop(key, None)
        return cursor.rowcount > 0

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

    def add_group_memory(
        self,
        bot_id: int,
        group_id: int,
        scope: str,
        content: str,
        *,
        user_id: int = 0,
        category: str = "fact",
    ) -> int:
        """保存群共享记忆或某个群成员的记忆。"""
        if scope not in ("group", "member"):
            raise ValueError("scope 必须是 group 或 member")
        if scope == "member" and not user_id:
            raise ValueError("成员记忆必须提供 user_id")
        if scope == "group":
            user_id = 0

        content = content.strip()
        if not content:
            raise ValueError("记忆内容不能为空")

        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        with self._conn:
            self._conn.execute(
                "INSERT INTO group_memories "
                "(bot_id, group_id, scope, user_id, category, content, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(bot_id, group_id, scope, user_id, content) "
                "DO UPDATE SET category = excluded.category, "
                "updated_at = excluded.updated_at",
                (
                    bot_id,
                    group_id,
                    scope,
                    user_id,
                    category,
                    content,
                    now,
                    now,
                ),
            )
            row = self._conn.execute(
                "SELECT id FROM group_memories "
                "WHERE bot_id = ? AND group_id = ? AND scope = ? "
                "AND user_id = ? AND content = ?",
                (bot_id, group_id, scope, user_id, content),
            ).fetchone()
        return int(row[0]) if row else 0

    def list_group_memories(
        self,
        bot_id: int,
        group_id: int,
        scope: str,
        *,
        user_id: int = 0,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 50))
        if scope == "group":
            user_id = 0
        rows = self._conn.execute(
            "SELECT id, category, content FROM group_memories "
            "WHERE bot_id = ? AND group_id = ? AND scope = ? "
            "AND user_id = ? "
            "ORDER BY updated_at DESC, id DESC LIMIT ?",
            (bot_id, group_id, scope, user_id, limit),
        ).fetchall()
        return [
            {"id": int(memory_id), "category": category, "content": content}
            for memory_id, category, content in rows
        ]

    def search_group_memories(
        self,
        bot_id: int,
        group_id: int,
        scope: str,
        *,
        user_id: int = 0,
        keyword: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 50))
        if scope == "group":
            user_id = 0
        clauses = [
            "bot_id = ?",
            "group_id = ?",
            "scope = ?",
            "user_id = ?",
        ]
        params: list[Any] = [bot_id, group_id, scope, user_id]
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
            "SELECT id, category, content FROM group_memories "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY updated_at DESC, id DESC LIMIT ?",
            params,
        ).fetchall()
        return [
            {"id": int(memory_id), "category": category, "content": content}
            for memory_id, category, content in rows
        ]

    def delete_group_memory(
        self,
        bot_id: int,
        group_id: int,
        scope: str,
        memory_id: int,
        *,
        user_id: int = 0,
    ) -> bool:
        if scope == "group":
            user_id = 0
        with self._conn:
            cursor = self._conn.execute(
                "DELETE FROM group_memories "
                "WHERE id = ? AND bot_id = ? AND group_id = ? "
                "AND scope = ? AND user_id = ?",
                (memory_id, bot_id, group_id, scope, user_id),
            )
        return cursor.rowcount > 0

    def add_sticker(
        self,
        key: str,
        sha256: str,
        file_path: str | Path,
        *,
        mime: str = "",
        description: str = "",
        tags: str = "",
        source: str = "user",
    ) -> dict[str, Any]:
        """保存表情包元数据；同一用户下相同哈希只保留一条。"""
        sha256 = sha256.strip()
        if not sha256:
            raise ValueError("表情包哈希不能为空")

        target = str(Path(file_path).expanduser())
        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        existing = self._conn.execute(
            "SELECT id FROM stickers WHERE session_key = ? AND sha256 = ?",
            (key, sha256),
        ).fetchone()

        with self._conn:
            self._conn.execute(
                """
                INSERT INTO stickers (
                    session_key, sha256, file_path, mime,
                    description, tags, source, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_key, sha256) DO UPDATE SET
                    file_path = excluded.file_path,
                    mime = CASE
                        WHEN excluded.mime <> '' THEN excluded.mime
                        ELSE stickers.mime
                    END,
                    description = CASE
                        WHEN excluded.description <> ''
                        THEN excluded.description
                        ELSE stickers.description
                    END,
                    tags = CASE
                        WHEN excluded.tags <> '' THEN excluded.tags
                        ELSE stickers.tags
                    END,
                    updated_at = excluded.updated_at
                """,
                (
                    key,
                    sha256,
                    target,
                    mime,
                    description.strip(),
                    tags.strip(),
                    source,
                    now,
                    now,
                ),
            )
            row = self._conn.execute(
                "SELECT id, description, tags FROM stickers "
                "WHERE session_key = ? AND sha256 = ?",
                (key, sha256),
            ).fetchone()

        sticker_id, saved_description, saved_tags = row
        return {
            "id": int(sticker_id),
            "sha256": sha256,
            "file_path": target,
            "mime": mime,
            "description": saved_description,
            "tags": saved_tags,
            "source": source,
            "created": existing is None,
        }

    def get_sticker(self, key: str, sticker_id: int) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT id, sha256, file_path, mime, description, tags, source, "
            "use_count, created_at, updated_at, last_used_at "
            "FROM stickers WHERE id = ? AND session_key = ?",
            (sticker_id, key),
        ).fetchone()
        if row is None:
            return None

        (
            found_id,
            sha256,
            file_path,
            mime,
            description,
            tags,
            source,
            use_count,
            created_at,
            updated_at,
            last_used_at,
        ) = row
        return {
            "id": int(found_id),
            "sha256": sha256,
            "file_path": file_path,
            "mime": mime,
            "description": description,
            "tags": tags,
            "source": source,
            "use_count": int(use_count),
            "created_at": created_at,
            "updated_at": updated_at,
            "last_used_at": last_used_at,
        }

    def search_stickers(
        self,
        key: str,
        keyword: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """按含义/标签关键词查询当前用户的表情包。"""
        limit = max(1, min(int(limit), 50))
        clauses = ["session_key = ?"]
        params: list[Any] = [key]

        if keyword:
            escaped = (
                keyword.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            clauses.append(
                "(description LIKE ? ESCAPE '\\' "
                "OR tags LIKE ? ESCAPE '\\')"
            )
            params.extend([f"%{escaped}%", f"%{escaped}%"])

        params.append(limit)
        rows = self._conn.execute(
            "SELECT id, sha256, file_path, mime, description, tags, "
            "use_count, updated_at "
            f"FROM stickers WHERE {' AND '.join(clauses)} "
            "ORDER BY use_count DESC, updated_at DESC, id DESC LIMIT ?",
            params,
        ).fetchall()
        return [
            {
                "id": int(sticker_id),
                "sha256": sha256,
                "file_path": file_path,
                "mime": mime,
                "description": description,
                "tags": tags,
                "use_count": int(use_count),
                "updated_at": updated_at,
            }
            for (
                sticker_id,
                sha256,
                file_path,
                mime,
                description,
                tags,
                use_count,
                updated_at,
            ) in rows
        ]

    def update_sticker_description(
        self,
        key: str,
        sticker_id: int,
        description: str,
        tags: str | None = None,
    ) -> bool:
        """记录或更新表情包的含义；``tags`` 为 ``None`` 时保留原标签。"""
        description = description.strip()
        if not description:
            raise ValueError("表情包含义不能为空")

        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        assignments = ["description = ?", "updated_at = ?"]
        params: list[Any] = [description, now]
        if tags is not None:
            assignments.append("tags = ?")
            params.append(tags.strip())
        params.extend([sticker_id, key])

        with self._conn:
            cursor = self._conn.execute(
                f"UPDATE stickers SET {', '.join(assignments)} "
                "WHERE id = ? AND session_key = ?",
                params,
            )
        return cursor.rowcount > 0

    def record_sticker_used(self, key: str, sticker_id: int) -> bool:
        """记录一次表情包发送，用于后续按使用频率排序。"""
        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        with self._conn:
            cursor = self._conn.execute(
                "UPDATE stickers SET use_count = use_count + 1, "
                "last_used_at = ?, updated_at = ? "
                "WHERE id = ? AND session_key = ?",
                (now, now, sticker_id, key),
            )
        return cursor.rowcount > 0

    def delete_sticker(self, key: str, sticker_id: int) -> bool:
        with self._conn:
            cursor = self._conn.execute(
                "DELETE FROM stickers WHERE id = ? AND session_key = ?",
                (sticker_id, key),
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

    def clear_context(self, key: str) -> None:
        """清空对话上下文：消息、摘要和长期记忆，保留自定义提示词。"""
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

    def clear(self, key: str) -> None:
        self.clear_context(key)
        with self._conn:
            self._conn.execute(
                "DELETE FROM user_prompts WHERE session_key = ?", (key,)
            )
        self._user_prompts.pop(key, None)

    def close(self) -> None:
        self._conn.close()
