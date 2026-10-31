"""``get_user_system_prompt`` 工具的定义与实现。"""

from __future__ import annotations

import json
from typing import Any

from ..config import plugin_config
from .base import Tool, ToolContext, make_definition

NAME = "get_user_system_prompt"

DEFINITION = make_definition(
    NAME,
    "查看当前私聊用户已设置的自定义 system 提示词。",
)


def execute(args: dict[str, Any], ctx: ToolContext) -> str:
    del args
    content = ctx.store.get_user_prompt(ctx.session_key)
    return json.dumps(
        {
            "content": content or None,
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
