import sqlite3

import pytest


class FakeClient:
    configured = True

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.requests: list[list[dict]] = []
        self.calls: list[dict] = []

    async def chat(self, messages, **kwargs) -> str:
        self.requests.append([dict(message) for message in messages])
        self.calls.append(kwargs)
        if not self.replies:
            raise AssertionError("没有可用的假回复")
        return self.replies.pop(0)

    async def chat_with_tools(self, messages, **kwargs) -> str:
        return await self.chat(messages, **kwargs)


@pytest.fixture(autouse=True)
def clear_group_compression_state():
    from nonebot_plugin_aichat_deepseek import chat

    chat._GROUP_LAST_SYSTEM.clear()
    chat._GROUP_LAST_PROMPT_TOKENS.clear()
    chat._GROUP_LAST_HISTORY_COUNT.clear()
    chat._GROUP_LAST_TOOLS.clear()
    yield
    chat._GROUP_LAST_SYSTEM.clear()
    chat._GROUP_LAST_PROMPT_TOKENS.clear()
    chat._GROUP_LAST_HISTORY_COUNT.clear()
    chat._GROUP_LAST_TOOLS.clear()


def add_messages(store, count: int, *, group_id: int = 123) -> list[int]:
    return [
        store.add_group_message(
            1,
            group_id,
            "user",
            f"消息{index}",
            sender_id=index,
            sender_name=f"成员{index}",
        )
        for index in range(count)
    ]


def test_token_helpers() -> None:
    from nonebot_plugin_aichat_deepseek.tokens import (
        estimate_tokens,
        truncate_to_tokens,
    )

    assert estimate_tokens("") == 0
    assert estimate_tokens("你好") == 2
    assert estimate_tokens("hello") <= 3
    assert estimate_tokens(truncate_to_tokens("中" * 50, 10)) <= 10
    assert truncate_to_tokens("中" * 50, 10).endswith("…")


def test_group_messages_exclude_compressed(store_cls) -> None:
    store = store_cls()
    ids = add_messages(store, 3)

    store.mark_group_messages_compressed(ids[:2])

    assert store.count_uncompressed_group_messages(1, 123) == 1
    assert store.build_group_messages(1, 123) == [
        {"role": "user", "content": "成员2(2)：消息2"}
    ]
    batch = store.get_group_compression_batch(1, 123, 10)
    assert [message["content"] for _, message in batch] == [
        "成员2(2)：消息2"
    ]
    store.close()


def test_group_summaries_merge_keeps_order(store_cls) -> None:
    store = store_cls()
    first = store.add_group_summary(1, 123, "摘要A", token_count=3)
    second = store.add_group_summary(1, 123, "摘要B", token_count=3)
    store.add_group_summary(1, 123, "摘要C", token_count=3)

    assert store.merge_group_summaries(
        1, 123, [first, second], "合并AB", token_count=2
    )

    chunks = store.list_group_summaries(1, 123)
    assert [chunk["content"] for chunk in chunks] == ["合并AB", "摘要C"]
    assert chunks[0]["token_count"] == 2
    store.close()


def test_group_summary_is_injected_into_system(
    monkeypatch, store_cls
) -> None:
    from nonebot_plugin_aichat_deepseek import chat

    store = store_cls()
    store.add_group_summary(1, 123, "群里周五开黑")
    store.add_group_memory(1, 123, "group", "群共享记忆")
    store.add_group_memory(1, 123, "member", "成员记忆", user_id=2)
    monkeypatch.setattr(chat, "store", store)

    messages = chat._build_group_request_messages(1, 123, 2, "小明", None)

    system = messages[0]["content"]
    assert "【群聊历史摘要】" in system
    assert "群里周五开黑" in system
    assert "【群聊记忆】" in system
    assert "【当前成员记忆：小明(2)】" in system
    assert system.index("【群聊历史摘要】") < system.index("【群聊记忆】")
    assert system.index("【群聊记忆】") < system.index("【当前成员记忆")
    store.close()


async def test_primary_compression_reuses_prefix_and_batch_limit(
    monkeypatch, store_cls
) -> None:
    from nonebot_plugin_aichat_deepseek import chat
    from nonebot_plugin_aichat_deepseek.config import plugin_config

    store = store_cls()
    add_messages(store, 5)
    fake = FakeClient("压缩后的摘要")
    system = {"role": "system", "content": "同一份 system"}
    session_key = "group:1:123"

    monkeypatch.setattr(chat, "store", store)
    monkeypatch.setattr(chat, "client", fake)
    monkeypatch.setattr(
        plugin_config, "deepseek_group_compression_batch_messages", 3
    )
    monkeypatch.setattr(
        plugin_config, "deepseek_group_compression_trigger_tokens", 10**9
    )
    monkeypatch.setattr(
        plugin_config, "deepseek_group_compression_summary_max_tokens", 1234
    )

    chat._GROUP_LAST_SYSTEM[session_key] = system
    chat._GROUP_LAST_HISTORY_COUNT[session_key] = 5
    chat._GROUP_LAST_PROMPT_TOKENS[session_key] = 100
    tools = [{"type": "function", "function": {"name": "web_search"}}]
    chat._GROUP_LAST_TOOLS[session_key] = tools

    assert await chat.compress_group_if_needed(1, 123, session_key)

    assert len(fake.requests) == 1
    request = fake.requests[0]
    assert request[0] == system
    assert [message["content"] for message in request[1:6]] == [
        "成员0(0)：消息0",
        "成员1(1)：消息1",
        "成员2(2)：消息2",
        "成员3(3)：消息3",
        "成员4(4)：消息4",
    ]
    assert request[-1]["role"] == "user"
    assert "压缩任务" in request[-1]["content"]
    assert "从第一条开始的 3 条" in request[-1]["content"]
    assert fake.calls[0]["max_tokens"] == 1234
    assert fake.calls[0]["tools"] == tools
    assert fake.calls[0]["tool_choice"] == "none"

    assert store.count_uncompressed_group_messages(1, 123) == 2
    chunks = store.list_group_summaries(1, 123)
    assert [chunk["content"] for chunk in chunks] == ["压缩后的摘要"]
    store.close()


async def test_compression_skipped_below_thresholds(
    monkeypatch, store_cls
) -> None:
    from nonebot_plugin_aichat_deepseek import chat
    from nonebot_plugin_aichat_deepseek.config import plugin_config

    store = store_cls()
    add_messages(store, 2)
    fake = FakeClient()
    session_key = "group:1:123"

    monkeypatch.setattr(chat, "store", store)
    monkeypatch.setattr(chat, "client", fake)
    monkeypatch.setattr(
        plugin_config, "deepseek_group_compression_batch_messages", 200
    )
    monkeypatch.setattr(
        plugin_config, "deepseek_group_compression_trigger_tokens", 1000
    )

    chat._GROUP_LAST_SYSTEM[session_key] = {
        "role": "system",
        "content": "system",
    }
    chat._GROUP_LAST_PROMPT_TOKENS[session_key] = 999

    assert not await chat.compress_group_if_needed(1, 123, session_key)
    assert fake.requests == []
    store.close()


async def test_token_trigger_merges_part_of_summaries(
    monkeypatch, store_cls
) -> None:
    from nonebot_plugin_aichat_deepseek import chat
    from nonebot_plugin_aichat_deepseek.config import plugin_config

    store = store_cls()
    add_messages(store, 2)
    store.add_group_summary(1, 123, "摘要A")
    store.add_group_summary(1, 123, "摘要B")
    store.add_group_summary(1, 123, "摘要C")
    fake = FakeClient("合并后的摘要")
    system = {
        "role": "system",
        "content": (
            "【群聊历史摘要】\n"
            "[摘要 1]\n摘要A\n\n[摘要 2]\n摘要B\n\n[摘要 3]\n摘要C"
        ),
    }
    session_key = "group:1:123"

    monkeypatch.setattr(chat, "store", store)
    monkeypatch.setattr(chat, "client", fake)
    monkeypatch.setattr(
        plugin_config, "deepseek_group_compression_batch_messages", 200
    )
    monkeypatch.setattr(
        plugin_config, "deepseek_group_compression_trigger_tokens", 1000
    )
    monkeypatch.setattr(
        plugin_config, "deepseek_group_compression_merge_summaries", 2
    )
    monkeypatch.setattr(
        plugin_config, "deepseek_group_compression_summary_max_tokens", 2048
    )

    chat._GROUP_LAST_SYSTEM[session_key] = system
    chat._GROUP_LAST_HISTORY_COUNT[session_key] = 2
    chat._GROUP_LAST_PROMPT_TOKENS[session_key] = 2000

    assert await chat.compress_group_if_needed(1, 123, session_key)

    assert len(fake.requests) == 1
    request = fake.requests[0]
    assert request[0] == system
    assert [message["content"] for message in request[1:3]] == [
        "成员0(0)：消息0",
        "成员1(1)：消息1",
    ]
    assert len(request) == 4
    assert "[摘要 1]" in request[-1]["content"]
    assert "[摘要 2]" in request[-1]["content"]
    assert fake.calls[0]["max_tokens"] == 2048

    chunks = store.list_group_summaries(1, 123)
    assert [chunk["content"] for chunk in chunks] == [
        "合并后的摘要",
        "摘要C",
    ]
    assert store.count_uncompressed_group_messages(1, 123) == 2
    store.close()


async def test_group_reply_compresses_after_sending_and_keeps_prefix(
    monkeypatch, store_cls
) -> None:
    from nonebot_plugin_aichat_deepseek import chat
    from nonebot_plugin_aichat_deepseek.config import plugin_config
    from tests.test_group import make_group_event

    store = store_cls()
    add_messages(store, 2)
    fake = FakeClient("群回复", "新摘要")

    monkeypatch.setattr(chat, "store", store)
    monkeypatch.setattr(chat, "client", fake)
    monkeypatch.setattr(
        plugin_config, "deepseek_group_compression_batch_messages", 3
    )
    monkeypatch.setattr(
        plugin_config, "deepseek_group_compression_trigger_tokens", 10**9
    )
    monkeypatch.setattr(
        plugin_config, "deepseek_group_compression_summary_max_tokens", 2048
    )
    monkeypatch.setattr(plugin_config, "deepseek_reply_interval", 0.0)
    monkeypatch.setattr(
        plugin_config, "deepseek_reply_interval_jitter", 0.0
    )
    monkeypatch.setattr(plugin_config, "deepseek_reply_delay", 0.0)
    monkeypatch.setattr(plugin_config, "deepseek_reply_delay_jitter", 0.0)

    sent: list[str] = []

    async def send(message: str) -> None:
        sent.append(message)

    await chat.process_group_message(
        make_group_event("当前问题", to_me=True), send
    )

    assert sent == ["群回复"]
    assert len(fake.requests) == 2

    reply_request, compression_request = fake.requests
    # 压缩请求原样重放回复请求的 system 和全部历史消息，保证前缀一致。
    assert compression_request[0] == reply_request[0]
    assert compression_request[1:4] == reply_request[1:4]
    assert len(compression_request) == len(reply_request) + 1

    assert store.count_uncompressed_group_messages(1, 123) == 1
    chunks = store.list_group_summaries(1, 123)
    assert [chunk["content"] for chunk in chunks] == ["新摘要"]

    # 下一轮请求会带上摘要，且不再包含已压缩的旧消息。
    refresh = chat._build_group_request_messages(1, 123, 2, "小明")
    assert "【群聊历史摘要】" in refresh[0]["content"]
    assert "新摘要" in refresh[0]["content"]
    assert len(refresh) == 2  # system + 当前未压缩消息
    store.close()


def test_old_group_table_is_migrated(store_cls, tmp_path) -> None:
    db_path = tmp_path / "chat.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE group_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_id INTEGER NOT NULL,
                group_id INTEGER NOT NULL,
                sender_id INTEGER,
                sender_name TEXT NOT NULL DEFAULT '',
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            "INSERT INTO group_messages "
            "(bot_id, group_id, sender_id, sender_name, role, content) "
            "VALUES (1, 123, 2, '小明', 'user', '旧消息')"
        )

    store = store_cls(db_path)
    assert store.build_group_messages(1, 123) == [
        {"role": "user", "content": "小明(2)：旧消息"}
    ]

    with sqlite3.connect(db_path) as conn:
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(group_messages)")
        }
        compressed = conn.execute(
            "SELECT compressed FROM group_messages"
        ).fetchone()[0]
    assert "compressed" in columns
    assert compressed == 0
    store.close()
