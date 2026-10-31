"""``save_user_memory`` 工具的定义与实现。"""

from __future__ import annotations

import json
from typing import Any

from ..formatting import strip_markdown
from .base import (
    Tool,
    ToolContext,
    error,
    group_scope,
    make_definition,
)
from .memory import MAX_MEMORY_CHARS, MEMORY_CATEGORIES

NAME = "save_user_memory"

DEFINITION = make_definition(
    NAME,
    "保存当前用户长期稳定的个人信息、偏好、习惯、关系或重要事实。"
    "群聊中保存的是当前发言人（按 QQ 区分）的成员记忆。"
    "当用户主动提供这类信息，或明确要求你记住时调用。"
    "不要保存一次性的临时内容、情绪或对话过程。",
    {
        "content": {
            "type": "string",
            "description": (
                "要记住的内容，使用第三人称，简短具体，"
                "例如：喜欢猫 / 住在杭州 / 职业是教师。"
            ),
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

    if ctx.chat_type == "group":
        scope = group_scope(ctx)
        if scope is None:
            return error("群聊记忆上下文不完整")
        bot_id, group_id, sender_id = scope
        memory_id = ctx.store.add_group_memory(
            bot_id,
            group_id,
            "member",
            content,
            user_id=sender_id,
            category=category,
        )
        return json.dumps(
            {
                "saved": True,
                "id": memory_id,
                "category": category,
                "content": content,
                "scope": "group_member",
                "user_id": sender_id,
            },
            ensure_ascii=False,
        )

    memory_id = ctx.store.add_memory(ctx.session_key, content, category)
    return json.dumps(
        {
            "saved": True,
            "id": memory_id,
            "category": category,
            "content": content,
            "scope": "private",
        },
        ensure_ascii=False,
    )


TOOL = Tool(name=NAME, definition=DEFINITION, handler=execute, group="memory")
