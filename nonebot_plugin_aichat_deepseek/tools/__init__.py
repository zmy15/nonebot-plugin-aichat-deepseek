"""模型工具包。

每个工具一个独立模块，模块内包含自己的定义、实现和启用条件；
``registry`` 只负责汇总和分发，``execute_tool`` 保持原有稳定入口。
"""

from __future__ import annotations

from typing import Any

from nonebot import get_bot

from ..history import ConversationStore
from .base import (
    SchedulerProvider,
    SearchCallable,
    Tool,
    ToolContext,
    make_definition,
)
from .cancel_scheduled_task import NAME as TOOL_CANCEL_SCHEDULED_TASK
from .clear_user_prompt import NAME as TOOL_CLEAR_USER_PROMPT
from .delete_memory import NAME as TOOL_DELETE_MEMORY
from .describe_sticker import NAME as TOOL_DESCRIBE_STICKER
from .get_user_prompt import NAME as TOOL_GET_USER_PROMPT
from .list_scheduled_tasks import NAME as TOOL_LIST_SCHEDULED_TASKS
from .memory import MEMORY_CATEGORIES, MEMORY_CATEGORY_LABELS
from .poke_user import NAME as TOOL_POKE_USER
from .query_history import NAME as TOOL_QUERY_HISTORY
from .registry import (
    TOOL_DEFINITIONS,
    build_tool_definitions,
    execute_tool as _execute_tool,
)
from .save_memory import NAME as TOOL_SAVE_MEMORY
from .schedule_task import NAME as TOOL_SCHEDULE_TASK
from .search_memory import NAME as TOOL_SEARCH_MEMORY
from .search_stickers import NAME as TOOL_SEARCH_STICKERS
from .send_sticker import NAME as TOOL_SEND_STICKER
from .set_user_prompt import NAME as TOOL_SET_USER_PROMPT
from .update_scheduled_task import NAME as TOOL_UPDATE_SCHEDULED_TASK
from .web_search import NAME as TOOL_WEB_SEARCH


async def execute_tool(
    name: str,
    arguments: str | dict[str, Any],
    session_key: str,
    store: ConversationStore,
    *,
    search_web: SearchCallable | None = None,
    get_scheduler: SchedulerProvider | None = None,
) -> str:
    """执行模型请求的工具，保留原有入口并注入外部依赖。"""
    return await _execute_tool(
        name,
        arguments,
        session_key,
        store,
        get_bot=get_bot,
        search_web=search_web,
        get_scheduler=get_scheduler,
    )


__all__ = [
    "Tool",
    "ToolContext",
    "make_definition",
    "MEMORY_CATEGORIES",
    "MEMORY_CATEGORY_LABELS",
    "TOOL_DEFINITIONS",
    "build_tool_definitions",
    "execute_tool",
    "TOOL_QUERY_HISTORY",
    "TOOL_WEB_SEARCH",
    "TOOL_SAVE_MEMORY",
    "TOOL_SEARCH_MEMORY",
    "TOOL_DELETE_MEMORY",
    "TOOL_SET_USER_PROMPT",
    "TOOL_GET_USER_PROMPT",
    "TOOL_CLEAR_USER_PROMPT",
    "TOOL_POKE_USER",
    "TOOL_SCHEDULE_TASK",
    "TOOL_LIST_SCHEDULED_TASKS",
    "TOOL_CANCEL_SCHEDULED_TASK",
    "TOOL_UPDATE_SCHEDULED_TASK",
    "TOOL_DESCRIBE_STICKER",
    "TOOL_SEARCH_STICKERS",
    "TOOL_SEND_STICKER",
]
