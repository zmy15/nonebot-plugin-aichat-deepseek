"""``describe_sticker`` 工具的定义与实现。"""

from __future__ import annotations

import json
from typing import Any

from ..config import plugin_config
from ..formatting import strip_markdown
from .base import (
    Tool,
    ToolContext,
    error,
    make_definition,
    sticker_scope_key,
)
from .sticker_utils import (
    MAX_STICKER_DESCRIPTION_CHARS,
    normalize_tags,
)

NAME = "describe_sticker"

DEFINITION = make_definition(
    NAME,
    "记录或更新一个已收藏表情包的含义。"
    "所有私聊和群聊共用同一个全局表情库。"
    "用户发送表情包后，消息里会给出表情包 ID；"
    "请根据图片内容或用户说明，用一两个词记录它表达的情绪或含义。"
    "如果用户明确说明了含义，必须优先采用用户的说法。",
    {
        "sticker_id": {
            "type": "integer",
            "description": (
                "表情包 ID，来自本轮消息提示或 search_stickers 结果。"
            ),
        },
        "description": {
            "type": "string",
            "description": (
                "简短含义，例如：无语、嘲笑、开心、委屈、求抱抱。"
                "最多 200 字。"
            ),
        },
        "tags": {
            "type": "string",
            "description": "可选，逗号分隔的标签，例如：无语,翻白眼。",
        },
    },
    required=("sticker_id", "description"),
)


def execute(args: dict[str, Any], ctx: ToolContext) -> str:
    try:
        sticker_id = int(args.get("sticker_id"))
    except (TypeError, ValueError):
        return error("sticker_id 必须是整数")

    description = args.get("description")
    if not isinstance(description, str) or not description.strip():
        return error("description 不能为空")

    description = strip_markdown(description).replace("\n", " ").strip()
    if not description:
        return error("description 不能为空")
    if len(description) > MAX_STICKER_DESCRIPTION_CHARS:
        return error(
            f"表情包含义过长，最多 {MAX_STICKER_DESCRIPTION_CHARS} 字"
        )

    try:
        tags = normalize_tags(args.get("tags"))
    except ValueError as exc:
        return error(str(exc))

    sticker_key = sticker_scope_key(ctx)
    if not ctx.store.update_sticker_description(
        sticker_key, sticker_id, description, tags
    ):
        return error(
            "没有找到该表情包，请使用本轮提示或 search_stickers 返回的 ID"
        )

    return json.dumps(
        {
            "saved": True,
            "sticker_id": sticker_id,
            "description": description,
            "tags": tags or "",
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
