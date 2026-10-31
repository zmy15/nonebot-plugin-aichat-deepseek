"""``delete_user_memory`` 工具的定义与实现。"""

from __future__ import annotations

import json
from typing import Any

from .base import (
    Tool,
    ToolContext,
    error,
    group_scope,
    make_definition,
)

NAME = "delete_user_memory"

DEFINITION = make_definition(
    NAME,
    "删除当前用户的一条长期记忆。"
    "群聊中只删除当前发言人（按 QQ 区分）的成员记忆。"
    "用户明确要求忘记某件事时调用，需要使用记忆 ID。",
    {
        "memory_id": {
            "type": "integer",
            "description": "要删除的记忆 ID。",
        },
    },
    required=("memory_id",),
)


def execute(args: dict[str, Any], ctx: ToolContext) -> str:
    try:
        memory_id = int(args.get("memory_id"))
    except (TypeError, ValueError):
        return error("memory_id 必须是整数")

    if ctx.chat_type == "group":
        scope = group_scope(ctx)
        if scope is None:
            return error("群聊记忆上下文不完整")
        bot_id, group_id, sender_id = scope
        deleted = ctx.store.delete_group_memory(
            bot_id,
            group_id,
            "member",
            memory_id,
            user_id=sender_id,
        )
    else:
        deleted = ctx.store.delete_memory(ctx.session_key, memory_id)
    return json.dumps(
        {"deleted": deleted, "memory_id": memory_id},
        ensure_ascii=False,
    )


TOOL = Tool(name=NAME, definition=DEFINITION, handler=execute, group="memory")
