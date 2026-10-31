from typing import Any

import pytest


class FakeClient:
    configured = True

    def __init__(self, *replies: str, error: Exception | None = None) -> None:
        self.replies = list(replies)
        self.error = error
        self.requests: list[list[dict[str, str]]] = []

    async def chat(
        self, messages: list[dict[str, str]], **kwargs: Any
    ) -> str:
        self.requests.append(list(messages))
        if self.error is not None:
            raise self.error
        return self.replies.pop(0)

    async def chat_with_tools(self, messages, **kwargs: Any) -> str:
        return await self.chat(messages)


def make_private_event(text: str, *, self_id: int = 1, user_id: int = 2):
    from nonebot.adapters.onebot.v11 import Message
    from nonebot.adapters.onebot.v11.event import PrivateMessageEvent, Sender

    return PrivateMessageEvent(
        time=0,
        self_id=self_id,
        post_type="message",
        sub_type="friend",
        user_id=user_id,
        message_type="private",
        message_id=1,
        message=Message(text),
        original_message=Message(text),
        raw_message=text,
        font=0,
        sender=Sender(user_id=user_id),
        to_me=True,
    )


def make_image_event(*segments, self_id: int = 1, user_id: int = 2):
    from nonebot.adapters.onebot.v11 import Message
    from nonebot.adapters.onebot.v11.event import PrivateMessageEvent, Sender

    message = Message(segments)
    return PrivateMessageEvent(
        time=0,
        self_id=self_id,
        post_type="message",
        sub_type="friend",
        user_id=user_id,
        message_type="private",
        message_id=1,
        message=message,
        original_message=message,
        raw_message="[CQ:image]",
        font=0,
        sender=Sender(user_id=user_id),
        to_me=True,
    )


async def test_reply_keeps_context(monkeypatch: pytest.MonkeyPatch) -> None:
    from nonebot_plugin_aichat_deepseek import chat as chat_module

    fake = FakeClient("第一轮回复", "第二轮回复")
    monkeypatch.setattr(chat_module, "client", fake)
    chat_module.store.clear("1:2")

    sent: list[str] = []

    async def send(message: str) -> None:
        sent.append(message)

    await chat_module.reply("1:2", "你好", send)
    await chat_module.reply("1:2", "继续", send)

    assert sent == ["第一轮回复", "第二轮回复"]
    assert len(fake.requests) == 2

    first = fake.requests[0]
    assert first[0]["role"] == "system"
    assert first[1] == {"role": "user", "content": "你好"}

    second = fake.requests[1]
    assert second[-1] == {"role": "user", "content": "继续"}
    assert second[-3:] == [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "第一轮回复"},
        {"role": "user", "content": "继续"},
    ]


async def test_reply_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from nonebot_plugin_aichat_deepseek import chat as chat_module

    fake = FakeClient("不会用到")
    fake.configured = False
    monkeypatch.setattr(chat_module, "client", fake)

    sent: list[str] = []

    async def send(message: str) -> None:
        sent.append(message)

    await chat_module.reply("1:2", "你好", send)

    assert sent == [chat_module.MISSING_API_KEY_TIP]
    assert fake.requests == []


async def test_reply_reports_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from nonebot_plugin_aichat_deepseek import chat as chat_module
    from nonebot_plugin_aichat_deepseek.data_source import DeepSeekError

    fake = FakeClient(error=DeepSeekError("bad key", status_code=401))
    monkeypatch.setattr(chat_module, "client", fake)
    chat_module.store.clear("1:2")

    sent: list[str] = []

    async def send(message: str) -> None:
        sent.append(message)

    await chat_module.reply("1:2", "你好", send)

    assert sent == ["DeepSeek API Key 无效，请检查 DEEPSEEK_API_KEY。"]
    assert chat_module.store.build_messages("1:2") == []


async def test_failed_turn_is_not_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    from nonebot_plugin_aichat_deepseek import chat as chat_module
    from nonebot_plugin_aichat_deepseek.data_source import DeepSeekError

    fake = FakeClient(error=DeepSeekError("boom"))
    monkeypatch.setattr(chat_module, "client", fake)
    chat_module.store.clear("1:2")

    async def send(message: str) -> None:
        pass

    await chat_module.reply("1:2", "失败的一轮", send)
    assert chat_module.store.build_messages("1:2") == []

    fake.error = None
    fake.replies.append("成功")
    await chat_module.reply("1:2", "新的一轮", send)

    last_request = fake.requests[-1]
    assert all(
        message["content"] != "失败的一轮" for message in last_request
    )


async def test_long_reply_is_split(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nonebot_plugin_aichat_deepseek import chat as chat_module
    from nonebot_plugin_aichat_deepseek.config import plugin_config

    answer = "x" * 25
    fake = FakeClient(answer)
    monkeypatch.setattr(chat_module, "client", fake)
    monkeypatch.setattr(plugin_config, "deepseek_reply_max_length", 10)
    monkeypatch.setattr(plugin_config, "deepseek_reply_interval", 0.0)
    monkeypatch.setattr(plugin_config, "deepseek_reply_interval_jitter", 0.0)
    chat_module.store.clear("1:2")

    sent: list[str] = []

    async def send(message: str) -> None:
        sent.append(message)

    await chat_module.reply("1:2", "你好", send)

    assert len(sent) == 3
    assert all(len(chunk) <= 10 for chunk in sent)
    assert "".join(sent) == answer


async def test_reply_splits_on_delimiter_with_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nonebot_plugin_aichat_deepseek import chat as chat_module
    from nonebot_plugin_aichat_deepseek.config import plugin_config

    fake = FakeClient("第一句|||第二句|||第三句")
    monkeypatch.setattr(chat_module, "client", fake)
    monkeypatch.setattr(plugin_config, "deepseek_reply_interval", 0.0)
    monkeypatch.setattr(plugin_config, "deepseek_reply_interval_jitter", 0.0)
    monkeypatch.setattr(chat_module, "next_reply_interval", lambda: 0.5)
    chat_module.store.clear("1:2")

    sent: list[str] = []
    sleeps: list[float] = []

    async def send(message: str) -> None:
        sent.append(message)

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(chat_module.asyncio, "sleep", fake_sleep)

    await chat_module.reply("1:2", "你好", send)

    assert sent == ["第一句", "第二句", "第三句"]
    assert sleeps == [0.5, 0.5]


async def test_reply_splits_paragraphs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nonebot_plugin_aichat_deepseek import chat as chat_module
    from nonebot_plugin_aichat_deepseek.config import plugin_config

    fake = FakeClient("第一段\n\n第二段\n\n第三段")
    monkeypatch.setattr(chat_module, "client", fake)
    monkeypatch.setattr(plugin_config, "deepseek_reply_interval", 0.0)
    monkeypatch.setattr(plugin_config, "deepseek_reply_interval_jitter", 0.0)
    monkeypatch.setattr(plugin_config, "deepseek_split_paragraphs", True)
    chat_module.store.clear("1:2")

    sent: list[str] = []

    async def send(message: str) -> None:
        sent.append(message)

    await chat_module.reply("1:2", "你好", send)

    assert sent == ["第一段", "第二段", "第三段"]


async def test_reply_removes_markdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nonebot_plugin_aichat_deepseek import chat as chat_module
    from nonebot_plugin_aichat_deepseek.config import plugin_config

    fake = FakeClient("**你好**|||# 标题|||`代码`")
    monkeypatch.setattr(chat_module, "client", fake)
    monkeypatch.setattr(plugin_config, "deepseek_reply_interval", 0.0)
    monkeypatch.setattr(plugin_config, "deepseek_reply_interval_jitter", 0.0)
    chat_module.store.clear("1:2")

    sent: list[str] = []

    async def send(message: str) -> None:
        sent.append(message)

    await chat_module.reply("1:2", "你好", send)

    assert sent == ["你好", "标题", "代码"]


async def test_empty_reply_gets_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nonebot_plugin_aichat_deepseek import chat as chat_module

    fake = FakeClient("|||")
    monkeypatch.setattr(chat_module, "client", fake)
    chat_module.store.clear("1:2")

    sent: list[str] = []

    async def send(message: str) -> None:
        sent.append(message)

    await chat_module.reply("1:2", "你好", send)

    assert sent == [chat_module.EMPTY_REPLY_TIP]


def test_next_reply_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    from nonebot_plugin_aichat_deepseek import chat as chat_module
    from nonebot_plugin_aichat_deepseek.config import plugin_config

    monkeypatch.setattr(plugin_config, "deepseek_reply_interval", 0.0)
    monkeypatch.setattr(plugin_config, "deepseek_reply_interval_jitter", 0.0)
    assert chat_module.next_reply_interval() == 0.0

    monkeypatch.setattr(plugin_config, "deepseek_reply_interval", 1.0)
    assert chat_module.next_reply_interval() == 1.0

    monkeypatch.setattr(plugin_config, "deepseek_reply_interval_jitter", 0.2)
    for _ in range(20):
        assert 0.8 <= chat_module.next_reply_interval() <= 1.2


def test_next_initial_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    from nonebot_plugin_aichat_deepseek import chat as chat_module
    from nonebot_plugin_aichat_deepseek.config import plugin_config

    monkeypatch.setattr(plugin_config, "deepseek_reply_delay", 0.0)
    monkeypatch.setattr(plugin_config, "deepseek_reply_delay_jitter", 0.0)
    assert chat_module.next_initial_delay() == 0.0

    monkeypatch.setattr(plugin_config, "deepseek_reply_delay", 1.0)
    assert chat_module.next_initial_delay() == 1.0

    monkeypatch.setattr(plugin_config, "deepseek_reply_delay_jitter", 0.3)
    for _ in range(20):
        assert 0.7 <= chat_module.next_initial_delay() <= 1.3


def test_usage_helpers() -> None:
    from nonebot_plugin_aichat_deepseek import chat as chat_module

    usage = {
        "prompt_tokens": 100,
        "completion_tokens": 10,
        "prompt_cache_hit_tokens": 40,
        "prompt_cache_miss_tokens": 60,
        "prompt_tokens_details": {"cached_tokens": 40},
    }
    assert chat_module._usage_numbers(usage) == (40, 60, 100, 10)

    total: dict[str, int] = {}
    chat_module._merge_usage(total, usage)
    assert total == {
        "calls": 1,
        "cache_hit": 40,
        "cache_miss": 60,
        "prompt_tokens": 100,
        "completion_tokens": 10,
    }


async def test_completeness_check(monkeypatch: pytest.MonkeyPatch) -> None:
    from nonebot_plugin_aichat_deepseek import chat as chat_module

    class CompleteClient:
        configured = True

        def __init__(self, answer: str) -> None:
            self.answer = answer

        async def chat(self, messages, **kwargs) -> str:
            return self.answer

    monkeypatch.setattr(
        chat_module, "client", CompleteClient("INCOMPLETE")
    )
    assert (
        await chat_module._is_message_complete("1:2", "我想问", [])
        is False
    )

    monkeypatch.setattr(chat_module, "client", CompleteClient("COMPLETE"))
    assert (
        await chat_module._is_message_complete("1:2", "你好", [])
        is True
    )

    assert (
        await chat_module._is_message_complete(
            "1:2", "看看这张图", [{"url": "a.png"}]
        )
        is True
    )


async def test_process_private_message_uses_aggregator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nonebot_plugin_aichat_deepseek import chat as chat_module
    from nonebot_plugin_aichat_deepseek.aggregator import MessageAggregator
    from nonebot_plugin_aichat_deepseek.config import plugin_config

    completed: list[str] = []

    async def is_complete(key, text, images) -> bool:
        return True

    async def handle(key, text, images, send) -> None:
        completed.append(text)

    aggregator = MessageAggregator(
        debounce_seconds=0.01,
        debounce_jitter=0,
        is_complete=is_complete,
        handler=handle,
    )
    monkeypatch.setattr(chat_module, "message_aggregator", aggregator)
    monkeypatch.setattr(
        plugin_config, "deepseek_aggregate_messages", True
    )

    async def send(message: str) -> None:
        pass

    await chat_module.process_private_message(
        make_private_event("你"),
        send,
    )
    await chat_module.process_private_message(
        make_private_event("好"),
        send,
    )
    import asyncio

    await asyncio.sleep(0.05)

    assert completed == ["你\n好"]


def test_system_prompt_contains_output_rules() -> None:
    from nonebot_plugin_aichat_deepseek import chat as chat_module
    from nonebot_plugin_aichat_deepseek.config import plugin_config

    prompt = chat_module._build_system_prompt()
    assert plugin_config.deepseek_system_prompt in prompt
    assert plugin_config.deepseek_split_delimiter in prompt
    assert "纯文本" in prompt
    assert "Markdown" in prompt
    assert "真人" in prompt
    assert "一句话不要太长" in prompt
    assert "句末可以不带标点" in prompt
    assert "优先分成多条" in prompt
    assert "query_chat_history" in prompt
    assert "web_search" in prompt
    assert "schedule_task" in prompt
    assert "list_scheduled_tasks" in prompt
    assert "不需要用户" in prompt
    assert "来源链接" not in prompt
    assert "save_user_memory" in prompt
    assert "UTC+8" in prompt
    assert "主动戳一戳" in prompt
    assert "戳回去" in prompt
    assert "不要等用户" in prompt
    assert "主动调用 send_sticker" in prompt
    assert "把表情包当成日常表达方式之一" in prompt
    assert "不要连续频繁发送表情包" not in prompt
    assert "不要频繁、无故" not in prompt


def test_format_error() -> None:
    from nonebot_plugin_aichat_deepseek.chat import _format_error
    from nonebot_plugin_aichat_deepseek.data_source import DeepSeekError

    assert "API Key 无效" in _format_error(DeepSeekError("x", status_code=401))
    assert "余额不足" in _format_error(DeepSeekError("x", status_code=402))
    assert "太频繁" in _format_error(DeepSeekError("x", status_code=429))
    assert "暂时不可用" in _format_error(DeepSeekError("x", status_code=503))
    assert "boom" in _format_error(DeepSeekError("boom"))

    long_message = "y" * 500
    formatted = _format_error(DeepSeekError(long_message))
    assert len(formatted) < 220


async def test_process_private_message_ignores_noise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nonebot_plugin_aichat_deepseek import chat as chat_module

    fake = FakeClient("收到")
    monkeypatch.setattr(chat_module, "client", fake)
    chat_module.store.clear("1:2")

    sent: list[str] = []

    async def send(message: Any) -> None:
        sent.append(message)

    await chat_module.process_private_message(make_private_event("   "), send)
    await chat_module.process_private_message(make_private_event("/ping"), send)
    await chat_module.process_private_message(
        make_private_event("self", self_id=1, user_id=1), send
    )
    assert sent == []
    assert fake.requests == []

    await chat_module.process_private_message(make_private_event("你好"), send)
    assert sent == ["收到"]


async def test_reply_archives_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    from nonebot_plugin_aichat_deepseek import chat as chat_module

    fake = FakeClient("归档回复")
    monkeypatch.setattr(chat_module, "client", fake)
    chat_module.store.clear("9:9")

    sent: list[str] = []

    async def send(message: str) -> None:
        sent.append(message)

    await chat_module.reply("9:9", "历史问题", send)

    rows = chat_module.store.query_history("9:9")
    assert len(rows) == 1
    assert rows[0]["user"] == "历史问题"
    assert rows[0]["assistant"] == "归档回复"
    assert sent == ["归档回复"]


async def test_reply_tool_can_query_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nonebot_plugin_aichat_deepseek import chat as chat_module

    class ToolCallingClient:
        configured = True

        def __init__(self) -> None:
            self.tool_result = ""

        async def chat_with_tools(
            self,
            messages,
            *,
            tools,
            tool_runner,
            max_tool_rounds,
            **kwargs,
        ) -> str:
            self.tool_result = await tool_runner(
                "query_chat_history", '{"keyword":"旧"}'
            )
            return "我记得一些"

    fake = ToolCallingClient()
    monkeypatch.setattr(chat_module, "client", fake)
    chat_module.store.clear("7:7")
    chat_module.store.add_turn("7:7", "旧问题", "旧回答")

    sent: list[str] = []

    async def send(message: str) -> None:
        sent.append(message)

    await chat_module.reply("7:7", "我们以前聊了什么", send)

    assert "旧问题" in fake.tool_result
    assert "旧回答" in fake.tool_result
    assert sent == ["我记得一些"]


async def test_reply_tool_can_save_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nonebot_plugin_aichat_deepseek import chat as chat_module

    class MemorySavingClient:
        configured = True

        async def chat_with_tools(
            self,
            messages,
            *,
            tools,
            tool_runner,
            max_tool_rounds,
            **kwargs,
        ) -> str:
            await tool_runner(
                "save_user_memory",
                '{"content":"喜欢猫","category":"preference"}',
            )
            return "记住了"

    monkeypatch.setattr(chat_module, "client", MemorySavingClient())
    chat_module.store.clear("8:8")

    sent: list[str] = []

    async def send(message: str) -> None:
        sent.append(message)

    await chat_module.reply("8:8", "我喜欢猫", send)

    memories = chat_module.store.list_memories("8:8")
    assert len(memories) == 1
    assert memories[0]["content"] == "喜欢猫"

    messages = chat_module._build_request_messages("8:8", "再聊")
    assert "【用户长期记忆】" in messages[0]["content"]
    assert "喜欢猫" in messages[0]["content"]
    assert sent == ["记住了"]


async def test_reply_tool_can_web_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nonebot_plugin_aichat_deepseek import chat as chat_module

    class SearchClient:
        configured = True

        def __init__(self) -> None:
            self.tool_result = ""
            self.tool_names: list[str] = []

        async def search(self, query, **kwargs) -> dict:
            assert query == "最近有什么新闻"
            return {
                "results": [
                    {
                        "title": "今日新闻",
                        "url": "https://example.com/news",
                        "snippet": "新闻摘要",
                        "summary": "新闻长摘要",
                    }
                ]
            }

        async def chat_with_tools(
            self,
            messages,
            *,
            tools,
            tool_runner,
            max_tool_rounds,
            **kwargs,
        ) -> str:
            self.tool_names = [
                tool["function"]["name"] for tool in tools
            ]
            self.tool_result = await tool_runner(
                "web_search", '{"query":"最近有什么新闻"}'
            )
            return "查到一条新闻"

    fake = SearchClient()
    monkeypatch.setattr(chat_module, "client", fake)
    chat_module.store.clear("10:10")

    sent: list[str] = []

    async def send(message: str) -> None:
        sent.append(message)

    await chat_module.reply("10:10", "最近有什么新闻", send)

    assert "web_search" in fake.tool_names
    assert "今日新闻" in fake.tool_result
    assert "https://example.com/news" in fake.tool_result
    assert sent == ["查到一条新闻"]


async def test_reply_tool_can_schedule_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nonebot_plugin_aichat_deepseek import chat as chat_module

    class FakeScheduler:
        def __init__(self) -> None:
            self.added: list[dict] = []

        def get_jobs(self):
            return []

        def add_job(self, func, trigger, **kwargs) -> None:
            self.added.append(
                {"func": func, "trigger": trigger, **kwargs}
            )

    class SchedulerClient:
        configured = True

        def __init__(self) -> None:
            self.tool_result = ""
            self.tool_names: list[str] = []

        async def chat_with_tools(
            self,
            messages,
            *,
            tools,
            tool_runner,
            max_tool_rounds,
            **kwargs,
        ) -> str:
            self.tool_names = [
                tool["function"]["name"] for tool in tools
            ]
            self.tool_result = await tool_runner(
                "schedule_task",
                '{"action":"chat","delay_seconds":60,'
                '"topic":"关心一下"}',
            )
            return "好的"

    scheduler = FakeScheduler()
    fake = SchedulerClient()
    monkeypatch.setattr(chat_module, "client", fake)
    monkeypatch.setattr(chat_module, "get_scheduler", lambda: scheduler)
    chat_module.store.clear("11:11")

    sent: list[str] = []

    async def send(message: str) -> None:
        sent.append(message)

    await chat_module.reply("11:11", "一分钟后戳我", send)

    assert "schedule_task" in fake.tool_names
    assert "scheduled" in fake.tool_result
    assert scheduler.added[0]["kwargs"]["action"] == "chat"
    assert scheduler.added[0]["kwargs"]["topic"] == "关心一下"
    assert scheduler.added[0]["kwargs"]["user_id"] == 11
    assert sent == ["好的"]


async def test_proactive_reply_generates_and_archives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nonebot_plugin_aichat_deepseek import chat as chat_module

    class FakeScheduler:
        def __init__(self) -> None:
            self.added: list[dict] = []
            self.removed: list[str] = []

        def add_job(self, func, trigger, **kwargs) -> None:
            self.added.append(
                {"func": func, "trigger": trigger, **kwargs}
            )

        def remove_job(self, job_id: str) -> None:
            self.removed.append(job_id)

    class ProactiveClient:
        configured = True

        def __init__(self) -> None:
            self.messages: list[dict] | None = None

        async def chat_with_tools(self, messages, **kwargs) -> str:
            self.messages = messages
            return "在忙吗"

    scheduler = FakeScheduler()
    fake = ProactiveClient()
    monkeypatch.setattr(chat_module, "client", fake)
    monkeypatch.setattr(
        chat_module, "get_scheduler", lambda: scheduler
    )
    chat_module.store.clear("12:12")

    sent: list[str] = []

    async def send(message: str) -> None:
        sent.append(message)

    await chat_module.proactive_reply("12:12", "关心一下", send)

    assert sent == ["在忙吗"]
    assert fake.messages is not None
    prompt = fake.messages[-1]["content"]
    assert "主动找用户聊天" in prompt
    assert "关心一下" in prompt

    stored = chat_module.store.build_messages("12:12")
    assert stored[0]["content"] == "（AI 主动找用户聊天）"
    assert stored[1]["content"] == "在忙吗"

    assert len(scheduler.added) == 1
    assert scheduler.added[0]["id"] == "aichat-followup:12:12"
    assert scheduler.added[0]["kwargs"]["user_id"] == 12


async def test_reply_with_image_uploads_and_sends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nonebot_plugin_aichat_deepseek import chat as chat_module
    from nonebot_plugin_aichat_deepseek.images import ImagePayload

    png = b"\x89PNG\r\n\x1a\n" + b"0" * 16

    class ImageClient:
        configured = True

        def __init__(self) -> None:
            self.uploaded: list[tuple[bytes, str, str]] = []
            self.messages: list[dict] | None = None

        async def upload_image(
            self, data: bytes, filename: str, content_type: str, **kwargs
        ) -> str:
            self.uploaded.append((data, filename, content_type))
            return "file-api-test"

        async def chat_with_tools(
            self,
            messages,
            *,
            tools,
            tool_runner,
            max_tool_rounds,
            **kwargs,
        ) -> str:
            self.messages = messages
            return "图片里是一只猫"

    fake = ImageClient()

    async def fake_fetch_image(segment, **kwargs) -> ImagePayload:
        return ImagePayload(png, "cat.png", "image/png")

    monkeypatch.setattr(chat_module, "client", fake)
    monkeypatch.setattr(chat_module, "fetch_image", fake_fetch_image)
    chat_module.store.clear("6:6")

    sent: list[str] = []

    async def send(message: str) -> None:
        sent.append(message)

    await chat_module.reply(
        "6:6",
        "看看这个",
        send,
        images=[{"url": "https://example.com/cat.png"}],
    )

    assert fake.uploaded == [(png, "cat.png", "image/png")]
    assert fake.messages is not None
    user_message = fake.messages[-1]
    assert user_message["content"] == [
        {"type": "text", "text": "看看这个"},
        {"type": "file", "file_id": "file-api-test"},
    ]

    stored = chat_module.store.build_messages("6:6")
    assert "（用户发送了 1 张图片）" in stored[0]["content"]
    assert sent == ["图片里是一只猫"]


async def test_reply_with_sticker_saves_and_notes(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from nonebot_plugin_aichat_deepseek import chat as chat_module
    from nonebot_plugin_aichat_deepseek.config import plugin_config
    from nonebot_plugin_aichat_deepseek.images import ImagePayload

    png = b"\x89PNG\r\n\x1a\n" + b"0" * 16

    class StickerClient:
        configured = True

        def __init__(self) -> None:
            self.messages: list[dict] | None = None

        async def upload_image(
            self, data: bytes, filename: str, content_type: str, **kwargs
        ) -> str:
            return "file-api-sticker"

        async def chat_with_tools(self, messages, **kwargs) -> str:
            self.messages = messages
            return "哈哈"

    fake = StickerClient()

    async def fake_fetch_image(segment, **kwargs) -> ImagePayload:
        return ImagePayload(png, "sticker.png", "image/png")

    monkeypatch.setattr(chat_module, "client", fake)
    monkeypatch.setattr(chat_module, "fetch_image", fake_fetch_image)
    monkeypatch.setattr(
        plugin_config,
        "deepseek_sticker_dir",
        str(tmp_path / "stickers"),
    )
    from nonebot_plugin_aichat_deepseek.history import (
        STICKER_LIBRARY_KEY,
    )

    for sticker in chat_module.store.search_stickers(
        STICKER_LIBRARY_KEY, limit=50
    ):
        chat_module.store.delete_sticker(
            STICKER_LIBRARY_KEY, sticker["id"]
        )
    chat_module.store.clear("4:4")

    sent: list[str] = []

    async def send(message: str) -> None:
        sent.append(message)

    await chat_module.reply(
        "4:4",
        "",
        send,
        images=[{"sub_type": 1, "url": "https://example.com/s.png"}],
    )

    records = chat_module.store.search_stickers(STICKER_LIBRARY_KEY)
    assert len(records) == 1

    assert fake.messages is not None
    note = fake.messages[-1]["content"][0]["text"]
    assert f"#{records[0]['id']}" in note
    assert "describe_sticker" in note
    assert "send_sticker" in note

    stored = chat_module.store.build_messages("4:4")
    assert "（用户发送了 1 个表情包）" in stored[0]["content"]
    assert sent == ["哈哈"]


async def test_process_private_message_passes_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nonebot.adapters.onebot.v11 import MessageSegment

    from nonebot_plugin_aichat_deepseek import chat as chat_module

    captured: dict = {}

    async def fake_reply(session_key, text, send, images=None) -> None:
        captured["session_key"] = session_key
        captured["text"] = text
        captured["images"] = images

    monkeypatch.setattr(chat_module, "reply", fake_reply)

    event = make_image_event(
        MessageSegment.image("https://example.com/cat.png")
    )

    async def send(message: str) -> None:
        pass

    await chat_module.process_private_message(event, send)

    assert captured["session_key"] == "1:2"
    assert captured["text"] == ""
    assert len(captured["images"]) == 1
