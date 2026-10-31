"""``recall_message`` 工具的定义与实现。"""

from __future__ import annotations

import json
from typing import Any

from nonebot import logger

from ..config import plugin_config
from ..sent_messages import MAX_SENT_MESSAGES, recent, remove
from .base import Tool, ToolContext, clip, error, make_definition

NAME = "recall_message"
MAX_RECALL = 5


DEFINITION = make_definition(
    NAME,
    "尝试撤回你在当前会话中最近发送的消息。"
    "可以按最近条数撤回，也可以用 keyword 按发送内容筛选要撤回的消息。"
    "只在发现自己发错内容、需要纠正刚才的消息，或用户要求撤回时调用；"
    "只能撤回机器人自己发送的消息，是否成功取决于平台是否仍允许撤回。",
    {
        "count": {
            "type": "integer",
            "description": "最多撤回几条，默认 1，最多 5。",
        },
        "keyword": {
            "type": "string",
            "description": (
                "可选，按机器人发送内容包含的关键词筛选，"
                "例如“抱歉”或“稍等”。"
            ),
        },
    },
)


def _bot_id(ctx: ToolContext) -> int | None:
    if ctx.chat_type == "group":
        return ctx.bot_id
    self_id, separator, _ = ctx.session_key.partition(":")
    if not separator or not self_id:
        return None
    try:
        return int(self_id)
    except ValueError:
        return None


async def execute(args: dict[str, Any], ctx: ToolContext) -> str:
    try:
        count = int(args.get("count", 1))
    except (TypeError, ValueError):
        return error("count 必须是整数")
    count = max(1, min(count, MAX_RECALL))

    keyword_value = args.get("keyword")
    if keyword_value is not None and not isinstance(keyword_value, str):
        return error("keyword 必须是字符串")
    keyword = (keyword_value or "").strip()

    pool = recent(ctx.session_key, MAX_SENT_MESSAGES)
    if not pool:
        return error(
            "当前会话没有可撤回的机器人消息记录（只记录本次运行中"
            "最近 2 分钟发送的消息）"
        )

    if keyword:
        messages = [
            item
            for item in pool
            if keyword.casefold() in item.content.casefold()
        ][-count:]
        if not messages:
            return error(
                f"最近 2 分钟内没有找到包含“{keyword}”的机器人消息"
            )
    else:
        messages = pool[-count:]

    bot_id = _bot_id(ctx)
    if bot_id is None:
        return error("无法确定当前机器人，不能撤回消息")
    try:
        bot = ctx.get_bot(str(bot_id))
    except Exception:
        return error("机器人当前未连接，无法撤回消息")

    recalled: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for item in reversed(messages):
        try:
            await bot.call_api("delete_msg", message_id=item.message_id)
        except Exception as exc:
            logger.warning(
                f"撤回消息失败 message_id={item.message_id}：{exc!r}"
            )
            failed.append(
                {
                    "message_id": item.message_id,
                    "error": exc.__class__.__name__,
                }
            )
            continue
        remove(ctx.session_key, item.message_id)
        recalled.append(
            {
                "message_id": item.message_id,
                "preview": clip(item.content, 40),
            }
        )

    if not recalled and failed:
        return error(
            "撤回失败，可能已超过平台允许的撤回时间："
            + "、".join(str(item["message_id"]) for item in failed)
        )

    return json.dumps(
        {
            "recalled": recalled,
            "failed": failed,
            "requested": count,
            "keyword": keyword or None,
        },
        ensure_ascii=False,
    )


TOOL = Tool(
    name=NAME,
    definition=DEFINITION,
    handler=execute,
    group="recall",
    enabled=lambda: plugin_config.deepseek_recall_enabled,
)
