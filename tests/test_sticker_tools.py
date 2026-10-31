import json

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 16


def test_sticker_tool_definitions(tools_mod) -> None:
    names = {tool["function"]["name"] for tool in tools_mod.TOOL_DEFINITIONS}
    assert "describe_sticker" in names
    assert "search_stickers" in names
    assert "send_sticker" in names

    enabled = tools_mod.build_tool_definitions(
        include_memory=False, include_stickers=True
    )
    assert [tool["function"]["name"] for tool in enabled] == [
        "query_chat_history",
        "describe_sticker",
        "search_stickers",
        "send_sticker",
    ]

    disabled = tools_mod.build_tool_definitions(include_memory=False)
    assert [tool["function"]["name"] for tool in disabled] == [
        "query_chat_history"
    ]


async def test_describe_and_search_sticker_tools(
    tools_mod, store_cls, tmp_path
) -> None:
    store = store_cls()
    sticker = store.add_sticker(
        "1:2", "a" * 64, tmp_path / "a.png", description=""
    )

    described = json.loads(
        await tools_mod.execute_tool(
            "describe_sticker",
            json.dumps(
                {
                    "sticker_id": sticker["id"],
                    "description": "**无语**",
                    "tags": "翻白眼、无语",
                },
                ensure_ascii=False,
            ),
            "1:2",
            store,
        )
    )
    assert described["saved"] is True
    assert described["description"] == "无语"
    assert described["tags"] == "翻白眼,无语"

    found = json.loads(
        await tools_mod.execute_tool(
            "search_stickers",
            json.dumps({"keyword": "无语"}, ensure_ascii=False),
            "1:2",
            store,
        )
    )
    assert found["count"] == 1
    assert found["stickers"][0]["id"] == sticker["id"]
    assert found["stickers"][0]["description"] == "无语"

    other = json.loads(
        await tools_mod.execute_tool(
            "describe_sticker",
            json.dumps(
                {"sticker_id": sticker["id"], "description": "嘲笑"},
                ensure_ascii=False,
            ),
            "1:3",
            store,
        )
    )
    assert "error" in other
    store.close()


async def test_send_sticker_tool(
    tools_mod, store_cls, tmp_path, monkeypatch
) -> None:
    class FakeBot:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict]] = []

        async def call_api(self, api: str, **kwargs):
            self.calls.append((api, kwargs))
            return {}

    bot = FakeBot()
    monkeypatch.setattr(tools_mod, "get_bot", lambda self_id: bot)

    path = tmp_path / "sticker.png"
    path.write_bytes(PNG)
    store = store_cls()
    sticker = store.add_sticker(
        "1:2", "a" * 64, path, description="无语", tags="无语,翻白眼"
    )

    sent = json.loads(
        await tools_mod.execute_tool(
            "send_sticker",
            json.dumps({"keyword": "无语"}, ensure_ascii=False),
            "1:2",
            store,
        )
    )
    assert sent["sent"] is True
    assert sent["sticker_id"] == sticker["id"]
    assert sent["method"] == "file_uri"
    assert bot.calls[0][0] == "send_private_msg"
    assert bot.calls[0][1]["user_id"] == 2
    assert bot.calls[0][1]["message"][0]["type"] == "image"

    used = store.get_sticker("1:2", sticker["id"])
    assert used is not None
    assert used["use_count"] == 1
    store.close()


async def test_send_sticker_tool_reports_missing_match(
    tools_mod, store_cls, tmp_path
) -> None:
    store = store_cls()
    store.add_sticker(
        "1:2", "a" * 64, tmp_path / "a.png", description="无语"
    )

    missing = json.loads(
        await tools_mod.execute_tool(
            "send_sticker",
            json.dumps({"keyword": "开心"}, ensure_ascii=False),
            "1:2",
            store,
        )
    )
    assert "没有找到" in missing["error"]
    assert "无语" in missing["error"]

    no_args = json.loads(
        await tools_mod.execute_tool("send_sticker", "{}", "1:2", store)
    )
    assert "至少" in no_args["error"]

    wrong_user = json.loads(
        await tools_mod.execute_tool(
            "send_sticker",
            json.dumps({"keyword": "无语"}, ensure_ascii=False),
            "1:3",
            store,
        )
    )
    assert "没有找到" in wrong_user["error"]
    store.close()
