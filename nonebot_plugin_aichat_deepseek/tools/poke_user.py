"""``poke_user`` 工具的定义与实现。"""

from __future__ import annotations

import json
from typing import Any

from nonebot import logger

from ..config import plugin_config
from .base import Tool, ToolContext, error, make_definition

NAME = "poke_user"

DEFINITION = make_definition(
    NAME,
    "戳一戳当前私聊用户；群聊中戳一戳当前发言人。"
    "用户要求戳一戳、提醒或互动时调用；"
    "不要等用户开口，聊天气氛合适时主动戳一戳；"
    "用户戳你时，也可以戳回去。",
)


async def execute(args: dict[str, Any], ctx: ToolContext) -> str:
    del args
    if ctx.chat_type == "group":
        if (
            ctx.bot_id is None
            or ctx.group_id is None
            or ctx.sender_id is None
        ):
            return error("群聊戳一戳上下文不完整")
        try:
            bot = ctx.get_bot(str(ctx.bot_id))
        except Exception:
            return error("机器人当前未连接，无法戳一戳")
        try:
            await bot.call_api(
                "send_poke",
                group_id=ctx.group_id,
                user_id=ctx.sender_id,
            )
        except Exception as exc:
            logger.warning(f"群聊戳一戳 API 调用失败：{exc!r}")
            return error(f"戳一戳失败：{exc.__class__.__name__}")
        return json.dumps(
            {
                "poked": True,
                "user_id": ctx.sender_id,
                "group_id": ctx.group_id,
                "api": "send_poke",
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
        return error("机器人当前未连接，无法戳一戳")

    try:
        await bot.call_api("friend_poke", user_id=target_id)
        api = "friend_poke"
    except Exception as first_error:
        try:
            await bot.call_api("send_poke", user_id=target_id)
            api = "send_poke"
        except Exception as second_error:
            logger.warning(
                f"戳一戳 API 调用失败：friend_poke={first_error!r} "
                f"send_poke={second_error!r}"
            )
            return error(f"戳一戳失败：{second_error.__class__.__name__}")

    return json.dumps(
        {
            "poked": True,
            "user_id": target_id,
            "api": api,
        },
        ensure_ascii=False,
    )


TOOL = Tool(
    name=NAME,
    definition=DEFINITION,
    handler=execute,
    group="poke",
    enabled=lambda: plugin_config.deepseek_poke_enabled,
)
