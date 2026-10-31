"""``clear_user_system_prompt`` 工具的定义与实现。"""

from __future__ import annotations

import json
from typing import Any

from ..config import plugin_config
from .base import Tool, ToolContext, make_definition

NAME = "clear_user_system_prompt"

DEFINITION = make_definition(
    NAME,
    "清除当前私聊用户的自定义 system 提示词，恢复默认人设和回复风格。",
)


def execute(args: dict[str, Any], ctx: ToolContext) -> str:
    del args
    return json.dumps(
        {"cleared": ctx.store.clear_user_prompt(ctx.session_key)},
        ensure_ascii=False,
    )


TOOL = Tool(
    name=NAME,
    definition=DEFINITION,
    handler=execute,
    group="custom_prompt",
    enabled=lambda: plugin_config.deepseek_custom_prompt_enabled,
)
