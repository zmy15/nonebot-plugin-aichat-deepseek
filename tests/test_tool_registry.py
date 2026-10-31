def test_each_tool_is_self_contained(tools_mod) -> None:
    from nonebot_plugin_aichat_deepseek.tools.registry import (
        ALL_TOOLS,
        TOOL_BY_NAME,
    )

    names = [tool.name for tool in ALL_TOOLS]

    assert names == [
        "query_chat_history",
        "web_search",
        "save_user_memory",
        "search_user_memory",
        "delete_user_memory",
        "set_user_system_prompt",
        "get_user_system_prompt",
        "clear_user_system_prompt",
        "poke_user",
        "schedule_task",
        "list_scheduled_tasks",
        "cancel_scheduled_task",
        "update_scheduled_task",
        "describe_sticker",
        "search_stickers",
        "send_sticker",
        "recall_message",
    ]
    assert len(names) == len(set(names))
    assert set(names) <= set(TOOL_BY_NAME)
    assert {
        "save_group_memory",
        "search_group_memory",
        "delete_group_memory",
    } <= set(TOOL_BY_NAME)

    for tool in ALL_TOOLS:
        assert tool.definition["function"]["name"] == tool.name
        assert callable(tool.handler)
        assert callable(tool.enabled)
        assert TOOL_BY_NAME[tool.name] is tool

    definitions = [
        tool["function"]["name"] for tool in tools_mod.TOOL_DEFINITIONS
    ]
    assert definitions == names

    descriptions = {
        tool["function"]["name"]: tool["function"]["description"]
        for tool in tools_mod.TOOL_DEFINITIONS
    }
    assert "不要连续频繁" not in descriptions["send_sticker"]
    assert "不要频繁" not in descriptions["poke_user"]
    assert "主动戳一戳" in descriptions["poke_user"]
    assert "戳回去" in descriptions["poke_user"]
    assert "不要等用户" in descriptions["poke_user"]
    assert "主动发送" in descriptions["send_sticker"]
