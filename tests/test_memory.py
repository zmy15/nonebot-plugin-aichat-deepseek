import json


def test_add_list_and_upsert_memory(store_cls) -> None:
    store = store_cls()
    first_id = store.add_memory("1:2", "喜欢猫", "preference")
    store.add_memory("1:2", "住在杭州", "profile")
    second_id = store.add_memory("1:2", "喜欢猫", "fact")

    assert first_id == second_id
    memories = store.list_memories("1:2")
    assert {item["content"]: item["category"] for item in memories} == {
        "喜欢猫": "fact",
        "住在杭州": "profile",
    }
    store.close()


def test_search_and_delete_memory(store_cls) -> None:
    store = store_cls()
    memory_id = store.add_memory("1:2", "喜欢猫", "preference")
    store.add_memory("1:2", "喜欢狗", "preference")
    store.add_memory("1:3", "喜欢猫", "preference")

    rows = store.search_memories("1:2", keyword="猫")
    assert len(rows) == 1
    assert rows[0]["id"] == memory_id
    assert store.delete_memory("1:2", memory_id) is True
    assert store.delete_memory("1:3", memory_id) is False
    assert store.search_memories("1:2", keyword="猫") == []
    store.close()


def test_clear_removes_memories(store_cls) -> None:
    store = store_cls()
    store.add_memory("1:2", "喜欢猫", "preference")
    store.clear("1:2")
    assert store.list_memories("1:2") == []
    store.close()


async def test_memory_tools(tools_mod, store_cls) -> None:
    store = store_cls()

    saved = json.loads(
        await tools_mod.execute_tool(
            "save_user_memory",
            json.dumps(
                {"content": "**喜欢猫**", "category": "preference"},
                ensure_ascii=False,
            ),
            "1:2",
            store,
        )
    )
    assert saved["saved"] is True
    assert saved["content"] == "喜欢猫"
    memory_id = saved["id"]

    found = json.loads(
        await tools_mod.execute_tool(
            "search_user_memory",
            json.dumps({"keyword": "猫"}, ensure_ascii=False),
            "1:2",
            store,
        )
    )
    assert found["count"] == 1
    assert found["memories"][0]["id"] == memory_id

    deleted = json.loads(
        await tools_mod.execute_tool(
            "delete_user_memory",
            json.dumps({"memory_id": memory_id}),
            "1:2",
            store,
        )
    )
    assert deleted["deleted"] is True
    store.close()


async def test_memory_tool_validates_arguments(tools_mod, store_cls) -> None:
    store = store_cls()

    empty = json.loads(
        await tools_mod.execute_tool(
            "save_user_memory", '{"content":"  "}', "1:2", store
        )
    )
    assert "error" in empty

    bad_category = json.loads(
        await tools_mod.execute_tool(
            "save_user_memory",
            json.dumps({"content": "猫", "category": "unknown"}),
            "1:2",
            store,
        )
    )
    assert "category" in bad_category["error"]

    bad_id = json.loads(
        await tools_mod.execute_tool(
            "delete_user_memory", '{"memory_id":"abc"}', "1:2", store
        )
    )
    assert "memory_id" in bad_id["error"]
    store.close()


def test_memory_tool_definitions(tools_mod) -> None:
    names = {
        tool["function"]["name"] for tool in tools_mod.TOOL_DEFINITIONS
    }
    assert "query_chat_history" in names
    assert "save_user_memory" in names
    assert "search_user_memory" in names
    assert "delete_user_memory" in names

    history_only = tools_mod.build_tool_definitions(include_memory=False)
    assert [tool["function"]["name"] for tool in history_only] == [
        "query_chat_history"
    ]


def test_memories_are_injected_into_system_prompt(
    monkeypatch, store_cls
) -> None:
    from nonebot_plugin_aichat_deepseek import chat

    store = store_cls()
    store.add_memory("5:5", "喜欢猫", "preference")
    store.add_memory("5:5", "住在杭州", "profile")
    monkeypatch.setattr(chat, "store", store)

    messages = chat._build_request_messages("5:5", "你好")
    system_prompt = messages[0]["content"]

    assert "【用户长期记忆】" in system_prompt
    assert "喜欢猫" in system_prompt
    assert "住在杭州" in system_prompt
    assert "偏好" in system_prompt
    assert "个人信息" in system_prompt
    store.close()


def test_memory_section_respects_char_budget(monkeypatch) -> None:
    from nonebot_plugin_aichat_deepseek import chat
    from nonebot_plugin_aichat_deepseek.config import plugin_config

    monkeypatch.setattr(plugin_config, "deepseek_memory_max_chars", 20)
    prompt = chat._build_system_prompt(
        "",
        [
            {"id": 1, "category": "preference", "content": "喜欢猫"},
            {"id": 2, "category": "preference", "content": "喜欢狗"},
        ],
    )
    assert "喜欢猫" in prompt
    assert "喜欢狗" not in prompt
