import json
import time
from typing import Any

import pytest


class FakeBot:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_api(self, api: str, **kwargs: Any):
        self.calls.append((api, kwargs))
        if self.fail:
            raise RuntimeError("平台不允许撤回")
        return {"message_id": kwargs.get("message_id")}


@pytest.fixture(autouse=True)
def clear_sent_messages():
    from nonebot_plugin_aichat_deepseek import sent_messages

    sent_messages.clear()
    yield
    sent_messages.clear()


def test_extract_message_id() -> None:
    from nonebot_plugin_aichat_deepseek.sent_messages import (
        extract_message_id,
    )

    class Result:
        message_id = "9"

    assert extract_message_id({"message_id": 1}) == 1
    assert extract_message_id({"message_id": "2"}) == 2
    assert extract_message_id(3) == 3
    assert extract_message_id(Result()) == 9
    assert extract_message_id(None) is None
    assert extract_message_id({"message_id": "bad"}) is None


def test_record_recent_remove_and_replace() -> None:
    from nonebot_plugin_aichat_deepseek import sent_messages

    sent_messages.record("1:2", 10, "第一条")
    sent_messages.record("1:2", 11, "第二条")
    sent_messages.record("1:2", 12, "第三条")

    assert [item.message_id for item in sent_messages.recent("1:2", 2)] == [
        11,
        12,
    ]

    sent_messages.record("1:2", 11, "替换后的第二条")
    assert [item.message_id for item in sent_messages.recent("1:2", 3)] == [
        10,
        12,
        11,
    ]
    assert sent_messages.recent("1:2", 1)[0].content == "替换后的第二条"

    sent_messages.remove("1:2", 11)
    assert [item.message_id for item in sent_messages.recent("1:2", 3)] == [
        10,
        12,
    ]


def test_message_expires_after_two_minutes() -> None:
    from nonebot_plugin_aichat_deepseek import sent_messages

    now = time.monotonic()
    sent_messages.record("1:2", 10, "超过两分钟", when=now - 121)
    assert sent_messages.recent("1:2") == []

    sent_messages.record("1:2", 11, "两分钟内", when=now - 119)
    assert [item.message_id for item in sent_messages.recent("1:2")] == [11]


async def test_recall_last_message_private(store_cls) -> None:
    from nonebot_plugin_aichat_deepseek import sent_messages
    from nonebot_plugin_aichat_deepseek.tools.base import ToolContext
    from nonebot_plugin_aichat_deepseek.tools.recall_message import execute

    store = store_cls()
    bot = FakeBot()
    sent_messages.record("1:2", 41, "第一条")
    sent_messages.record("1:2", 42, "第二条")
    ctx = ToolContext(
        session_key="1:2",
        store=store,
        get_bot=lambda bot_id: bot,
        chat_type="private",
    )

    result = json.loads(await execute({"count": 1}, ctx))

    assert bot.calls == [("delete_msg", {"message_id": 42})]
    assert result["recalled"][0]["message_id"] == 42
    assert [item.message_id for item in sent_messages.recent("1:2")] == [41]
    store.close()


async def test_recall_multiple_in_group(store_cls) -> None:
    from nonebot_plugin_aichat_deepseek import sent_messages
    from nonebot_plugin_aichat_deepseek.tools.base import ToolContext
    from nonebot_plugin_aichat_deepseek.tools.recall_message import execute

    store = store_cls()
    bot = FakeBot()
    sent_messages.record("group:1:10", 51, "群消息1")
    sent_messages.record("group:1:10", 52, "群消息2")
    ctx = ToolContext(
        session_key="group:1:10",
        store=store,
        get_bot=lambda bot_id: bot,
        chat_type="group",
        bot_id=1,
        group_id=10,
    )

    result = json.loads(await execute({"count": 2}, ctx))

    assert [call[1]["message_id"] for call in bot.calls] == [52, 51]
    assert len(result["recalled"]) == 2
    assert sent_messages.recent("group:1:10") == []
    store.close()


async def test_recall_by_content_keyword(store_cls) -> None:
    from nonebot_plugin_aichat_deepseek import sent_messages
    from nonebot_plugin_aichat_deepseek.tools.base import ToolContext
    from nonebot_plugin_aichat_deepseek.tools.recall_message import execute

    store = store_cls()
    bot = FakeBot()
    sent_messages.record("1:2", 71, "抱歉，我说错了")
    sent_messages.record("1:2", 72, "稍等一下")
    sent_messages.record("1:2", 73, "抱歉，再补一句")
    ctx = ToolContext(
        session_key="1:2",
        store=store,
        get_bot=lambda bot_id: bot,
        chat_type="private",
    )

    result = json.loads(
        await execute({"keyword": "抱歉", "count": 1}, ctx)
    )

    assert [call[1]["message_id"] for call in bot.calls] == [73]
    assert result["keyword"] == "抱歉"
    assert [item.message_id for item in sent_messages.recent("1:2", 5)] == [
        71,
        72,
    ]
    store.close()


async def test_recall_by_keyword_multiple_matches(store_cls) -> None:
    from nonebot_plugin_aichat_deepseek import sent_messages
    from nonebot_plugin_aichat_deepseek.tools.base import ToolContext
    from nonebot_plugin_aichat_deepseek.tools.recall_message import execute

    store = store_cls()
    bot = FakeBot()
    sent_messages.record("1:2", 74, "Sorry，第一条")
    sent_messages.record("1:2", 75, "无关消息")
    sent_messages.record("1:2", 76, "sorry，第二条")
    ctx = ToolContext(
        session_key="1:2",
        store=store,
        get_bot=lambda bot_id: bot,
        chat_type="private",
    )

    result = json.loads(
        await execute({"keyword": "SORRY", "count": 2}, ctx)
    )

    assert [call[1]["message_id"] for call in bot.calls] == [76, 74]
    assert len(result["recalled"]) == 2
    assert [item.message_id for item in sent_messages.recent("1:2", 5)] == [
        75
    ]
    store.close()


async def test_recall_by_keyword_without_match(store_cls) -> None:
    from nonebot_plugin_aichat_deepseek import sent_messages
    from nonebot_plugin_aichat_deepseek.tools.base import ToolContext
    from nonebot_plugin_aichat_deepseek.tools.recall_message import execute

    store = store_cls()
    sent_messages.record("1:2", 77, "正常内容")
    ctx = ToolContext(
        session_key="1:2",
        store=store,
        get_bot=lambda bot_id: FakeBot(),
        chat_type="private",
    )

    result = await execute({"keyword": "不存在"}, ctx)

    assert "没有找到包含“不存在”" in result
    assert [item.message_id for item in sent_messages.recent("1:2")] == [77]
    store.close()


async def test_recall_keyword_must_be_string(store_cls) -> None:
    from nonebot_plugin_aichat_deepseek.tools.base import ToolContext
    from nonebot_plugin_aichat_deepseek.tools.recall_message import execute

    store = store_cls()
    ctx = ToolContext(
        session_key="1:2",
        store=store,
        get_bot=lambda bot_id: FakeBot(),
        chat_type="private",
    )

    result = await execute({"keyword": 1}, ctx)

    assert "keyword 必须是字符串" in result
    store.close()


async def test_recall_failure_keeps_record(store_cls) -> None:
    from nonebot_plugin_aichat_deepseek import sent_messages
    from nonebot_plugin_aichat_deepseek.tools.base import ToolContext
    from nonebot_plugin_aichat_deepseek.tools.recall_message import execute

    store = store_cls()
    bot = FakeBot(fail=True)
    sent_messages.record("1:2", 61, "撤回不了的消息")
    ctx = ToolContext(
        session_key="1:2",
        store=store,
        get_bot=lambda bot_id: bot,
        chat_type="private",
    )

    result = await execute({}, ctx)

    assert "撤回失败" in result
    assert [item.message_id for item in sent_messages.recent("1:2")] == [61]
    store.close()


async def test_recall_without_records(store_cls) -> None:
    from nonebot_plugin_aichat_deepseek.tools.base import ToolContext
    from nonebot_plugin_aichat_deepseek.tools.recall_message import execute

    store = store_cls()
    ctx = ToolContext(
        session_key="1:2",
        store=store,
        get_bot=lambda bot_id: FakeBot(),
        chat_type="private",
    )

    result = await execute({"count": 1}, ctx)

    assert "没有可撤回" in result
    store.close()


async def test_reply_records_sent_message_ids(
    monkeypatch, store_cls
) -> None:
    from nonebot_plugin_aichat_deepseek import chat, sent_messages
    from nonebot_plugin_aichat_deepseek.config import plugin_config

    class FakeClient:
        configured = True

        async def chat(self, messages, **kwargs) -> str:
            return "回答"

        async def chat_with_tools(self, messages, **kwargs) -> str:
            return "回答"

    store = store_cls()
    store.clear("1:2")
    monkeypatch.setattr(chat, "client", FakeClient())
    monkeypatch.setattr(chat, "store", store)
    monkeypatch.setattr(plugin_config, "deepseek_reply_delay", 0.0)
    monkeypatch.setattr(plugin_config, "deepseek_reply_delay_jitter", 0.0)
    monkeypatch.setattr(plugin_config, "deepseek_reply_interval", 0.0)
    monkeypatch.setattr(
        plugin_config, "deepseek_reply_interval_jitter", 0.0
    )

    sent: list[str] = []

    async def send(message: str):
        sent.append(message)
        return {"message_id": 42}

    await chat.reply("1:2", "你好", send)

    assert sent == ["回答"]
    assert sent_messages.recent("1:2", 1)[0].message_id == 42
    store.close()
