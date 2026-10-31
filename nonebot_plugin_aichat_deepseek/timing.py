"""回复节奏、命令前缀和提问判断等轻量工具。"""

from __future__ import annotations

import random

from nonebot import get_driver

from .config import plugin_config


def _starts_with_command(text: str) -> bool:
    """以命令前缀开头的消息交给命令响应器，避免和 /ping 等命令冲突。"""
    command_start = get_driver().config.command_start or set()
    return any(prefix and text.startswith(prefix) for prefix in command_start)


def next_reply_interval() -> float:
    """计算两条消息之间的等待秒数，带随机抖动，避免机械感。"""
    interval = plugin_config.deepseek_reply_interval
    jitter = plugin_config.deepseek_reply_interval_jitter
    if interval <= 0 and jitter <= 0:
        return 0.0
    return max(0.0, interval + random.uniform(-jitter, jitter))


def next_initial_delay() -> float:
    """首次回复前的随机延迟，模拟真人看到消息后停顿一下。"""
    delay = plugin_config.deepseek_reply_delay
    jitter = plugin_config.deepseek_reply_delay_jitter
    if delay <= 0 and jitter <= 0:
        return 0.0
    return max(0.0, delay + random.uniform(-jitter, jitter))


_QUESTION_MARKERS = (
    "怎么样",
    "好不好",
    "要不要",
    "是不是",
    "有没有",
    "在吗",
    "忙吗",
    "吃了吗",
)


def _looks_like_question(text: str) -> bool:
    text = text.strip()
    if not text:
        return False
    if "?" in text or "？" in text:
        return True
    if text.endswith(("吗", "呢", "嘛", "么")):
        return True
    return any(marker in text for marker in _QUESTION_MARKERS)
