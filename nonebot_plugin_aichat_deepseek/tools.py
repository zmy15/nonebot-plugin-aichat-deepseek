"""可供模型调用的工具定义与执行逻辑。

目前提供 ``query_chat_history``：查询当前用户过去的聊天记录。
所有时间参数和返回时间都按 UTC+8 解释。
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from .history import UTC8, ConversationStore

TOOL_QUERY_HISTORY = "query_chat_history"
_MAX_LIMIT = 20
_MAX_CONTENT_CHARS = 600

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": TOOL_QUERY_HISTORY,
            "description": (
                "查询当前用户与 AI 过去的历史聊天记录。"
                "当用户询问以前聊过什么、回忆之前的内容、按时间查找对话时调用。"
                "关键词、开始时间、结束时间可以组合使用；"
                "只能查询当前私聊用户自己的记录；时间统一按 UTC+8。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": (
                            "可选，按关键词搜索用户或 AI 的消息内容，"
                            "可以和开始/结束时间组合使用。"
                        ),
                    },
                    "start_time": {
                        "type": "string",
                        "description": (
                            "可选，开始时间，UTC+8。"
                            "格式：YYYY-MM-DD 或 YYYY-MM-DD HH:MM:SS。"
                        ),
                    },
                    "end_time": {
                        "type": "string",
                        "description": (
                            "可选，结束时间，UTC+8。"
                            "只写日期时包含当天 23:59:59。"
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "description": "可选，返回条数，1-20，默认 10。",
                    },
                },
                "required": [],
            },
        },
    }
]

_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _error(message: str) -> str:
    return json.dumps({"error": message}, ensure_ascii=False)


def _parse_time(value: str, *, end_of_day: bool = False) -> int:
    text = value.strip().replace("/", "-")
    if not text:
        raise ValueError("时间不能为空")
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"

    if _DATE_ONLY_RE.fullmatch(text):
        moment = datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=UTC8)
        if end_of_day:
            moment = moment.replace(hour=23, minute=59, second=59)
        return int(moment.timestamp())

    try:
        moment = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(
            "时间格式无效，请使用 UTC+8 的 YYYY-MM-DD 或 YYYY-MM-DD HH:MM:SS"
        ) from exc

    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC8)
    return int(moment.timestamp())


def _parse_arguments(arguments: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(arguments, dict):
        return arguments
    if not isinstance(arguments, str):
        raise ValueError("工具参数必须是 JSON 字符串")

    try:
        value = json.loads(arguments or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError("工具参数不是合法 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("工具参数必须是 JSON 对象")
    return value


def _clip(text: str, limit: int = _MAX_CONTENT_CHARS) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit]}…"


async def execute_tool(
    name: str,
    arguments: str | dict[str, Any],
    session_key: str,
    store: ConversationStore,
) -> str:
    """执行模型请求的工具，返回给模型的字符串结果。"""
    if name != TOOL_QUERY_HISTORY:
        return _error(f"未知工具：{name}")

    try:
        args = _parse_arguments(arguments)
    except ValueError as exc:
        return _error(str(exc))

    keyword = args.get("keyword")
    if keyword is not None and not isinstance(keyword, str):
        return _error("keyword 必须是字符串")

    start_value = args.get("start_time")
    end_value = args.get("end_time")
    if start_value is not None and not isinstance(start_value, str):
        return _error("start_time 必须是字符串")
    if end_value is not None and not isinstance(end_value, str):
        return _error("end_time 必须是字符串")

    try:
        start_ts = _parse_time(start_value) if start_value else None
        end_ts = (
            _parse_time(end_value, end_of_day=True) if end_value else None
        )
    except ValueError as exc:
        return _error(str(exc))

    raw_limit = args.get("limit", 10)
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(limit, _MAX_LIMIT))

    rows = store.query_history(
        session_key,
        start_ts=start_ts,
        end_ts=end_ts,
        keyword=keyword.strip() if keyword else None,
        limit=limit,
    )
    payload = {
        "timezone": "UTC+8",
        "count": len(rows),
        "turns": [
            {
                "time": row["time"],
                "user": _clip(row["user"]),
                "assistant": _clip(row["assistant"]),
            }
            for row in rows
        ],
    }
    return json.dumps(payload, ensure_ascii=False)
