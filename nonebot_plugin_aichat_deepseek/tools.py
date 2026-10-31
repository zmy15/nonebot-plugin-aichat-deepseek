"""可供模型调用的工具定义与执行逻辑。

提供：
- ``query_chat_history``：按关键词/时间查询历史聊天记录
- ``save_user_memory``：保存用户长期信息、偏好等
- ``search_user_memory``：搜索已保存的长期记忆
- ``delete_user_memory``：删除某条长期记忆

时间统一按 UTC+8 解释。
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from .formatting import strip_markdown
from .history import UTC8, ConversationStore

TOOL_QUERY_HISTORY = "query_chat_history"
TOOL_SAVE_MEMORY = "save_user_memory"
TOOL_SEARCH_MEMORY = "search_user_memory"
TOOL_DELETE_MEMORY = "delete_user_memory"

MEMORY_CATEGORIES = (
    "profile",
    "preference",
    "habit",
    "relationship",
    "fact",
)
MEMORY_CATEGORY_LABELS = {
    "profile": "个人信息",
    "preference": "偏好",
    "habit": "习惯",
    "relationship": "关系",
    "fact": "事实",
}

_MAX_LIMIT = 20
_MAX_CONTENT_CHARS = 600
_MAX_MEMORY_CHARS = 500

QUERY_HISTORY_TOOL: dict[str, Any] = {
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

SAVE_MEMORY_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": TOOL_SAVE_MEMORY,
        "description": (
            "保存用户长期稳定的个人信息、偏好、习惯、关系或重要事实。"
            "当用户主动提供这类信息，或明确要求你记住时调用。"
            "不要保存一次性的临时内容、情绪或对话过程。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
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
            "required": ["content"],
        },
    },
}

SEARCH_MEMORY_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": TOOL_SEARCH_MEMORY,
        "description": "按关键词搜索当前用户已保存的长期记忆。",
        "parameters": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "可选，记忆内容关键词。",
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

DELETE_MEMORY_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": TOOL_DELETE_MEMORY,
        "description": (
            "删除当前用户的一条长期记忆。"
            "用户明确要求忘记某件事时调用，需要使用记忆 ID。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "memory_id": {
                    "type": "integer",
                    "description": "要删除的记忆 ID。",
                },
            },
            "required": ["memory_id"],
        },
    },
}

MEMORY_TOOL_DEFINITIONS = [
    SAVE_MEMORY_TOOL,
    SEARCH_MEMORY_TOOL,
    DELETE_MEMORY_TOOL,
]


def build_tool_definitions(*, include_memory: bool = True) -> list[dict[str, Any]]:
    tools = [QUERY_HISTORY_TOOL]
    if include_memory:
        tools.extend(MEMORY_TOOL_DEFINITIONS)
    return tools


TOOL_DEFINITIONS = build_tool_definitions()

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


def _parse_limit(value: Any, default: int) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        limit = default
    return max(1, min(limit, _MAX_LIMIT))


def _execute_query_history(
    args: dict[str, Any],
    session_key: str,
    store: ConversationStore,
) -> str:
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

    rows = store.query_history(
        session_key,
        start_ts=start_ts,
        end_ts=end_ts,
        keyword=keyword.strip() if keyword else None,
        limit=_parse_limit(args.get("limit", 10), 10),
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


def _execute_save_memory(
    args: dict[str, Any],
    session_key: str,
    store: ConversationStore,
) -> str:
    content = args.get("content")
    if not isinstance(content, str) or not content.strip():
        return _error("content 不能为空")

    content = strip_markdown(content).replace("\n", " ").strip()
    if not content:
        return _error("content 不能为空")
    if len(content) > _MAX_MEMORY_CHARS:
        return _error(f"记忆内容过长，最多 {_MAX_MEMORY_CHARS} 字")

    category = args.get("category", "fact")
    if not isinstance(category, str) or category not in MEMORY_CATEGORIES:
        return _error("category 必须是 profile/preference/habit/relationship/fact")

    memory_id = store.add_memory(session_key, content, category)
    return json.dumps(
        {
            "saved": True,
            "id": memory_id,
            "category": category,
            "content": content,
        },
        ensure_ascii=False,
    )


def _execute_search_memory(
    args: dict[str, Any],
    session_key: str,
    store: ConversationStore,
) -> str:
    keyword = args.get("keyword")
    if keyword is not None and not isinstance(keyword, str):
        return _error("keyword 必须是字符串")

    rows = store.search_memories(
        session_key,
        keyword=keyword.strip() if keyword else None,
        limit=_parse_limit(args.get("limit", 10), 10),
    )
    payload = {
        "count": len(rows),
        "memories": [
            {
                "id": row["id"],
                "category": row["category"],
                "content": _clip(row["content"]),
            }
            for row in rows
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


def _execute_delete_memory(
    args: dict[str, Any],
    session_key: str,
    store: ConversationStore,
) -> str:
    try:
        memory_id = int(args.get("memory_id"))
    except (TypeError, ValueError):
        return _error("memory_id 必须是整数")

    deleted = store.delete_memory(session_key, memory_id)
    return json.dumps(
        {"deleted": deleted, "memory_id": memory_id},
        ensure_ascii=False,
    )


async def execute_tool(
    name: str,
    arguments: str | dict[str, Any],
    session_key: str,
    store: ConversationStore,
) -> str:
    """执行模型请求的工具，返回给模型的字符串结果。"""
    handlers = {
        TOOL_QUERY_HISTORY: _execute_query_history,
        TOOL_SAVE_MEMORY: _execute_save_memory,
        TOOL_SEARCH_MEMORY: _execute_search_memory,
        TOOL_DELETE_MEMORY: _execute_delete_memory,
    }
    handler = handlers.get(name)
    if handler is None:
        return _error(f"未知工具：{name}")

    try:
        args = _parse_arguments(arguments)
    except ValueError as exc:
        return _error(str(exc))

    return handler(args, session_key, store)
