"""``update_scheduled_task`` 工具的定义与实现。"""

from __future__ import annotations

import json
from typing import Any

from ..config import plugin_config
from ..formatting import strip_markdown
from ..scheduled_tasks import (
    add_scheduled_job,
    find_job,
    job_run_at,
    owns_job,
    parse_schedule_time,
)
from .base import Tool, ToolContext, error, make_definition

NAME = "update_scheduled_task"

MAX_TOPIC_CHARS = 200

DEFINITION = make_definition(
    NAME,
    "修改当前私聊用户已有的定时任务。"
    "可以修改执行时间、任务类型或话题，至少提供一个要更新的字段；"
    "只能修改当前用户自己的任务。",
    {
        "job_id": {
            "type": "string",
            "description": "要修改的定时任务 ID。",
        },
        "action": {
            "type": "string",
            "enum": ["chat", "poke"],
            "description": "可选，新的任务类型：chat 主动聊天，poke 戳一戳。",
        },
        "topic": {
            "type": "string",
            "description": "可选，新的聊天话题；留空表示不指定话题。",
        },
        "delay_seconds": {
            "type": "integer",
            "description": "可选，从当前时间起多少秒后执行；与 run_at 二选一。",
        },
        "run_at": {
            "type": "string",
            "description": (
                "可选，新的执行时间，UTC+8，"
                "格式 YYYY-MM-DD HH:MM:SS 或 ISO；与 delay_seconds 二选一。"
            ),
        },
    },
    required=("job_id",),
)


def execute(args: dict[str, Any], ctx: ToolContext) -> str:
    job_id = args.get("job_id")
    if not isinstance(job_id, str) or not job_id.strip():
        return error("job_id 不能为空")
    job_id = job_id.strip()

    has_update = any(
        key in args
        for key in ("action", "topic", "delay_seconds", "run_at")
    )
    if not has_update:
        return error("至少提供一个要更新的字段")

    if ctx.get_scheduler is None:
        return error("定时任务功能未启用")
    scheduler = ctx.get_scheduler()
    if scheduler is None:
        return error(
            "定时任务功能未启用，请先安装 nonebot-plugin-apscheduler"
        )

    self_id, separator, user_id = ctx.session_key.partition(":")
    if not separator or not self_id or not user_id:
        return error("无法解析当前会话用户")
    try:
        target_id = int(user_id)
    except ValueError:
        return error("当前会话用户 ID 无效")

    job = find_job(scheduler, job_id)
    if job is None or not owns_job(job, self_id, target_id):
        return error("没有找到属于当前用户的定时任务")

    kwargs = getattr(job, "kwargs", None)
    if not isinstance(kwargs, dict):
        kwargs = {}
    existing_action = kwargs.get("action")
    if existing_action not in ("chat", "poke"):
        existing_action = "chat"
    existing_topic = kwargs.get("topic") or ""

    if "action" in args:
        action = args.get("action")
        if action not in ("chat", "poke"):
            return error("action 必须是 chat 或 poke")
    else:
        action = existing_action

    if "topic" in args:
        topic_value = args.get("topic")
        if not isinstance(topic_value, str):
            return error("topic 必须是字符串")
        topic = strip_markdown(topic_value).strip()
        if len(topic) > MAX_TOPIC_CHARS:
            return error(f"topic 最多 {MAX_TOPIC_CHARS} 字")
    else:
        topic = existing_topic

    if action == "poke":
        if "topic" in args and topic:
            return error("poke 任务不支持 topic，如需聊天请同时设置 action=chat")
        topic = ""

    if "delay_seconds" in args or "run_at" in args:
        try:
            run_date = parse_schedule_time(args)
        except ValueError as exc:
            return error(str(exc))
    else:
        run_date = job_run_at(job)
        if run_date is None:
            return error("任务已执行或没有下次执行时间，无法修改")

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
        return error(f"更新定时任务失败：{exc.__class__.__name__}")

    return json.dumps(
        {
            "updated": True,
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
