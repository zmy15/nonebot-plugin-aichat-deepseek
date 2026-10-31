"""工具注册表：只负责汇总定义和分发调用，不包含任何工具实现。"""

from __future__ import annotations

import inspect
import json
import time
from typing import Any, Callable

from nonebot import logger

from ..history import ConversationStore
from .base import (
    SchedulerProvider,
    SearchCallable,
    Tool,
    ToolContext,
    error,
    parse_arguments,
)
from .cancel_scheduled_task import TOOL as CANCEL_SCHEDULED_TASK_TOOL
from .clear_user_prompt import TOOL as CLEAR_USER_PROMPT_TOOL
from .delete_memory import TOOL as DELETE_MEMORY_TOOL
from .describe_sticker import TOOL as DESCRIBE_STICKER_TOOL
from .get_user_prompt import TOOL as GET_USER_PROMPT_TOOL
from .list_scheduled_tasks import TOOL as LIST_SCHEDULED_TASKS_TOOL
from .poke_user import TOOL as POKE_USER_TOOL
from .query_history import TOOL as QUERY_HISTORY_TOOL
from .schedule_task import TOOL as SCHEDULE_TASK_TOOL
from .save_memory import TOOL as SAVE_MEMORY_TOOL
from .search_memory import TOOL as SEARCH_MEMORY_TOOL
from .search_stickers import TOOL as SEARCH_STICKERS_TOOL
from .send_sticker import TOOL as SEND_STICKER_TOOL
from .set_user_prompt import TOOL as SET_USER_PROMPT_TOOL
from .update_scheduled_task import TOOL as UPDATE_SCHEDULED_TASK_TOOL
from .web_search import TOOL as WEB_SEARCH_TOOL

ALL_TOOLS: tuple[Tool, ...] = (
    QUERY_HISTORY_TOOL,
    WEB_SEARCH_TOOL,
    SAVE_MEMORY_TOOL,
    SEARCH_MEMORY_TOOL,
    DELETE_MEMORY_TOOL,
    SET_USER_PROMPT_TOOL,
    GET_USER_PROMPT_TOOL,
    CLEAR_USER_PROMPT_TOOL,
    POKE_USER_TOOL,
    SCHEDULE_TASK_TOOL,
    LIST_SCHEDULED_TASKS_TOOL,
    CANCEL_SCHEDULED_TASK_TOOL,
    UPDATE_SCHEDULED_TASK_TOOL,
    DESCRIBE_STICKER_TOOL,
    SEARCH_STICKERS_TOOL,
    SEND_STICKER_TOOL,
)

TOOL_BY_NAME: dict[str, Tool] = {tool.name: tool for tool in ALL_TOOLS}


def build_tool_definitions(
    *,
    include_memory: bool = True,
    include_custom_prompt: bool = False,
    include_poke: bool = False,
    include_stickers: bool = False,
    include_search: bool = False,
    include_scheduler: bool = False,
) -> list[dict[str, Any]]:
    groups = {"always"}
    if include_memory:
        groups.add("memory")
    if include_custom_prompt:
        groups.add("custom_prompt")
    if include_poke:
        groups.add("poke")
    if include_stickers:
        groups.add("stickers")
    if include_search:
        groups.add("search")
    if include_scheduler:
        groups.add("scheduler")
    return [
        tool.definition for tool in ALL_TOOLS if tool.group in groups
    ]


TOOL_DEFINITIONS = build_tool_definitions(
    include_custom_prompt=True,
    include_poke=True,
    include_stickers=True,
    include_search=True,
    include_scheduler=True,
)


async def execute_tool(
    name: str,
    arguments: str | dict[str, Any],
    session_key: str,
    store: ConversationStore,
    *,
    get_bot: Callable[[str], Any],
    search_web: SearchCallable | None = None,
    get_scheduler: SchedulerProvider | None = None,
) -> str:
    """执行模型请求的工具，返回给模型的字符串结果。"""
    started = time.perf_counter()
    args_size = (
        len(arguments)
        if isinstance(arguments, str)
        else len(json.dumps(arguments, ensure_ascii=False))
    )
    logger.info(
        f"[tool] start session={session_key} name={name} "
        f"args_len={args_size}"
    )

    tool = TOOL_BY_NAME.get(name)
    if tool is None or not tool.enabled():
        logger.warning(
            f"[tool] error session={session_key} name={name} "
            f"reason=unknown_tool duration_ms={_elapsed_ms(started)}"
        )
        return error(f"未知工具：{name}")

    try:
        args = parse_arguments(arguments)
    except ValueError as exc:
        logger.warning(
            f"[tool] error session={session_key} name={name} "
            f"reason=invalid_arguments duration_ms={_elapsed_ms(started)} "
            f"message={exc}"
        )
        return error(str(exc))

    context = ToolContext(
        session_key=session_key,
        store=store,
        get_bot=get_bot,
        search_web=search_web,
        get_scheduler=get_scheduler,
    )
    try:
        result = tool.handler(args, context)
        if inspect.isawaitable(result):
            result = await result
    except Exception:
        logger.exception(
            f"[tool] error session={session_key} name={name} "
            f"reason=exception duration_ms={_elapsed_ms(started)}"
        )
        raise

    status = "ok"
    error_message = ""
    try:
        payload = json.loads(result)
    except (TypeError, ValueError):
        payload = None
    if isinstance(payload, dict) and "error" in payload:
        status = "error"
        error_message = str(payload["error"])[:200]

    logger.info(
        f"[tool] done session={session_key} name={name} status={status} "
        f"duration_ms={_elapsed_ms(started)} result_chars={len(result)}"
        + (f" error={error_message}" if error_message else "")
    )
    return result


def _elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)
