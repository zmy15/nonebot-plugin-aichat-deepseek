import json


def test_web_search_tool_definition(tools_mod) -> None:
    tool = next(
        item
        for item in tools_mod.TOOL_DEFINITIONS
        if item["function"]["name"] == "web_search"
    )
    assert tool["type"] == "function"
    assert "site:" in tool["function"]["description"]
    assert "来源链接" not in tool["function"]["description"]
    assert "need_content" in tool["function"]["parameters"]["properties"]

    enabled = tools_mod.build_tool_definitions(
        include_memory=False, include_search=True
    )
    assert [item["function"]["name"] for item in enabled] == [
        "query_chat_history",
        "web_search",
    ]

    disabled = tools_mod.build_tool_definitions(include_memory=False)
    assert "web_search" not in {
        item["function"]["name"] for item in disabled
    }


async def test_web_search_tool_formats_results(tools_mod, store_cls) -> None:
    calls: list[dict] = []

    async def fake_search(
        query,
        *,
        count,
        need_content,
        ori_question=None,
        session_key="",
    ):
        calls.append(
            {
                "query": query,
                "count": count,
                "need_content": need_content,
                "ori_question": ori_question,
                "session_key": session_key,
            }
        )
        return {
            "results": [
                {
                    "title": "结果一",
                    "url": "https://example.com/1",
                    "snippet": "s" * 500,
                    "summary": "m" * 1200,
                    "content": "c" * 4000,
                    "site_name": "Example",
                    "date": "2026-01-01T00:00:00+00:00",
                    "authority": 3,
                    "rerank_score": 2.4,
                },
                {
                    "title": "结果二",
                    "url": "https://example.com/2",
                    "snippet": "短摘要",
                    "summary": "长摘要",
                },
            ]
        }

    store = store_cls()
    raw = await tools_mod.execute_tool(
        "web_search",
        json.dumps(
            {
                "query": " DeepSeek ",
                "count": 2,
                "ori_question": "DeepSeek 最近有什么新闻",
            },
            ensure_ascii=False,
        ),
        "1:2",
        store,
        search_web=fake_search,
    )
    data = json.loads(raw)

    assert data["query"] == "DeepSeek"
    assert data["count"] == 2
    first = data["results"][0]
    assert first["title"] == "结果一"
    assert first["url"] == "https://example.com/1"
    assert len(first["snippet"]) == 401
    assert len(first["summary"]) == 1001
    assert "content" not in first
    assert first["site_name"] == "Example"
    assert first["authority"] == 3
    assert first["rerank_score"] == 2.4

    assert calls[0] == {
        "query": "DeepSeek",
        "count": 2,
        "need_content": False,
        "ori_question": "DeepSeek 最近有什么新闻",
        "session_key": "1:2",
    }

    with_content = json.loads(
        await tools_mod.execute_tool(
            "web_search",
            json.dumps({"query": "DeepSeek", "need_content": True}),
            "1:2",
            store,
            search_web=fake_search,
        )
    )
    assert len(with_content["results"][0]["content"]) == 3001
    store.close()


async def test_web_search_tool_validates_arguments(
    tools_mod, store_cls
) -> None:
    seen: list[int] = []

    async def fake_search(query, *, count, **kwargs):
        seen.append(count)
        return {"results": []}

    store = store_cls()

    for args in (
        {},
        {"query": "   "},
        {"query": "x" * 129},
        {"query": "ok", "count": "abc"},
        {"query": "ok", "need_content": "true"},
        {"query": "ok", "ori_question": "y" * 129},
    ):
        raw = await tools_mod.execute_tool(
            "web_search",
            json.dumps(args, ensure_ascii=False),
            "1:2",
            store,
            search_web=fake_search,
        )
        assert "error" in json.loads(raw)

    empty = json.loads(
        await tools_mod.execute_tool(
            "web_search",
            json.dumps({"query": "ok", "count": 100}),
            "1:2",
            store,
            search_web=fake_search,
        )
    )
    assert empty["count"] == 0
    assert empty["message"] == "没有找到相关结果"
    assert seen == [50]
    store.close()


async def test_web_search_tool_without_service(tools_mod, store_cls) -> None:
    store = store_cls()
    raw = await tools_mod.execute_tool(
        "web_search", '{"query":"ok"}', "1:2", store
    )
    assert "未配置" in json.loads(raw)["error"]
    store.close()


async def test_web_search_tool_formats_errors(
    tools_mod, store_cls
) -> None:
    class SearchError(Exception):
        def __init__(self, message: str, status_code: int | None) -> None:
            super().__init__(message)
            self.status_code = status_code

    async def run(status: int | None) -> str:
        async def fake_search(query, **kwargs):
            raise SearchError("boom", status)

        raw = await tools_mod.execute_tool(
            "web_search",
            '{"query":"ok"}',
            "1:2",
            store,
            search_web=fake_search,
        )
        return json.loads(raw)["error"]

    store = store_cls()
    assert "API Key" in await run(401)
    assert "余额" in await run(402)
    assert "频繁" in await run(429)
    assert "暂时不可用" in await run(503)
    assert "参数不合法" in await run(400)
    assert "网页搜索失败" in await run(None)
    store.close()
