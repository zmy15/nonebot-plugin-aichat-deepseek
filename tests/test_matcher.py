from typing import Any

import pytest
from nonebug import App


class FakeClient:
    configured = True

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.requests: list[list[dict[str, str]]] = []

    async def chat(self, messages: list[dict[str, str]]) -> str:
        self.requests.append(list(messages))
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


def make_group_event(text: str, *, self_id: int = 1, user_id: int = 2):
    from nonebot.adapters.onebot.v11 import Message
    from nonebot.adapters.onebot.v11.event import GroupMessageEvent, Sender

    return GroupMessageEvent(
        time=0,
        self_id=self_id,
        post_type="message",
        sub_type="normal",
        user_id=user_id,
        message_type="group",
        message_id=1,
        message=Message(text),
        original_message=Message(text),
        raw_message=text,
        font=0,
        sender=Sender(user_id=user_id),
        to_me=False,
        group_id=10,
    )


def make_bot(ctx: Any):
    from nonebot.adapters.onebot.v11 import Adapter, Bot

    return ctx.create_bot(
        base=Bot,
        adapter=ctx.create_adapter(base=Adapter),
        self_id="1",
    )


async def test_private_message_triggers_reply(
    app: App, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nonebot_plugin_aichat_deepseek import chat

    fake = FakeClient("你好呀")
    monkeypatch.setattr(chat, "client", fake)
    chat.store.clear("1:2")

    async with app.test_matcher(chat.private_chat) as ctx:
        bot = make_bot(ctx)
        event = make_private_event("你好")
        ctx.receive_event(bot, event)
        ctx.should_pass_rule()
        ctx.should_call_send(event, "你好呀", result=None)


async def test_group_message_does_not_trigger(
    app: App, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nonebot_plugin_aichat_deepseek import chat

    fake = FakeClient("不应该发送")
    monkeypatch.setattr(chat, "client", fake)

    async with app.test_matcher(chat.private_chat) as ctx:
        bot = make_bot(ctx)
        event = make_group_event("你好")
        ctx.receive_event(bot, event)
        ctx.should_not_pass_rule()

    assert fake.requests == []


async def test_command_is_not_handled_as_chat(
    app: App, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nonebot_plugin_aichat_deepseek import chat

    fake = FakeClient("不应该发送")
    monkeypatch.setattr(chat, "client", fake)

    async with app.test_matcher(chat.private_chat) as ctx:
        bot = make_bot(ctx)
        event = make_private_event("/ping")
        ctx.receive_event(bot, event)
        ctx.should_pass_rule()

    assert fake.requests == []


async def test_ping_still_works(app: App) -> None:
    import nonebot_plugin_aichat_deepseek as plugin

    async with app.test_matcher(plugin.ping) as ctx:
        bot = make_bot(ctx)
        event = make_private_event("/ping")
        ctx.receive_event(bot, event)
        ctx.should_pass_rule()
        ctx.should_call_send(event, "pong", result=None)
        ctx.should_finished()
