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
    chat_module.store.clear("1:2")

    sent: list[str] = []

    async def send(message: str) -> None:
        sent.append(message)

    await chat_module.reply("1:2", "你好", send)

    assert len(sent) == 3
    assert all(len(chunk) <= 10 for chunk in sent)
    assert "".join(sent) == answer


def test_split_text() -> None:
    from nonebot_plugin_aichat_deepseek.chat import split_text

    assert split_text("  ", 10) == []
    assert split_text("short", 100) == ["short"]
    assert split_text("abcdefghijklmnop", 5) == ["abcde", "fghij", "klmno", "p"]
    assert split_text("line1\nline2\nline3", 12) == ["line1\nline2", "line3"]


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
