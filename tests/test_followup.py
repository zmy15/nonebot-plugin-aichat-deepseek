from datetime import datetime


class FakeScheduler:
    def __init__(self) -> None:
        self.added: list[dict] = []
        self.removed: list[str] = []

    def add_job(self, func, trigger, **kwargs) -> None:
        self.added.append({"func": func, "trigger": trigger, **kwargs})

    def remove_job(self, job_id: str) -> None:
        self.removed.append(job_id)


def make_private_event(text: str, *, self_id: int = 1, user_id: int = 2):
    from nonebot.adapters.onebot.v11 import Message
    from nonebot.adapters.onebot.v11.event import (
        PrivateMessageEvent,
        Sender,
    )

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


def test_looks_like_question() -> None:
    from nonebot_plugin_aichat_deepseek.chat import _looks_like_question

    for text in ("在吗？", "吃了吗", "最近怎么样", "要不要一起", "在吗"):
        assert _looks_like_question(text) is True

    for text in ("好的", "晚安", "我去吃饭了", ""):
        assert _looks_like_question(text) is False


async def test_reply_schedules_followup(monkeypatch) -> None:
    from nonebot_plugin_aichat_deepseek import chat

    class Client:
        configured = True

        async def chat_with_tools(self, messages, **kwargs) -> str:
            return "在吗？"

    scheduler = FakeScheduler()
    monkeypatch.setattr(chat, "client", Client())
    monkeypatch.setattr(chat, "get_scheduler", lambda: scheduler)
    chat.store.clear("1:13")

    sent: list[str] = []

    async def send(message: str) -> None:
        sent.append(message)

    await chat.reply("1:13", "你好", send)

    assert sent == ["在吗？"]
    assert len(scheduler.added) == 1
    added = scheduler.added[0]
    assert added["id"] == "aichat-followup:1:13"
    assert added["kwargs"]["self_id"] == "1"
    assert added["kwargs"]["user_id"] == 13
    assert added["kwargs"]["token"]
    assert isinstance(added["run_date"], datetime)


async def test_statement_cancels_followup(monkeypatch) -> None:
    from nonebot_plugin_aichat_deepseek import chat

    class Client:
        configured = True

        async def chat_with_tools(self, messages, **kwargs) -> str:
            return "晚安"

    scheduler = FakeScheduler()
    monkeypatch.setattr(chat, "client", Client())
    monkeypatch.setattr(chat, "get_scheduler", lambda: scheduler)
    chat.store.clear("15:15")

    async def send(message: str) -> None:
        pass

    await chat.reply("15:15", "晚安", send)

    assert scheduler.added == []
    assert scheduler.removed == ["aichat-followup:15:15"]


async def test_incoming_message_cancels_followup(monkeypatch) -> None:
    from nonebot_plugin_aichat_deepseek import chat

    scheduler = FakeScheduler()
    monkeypatch.setattr(chat, "get_scheduler", lambda: scheduler)

    async def fake_reply(session_key, text, send, images=None) -> None:
        pass

    monkeypatch.setattr(chat, "reply", fake_reply)

    async def send(message: str) -> None:
        pass

    await chat.process_private_message(
        make_private_event("你好"), send
    )

    assert scheduler.removed == ["aichat-followup:1:2"]


async def test_followup_reply_does_not_schedule_again(monkeypatch) -> None:
    from nonebot_plugin_aichat_deepseek import chat

    class Client:
        configured = True

        async def chat_with_tools(self, messages, **kwargs) -> str:
            return "还在吗？"

    scheduler = FakeScheduler()
    monkeypatch.setattr(chat, "client", Client())
    monkeypatch.setattr(chat, "get_scheduler", lambda: scheduler)
    chat.store.clear("16:16")

    sent: list[str] = []

    async def send(message: str) -> None:
        sent.append(message)

    await chat.followup_reply("16:16", send)

    assert sent == ["还在吗？"]
    assert scheduler.added == []
    stored = chat.store.build_messages("16:16")
    assert stored[0]["content"] == "（AI 追问未回复的用户）"
    assert stored[1]["content"] == "还在吗？"


async def test_run_followup_task_sends(monkeypatch) -> None:
    from nonebot_plugin_aichat_deepseek import chat, scheduled_tasks

    scheduler = FakeScheduler()
    scheduled_tasks.schedule_followup(
        scheduler,
        session_key="1:2",
        self_id="1",
        user_id=2,
        delay_seconds=60,
        token="token-1",
    )

    calls: list[tuple] = []

    class FakeBot:
        async def call_api(self, api: str, **kwargs):
            calls.append((api, kwargs))
            return {}

    async def fake_followup(session_key, send) -> None:
        calls.append(("followup", session_key))
        await send("还在吗")

    monkeypatch.setattr(chat, "followup_reply", fake_followup)
    monkeypatch.setattr(
        scheduled_tasks, "get_bot", lambda self_id: FakeBot()
    )

    await scheduled_tasks.run_followup_task(
        session_key="1:2",
        self_id="1",
        user_id=2,
        token="token-1",
    )

    assert calls == [
        ("followup", "1:2"),
        ("send_private_msg", {"user_id": 2, "message": "还在吗"}),
    ]


async def test_run_followup_task_skips_cancelled() -> None:
    from nonebot_plugin_aichat_deepseek import scheduled_tasks

    scheduler = FakeScheduler()
    scheduled_tasks.schedule_followup(
        scheduler,
        session_key="1:3",
        self_id="1",
        user_id=3,
        delay_seconds=60,
        token="token-2",
    )
    scheduled_tasks.cancel_followup(scheduler, "1:3")

    await scheduled_tasks.run_followup_task(
        session_key="1:3",
        self_id="1",
        user_id=3,
        token="token-2",
    )
