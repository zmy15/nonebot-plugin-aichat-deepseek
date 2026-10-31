import json


def make_poke(*, self_id: int = 1, user_id: int = 2, target_id: int = 1, group_id=None):
    from nonebot.adapters.onebot.v11.event import PokeNotifyEvent

    return PokeNotifyEvent(
        time=0,
        self_id=self_id,
        post_type="notice",
        notice_type="notify",
        sub_type="poke",
        user_id=user_id,
        target_id=target_id,
        group_id=group_id,
    )


def test_private_poke_rule() -> None:
    from nonebot_plugin_aichat_deepseek import chat

    assert chat._is_private_poke(make_poke()) is True
    assert chat._is_private_poke(make_poke(target_id=3)) is False
    assert chat._is_private_poke(make_poke(group_id=123)) is False
    assert chat._is_private_poke(make_poke(user_id=1)) is False


async def test_process_private_poke_replies(monkeypatch) -> None:
    from nonebot_plugin_aichat_deepseek import chat

    captured: dict = {}

    async def fake_reply(session_key, text, send, images=None) -> None:
        captured["session_key"] = session_key
        captured["text"] = text
        captured["images"] = images

    monkeypatch.setattr(chat, "reply", fake_reply)

    async def send(message: str) -> None:
        pass

    await chat.process_private_poke(make_poke(), send)

    assert captured["session_key"] == "1:2"
    assert captured["text"] == chat.POKE_BACK_PROMPT
    assert captured["images"] is None


async def test_process_private_poke_without_tools_uses_base_prompt(
    monkeypatch,
) -> None:
    from nonebot_plugin_aichat_deepseek import chat
    from nonebot_plugin_aichat_deepseek.config import plugin_config

    captured: dict = {}

    async def fake_reply(session_key, text, send, images=None) -> None:
        captured["text"] = text

    monkeypatch.setattr(chat, "reply", fake_reply)
    monkeypatch.setattr(plugin_config, "deepseek_tools_enabled", False)

    async def send(message: str) -> None:
        pass

    await chat.process_private_poke(make_poke(), send)

    assert captured["text"] == chat.POKE_PROMPT


async def test_poke_tool_calls_friend_poke(
    tools_mod, store_cls, monkeypatch
) -> None:
    calls: list[tuple[str, dict]] = []

    class FakeBot:
        async def call_api(self, api: str, **kwargs) -> dict:
            calls.append((api, kwargs))
            return {}

    monkeypatch.setattr(tools_mod, "get_bot", lambda self_id: FakeBot())
    store = store_cls()

    raw = await tools_mod.execute_tool(
        tools_mod.TOOL_POKE_USER, "{}", "1:2", store
    )
    data = json.loads(raw)

    assert data["poked"] is True
    assert data["api"] == "friend_poke"
    assert calls == [("friend_poke", {"user_id": 2})]
    store.close()


async def test_poke_tool_falls_back_to_send_poke(
    tools_mod, store_cls, monkeypatch
) -> None:
    calls: list[str] = []

    class FakeBot:
        async def call_api(self, api: str, **kwargs) -> dict:
            calls.append(api)
            if api == "friend_poke":
                raise RuntimeError("unsupported")
            return {}

    monkeypatch.setattr(tools_mod, "get_bot", lambda self_id: FakeBot())
    store = store_cls()

    raw = await tools_mod.execute_tool(
        tools_mod.TOOL_POKE_USER, "{}", "1:2", store
    )
    data = json.loads(raw)

    assert data["poked"] is True
    assert data["api"] == "send_poke"
    assert calls == ["friend_poke", "send_poke"]
    store.close()


async def test_poke_tool_handles_missing_bot(
    tools_mod, store_cls, monkeypatch
) -> None:
    def missing(self_id):
        raise ValueError("no bot")

    monkeypatch.setattr(tools_mod, "get_bot", missing)
    store = store_cls()

    raw = await tools_mod.execute_tool(
        tools_mod.TOOL_POKE_USER, "{}", "1:2", store
    )
    assert "error" in json.loads(raw)
    store.close()


def test_poke_tool_definition(tools_mod) -> None:
    names = {
        tool["function"]["name"]
        for tool in tools_mod.build_tool_definitions(include_poke=True)
    }
    assert tools_mod.TOOL_POKE_USER in names

    names_without = {
        tool["function"]["name"]
        for tool in tools_mod.build_tool_definitions(include_poke=False)
    }
    assert tools_mod.TOOL_POKE_USER not in names_without
