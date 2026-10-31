import json


def make_group_event(
    text: str = "",
    *,
    segments=None,
    to_me: bool = False,
    group_id: int = 123,
    self_id: int = 1,
    user_id: int = 2,
    nickname: str = "小明",
    card: str = "",
):
    from nonebot.adapters.onebot.v11 import Message
    from nonebot.adapters.onebot.v11.event import GroupMessageEvent, Sender

    message = (
        Message(segments) if segments is not None else Message(text)
    )
    return GroupMessageEvent(
        time=0,
        self_id=self_id,
        post_type="message",
        sub_type="normal",
        user_id=user_id,
        message_type="group",
        message_id=1,
        message=message,
        original_message=message,
        raw_message=str(message),
        font=0,
        sender=Sender(user_id=user_id, nickname=nickname, card=card),
        group_id=group_id,
        to_me=to_me,
    )


def test_group_ids_and_rule(monkeypatch) -> None:
    from nonebot_plugin_aichat_deepseek import chat
    from nonebot_plugin_aichat_deepseek.config import plugin_config

    monkeypatch.setattr(plugin_config, "deepseek_group_enabled", True)

    monkeypatch.setattr(plugin_config, "deepseek_group_ids", "")
    assert chat._group_ids() is None
    assert chat._is_group_message(make_group_event(group_id=999)) is True

    monkeypatch.setattr(
        plugin_config, "deepseek_group_ids", "123, 456"
    )
    assert chat._group_ids() == {123, 456}
    assert chat._is_group_message(make_group_event(group_id=123)) is True
    assert chat._is_group_message(make_group_event(group_id=999)) is False


def test_group_sender_name_and_at_detection() -> None:
    from nonebot.adapters.onebot.v11 import MessageSegment

    from nonebot_plugin_aichat_deepseek import chat

    event = make_group_event(
        segments=[
            MessageSegment.at(1),
            MessageSegment.text(" 你好"),
        ],
        nickname="小明",
    )
    assert chat._group_sender_name(event) == "小明"
    assert chat._has_at_bot(event) is True

    carded = make_group_event(card="群名片", nickname="小明")
    assert chat._group_sender_name(carded) == "群名片"


class GroupClient:
    configured = True

    def __init__(self, answer: str = "你好呀") -> None:
        self.answer = answer
        self.messages: list[dict] | None = None
        self.tools: list[dict] = []
        self.tool_runner = None

    async def chat(self, messages, **kwargs) -> str:
        self.messages = messages
        return self.answer

    async def chat_with_tools(self, messages, **kwargs) -> str:
        self.messages = messages
        self.tools = kwargs.get("tools") or []
        self.tool_runner = kwargs.get("tool_runner")
        return self.answer


async def test_group_at_message_replies_and_archives(monkeypatch) -> None:
    from nonebot_plugin_aichat_deepseek import chat

    fake = GroupClient()
    monkeypatch.setattr(chat, "client", fake)
    chat.store.clear_group_context(1, 123)

    sent: list[str] = []

    async def send(message: str) -> None:
        sent.append(message)

    await chat.process_group_message(
        make_group_event("你好", to_me=True), send
    )

    assert sent == ["你好呀"]
    assert fake.messages is not None
    assert "群聊规则" in fake.messages[0]["content"]
    assert fake.messages[-1] == {
        "role": "user",
        "content": "小明(2)：你好",
    }

    tool_names = {
        tool["function"]["name"] for tool in fake.tools
    }
    assert "save_user_memory" in tool_names
    assert "save_group_memory" in tool_names
    assert "poke_user" in tool_names
    assert "send_sticker" in tool_names
    assert "web_search" in tool_names
    assert "query_chat_history" not in tool_names
    assert "schedule_task" not in tool_names

    history = chat.store.build_group_messages(1, 123)
    assert history[0] == {
        "role": "user",
        "content": "小明(2)：你好",
    }
    assert history[1] == {"role": "assistant", "content": "你好呀"}


async def test_group_at_segment_triggers_reply(monkeypatch) -> None:
    from nonebot.adapters.onebot.v11 import MessageSegment

    from nonebot_plugin_aichat_deepseek import chat

    fake = GroupClient("在呢")
    monkeypatch.setattr(chat, "client", fake)
    chat.store.clear_group_context(1, 123)

    sent: list[str] = []

    async def send(message: str) -> None:
        sent.append(message)

    await chat.process_group_message(
        make_group_event(
            segments=[
                MessageSegment.at(1),
                MessageSegment.text(" 在吗"),
            ],
            to_me=False,
        ),
        send,
    )
    assert sent == ["在呢"]


async def test_group_random_message_only_stores_context(
    monkeypatch,
) -> None:
    from nonebot_plugin_aichat_deepseek import chat

    fake = GroupClient()
    monkeypatch.setattr(chat, "client", fake)
    monkeypatch.setattr(chat, "_should_group_reply", lambda key: False)
    chat.store.clear_group_context(1, 123)

    sent: list[str] = []

    async def send(message: str) -> None:
        sent.append(message)

    await chat.process_group_message(make_group_event("随便聊聊"), send)

    assert sent == []
    assert fake.messages is None
    history = chat.store.build_group_messages(1, 123)
    assert history == [
        {"role": "user", "content": "小明(2)：随便聊聊"}
    ]


async def test_group_random_message_can_reply(monkeypatch) -> None:
    from nonebot_plugin_aichat_deepseek import chat

    fake = GroupClient("哈哈")
    monkeypatch.setattr(chat, "client", fake)
    monkeypatch.setattr(chat, "_should_group_reply", lambda key: True)
    chat.store.clear_group_context(1, 123)

    sent: list[str] = []

    async def send(message: str) -> None:
        sent.append(message)

    await chat.process_group_message(make_group_event("今天好累"), send)

    assert sent == ["哈哈"]
    history = chat.store.build_group_messages(1, 123)
    assert history[0]["content"] == "小明(2)：今天好累"
    assert history[1] == {"role": "assistant", "content": "哈哈"}


async def test_group_context_contains_other_messages(monkeypatch) -> None:
    from nonebot_plugin_aichat_deepseek import chat

    fake = GroupClient("吃点好的")
    monkeypatch.setattr(chat, "client", fake)
    chat.store.clear_group_context(1, 123)
    chat.store.add_group_message(
        1,
        123,
        "user",
        "早上好",
        sender_id=3,
        sender_name="小红",
    )
    chat.store.add_group_message(
        1, 123, "assistant", "早上好呀"
    )

    async def send(message: str) -> None:
        pass

    await chat.process_group_message(
        make_group_event("今天吃什么", to_me=True), send
    )

    assert fake.messages is not None
    contents = [message["content"] for message in fake.messages]
    assert "小红(3)：早上好" in contents
    assert "早上好呀" in contents
    assert contents[-1] == "小明(2)：今天吃什么"


async def test_group_non_text_message_is_stored(monkeypatch) -> None:
    from nonebot.adapters.onebot.v11 import MessageSegment

    from nonebot_plugin_aichat_deepseek import chat

    chat.store.clear_group_context(1, 123)
    sent: list[str] = []

    async def send(message: str) -> None:
        sent.append(message)

    await chat.process_group_message(
        make_group_event(
            segments=[MessageSegment.image("https://example.com/a.png")]
        ),
        send,
    )

    assert sent == []
    history = chat.store.build_group_messages(1, 123)
    assert history == [
        {"role": "user", "content": "小明(2)：[图片]"}
    ]


async def test_group_sticker_image_is_collected(
    monkeypatch, tmp_path
) -> None:
    from nonebot.adapters.onebot.v11 import MessageSegment

    from nonebot_plugin_aichat_deepseek import chat
    from nonebot_plugin_aichat_deepseek.config import plugin_config
    from nonebot_plugin_aichat_deepseek.images import ImagePayload

    png = b"\x89PNG\r\n\x1a\n" + b"0" * 16
    monkeypatch.setattr(
        plugin_config,
        "deepseek_sticker_dir",
        str(tmp_path / "stickers"),
    )
    monkeypatch.setattr(chat, "_should_group_reply", lambda key: False)

    async def fake_fetch(segment, **kwargs):
        return ImagePayload(png, "a.png", "image/png")

    monkeypatch.setattr(chat, "fetch_image", fake_fetch)
    chat.store.clear_group_context(1, 123)
    segment = MessageSegment.image("https://example.com/a.png")
    segment.data["sub_type"] = 1

    async def send(message: str) -> None:
        pass

    await chat.process_group_message(
        make_group_event(segments=[segment]), send
    )

    from nonebot_plugin_aichat_deepseek.history import (
        STICKER_LIBRARY_KEY,
    )

    history = chat.store.build_group_messages(1, 123)
    assert "#" in history[0]["content"]
    stickers = chat.store.search_stickers(STICKER_LIBRARY_KEY)
    assert len(stickers) == 1
    assert chat.store.search_stickers("1:2") == []


def test_group_cooldown(monkeypatch) -> None:
    from nonebot_plugin_aichat_deepseek import chat
    from nonebot_plugin_aichat_deepseek.config import plugin_config

    monkeypatch.setattr(
        plugin_config, "deepseek_group_reply_probability", 1.0
    )
    monkeypatch.setattr(
        plugin_config, "deepseek_group_reply_cooldown", 60.0
    )
    chat._GROUP_LAST_REPLY.clear()

    assert chat._should_group_reply("group:1:123") is True
    chat._mark_group_reply("group:1:123")
    assert chat._should_group_reply("group:1:123") is False


async def test_group_memory_tools_use_member_and_group_scope(
    tools_mod, store_cls
) -> None:
    store = store_cls()

    async def call(name, args, sender_id, sender_name):
        return json.loads(
            await tools_mod.execute_tool(
                name,
                json.dumps(args, ensure_ascii=False),
                "group:1:123",
                store,
                chat_type="group",
                bot_id=1,
                group_id=123,
                sender_id=sender_id,
                sender_name=sender_name,
            )
        )

    saved = await call("save_user_memory", {"content": "喜欢猫"}, 2, "小明")
    assert saved["scope"] == "group_member"
    await call("save_user_memory", {"content": "喜欢狗"}, 3, "小红")
    group_saved = await call(
        "save_group_memory", {"content": "周五晚上开黑"}, 2, "小明"
    )
    assert group_saved["scope"] == "group"

    member_two = store.list_group_memories(
        1, 123, "member", user_id=2
    )
    member_three = store.list_group_memories(
        1, 123, "member", user_id=3
    )
    group_memories = store.list_group_memories(1, 123, "group")
    assert [row["content"] for row in member_two] == ["喜欢猫"]
    assert [row["content"] for row in member_three] == ["喜欢狗"]
    assert [row["content"] for row in group_memories] == [
        "周五晚上开黑"
    ]

    found = await call(
        "search_user_memory", {"keyword": "猫"}, 2, "小明"
    )
    assert found["count"] == 1
    group_found = await call(
        "search_group_memory", {"keyword": "开黑"}, 2, "小明"
    )
    assert group_found["count"] == 1

    deleted = await call(
        "delete_user_memory",
        {"memory_id": member_two[0]["id"]},
        2,
        "小明",
    )
    assert deleted["deleted"] is True
    assert store.list_group_memories(1, 123, "member", user_id=2) == []
    assert store.list_memories("1:2") == []
    store.close()


async def test_group_prompt_injects_group_and_current_member_memory(
    monkeypatch, store_cls
) -> None:
    from nonebot_plugin_aichat_deepseek import chat

    fake = GroupClient("收到")
    monkeypatch.setattr(chat, "client", fake)
    store = store_cls()
    monkeypatch.setattr(chat, "store", store)
    store.clear_group_context(1, 123)
    store.add_group_memory(
        1, 123, "member", "喜欢猫", user_id=2
    )
    store.add_group_memory(
        1, 123, "member", "喜欢狗", user_id=3
    )
    store.add_group_memory(1, 123, "group", "周五开黑")

    async def send(message: str) -> None:
        pass

    await chat.process_group_message(
        make_group_event("你还记得我吗", to_me=True), send
    )

    assert fake.messages is not None
    system = fake.messages[0]["content"]
    assert "【群聊记忆】" in system
    assert "周五开黑" in system
    assert "【当前成员记忆：小明(2)】" in system
    assert "喜欢猫" in system
    assert "喜欢狗" not in system
    store.close()


def test_group_tool_definitions(tools_mod) -> None:
    names = {
        tool["function"]["name"]
        for tool in tools_mod.build_group_tool_definitions()
    }
    assert {
        "save_user_memory",
        "search_user_memory",
        "delete_user_memory",
        "save_group_memory",
        "search_group_memory",
        "delete_group_memory",
    } <= names
    assert {
        "poke_user",
        "describe_sticker",
        "search_stickers",
        "send_sticker",
        "recall_message",
        "web_search",
    } <= names
    assert "query_chat_history" not in names
    assert "schedule_task" not in names


def test_group_and_private_messages_are_separate(store_cls) -> None:
    store = store_cls()
    store.add_turn("1:2", "私聊消息", "私聊回复")
    store.add_group_message(
        1,
        123,
        "user",
        "群聊消息",
        sender_id=3,
        sender_name="小红",
    )

    private = store.build_messages("1:2")
    group = store.build_group_messages(1, 123)
    assert [item["content"] for item in private] == [
        "私聊消息",
        "私聊回复",
    ]
    assert group == [
        {"role": "user", "content": "小红(3)：群聊消息"}
    ]
    store.close()
