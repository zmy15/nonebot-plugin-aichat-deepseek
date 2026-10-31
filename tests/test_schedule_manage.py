import json
from datetime import datetime, timedelta
from types import SimpleNamespace


class FakeScheduler:
    def __init__(self, jobs=None) -> None:
        self.jobs = list(jobs or [])
        self.added: list[dict] = []
        self.removed: list[str] = []

    def get_jobs(self):
        return list(self.jobs)

    def get_job(self, job_id: str):
        for job in self.jobs:
            if job.id == job_id:
                return job
        return None

    def add_job(self, func, trigger, **kwargs) -> None:
        self.added.append({"func": func, "trigger": trigger, **kwargs})
        job = SimpleNamespace(
            id=kwargs["id"],
            kwargs=kwargs.get("kwargs", {}),
            next_run_time=kwargs.get("run_date"),
        )
        self.jobs = [
            item for item in self.jobs if item.id != job.id
        ] + [job]

    def remove_job(self, job_id: str) -> None:
        self.removed.append(job_id)
        self.jobs = [item for item in self.jobs if item.id != job_id]


def make_job(
    job_id: str,
    *,
    self_id: str = "1",
    user_id: int = 2,
    action: str = "chat",
    topic: str = "",
    run_at: datetime | None = None,
):
    return SimpleNamespace(
        id=job_id,
        kwargs={
            "self_id": self_id,
            "user_id": user_id,
            "action": action,
            "topic": topic,
        },
        next_run_time=run_at,
    )


def test_management_tool_definitions(tools_mod) -> None:
    names = {
        tool["function"]["name"] for tool in tools_mod.TOOL_DEFINITIONS
    }
    assert {
        "list_scheduled_tasks",
        "cancel_scheduled_task",
        "update_scheduled_task",
    } <= names

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


async def test_list_scheduled_tasks_only_current_user(
    tools_mod, store_cls
) -> None:
    from nonebot_plugin_aichat_deepseek.history import UTC8

    now = datetime.now(UTC8)
    scheduler = FakeScheduler(
        [
            make_job(
                "aichat:1:2:a",
                run_at=now + timedelta(minutes=10),
                topic="话题 A",
            ),
            make_job(
                "aichat:1:2:b",
                action="poke",
                run_at=now + timedelta(minutes=5),
            ),
            make_job(
                "aichat:1:3:c",
                user_id=3,
                run_at=now + timedelta(minutes=1),
            ),
            SimpleNamespace(
                id="aichat-followup:1:2",
                kwargs={"self_id": "1", "user_id": 2},
                next_run_time=now + timedelta(minutes=2),
            ),
        ]
    )
    store = store_cls()

    raw = await tools_mod.execute_tool(
        "list_scheduled_tasks",
        "{}",
        "1:2",
        store,
        get_scheduler=lambda: scheduler,
    )
    data = json.loads(raw)

    assert data["count"] == 2
    assert data["max_jobs"] == 5
    assert [task["job_id"] for task in data["tasks"]] == [
        "aichat:1:2:b",
        "aichat:1:2:a",
    ]
    assert data["tasks"][0]["action"] == "poke"
    store.close()


async def test_cancel_scheduled_task(tools_mod, store_cls) -> None:
    from nonebot_plugin_aichat_deepseek.history import UTC8

    now = datetime.now(UTC8)
    own = make_job("aichat:1:2:a", run_at=now + timedelta(minutes=5))
    other = make_job(
        "aichat:1:3:b",
        user_id=3,
        run_at=now + timedelta(minutes=5),
    )
    scheduler = FakeScheduler([own, other])
    store = store_cls()

    raw = await tools_mod.execute_tool(
        "cancel_scheduled_task",
        json.dumps({"job_id": own.id}),
        "1:2",
        store,
        get_scheduler=lambda: scheduler,
    )
    data = json.loads(raw)
    assert data["cancelled"] is True
    assert data["job_id"] == own.id
    assert scheduler.removed == [own.id]

    forbidden = json.loads(
        await tools_mod.execute_tool(
            "cancel_scheduled_task",
            json.dumps({"job_id": other.id}),
            "1:2",
            store,
            get_scheduler=lambda: scheduler,
        )
    )
    assert "没有找到" in forbidden["error"]

    missing = json.loads(
        await tools_mod.execute_tool(
            "cancel_scheduled_task",
            json.dumps({"job_id": "aichat:1:2:missing"}),
            "1:2",
            store,
            get_scheduler=lambda: scheduler,
        )
    )
    assert "没有找到" in missing["error"]
    store.close()


async def test_update_scheduled_task_time_and_topic(
    tools_mod, store_cls
) -> None:
    from nonebot_plugin_aichat_deepseek.history import UTC8

    now = datetime.now(UTC8)
    job = make_job(
        "aichat:1:2:a",
        run_at=now + timedelta(minutes=5),
        topic="旧话题",
    )
    scheduler = FakeScheduler([job])
    store = store_cls()

    raw = await tools_mod.execute_tool(
        "update_scheduled_task",
        json.dumps(
            {
                "job_id": job.id,
                "topic": "新话题",
                "delay_seconds": 60,
            },
            ensure_ascii=False,
        ),
        "1:2",
        store,
        get_scheduler=lambda: scheduler,
    )
    data = json.loads(raw)

    assert data["updated"] is True
    assert data["job_id"] == job.id
    assert data["topic"] == "新话题"
    added = scheduler.added[0]
    assert added["id"] == job.id
    assert added["kwargs"]["action"] == "chat"
    assert added["kwargs"]["topic"] == "新话题"
    assert (
        added["run_date"] - datetime.now(UTC8)
    ).total_seconds() <= 65
    store.close()


async def test_update_scheduled_task_action_to_poke(
    tools_mod, store_cls
) -> None:
    from nonebot_plugin_aichat_deepseek.history import UTC8

    now = datetime.now(UTC8)
    run_at = now + timedelta(minutes=5)
    job = make_job(
        "aichat:1:2:a",
        run_at=run_at,
        topic="旧话题",
    )
    scheduler = FakeScheduler([job])
    store = store_cls()

    raw = await tools_mod.execute_tool(
        "update_scheduled_task",
        json.dumps({"job_id": job.id, "action": "poke"}),
        "1:2",
        store,
        get_scheduler=lambda: scheduler,
    )
    data = json.loads(raw)

    assert data["action"] == "poke"
    assert data["topic"] is None
    added = scheduler.added[0]
    assert added["kwargs"]["topic"] == ""
    assert added["run_date"] == run_at
    store.close()


async def test_update_scheduled_task_validation(
    tools_mod, store_cls
) -> None:
    from nonebot_plugin_aichat_deepseek.history import UTC8

    now = datetime.now(UTC8)
    own = make_job("aichat:1:2:a", run_at=now + timedelta(minutes=5))
    other = make_job(
        "aichat:1:3:b",
        user_id=3,
        run_at=now + timedelta(minutes=5),
    )
    scheduler = FakeScheduler([own, other])
    store = store_cls()

    cases = [
        {"job_id": own.id},
        {"job_id": own.id, "action": "unknown"},
        {"job_id": own.id, "topic": 1},
        {"job_id": own.id, "topic": "x" * 201},
        {"job_id": own.id, "action": "poke", "topic": "xxx"},
        {"job_id": own.id, "delay_seconds": 0},
        {"job_id": own.id, "run_at": "昨天"},
    ]
    for args in cases:
        raw = await tools_mod.execute_tool(
            "update_scheduled_task",
            json.dumps(args, ensure_ascii=False),
            "1:2",
            store,
            get_scheduler=lambda: scheduler,
        )
        assert "error" in json.loads(raw)

    forbidden = json.loads(
        await tools_mod.execute_tool(
            "update_scheduled_task",
            json.dumps({"job_id": other.id, "topic": "x"}),
            "1:2",
            store,
            get_scheduler=lambda: scheduler,
        )
    )
    assert "没有找到" in forbidden["error"]

    no_time = make_job(
        "aichat:1:2:c",
        run_at=None,
        topic="旧话题",
    )
    scheduler.jobs.append(no_time)
    raw = await tools_mod.execute_tool(
        "update_scheduled_task",
        json.dumps({"job_id": no_time.id, "topic": "新话题"}),
        "1:2",
        store,
        get_scheduler=lambda: scheduler,
    )
    assert "没有下次执行时间" in json.loads(raw)["error"]
    store.close()


async def test_management_tools_without_scheduler(
    tools_mod, store_cls
) -> None:
    store = store_cls()

    for name, args in (
        ("list_scheduled_tasks", {}),
        ("cancel_scheduled_task", {"job_id": "aichat:1:2:x"}),
        (
            "update_scheduled_task",
            {"job_id": "aichat:1:2:x", "topic": "x"},
        ),
    ):
        raw = await tools_mod.execute_tool(
            name,
            json.dumps(args),
            "1:2",
            store,
            get_scheduler=lambda: None,
        )
        assert "未启用" in json.loads(raw)["error"]
    store.close()
