"""``list_scheduled_tasks`` 工具的定义与实现。"""

from __future__ import annotations

import json
from typing import Any

from ..config import plugin_config
from ..scheduled_tasks import (
    describe_job,
    job_run_at,
    list_user_jobs,
)
from .base import Tool, ToolContext, error, make_definition

NAME = "list_scheduled_tasks"

DEFINITION = make_definition(
    NAME,
    "查看当前私聊用户已创建的定时任务。"
    "返回任务 ID、类型、话题和下次执行时间；"
    "只能查看当前用户自己的任务，不会显示其他用户的任务。",
)


def execute(args: dict[str, Any], ctx: ToolContext) -> str:
    del args
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

    jobs = list_user_jobs(scheduler, self_id, target_id)
    pairs = [(job, job_run_at(job)) for job in jobs]
    pairs.sort(
        key=lambda item: (
            item[1] is None,
            item[1].timestamp() if item[1] is not None else 0.0,
        )
    )
    tasks = [describe_job(job) for job, _ in pairs]
    return json.dumps(
        {
            "count": len(tasks),
            "max_jobs": plugin_config.deepseek_scheduler_max_jobs,
            "tasks": tasks,
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
