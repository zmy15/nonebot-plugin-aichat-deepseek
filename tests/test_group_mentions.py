import pytest

from tests.test_group import make_group_event


class FakeClient:
    configured = True

    def __init__(self, answer: str = "收到") -> None:
        self.answer = answer
        self.requests: list[list[dict]] = []

    async def chat(self, messages, **kwargs) -> str:
        self.requests.append([dict(message) for message in messages])
        return self.answer

    async def chat_with_tools(self, messages, **kwargs) -> str:
        return await self.chat(messages, **kwargs)


class FakeBot:
    def __init__(self, nickname: str = "小助手", card: str = "群助手") -> None:
        self.nickname = nickname
        self.card = card
        self.calls: list[str] = []

    async def call_api(self, api: str, **kwargs):
        self.calls.append(api)
        if api == "get_login_info":
            return {"nickname": self.nickname}
        if api == "get_group_member_info":
            return {"card": self.card, "nickname": self.nickname}
        raise AssertionError(f"unexpected api: {api}")


@pytest.fixture(autouse=True)
def clear_mention_state(monkeypatch):
    from nonebot_plugin_aichat_deepseek import chat
    from nonebot_plugin_aichat_deepseek.config import plugin_config

    chat._GROUP_LAST_REPLY.clear()
    chat._BOT_NAMES_CACHE.clear()
    monkeypatch.setattr(plugin_config, "deepseek_reply_delay", 0.0)
    monkeypatch.setattr(plugin_config, "deepseek_reply_delay_jitter", 0.0)
    monkeypatch.setattr(plugin_config, "deepseek_reply_interval", 0.0)
    monkeypatch.setattr(
        plugin_config, "deepseek_reply_interval_jitter", 0.0
    )
    yield
    chat._GROUP_LAST_REPLY.clear()
    chat._BOT_NAMES_CACHE.clear()


def test_mentions_bot_matches_chinese_and_ascii_words() -> None:
    from nonebot_plugin_aichat_deepseek import chat

    assert chat._mentions_bot("小助手在吗", ["小助手"]) is True
    assert chat._mentions_bot("AI 你觉得呢", ["ai"]) is True
    assert chat._mentions_bot("said something", ["ai"]) is False
    assert chat._mentions_bot("今天吃什么", ["小助手"]) is False
    assert chat._mentions_bot("", ["小助手"]) is False


async def test_configured_name_triggers_reply_without_at(monkeypatch) -> None:
    from nonebot_plugin_aichat_deepseek import chat
    from nonebot_plugin_aichat_deepseek.config import plugin_config

    fake = FakeClient()
    monkeypatch.setattr(chat, "client", fake)
    monkeypatch.setattr(chat, "_should_group_reply", lambda key: False)
    monkeypatch.setattr(
        plugin_config, "deepseek_group_bot_names", "小助手, AI"
    )
    monkeypatch.setattr(
        plugin_config, "deepseek_group_mention_reply", True
    )
    chat.store.clear_group_context(1, 123)

    sent: list[str] = []

    async def send(message: str) -> None:
        sent.append(message)

    await chat.process_group_message(
        make_group_event("小助手在吗", to_me=False), send
    )

    assert sent == ["收到"]
    assert len(fake.requests) == 1


async def test_auto_nickname_and_card_trigger_reply(monkeypatch) -> None:
    from nonebot_plugin_aichat_deepseek import chat
    from nonebot_plugin_aichat_deepseek.config import plugin_config

    fake = FakeClient()
    bot = FakeBot(nickname="小助手", card="群助手")
    monkeypatch.setattr(chat, "client", fake)
    monkeypatch.setattr(chat, "_should_group_reply", lambda key: False)
    monkeypatch.setattr(plugin_config, "deepseek_group_bot_names", "")
    monkeypatch.setattr(
        plugin_config, "deepseek_group_mention_reply", True
    )
    chat.store.clear_group_context(1, 456)

    sent: list[str] = []

    async def send(message: str) -> None:
        sent.append(message)

    await chat.process_group_message(
        make_group_event("群助手怎么看", group_id=456),
        send,
        bot,
    )

    assert sent == ["收到"]
    assert "get_login_info" in bot.calls
    assert "get_group_member_info" in bot.calls


async def test_no_mention_keeps_probability_behaviour(monkeypatch) -> None:
    from nonebot_plugin_aichat_deepseek import chat
    from nonebot_plugin_aichat_deepseek.config import plugin_config

    fake = FakeClient()
    monkeypatch.setattr(chat, "client", fake)
    monkeypatch.setattr(chat, "_should_group_reply", lambda key: False)
    monkeypatch.setattr(
        plugin_config, "deepseek_group_bot_names", "小助手"
    )
    chat.store.clear_group_context(1, 789)

    sent: list[str] = []

    async def send(message: str) -> None:
        sent.append(message)

    await chat.process_group_message(
        make_group_event("今天吃什么", group_id=789), send
    )

    assert sent == []


async def test_mention_reply_can_be_disabled(monkeypatch) -> None:
    from nonebot_plugin_aichat_deepseek import chat
    from nonebot_plugin_aichat_deepseek.config import plugin_config

    fake = FakeClient()
    monkeypatch.setattr(chat, "client", fake)
    monkeypatch.setattr(chat, "_should_group_reply", lambda key: False)
    monkeypatch.setattr(
        plugin_config, "deepseek_group_bot_names", "小助手"
    )
    monkeypatch.setattr(
        plugin_config, "deepseek_group_mention_reply", False
    )
    chat.store.clear_group_context(1, 321)

    sent: list[str] = []

    async def send(message: str) -> None:
        sent.append(message)

    await chat.process_group_message(
        make_group_event("小助手在吗", group_id=321), send
    )

    assert sent == []
    assert fake.requests == []
