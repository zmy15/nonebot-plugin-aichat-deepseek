"""``search_stickers`` 工具的定义与实现。"""

from __future__ import annotations

import json
from typing import Any

from ..config import plugin_config
from .base import (
    Tool,
    ToolContext,
    clip,
    error,
    make_definition,
    parse_limit,
)

NAME = "search_stickers"

DEFINITION = make_definition(
    NAME,
    "查询当前用户已收藏的表情包。"
    "关键词会匹配表情包的含义和标签；不传关键词时返回常用的表情包。"
    "用于在发表情包前确认有哪些含义可选。",
    {
        "keyword": {
            "type": "string",
            "description": "可选，按含义或标签搜索，例如：无语、开心。",
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

    default_limit = plugin_config.deepseek_sticker_search_limit
    limit = parse_limit(args.get("limit", default_limit), default_limit)
    rows = ctx.store.search_stickers(
        ctx.session_key,
        keyword=keyword.strip() if keyword else None,
        limit=limit,
    )
    return json.dumps(
        {
            "count": len(rows),
            "stickers": [
                {
                    "id": row["id"],
                    "description": clip(row["description"]) or "（未记录含义）",
                    "tags": row["tags"],
                    "uses": row["use_count"],
                }
                for row in rows
            ],
        },
        ensure_ascii=False,
    )


TOOL = Tool(
    name=NAME,
    definition=DEFINITION,
    handler=execute,
    group="stickers",
    enabled=lambda: plugin_config.deepseek_sticker_enabled,
)
