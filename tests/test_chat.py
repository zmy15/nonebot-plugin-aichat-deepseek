from typing import Any

import pytest


class FakeClient:
    configured = True

    def __init__(self, *replies: str, error: Exception | None = None) -> None:
        self.replies = list(replies)
        self.error = error
        self.requests: list[list[dict[str, str]]] = []

    async def chat(self, messages: list[dict[str, str]]) -> str:
        self.requests.append(list(messages))
        if self.error is not None:
            raise self.error
        return self.replies.pop(0)


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


def test_system_prompt_contains_output_rules() -> None:
    from nonebot_plugin_aichat_deepseek import chat as chat_module
    from nonebot_plugin_aichat_deepseek.config import plugin_config

    prompt = chat_module._build_system_prompt()
    assert plugin_config.deepseek_system_prompt in prompt
    assert plugin_config.deepseek_split_delimiter in prompt
    assert "纯文本" in prompt
    assert "Markdown" in prompt


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
