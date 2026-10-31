"""``search_user_memory`` 工具的定义与实现。"""

from __future__ import annotations

import json
from typing import Any

from .base import (
    Tool,
    ToolContext,
    clip,
    error,
    group_scope,
    make_definition,
    parse_limit,
)

NAME = "search_user_memory"

DEFINITION = make_definition(
    NAME,
    "按关键词搜索当前用户的长期记忆。"
    "群聊中只搜索当前发言人（按 QQ 区分）的成员记忆。",
    {
        "keyword": {
            "type": "string",
            "description": "可选，记忆内容关键词。",
        },
        "limit": {
            "type": "integer",
            "description": "可选，返回条数，1-20，默认 10。",
        },
    },
)


def execute(args: dict[str, Any], ctx: ToolContext) -> str:
    keyword = args.get("keyword")
    if keyword is not None and not isinstance(keyword, str):
        return error("keyword 必须是字符串")

    limit = parse_limit(args.get("limit", 10), 10)
    if ctx.chat_type == "group":
        scope = group_scope(ctx)
        if scope is None:
            return error("群聊记忆上下文不完整")
        bot_id, group_id, sender_id = scope
        rows = ctx.store.search_group_memories(
            bot_id,
            group_id,
            "member",
            user_id=sender_id,
            keyword=keyword.strip() if keyword else None,
            limit=limit,
        )
    else:
        rows = ctx.store.search_memories(
            ctx.session_key,
            keyword=keyword.strip() if keyword else None,
            limit=limit,
        )
    payload = {
        "count": len(rows),
        "memories": [
            {
                "id": row["id"],
                "category": row["category"],
                "content": clip(row["content"]),
            }
            for row in rows
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


TOOL = Tool(name=NAME, definition=DEFINITION, handler=execute, group="memory")
