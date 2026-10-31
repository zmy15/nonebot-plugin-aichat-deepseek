"""``send_sticker`` 工具的定义与实现。"""

from __future__ import annotations

import json
from typing import Any

from ..config import plugin_config
from ..stickers import StickerError, send_sticker_image
from .base import (
    Tool,
    ToolContext,
    error,
    make_definition,
    sticker_scope_key,
)

NAME = "send_sticker"

DEFINITION = make_definition(
    NAME,
    "从全局表情库中查找并发送一个表情包，私聊和群聊共用。"
    "sticker_id 和 keyword 至少提供一个，优先使用 sticker_id。"
    "不要等用户明确要求，聊天中可以根据情绪主动发送合适的表情包。",
    {
        "sticker_id": {
            "type": "integer",
            "description": "可选，要发送的表情包 ID。",
        },
        "keyword": {
            "type": "string",
            "description": "可选，按含义或标签查找，例如：无语、嘲笑。",
        },
    },
)


async def execute(args: dict[str, Any], ctx: ToolContext) -> str:
    keyword = args.get("keyword")
    if keyword is not None and not isinstance(keyword, str):
        return error("keyword 必须是字符串")

    sticker_key = sticker_scope_key(ctx)

    sticker: dict[str, Any] | None = None
    sticker_id_value = args.get("sticker_id")
    if sticker_id_value is not None:
        try:
            sticker_id = int(sticker_id_value)
        except (TypeError, ValueError):
            return error("sticker_id 必须是整数")
        sticker = ctx.store.get_sticker(sticker_key, sticker_id)
        if sticker is None:
            return error(
                "没有找到该表情包，请使用本轮提示或 search_stickers 返回的 ID"
            )
    elif keyword and keyword.strip():
        rows = ctx.store.search_stickers(
            sticker_key, keyword=keyword.strip(), limit=1
        )
        if not rows:
            examples = [
                row["description"]
                for row in ctx.store.search_stickers(sticker_key, limit=5)
                if row["description"]
            ]
            hint = (
                "；可用的表情包含义：" + "、".join(examples)
                if examples
                else "；表情库为空，或这些表情包还没有记录含义"
            )
            return error(f"没有找到匹配“{keyword.strip()}”的表情包{hint}")
        sticker = rows[0]
    else:
        return error("sticker_id 和 keyword 至少提供一个")

    if ctx.chat_type == "group":
        if ctx.bot_id is None or ctx.group_id is None:
            return error("群聊表情包上下文不完整")
        try:
            bot = ctx.get_bot(str(ctx.bot_id))
        except Exception:
            return error("机器人当前未连接，无法发送表情包")
        try:
            method = await send_sticker_image(
                bot,
                None,
                sticker["file_path"],
                group_id=ctx.group_id,
                session_key=ctx.session_key,
            )
        except StickerError as exc:
            return error(str(exc))
        ctx.store.record_sticker_used(
            sticker_key, int(sticker["id"])
        )
        return json.dumps(
            {
                "sent": True,
                "sticker_id": sticker["id"],
                "description": sticker["description"] or None,
                "tags": sticker["tags"] or None,
                "method": method,
                "group_id": ctx.group_id,
            },
            ensure_ascii=False,
        )

    self_id, separator, user_id = ctx.session_key.partition(":")
    if not separator or not self_id or not user_id:
        return error("无法解析当前会话用户")
    try:
        target_id = int(user_id)
    except ValueError:
        return error("当前会话用户 ID 无效")

    try:
        bot = ctx.get_bot(self_id)
    except Exception:
        return error("机器人当前未连接，无法发送表情包")

    try:
        method = await send_sticker_image(
            bot,
            target_id,
            sticker["file_path"],
            session_key=ctx.session_key,
        )
    except StickerError as exc:
        return error(str(exc))

    ctx.store.record_sticker_used(sticker_key, int(sticker["id"]))
    return json.dumps(
        {
            "sent": True,
            "sticker_id": sticker["id"],
            "description": sticker["description"] or None,
            "tags": sticker["tags"] or None,
            "method": method,
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
