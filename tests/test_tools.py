import json
from datetime import datetime, timedelta, timezone

UTC8 = timezone(timedelta(hours=8))


def _when(day: int, hour: int = 10) -> datetime:
    return datetime(2026, 10, day, hour, 0, tzinfo=UTC8)


def test_tool_definition(tools_mod) -> None:
    assert tools_mod.TOOL_QUERY_HISTORY == "query_chat_history"
    tool = tools_mod.TOOL_DEFINITIONS[0]
    assert tool["type"] == "function"
    assert tool["function"]["name"] == "query_chat_history"
    assert "UTC+8" in tool["function"]["description"]


async def test_query_history_by_keyword(tools_mod, store_cls) -> None:
    db = store_cls()
    db.add_turn("1:2", "我喜欢猫", "猫很可爱", when=_when(1))
    db.add_turn("1:2", "今天吃什么", "吃面条", when=_when(2))

    raw = await tools_mod.execute_tool(
        "query_chat_history",
        json.dumps({"keyword": "猫"}, ensure_ascii=False),
        "1:2",
        db,
    )
    data = json.loads(raw)
    assert data["timezone"] == "UTC+8"
    assert data["count"] == 1
    assert data["turns"][0]["user"] == "我喜欢猫"
    assert data["turns"][0]["time"] == "2026-10-01 10:00:00"
    db.close()


async def test_query_history_by_date_range(tools_mod, store_cls) -> None:
    db = store_cls()
    db.add_turn("1:2", "第一天", "a", when=_when(1))
    db.add_turn("1:2", "第二天", "b", when=_when(2, 23))
    db.add_turn("1:2", "第三天", "c", when=_when(3))

    raw = await tools_mod.execute_tool(
        "query_chat_history",
        json.dumps(
            {"start_time": "2026-10-02", "end_time": "2026-10-02"},
            ensure_ascii=False,
        ),
        "1:2",
        db,
    )
    data = json.loads(raw)
    assert [turn["user"] for turn in data["turns"]] == ["第二天"]
    db.close()


async def test_query_history_combines_keyword_and_time(
    tools_mod, store_cls
) -> None:
    db = store_cls()
    db.add_turn("1:2", "第一天聊到猫", "a", when=_when(1))
    db.add_turn("1:2", "第二天也聊到猫", "b", when=_when(2))
    db.add_turn("1:2", "第三天聊到狗", "c", when=_when(3))

    raw = await tools_mod.execute_tool(
        "query_chat_history",
        json.dumps(
            {
                "keyword": "猫",
                "start_time": "2026-10-02",
                "end_time": "2026-10-02",
            },
            ensure_ascii=False,
        ),
        "1:2",
        db,
    )
    data = json.loads(raw)
    assert [turn["user"] for turn in data["turns"]] == ["第二天也聊到猫"]
    db.close()


async def test_query_history_is_scoped_to_session(
    tools_mod, store_cls
) -> None:
    db = store_cls()
    db.add_turn("1:2", "用户二的记录", "a", when=_when(1))
    db.add_turn("1:3", "用户三的记录", "b", when=_when(2))

    raw = await tools_mod.execute_tool(
        "query_chat_history", "{}", "1:2", db
    )
    data = json.loads(raw)
    assert data["count"] == 1
    assert data["turns"][0]["user"] == "用户二的记录"
    db.close()


async def test_query_history_limit_is_capped(tools_mod, store_cls) -> None:
    db = store_cls()
    for day in range(1, 26):
        db.add_turn("1:2", f"问题{day}", f"回答{day}", when=_when(day))

    raw = await tools_mod.execute_tool(
        "query_chat_history", json.dumps({"limit": 100}), "1:2", db
    )
    data = json.loads(raw)
    assert data["count"] == 20
    assert data["turns"][-1]["user"] == "问题25"
    db.close()


async def test_tool_reports_invalid_arguments(tools_mod, store_cls) -> None:
    db = store_cls()

    invalid_json = await tools_mod.execute_tool(
        "query_chat_history", "not json", "1:2", db
    )
    assert "error" in json.loads(invalid_json)

    invalid_time = await tools_mod.execute_tool(
        "query_chat_history",
        json.dumps({"start_time": "昨天"}),
        "1:2",
        db,
    )
    assert "UTC+8" in json.loads(invalid_time)["error"]

    unknown = await tools_mod.execute_tool(
        "other_tool", "{}", "1:2", db
    )
    assert "未知工具" in json.loads(unknown)["error"]
    db.close()


async def test_tool_result_content_is_clipped(
    tools_mod, store_cls
) -> None:
    db = store_cls()
    db.add_turn("1:2", "长" * 1000, "短", when=_when(1))

    raw = await tools_mod.execute_tool(
        "query_chat_history", "{}", "1:2", db
    )
    data = json.loads(raw)
    assert len(data["turns"][0]["user"]) == 601
    assert data["turns"][0]["user"].endswith("…")
    db.close()
