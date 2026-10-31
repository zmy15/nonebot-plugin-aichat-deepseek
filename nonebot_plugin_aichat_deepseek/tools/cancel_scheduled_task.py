"""``cancel_scheduled_task`` 工具的定义与实现。"""

from __future__ import annotations

import json
from typing import Any

from ..config import plugin_config
from ..scheduled_tasks import find_job, owns_job
from .base import Tool, ToolContext, error, make_definition

NAME = "cancel_scheduled_task"

DEFINITION = make_definition(
    NAME,
    "取消当前私聊用户的一个定时任务。"
    "需要先通过 list_scheduled_tasks 或创建任务时获得 job_id；"
    "只能取消当前用户自己的任务。",
    {
        "job_id": {
            "type": "string",
            "description": "要取消的定时任务 ID。",
        },
    },
    required=("job_id",),
)


def execute(args: dict[str, Any], ctx: ToolContext) -> str:
    job_id = args.get("job_id")
    if not isinstance(job_id, str) or not job_id.strip():
        return error("job_id 不能为空")
    job_id = job_id.strip()

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

    remove_job = getattr(scheduler, "remove_job", None)
    if not callable(remove_job):
        return error("当前调度器不支持取消任务")
    try:
        remove_job(job_id)
    except Exception as exc:
        return error(f"取消定时任务失败：{exc.__class__.__name__}")

    return json.dumps(
        {"cancelled": True, "job_id": job_id},
        ensure_ascii=False,
    )


TOOL = Tool(
    name=NAME,
    definition=DEFINITION,
    handler=execute,
    group="scheduler",
    enabled=lambda: plugin_config.deepseek_scheduler_enabled,
)
