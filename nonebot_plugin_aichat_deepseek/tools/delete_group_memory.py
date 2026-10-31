"""``delete_group_memory`` 工具的定义与实现。"""

from __future__ import annotations

import json
from typing import Any

from .base import (
    Tool,
    ToolContext,
    error,
    group_context,
    make_definition,
)

NAME = "delete_group_memory"

DEFINITION = make_definition(
    NAME,
    "删除当前群聊共享的一条长期记忆。"
    "群成员明确要求忘记群里的某件事时调用，需要使用记忆 ID。",
    {
        "memory_id": {
            "type": "integer",
            "description": "要删除的群聊记忆 ID。",
        },
    },
    required=("memory_id",),
)


def execute(args: dict[str, Any], ctx: ToolContext) -> str:
    scope = group_context(ctx)
    if scope is None:
        return error("群聊记忆只在群聊中可用")

    try:
        memory_id = int(args.get("memory_id"))
    except (TypeError, ValueError):
        return error("memory_id 必须是整数")

    bot_id, group_id = scope
    deleted = ctx.store.delete_group_memory(
        bot_id,
        group_id,
        "group",
        memory_id,
    )
    return json.dumps(
        {"deleted": deleted, "memory_id": memory_id},
        ensure_ascii=False,
    )


TOOL = Tool(
    name=NAME,
    definition=DEFINITION,
    handler=execute,
    group="group_memory",
)
