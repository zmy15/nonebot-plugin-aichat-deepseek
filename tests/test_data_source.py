import json

import httpx
import pytest


def make_client(client_cls, handler, **overrides):
    kwargs = {
        "api_key": "sk-test",
        "api_base": "https://api.deepseek.com",
        "model": "deepseek-flash",
        "timeout": 5.0,
        "transport": httpx.MockTransport(handler),
    }
    kwargs.update(overrides)
    return client_cls(**kwargs)


MESSAGES = [{"role": "user", "content": "你好"}]


async def test_chat_success_and_payload(ds) -> None:
    seen: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-1",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": " 你好呀 "},
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 2},
            },
        )

    client = make_client(ds.DeepSeekClient, handler)
    assert await client.chat(MESSAGES) == "你好呀"

    request = seen["request"]
    assert request.method == "POST"
    assert str(request.url) == "https://api.deepseek.com/chat/completions"
    assert request.headers["Authorization"] == "Bearer sk-test"
    assert request.headers["Content-Type"] == "application/json"

    payload = json.loads(request.content)
    assert payload["model"] == "deepseek-flash"
    assert payload["messages"] == MESSAGES
    assert payload["stream"] is False
    assert payload["temperature"] == 1.0
    assert "max_tokens" not in payload
    assert "thinking" not in payload


async def test_chat_can_replay_tools_with_choice_none(ds) -> None:
    seen: dict[str, dict] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "摘要"}}]},
        )

    tools = [{"type": "function", "function": {"name": "web_search"}}]
    client = make_client(ds.DeepSeekClient, handler)

    assert (
        await client.chat(
            MESSAGES,
            tools=tools,
            tool_choice="none",
            max_tokens=10000,
            thinking=False,
        )
        == "摘要"
    )

    payload = seen["payload"]
    assert payload["tools"] == tools
    assert payload["tool_choice"] == "none"
    assert payload["max_tokens"] == 10000
    assert payload["thinking"] == {"type": "disabled"}


async def test_base_url_trailing_slash(ds) -> None:
    seen: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "ok"}}]}
        )

    client = make_client(
        ds.DeepSeekClient, handler, api_base="https://api.deepseek.com/"
    )
    await client.chat(MESSAGES)
    assert str(seen["request"].url) == "https://api.deepseek.com/chat/completions"


async def test_max_tokens_and_thinking_payload(ds) -> None:
    seen: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "ok"}}]}
        )

    client = make_client(ds.DeepSeekClient, handler, max_tokens=128, thinking=True)
    await client.chat(MESSAGES)
    payload = json.loads(seen["request"].content)
    assert payload["max_tokens"] == 128
    assert payload["thinking"] == {"type": "enabled"}

    client = make_client(ds.DeepSeekClient, handler, thinking=False)
    await client.chat(MESSAGES)
    payload = json.loads(seen["request"].content)
    assert payload["thinking"] == {"type": "disabled"}


async def test_http_error_uses_api_message(ds) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"error": {"message": "Authentication Fails", "type": "auth"}},
        )

    client = make_client(ds.DeepSeekClient, handler)
    with pytest.raises(ds.DeepSeekError) as exc_info:
        await client.chat(MESSAGES)

    exc = exc_info.value
    assert exc.status_code == 401
    assert "Authentication Fails" in str(exc)


async def test_http_error_without_json_body(ds) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="Too Many Requests")

    client = make_client(ds.DeepSeekClient, handler)
    with pytest.raises(ds.DeepSeekError) as exc_info:
        await client.chat(MESSAGES)

    assert exc_info.value.status_code == 429
    assert "Too Many Requests" in str(exc_info.value)


async def test_invalid_json_response(ds) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    client = make_client(ds.DeepSeekClient, handler)
    with pytest.raises(ds.DeepSeekError, match="无法解析"):
        await client.chat(MESSAGES)


async def test_empty_choices(ds) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    client = make_client(ds.DeepSeekClient, handler)
    with pytest.raises(ds.DeepSeekError, match="空回复"):
        await client.chat(MESSAGES)


async def test_search_success_and_payload(ds) -> None:
    seen: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "DeepSeek",
                        "url": "https://example.com",
                        "snippet": "snippet",
                        "summary": "summary",
                        "content": "content",
                        "site_name": "Example",
                        "date": "2026-01-01T00:00:00+00:00",
                        "authority": 3,
                        "rerank_score": 2.4,
                    }
                ]
            },
        )

    client = make_client(ds.DeepSeekClient, handler)
    data = await client.search(
        "DeepSeek",
        count=5,
        need_content=True,
        ori_question="DeepSeek 最近有什么新闻",
    )

    request = seen["request"]
    assert request.method == "POST"
    assert str(request.url) == "https://api.deepseek.com/v1/tools/search"
    assert request.headers["Authorization"] == "Bearer sk-test"
    assert request.headers["Content-Type"] == "application/json"

    payload = json.loads(request.content)
    assert payload == {
        "query": "DeepSeek",
        "count": 5,
        "need_content": True,
        "ori_question": "DeepSeek 最近有什么新闻",
    }
    assert data["results"][0]["title"] == "DeepSeek"


async def test_search_base_url_with_v1(ds) -> None:
    seen: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return httpx.Response(200, json={"results": []})

    client = make_client(
        ds.DeepSeekClient,
        handler,
        api_base="https://api.deepseek.com/v1/",
    )
    assert await client.search("test") == {"results": []}
    assert str(seen["request"].url) == "https://api.deepseek.com/v1/tools/search"
    assert "ori_question" not in json.loads(seen["request"].content)


async def test_search_http_error(ds) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"error": {"message": "Authentication Fails"}},
        )

    client = make_client(ds.DeepSeekClient, handler)
    with pytest.raises(ds.DeepSeekError) as exc_info:
        await client.search("test")

    assert exc_info.value.status_code == 401
    assert "Authentication Fails" in str(exc_info.value)


async def test_search_invalid_response(ds) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": "not-a-list"})

    client = make_client(ds.DeepSeekClient, handler)
    with pytest.raises(ds.DeepSeekError, match="无法解析"):
        await client.search("test")


async def test_search_without_api_key(ds) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("不应发起请求")

    client = make_client(ds.DeepSeekClient, handler, api_key=None)
    with pytest.raises(ds.DeepSeekError, match="未配置"):
        await client.search("test")


async def test_empty_content(ds) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": " "}}]})

    client = make_client(ds.DeepSeekClient, handler)
    with pytest.raises(ds.DeepSeekError, match="空回复"):
        await client.chat(MESSAGES)


async def test_missing_api_key_does_not_request(ds) -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    client = make_client(ds.DeepSeekClient, handler, api_key=None)
    assert not client.configured
    with pytest.raises(ds.DeepSeekError, match="DEEPSEEK_API_KEY"):
        await client.chat(MESSAGES)
    assert called is False


async def test_timeout_is_wrapped(ds) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    client = make_client(ds.DeepSeekClient, handler)
    with pytest.raises(ds.DeepSeekError, match="超时"):
        await client.chat(MESSAGES)


async def test_network_error_is_wrapped(ds) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = make_client(ds.DeepSeekClient, handler)
    with pytest.raises(ds.DeepSeekError, match="请求 DeepSeek API 失败"):
        await client.chat(MESSAGES)


async def test_chat_with_tools_executes_tool(ds) -> None:
    requests: list[dict] = []
    responses = [
        httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "query_chat_history",
                                        "arguments": '{"keyword":"猫"}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
        ),
        httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": "最终回复"}}
                ]
            },
        ),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return responses.pop(0)

    tools = [
        {
            "type": "function",
            "function": {
                "name": "query_chat_history",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    calls: list[tuple[str, str]] = []

    async def runner(name: str, arguments: str) -> str:
        calls.append((name, arguments))
        return '{"turns": []}'

    client = make_client(ds.DeepSeekClient, handler)
    content = await client.chat_with_tools(
        MESSAGES,
        tools=tools,
        tool_runner=runner,
        max_tool_rounds=3,
    )

    assert content == "最终回复"
    assert calls == [("query_chat_history", '{"keyword":"猫"}')]
    assert requests[0]["tools"] == tools

    second_messages = requests[1]["messages"]
    assert second_messages[-2]["role"] == "assistant"
    assert second_messages[-2]["tool_calls"][0]["id"] == "call_1"
    assert second_messages[-1] == {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": '{"turns": []}',
    }


async def test_chat_with_tools_stops_after_max_rounds(ds) -> None:
    request_count = 0
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        requests.append(json.loads(request.content))
        if request_count <= 2:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": f"call_{request_count}",
                                        "type": "function",
                                        "function": {
                                            "name": "query_chat_history",
                                            "arguments": "{}",
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": "最终回复"}}
                ]
            },
        )

    async def runner(name: str, arguments: str) -> str:
        return "ok"

    client = make_client(ds.DeepSeekClient, handler)
    content = await client.chat_with_tools(
        MESSAGES,
        tools=[{"type": "function", "function": {"name": "t"}}],
        tool_runner=runner,
        max_tool_rounds=2,
    )

    assert content == "最终回复"
    assert request_count == 3
    assert "tools" not in requests[-1]


async def test_tool_runner_error_is_reported_to_model(ds) -> None:
    requests: list[dict] = []
    responses = [
        httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "query_chat_history",
                                        "arguments": "{}",
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
        ),
        httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": "好的"}}
                ]
            },
        ),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return responses.pop(0)

    async def runner(name: str, arguments: str) -> str:
        raise RuntimeError("database down")

    client = make_client(ds.DeepSeekClient, handler)
    await client.chat_with_tools(
        MESSAGES,
        tools=[{"type": "function", "function": {"name": "t"}}],
        tool_runner=runner,
    )

    tool_message = requests[1]["messages"][-1]
    assert tool_message["role"] == "tool"
    assert "执行失败" in tool_message["content"]


async def test_usage_callback(ds) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 10,
                    "prompt_cache_hit_tokens": 40,
                    "prompt_cache_miss_tokens": 60,
                    "prompt_tokens_details": {"cached_tokens": 40},
                },
            },
        )

    seen: list[dict] = []
    client = make_client(ds.DeepSeekClient, handler)
    await client.chat(MESSAGES, on_usage=seen.append)

    assert seen[0]["prompt_cache_hit_tokens"] == 40
    assert seen[0]["prompt_cache_miss_tokens"] == 60


async def test_upload_image_uses_files_api(ds) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": "file-api-test"})

    client = make_client(
        ds.DeepSeekClient,
        handler,
        image_expire_seconds=3600,
    )
    file_id = await client.upload_image(
        b"\x89PNG\r\n\x1a\n" + b"0" * 16,
        "cat.png",
        "image/png",
    )

    assert file_id == "file-api-test"
    request = requests[0]
    assert request.method == "POST"
    assert str(request.url) == "https://api.deepseek.com/files"
    assert request.headers["Authorization"] == "Bearer sk-test"

    body = request.content
    assert b'name="purpose"' in body
    assert b"user_data" in body
    assert b'name="expires_after[anchor]"' in body
    assert b'name="expires_after[seconds]"' in body
    assert b'filename="cat.png"' in body


async def test_upload_image_can_be_permanent(ds) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": "file-api-test"})

    client = make_client(
        ds.DeepSeekClient,
        handler,
        image_expire_seconds=0,
    )
    await client.upload_image(b"\x89PNG\r\n\x1a\n", "a.png", "image/png")

    assert b"expires_after" not in requests[0].content


async def test_upload_image_error(ds) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"error": {"message": "invalid image"}},
        )

    client = make_client(ds.DeepSeekClient, handler)
    with pytest.raises(ds.DeepSeekError) as exc_info:
        await client.upload_image(b"not-image", "a.png", "image/png")

    assert exc_info.value.status_code == 400
    assert "invalid image" in str(exc_info.value)


async def test_upload_image_rejects_invalid_expiry(ds) -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"id": "file-api-test"})

    client = make_client(
        ds.DeepSeekClient,
        handler,
        image_expire_seconds=60,
    )
    with pytest.raises(ds.DeepSeekError, match="有效期"):
        await client.upload_image(b"\x89PNG\r\n\x1a\n", "a.png", "image/png")
    assert called is False
