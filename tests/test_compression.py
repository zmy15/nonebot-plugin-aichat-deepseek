class FakeClient:
    configured = True

    def __init__(self, *replies: str, error: Exception | None = None) -> None:
        self.replies = list(replies)
        self.error = error
        self.requests: list[list[dict[str, str]]] = []

    async def chat(self, messages: list[dict[str, str]]) -> str:
        self.requests.append(list(messages))
        if self.error is not None:
            raise self.error
        return self.replies.pop(0)


async def test_compress_if_needed_uses_summary_model(
    monkeypatch, store_cls
) -> None:
    from nonebot_plugin_aichat_deepseek import chat

    fake = FakeClient("**新摘要**")
    store = store_cls(max_turns=30, trigger_turns=1, batch_messages=2)
    store.add_turn("1:2", "q1", "a1")
    store.add_turn("1:2", "q2", "a2")

    monkeypatch.setattr(chat, "client", fake)
    monkeypatch.setattr(chat, "store", store)

    await chat.compress_if_needed("1:2")

    assert store.get_summary("1:2") == "新摘要"
    assert store.build_messages("1:2") == [
        {"role": "user", "content": "q2"},
        {"role": "assistant", "content": "a2"},
    ]
    assert len(fake.requests) == 1
    prompt = fake.requests[0][1]["content"]
    assert "q1" in prompt
    assert "a1" in prompt
    assert "q2" not in prompt
    store.close()


async def test_compress_skipped_when_below_threshold(
    monkeypatch, store_cls
) -> None:
    from nonebot_plugin_aichat_deepseek import chat

    fake = FakeClient("不应该被调用")
    store = store_cls(max_turns=30, trigger_turns=30, batch_messages=20)
    store.add_turn("1:2", "q1", "a1")

    monkeypatch.setattr(chat, "client", fake)
    monkeypatch.setattr(chat, "store", store)

    await chat.compress_if_needed("1:2")

    assert fake.requests == []
    assert store.get_summary("1:2") == ""
    store.close()


async def test_compression_failure_keeps_history(
    monkeypatch, store_cls
) -> None:
    from nonebot_plugin_aichat_deepseek import chat
    from nonebot_plugin_aichat_deepseek.data_source import DeepSeekError

    fake = FakeClient(error=DeepSeekError("summary failed"))
    store = store_cls(max_turns=30, trigger_turns=1, batch_messages=2)
    store.add_turn("1:2", "q1", "a1")
    store.add_turn("1:2", "q2", "a2")

    monkeypatch.setattr(chat, "client", fake)
    monkeypatch.setattr(chat, "store", store)

    await chat.compress_if_needed("1:2")

    assert store.get_summary("1:2") == ""
    assert len(store.build_messages("1:2")) == 4
    store.close()


def test_summary_is_after_system_rules() -> None:
    from nonebot_plugin_aichat_deepseek import chat

    prompt = chat._build_system_prompt("用户喜欢猫")
    assert "【历史对话摘要】" in prompt
    assert "用户喜欢猫" in prompt
    assert prompt.index("用户喜欢猫") > prompt.index("输出要求")


async def test_reply_triggers_compression(monkeypatch, store_cls) -> None:
    from nonebot_plugin_aichat_deepseek import chat
    from nonebot_plugin_aichat_deepseek.config import plugin_config

    fake = FakeClient("回答1", "回答2", "摘要")
    store = store_cls(max_turns=30, trigger_turns=1, batch_messages=2)

    monkeypatch.setattr(chat, "client", fake)
    monkeypatch.setattr(chat, "store", store)
    monkeypatch.setattr(plugin_config, "deepseek_reply_interval", 0.0)
    monkeypatch.setattr(plugin_config, "deepseek_reply_interval_jitter", 0.0)
    monkeypatch.setattr(plugin_config, "deepseek_reply_max_segments", 4)

    sent: list[str] = []

    async def send(message: str) -> None:
        sent.append(message)

    await chat.reply("1:2", "问题1", send)
    assert store.get_summary("1:2") == ""

    await chat.reply("1:2", "问题2", send)

    assert sent == ["回答1", "回答2"]
    assert store.get_summary("1:2") == "摘要"
    assert store.build_messages("1:2") == [
        {"role": "user", "content": "问题2"},
        {"role": "assistant", "content": "回答2"},
    ]
    store.close()
