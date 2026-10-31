def test_each_tool_is_self_contained(tools_mod) -> None:
    from nonebot_plugin_aichat_deepseek.tools.registry import (
        ALL_TOOLS,
        TOOL_BY_NAME,
    )

    names = [tool.name for tool in ALL_TOOLS]

    assert names == [
        "query_chat_history",
        "save_user_memory",
        "search_user_memory",
        "delete_user_memory",
        "set_user_system_prompt",
        "get_user_system_prompt",
        "clear_user_system_prompt",
        "poke_user",
        "describe_sticker",
        "search_stickers",
        "send_sticker",
    ]
    assert len(names) == len(set(names))
    assert set(names) == set(TOOL_BY_NAME)

    for tool in ALL_TOOLS:
        assert tool.definition["function"]["name"] == tool.name
        assert callable(tool.handler)
        assert callable(tool.enabled)
        assert TOOL_BY_NAME[tool.name] is tool

    definitions = [
        tool["function"]["name"] for tool in tools_mod.TOOL_DEFINITIONS
    ]
    assert definitions == names
