"""工具基础设施：把工具定义、实现和执行开关解耦。

每个工具模块只依赖这里，并导出一个 ``Tool`` 描述对象；
``registry`` 负责汇总这些对象，``tools`` 包只暴露稳定入口。
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeAlias

from ..history import ConversationStore

MAX_LIST_LIMIT = 20
MAX_CONTENT_CHARS = 600

ToolHandler: TypeAlias = Callable[
    [dict[str, Any], "ToolContext"], str | Awaitable[str]
]
SearchCallable: TypeAlias = Callable[..., Awaitable[dict[str, Any]]]
SchedulerProvider: TypeAlias = Callable[[], Any | None]


def always_enabled() -> bool:
    return True


@dataclass(frozen=True, slots=True)
class Tool:
    """一个独立工具：名称、模型定义、实现和运行时启用条件。"""

    name: str
    definition: dict[str, Any]
    handler: ToolHandler
    group: str = "always"
    enabled: Callable[[], bool] = field(default=always_enabled)


@dataclass(slots=True)
class ToolContext:
    """工具执行时需要的上下文，避免实现直接依赖全局状态。"""

    session_key: str
    store: ConversationStore
    get_bot: Callable[[str], Any]
    search_web: SearchCallable | None = None
    get_scheduler: SchedulerProvider | None = None


def make_definition(
    name: str,
    description: str,
    properties: dict[str, Any] | None = None,
    required: tuple[str, ...] = (),
) -> dict[str, Any]:
    """生成 OpenAI/DeepSeek function calling 格式的工具定义。"""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties or {},
                "required": list(required),
            },
        },
    }


def error(message: str) -> str:
    return json.dumps({"error": message}, ensure_ascii=False)


def parse_arguments(arguments: str | dict[str, Any]) -> dict[str, Any]:
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


def clip(text: str, limit: int = MAX_CONTENT_CHARS) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit]}…"


def parse_limit(value: Any, default: int) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        limit = default
    return max(1, min(limit, MAX_LIST_LIMIT))
