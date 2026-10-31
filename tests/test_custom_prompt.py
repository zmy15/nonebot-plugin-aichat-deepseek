import json


def test_user_prompt_crud(store_cls) -> None:
    store = store_cls()
    assert store.get_user_prompt("1:2") == ""

    store.set_user_prompt("1:2", "  以后用简短、傲娇的语气回复我  ")
    assert store.get_user_prompt("1:2") == "以后用简短、傲娇的语气回复我"

    store.set_user_prompt("1:2", "换一个设定")
    assert store.get_user_prompt("1:2") == "换一个设定"
    assert store.get_user_prompt("1:3") == ""

    assert store.clear_user_prompt("1:2") is True
    assert store.clear_user_prompt("1:2") is False
    assert store.get_user_prompt("1:2") == ""
    store.close()


def test_user_prompt_persists(tmp_path, store_cls) -> None:
    db_path = tmp_path / "chat.db"
    store = store_cls(db_path=db_path)
    store.set_user_prompt("1:2", "以后多分几条消息")
    store.close()

    reopened = store_cls(db_path=db_path)
    assert reopened.get_user_prompt("1:2") == "以后多分几条消息"
    reopened.close()


async def test_custom_prompt_tools(tools_mod, store_cls) -> None:
    store = store_cls()

    raw = await tools_mod.execute_tool(
        tools_mod.TOOL_SET_USER_PROMPT,
        json.dumps({"content": "以后用简短、傲娇的语气回复我"}),
        "1:2",
        store,
    )
    saved = json.loads(raw)
    assert saved["saved"] is True
    assert saved["length"] == len("以后用简短、傲娇的语气回复我")
    assert store.get_user_prompt("1:2") == "以后用简短、傲娇的语气回复我"

    raw = await tools_mod.execute_tool(
        tools_mod.TOOL_GET_USER_PROMPT, "{}", "1:2", store
    )
    current = json.loads(raw)
    assert current["content"] == "以后用简短、傲娇的语气回复我"

    raw = await tools_mod.execute_tool(
        tools_mod.TOOL_CLEAR_USER_PROMPT, "{}", "1:2", store
    )
    assert json.loads(raw)["cleared"] is True
    assert store.get_user_prompt("1:2") == ""
    store.close()


async def test_custom_prompt_tool_validates_content(
    tools_mod, store_cls, monkeypatch
) -> None:
    from nonebot_plugin_aichat_deepseek.config import plugin_config

    store = store_cls()

    empty = json.loads(
        await tools_mod.execute_tool(
            tools_mod.TOOL_SET_USER_PROMPT,
            json.dumps({"content": "   "}),
            "1:2",
            store,
        )
    )
    assert "error" in empty

    monkeypatch.setattr(
        plugin_config, "deepseek_custom_prompt_max_chars", 5
    )
    too_long = json.loads(
        await tools_mod.execute_tool(
            tools_mod.TOOL_SET_USER_PROMPT,
            json.dumps({"content": "123456"}),
            "1:2",
            store,
        )
    )
    assert "error" in too_long
    assert store.get_user_prompt("1:2") == ""
    store.close()


def test_custom_prompt_tool_definitions(tools_mod) -> None:
    names = {
        tool["function"]["name"]
        for tool in tools_mod.build_tool_definitions(
            include_custom_prompt=True
        )
    }
    assert tools_mod.TOOL_SET_USER_PROMPT in names
    assert tools_mod.TOOL_GET_USER_PROMPT in names
    assert tools_mod.TOOL_CLEAR_USER_PROMPT in names

    names_without = {
        tool["function"]["name"]
        for tool in tools_mod.build_tool_definitions(
            include_custom_prompt=False
        )
    }
    assert tools_mod.TOOL_SET_USER_PROMPT not in names_without


def test_custom_prompt_is_injected(monkeypatch) -> None:
    from nonebot_plugin_aichat_deepseek import chat
    from nonebot_plugin_aichat_deepseek.config import plugin_config

    chat.store.clear("1:2")
    chat.store.set_user_prompt("1:2", "以后用简短、傲娇的语气回复我")

    messages = chat._build_request_messages("1:2", "你好")
    system = messages[0]["content"]
    assert "【用户自定义指令】" in system
    assert "以后用简短、傲娇的语气回复我" in system

    monkeypatch.setattr(
        plugin_config, "deepseek_custom_prompt_enabled", False
    )
    messages = chat._build_request_messages("1:2", "你好")
    assert "【用户自定义指令】" not in messages[0]["content"]

    chat.store.clear("1:2")
