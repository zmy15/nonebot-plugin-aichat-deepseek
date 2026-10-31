"""``schedule_task`` 工具的定义与实现。"""

from __future__ import annotations

import json
from typing import Any

from ..config import plugin_config
from ..formatting import strip_markdown
from ..scheduled_tasks import (
    add_scheduled_job,
    new_job_id,
    owns_job,
    parse_schedule_time,
)
from .base import Tool, ToolContext, error, make_definition

NAME = "schedule_task"

MAX_TOPIC_CHARS = 200

DEFINITION = make_definition(
    NAME,
    "创建一个定时任务，到点后由你主动找当前私聊用户聊天，或戳一戳。"
    "每次回复时都可以主动判断是否需要安排，"
    "不需要用户明确要求定时；"
    "例如用户说要去忙、吃饭、睡觉、出门，或聊天告一段落时，"
    "可以安排稍后关心。"
    "主动聊天时你会根据上下文、人设和记忆生成消息，"
    "而不是发送固定文本。"
    "只作用于当前私聊用户，不能指定其他人；"
    "任务保存在内存中，机器人重启后会丢失。",
    {
        "action": {
            "type": "string",
            "enum": ["chat", "poke"],
            "description": "任务类型：chat 主动聊天，poke 戳一戳。",
        },
        "topic": {
            "type": "string",
            "description": (
                "可选，这次主动聊天想聊什么、想表达什么，"
                "例如：关心用户喝水 / 问问他今天过得怎么样。"
                "留空则自由发挥。"
            ),
        },
        "delay_seconds": {
            "type": "integer",
            "description": (
                "多少秒后执行，1 到配置的最大延迟秒数（默认 7 天）。"
                "与 run_at 二选一。"
            ),
        },
        "run_at": {
            "type": "string",
            "description": (
                "指定执行时间，UTC+8，格式 YYYY-MM-DD HH:MM:SS 或 ISO。"
                "与 delay_seconds 二选一。"
            ),
        },
    },
    required=("action",),
)


def _active_job_count(
    scheduler: Any,
    self_id: str,
    user_id: int,
) -> int:
    get_jobs = getattr(scheduler, "get_jobs", None)
    if not callable(get_jobs):
        return 0
    try:
        jobs = get_jobs()
    except Exception:
        return 0
    return sum(
        1 for job in jobs if owns_job(job, self_id, user_id)
    )


def execute(args: dict[str, Any], ctx: ToolContext) -> str:
    action = args.get("action")
    if action not in ("chat", "poke"):
        return error("action 必须是 chat 或 poke")

    topic_value = args.get("topic")
    topic = ""
    if topic_value is not None:
        if not isinstance(topic_value, str):
            return error("topic 必须是字符串")
        topic = strip_markdown(topic_value).strip()
        if len(topic) > MAX_TOPIC_CHARS:
            return error(f"topic 最多 {MAX_TOPIC_CHARS} 字")
    if action == "poke":
        topic = ""

    try:
        run_date = parse_schedule_time(args)
    except ValueError as exc:
        return error(str(exc))

    self_id, separator, user_id = ctx.session_key.partition(":")
    if not separator or not self_id or not user_id:
        return error("无法解析当前会话用户")
    try:
        target_id = int(user_id)
    except ValueError:
        return error("当前会话用户 ID 无效")

    if ctx.get_scheduler is None:
        return error("定时任务功能未启用")
    scheduler = ctx.get_scheduler()
    if scheduler is None:
        return error(
            "定时任务功能未启用，请先安装 nonebot-plugin-apscheduler"
        )

    max_jobs = plugin_config.deepseek_scheduler_max_jobs
    if _active_job_count(scheduler, self_id, target_id) >= max_jobs:
        return error(f"当前定时任务已达到上限（{max_jobs} 个）")

    job_id = new_job_id(self_id, target_id)
    try:
        add_scheduled_job(
            scheduler,
            job_id=job_id,
            self_id=self_id,
            user_id=target_id,
            action=action,
            topic=topic,
            run_date=run_date,
        )
    except Exception as exc:
        return error(f"创建定时任务失败：{exc.__class__.__name__}")

    return json.dumps(
        {
            "scheduled": True,
            "job_id": job_id,
            "action": action,
            "topic": topic or None,
            "run_at": run_date.strftime("%Y-%m-%d %H:%M:%S"),
        },
        ensure_ascii=False,
    )


TOOL = Tool(
    name=NAME,
    definition=DEFINITION,
    handler=execute,
    group="scheduler",
    enabled=lambda: plugin_config.deepseek_scheduler_enabled,
)
