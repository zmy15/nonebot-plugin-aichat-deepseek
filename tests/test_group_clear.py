import pytest
from nonebug import App

from tests.test_matcher import make_bot, make_group_event, make_private_event


DONE_456 = "已清空群 456 的全部上下文（消息、摘要和群记忆）。"
USAGE = "用法：/清空群 <群号>，或在目标群内直接发送 /清空群。"


@pytest.fixture(autouse=True)
def clear_state():
    from nonebot_plugin_aichat_deepseek import chat

    chat._GROUP_LAST_REPLY.clear()
    chat._GROUP_LAST_SYSTEM.clear()
    chat._GROUP_LAST_PROMPT_TOKENS.clear()
    chat._GROUP_LAST_HISTORY_COUNT.clear()
    chat._GROUP_LAST_TOOLS.clear()
    yield
    chat._GROUP_LAST_REPLY.clear()
    chat._GROUP_LAST_SYSTEM.clear()
    chat._GROUP_LAST_PROMPT_TOKENS.clear()
    chat._GROUP_LAST_HISTORY_COUNT.clear()
    chat._GROUP_LAST_TOOLS.clear()


def seed_group(chat, bot_id: int, group_id: int) -> None:
    chat.store.clear_group_all(bot_id, group_id)
    chat.store.add_group_message(
        bot_id,
        group_id,
        "user",
        "旧消息",
        sender_id=3,
        sender_name="小明",
    )
    chat.store.add_group_summary(bot_id, group_id, "旧摘要")
    chat.store.add_group_memory(bot_id, group_id, "group", "群共享记忆")
    chat.store.add_group_memory(
        bot_id, group_id, "member", "成员记忆", user_id=3
    )


async def test_superuser_clears_specified_group(
    app: App, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nonebot import get_driver

    from nonebot_plugin_aichat_deepseek import chat

    monkeypatch.setattr(get_driver().config, "superusers", {"2"})
    seed_group(chat, 1, 456)
    chat.store.clear_group_all(1, 457)
    chat.store.add_group_message(1, 457, "user", "其他群消息")

    session_key = "group:1:456"
    chat._GROUP_LAST_REPLY[session_key] = 1.0
    chat._GROUP_LAST_SYSTEM[session_key] = {
        "role": "system",
        "content": "旧 system",
    }
    chat._GROUP_LAST_PROMPT_TOKENS[session_key] = 123
    chat._GROUP_LAST_HISTORY_COUNT[session_key] = 2
    chat._GROUP_LAST_TOOLS[session_key] = []

    async with app.test_matcher(chat.clear_group_command) as ctx:
        bot = make_bot(ctx)
        event = make_private_event("/清空群 456")
        ctx.receive_event(bot, event)
        ctx.should_pass_rule()
        ctx.should_pass_permission()
        ctx.should_call_send(event, DONE_456, result=None)
        ctx.should_finished()

    assert chat.store.count_uncompressed_group_messages(1, 456) == 0
    assert chat.store.list_group_summaries(1, 456) == []
    assert chat.store.list_group_memories(1, 456, "group") == []
    assert chat.store.list_group_memories(1, 456, "member", user_id=3) == []
    assert not chat._GROUP_LAST_REPLY.get(session_key)
    assert not chat._GROUP_LAST_SYSTEM.get(session_key)
    assert not chat._GROUP_LAST_PROMPT_TOKENS.get(session_key)
    assert not chat._GROUP_LAST_HISTORY_COUNT.get(session_key)
    assert not chat._GROUP_LAST_TOOLS.get(session_key)

    # 其他群不受影响
    assert chat.store.count_uncompressed_group_messages(1, 457) == 1
    chat.store.clear_group_all(1, 457)


async def test_clear_group_without_argument_uses_current_group(
    app: App, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nonebot import get_driver

    from nonebot_plugin_aichat_deepseek import chat

    monkeypatch.setattr(get_driver().config, "superusers", {"2"})
    seed_group(chat, 1, 10)

    async with app.test_matcher(chat.clear_group_command) as ctx:
        bot = make_bot(ctx)
        event = make_group_event("/清空群")
        ctx.receive_event(bot, event)
        ctx.should_pass_rule()
        ctx.should_pass_permission()
        ctx.should_call_send(
            event,
            "已清空群 10 的全部上下文（消息、摘要和群记忆）。",
            result=None,
        )
        ctx.should_finished()

    assert chat.store.count_uncompressed_group_messages(1, 10) == 0


async def test_non_superuser_cannot_clear_group(
    app: App, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nonebot import get_driver

    from nonebot_plugin_aichat_deepseek import chat

    monkeypatch.setattr(get_driver().config, "superusers", set())
    seed_group(chat, 1, 654)

    async with app.test_matcher(chat.clear_group_command) as ctx:
        bot = make_bot(ctx)
        event = make_private_event("/清空群 654")
        ctx.receive_event(bot, event)
        ctx.should_pass_rule()
        ctx.should_not_pass_permission()

    assert chat.store.count_uncompressed_group_messages(1, 654) == 1
    chat.store.clear_group_all(1, 654)


async def test_private_clear_group_without_id_shows_usage(
    app: App, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nonebot import get_driver

    from nonebot_plugin_aichat_deepseek import chat

    monkeypatch.setattr(get_driver().config, "superusers", {"2"})

    async with app.test_matcher(chat.clear_group_command) as ctx:
        bot = make_bot(ctx)
        event = make_private_event("/清空群")
        ctx.receive_event(bot, event)
        ctx.should_pass_rule()
        ctx.should_pass_permission()
        ctx.should_call_send(event, USAGE, result=None)
        ctx.should_finished()


def test_store_clear_group_all_removes_memories(store_cls) -> None:
    store = store_cls()
    store.add_group_message(1, 1, "user", "消息")
    store.add_group_summary(1, 1, "摘要")
    store.add_group_memory(1, 1, "group", "群记忆")
    store.add_group_memory(1, 1, "member", "成员记忆", user_id=2)

    store.clear_group_all(1, 1)

    assert store.count_uncompressed_group_messages(1, 1) == 0
    assert store.list_group_summaries(1, 1) == []
    assert store.list_group_memories(1, 1, "group") == []
    assert store.list_group_memories(1, 1, "member", user_id=2) == []
    store.close()
