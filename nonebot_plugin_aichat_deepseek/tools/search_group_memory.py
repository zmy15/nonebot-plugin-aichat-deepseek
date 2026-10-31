"""``search_group_memory`` 工具的定义与实现。"""

from __future__ import annotations

import json
from typing import Any

from .base import (
    Tool,
    ToolContext,
    clip,
    error,
    group_context,
    make_definition,
    parse_limit,
)

NAME = "search_group_memory"

DEFINITION = make_definition(
    NAME,
    "按关键词搜索当前群聊共享的长期记忆。",
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
    scope = group_context(ctx)
    if scope is None:
        return error("群聊记忆只在群聊中可用")

    keyword = args.get("keyword")
    if keyword is not None and not isinstance(keyword, str):
        return error("keyword 必须是字符串")

    bot_id, group_id = scope
    rows = ctx.store.search_group_memories(
        bot_id,
        group_id,
        "group",
        keyword=keyword.strip() if keyword else None,
        limit=parse_limit(args.get("limit", 10), 10),
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


TOOL = Tool(
    name=NAME,
    definition=DEFINITION,
    handler=execute,
    group="group_memory",
)
