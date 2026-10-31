"""``set_user_system_prompt`` 工具的定义与实现。"""

from __future__ import annotations

import json
from typing import Any

from ..config import plugin_config
from .base import Tool, ToolContext, error, make_definition

NAME = "set_user_system_prompt"

DEFINITION = make_definition(
    NAME,
    "设置当前私聊用户专属的 system 提示词，用来改变人设、语气、"
    "回复风格或长期设定。"
    "当用户明确说“以后用……语气回复”“记住我的设定”“按这个风格来”时调用。"
    "会覆盖该用户之前的自定义提示词，只影响当前用户。",
    {
        "content": {
            "type": "string",
            "description": (
                "完整的自定义 system 提示词，简洁明确，"
                "例如：以后用简短、傲娇的语气回复我。"
            ),
        },
    },
    required=("content",),
)


def execute(args: dict[str, Any], ctx: ToolContext) -> str:
    content = args.get("content")
    if not isinstance(content, str):
        return error("content 必须是字符串")

    content = content.strip()
    if not content:
        return error("自定义提示词不能为空")

    max_chars = plugin_config.deepseek_custom_prompt_max_chars
    if len(content) > max_chars:
        return error(f"自定义提示词不能超过 {max_chars} 个字符")

    ctx.store.set_user_prompt(ctx.session_key, content)
    return json.dumps(
        {
            "saved": True,
            "content": content,
            "length": len(content),
        },
        ensure_ascii=False,
    )


TOOL = Tool(
    name=NAME,
    definition=DEFINITION,
    handler=execute,
    group="custom_prompt",
    enabled=lambda: plugin_config.deepseek_custom_prompt_enabled,
)
