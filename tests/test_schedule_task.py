import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest


class FakeScheduler:
    def __init__(self, jobs=None) -> None:
        self.jobs = list(jobs or [])
        self.added: list[dict] = []

    def get_jobs(self):
        return self.jobs

    def add_job(self, func, trigger, **kwargs) -> None:
        self.added.append({"func": func, "trigger": trigger, **kwargs})
        self.jobs.append(SimpleNamespace(id=kwargs["id"]))


def test_schedule_task_tool_definition(tools_mod) -> None:
    names = {
        tool["function"]["name"] for tool in tools_mod.TOOL_DEFINITIONS
    }
    assert "schedule_task" in names

    enabled = tools_mod.build_tool_definitions(
        include_memory=False, include_scheduler=True
    )
    assert [tool["function"]["name"] for tool in enabled] == [
        "query_chat_history",
        "schedule_task",
        "list_scheduled_tasks",
        "cancel_scheduled_task",
        "update_scheduled_task",
    ]

    disabled = tools_mod.build_tool_definitions(include_memory=False)
    assert "schedule_task" not in {
        tool["function"]["name"] for tool in disabled
    }


async def test_schedule_task_delay_chat(tools_mod, store_cls) -> None:
    from nonebot_plugin_aichat_deepseek.history import UTC8

    scheduler = FakeScheduler()
    store = store_cls()
    before = datetime.now(UTC8)

    raw = await tools_mod.execute_tool(
        "schedule_task",
        json.dumps(
            {
                "action": "chat",
                "topic": "关心用户喝水",
                "delay_seconds": 60,
            },
            ensure_ascii=False,
        ),
        "1:2",
        store,
        get_scheduler=lambda: scheduler,
    )
    data = json.loads(raw)

    assert data["scheduled"] is True
    assert data["action"] == "chat"
    assert data["topic"] == "关心用户喝水"
    assert data["job_id"].startswith("aichat:1:2:")
    assert "content" not in data

    added = scheduler.added[0]
    assert data["run_at"] == added["run_date"].strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    assert added["trigger"] == "date"
    assert added["kwargs"] == {
        "job_id": data["job_id"],
        "self_id": "1",
        "user_id": 2,
        "action": "chat",
        "topic": "关心用户喝水",
    }
    assert before + timedelta(seconds=55) <= added["run_date"]
    assert added["run_date"] <= before + timedelta(seconds=65)
    store.close()


async def test_schedule_task_run_at_poke(tools_mod, store_cls) -> None:
    from nonebot_plugin_aichat_deepseek.history import UTC8

    scheduler = FakeScheduler()
    store = store_cls()
    run_at = (datetime.now(UTC8) + timedelta(minutes=10)).replace(
        microsecond=0
    )

    raw = await tools_mod.execute_tool(
        "schedule_task",
        json.dumps(
            {
                "action": "poke",
                "run_at": run_at.strftime("%Y-%m-%d %H:%M:%S"),
            },
            ensure_ascii=False,
        ),
        "1:2",
        store,
        get_scheduler=lambda: scheduler,
    )
    data = json.loads(raw)

    assert data["scheduled"] is True
    assert data["action"] == "poke"
    assert data["topic"] is None
    assert data["run_at"] == run_at.strftime("%Y-%m-%d %H:%M:%S")
    assert scheduler.added[0]["run_date"] == run_at
    assert scheduler.added[0]["kwargs"]["topic"] == ""
    store.close()


async def test_schedule_task_validates_arguments(
    tools_mod, store_cls
) -> None:
    from nonebot_plugin_aichat_deepseek.config import plugin_config
    from nonebot_plugin_aichat_deepseek.history import UTC8

    scheduler = FakeScheduler()
    store = store_cls()
    now = datetime.now(UTC8)

    cases = [
        {},
        {"action": "unknown"},
        {"action": "chat", "topic": 123, "delay_seconds": 60},
        {"action": "chat", "topic": "x" * 201, "delay_seconds": 60},
        {"action": "chat"},
        {
            "action": "chat",
            "delay_seconds": 60,
            "run_at": (now + timedelta(minutes=1)).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
        },
        {"action": "chat", "delay_seconds": 0},
        {
            "action": "chat",
            "delay_seconds": plugin_config.deepseek_scheduler_max_delay_seconds
            + 1,
        },
        {"action": "chat", "run_at": "昨天"},
        {
            "action": "chat",
            "run_at": (now - timedelta(seconds=1)).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
        },
    ]

    for args in cases:
        raw = await tools_mod.execute_tool(
            "schedule_task",
            json.dumps(args, ensure_ascii=False),
            "1:2",
            store,
            get_scheduler=lambda: scheduler,
        )
        assert "error" in json.loads(raw)

    missing_scheduler = json.loads(
        await tools_mod.execute_tool(
            "schedule_task",
            json.dumps({"action": "poke", "delay_seconds": 60}),
            "1:2",
            store,
            get_scheduler=lambda: None,
        )
    )
    assert "未启用" in missing_scheduler["error"]
    store.close()


async def test_schedule_task_rejects_too_many_jobs(
    tools_mod, store_cls
) -> None:
    from nonebot_plugin_aichat_deepseek.config import plugin_config

    jobs = [
        SimpleNamespace(
            id=f"aichat:1:2:{index}",
            kwargs={"self_id": "1", "user_id": 2},
            next_run_time=None,
        )
        for index in range(plugin_config.deepseek_scheduler_max_jobs)
    ]
    scheduler = FakeScheduler(jobs=jobs)
    store = store_cls()

    raw = await tools_mod.execute_tool(
        "schedule_task",
        json.dumps(
            {"action": "poke", "delay_seconds": 60}, ensure_ascii=False
        ),
        "1:2",
        store,
        get_scheduler=lambda: scheduler,
    )
    assert "上限" in json.loads(raw)["error"]
    store.close()


async def test_run_scheduled_task_chat(monkeypatch) -> None:
    from nonebot_plugin_aichat_deepseek import chat, scheduled_tasks

    calls: list[tuple] = []

    class FakeBot:
        async def call_api(self, api: str, **kwargs):
            calls.append((api, kwargs))
            return {}

    async def fake_proactive(session_key, topic, send) -> None:
        calls.append(("proactive", session_key, topic))
        await send("在忙吗")

    monkeypatch.setattr(chat, "proactive_reply", fake_proactive)
    monkeypatch.setattr(
        scheduled_tasks, "get_bot", lambda self_id: FakeBot()
    )

    await scheduled_tasks.run_scheduled_task(
        job_id="job-1",
        self_id="1",
        user_id=2,
        action="chat",
        topic="关心一下",
    )

    assert calls == [
        ("proactive", "1:2", "关心一下"),
        ("send_private_msg", {"user_id": 2, "message": "在忙吗"}),
    ]


async def test_run_scheduled_task_poke_fallback(monkeypatch) -> None:
    from nonebot_plugin_aichat_deepseek import scheduled_tasks

    calls: list[str] = []

    class FakeBot:
        async def call_api(self, api: str, **kwargs):
            calls.append(api)
            if api == "friend_poke":
                raise RuntimeError("unsupported")
            return {}

    monkeypatch.setattr(
        scheduled_tasks, "get_bot", lambda self_id: FakeBot()
    )

    await scheduled_tasks.run_scheduled_task(
        job_id="job-2",
        self_id="1",
        user_id=2,
        action="poke",
    )
    assert calls == ["friend_poke", "send_poke"]


async def test_run_scheduled_task_skips_missing_bot(monkeypatch) -> None:
    from nonebot_plugin_aichat_deepseek import scheduled_tasks

    def missing(self_id):
        raise ValueError("no bot")

    monkeypatch.setattr(scheduled_tasks, "get_bot", missing)
    await scheduled_tasks.run_scheduled_task(
        job_id="job-3",
        self_id="1",
        user_id=2,
        action="chat",
        topic="关心一下",
    )


def test_schedule_task_definition_fields(tools_mod) -> None:
    tool = next(
        item
        for item in tools_mod.TOOL_DEFINITIONS
        if item["function"]["name"] == "schedule_task"
    )
    properties = tool["function"]["parameters"]["properties"]
    assert set(properties) == {
        "action",
        "topic",
        "delay_seconds",
        "run_at",
    }
    assert tool["function"]["parameters"]["required"] == ["action"]
    description = tool["function"]["description"]
    assert "主动" in description
    assert "不需要用户" in description
    assert "上下文" in description
    assert "内存" in description


@pytest.mark.parametrize("action", ["chat", "poke"])
async def test_schedule_task_action_enum(
    tools_mod, store_cls, action
) -> None:
    scheduler = FakeScheduler()
    store = store_cls()
    raw = await tools_mod.execute_tool(
        "schedule_task",
        json.dumps(
            {
                "action": action,
                "topic": "关心一下" if action == "chat" else "",
                "delay_seconds": 30,
            },
            ensure_ascii=False,
        ),
        "1:2",
        store,
        get_scheduler=lambda: scheduler,
    )
    data = json.loads(raw)
    assert data["action"] == action
    if action == "chat":
        assert data["topic"] == "关心一下"
    else:
        assert data["topic"] is None
    store.close()
