"""``save_group_memory`` 工具的定义与实现。"""

from __future__ import annotations

import json
from typing import Any

from ..formatting import strip_markdown
from .base import (
    Tool,
    ToolContext,
    error,
    group_context,
    make_definition,
)
from .memory import MAX_MEMORY_CHARS, MEMORY_CATEGORIES

NAME = "save_group_memory"

DEFINITION = make_definition(
    NAME,
    "保存整个群聊共享的长期记忆，例如群规则、群活动、"
    "大家共同约定的事情或群里重要的事实。"
    "只保存群级别的信息，不要保存单个成员的私人信息；"
    "成员个人信息请用 save_user_memory。",
    {
        "content": {
            "type": "string",
            "description": "要记住的群聊共享信息，简短具体。",
        },
        "category": {
            "type": "string",
            "enum": list(MEMORY_CATEGORIES),
            "description": "记忆分类，默认 fact。",
        },
    },
    required=("content",),
)


def execute(args: dict[str, Any], ctx: ToolContext) -> str:
    scope = group_context(ctx)
    if scope is None:
        return error("群聊记忆只在群聊中可用")

    content = args.get("content")
    if not isinstance(content, str) or not content.strip():
        return error("content 不能为空")

    content = strip_markdown(content).replace("\n", " ").strip()
    if not content:
        return error("content 不能为空")
    if len(content) > MAX_MEMORY_CHARS:
        return error(f"记忆内容过长，最多 {MAX_MEMORY_CHARS} 字")

    category = args.get("category", "fact")
    if not isinstance(category, str) or category not in MEMORY_CATEGORIES:
        return error(
            "category 必须是 profile/preference/habit/relationship/fact"
        )

    bot_id, group_id = scope
    memory_id = ctx.store.add_group_memory(
        bot_id,
        group_id,
        "group",
        content,
        category=category,
    )
    return json.dumps(
        {
            "saved": True,
            "id": memory_id,
            "category": category,
            "content": content,
            "scope": "group",
        },
        ensure_ascii=False,
    )


TOOL = Tool(
    name=NAME,
    definition=DEFINITION,
    handler=execute,
    group="group_memory",
)
