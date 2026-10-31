"""token 用量统计、对话日志和错误文案。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from nonebot import logger

from .data_source import DeepSeekError


def _usage_numbers(usage: Mapping[str, Any]) -> tuple[int, int, int, int]:
    """返回 cache_hit / cache_miss / prompt_tokens / completion_tokens。"""
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    details = usage.get("prompt_tokens_details")
    cached = details.get("cached_tokens") if isinstance(details, dict) else None

    cache_hit = usage.get("prompt_cache_hit_tokens", cached)
    cache_hit = int(cache_hit or 0)
    cache_miss = usage.get("prompt_cache_miss_tokens")
    cache_miss = (
        int(cache_miss)
        if cache_miss is not None
        else max(0, prompt_tokens - cache_hit)
    )
    completion_tokens = int(usage.get("completion_tokens") or 0)
    return cache_hit, cache_miss, prompt_tokens, completion_tokens


def _merge_usage(total: dict[str, int], usage: Mapping[str, Any]) -> None:
    cache_hit, cache_miss, prompt_tokens, completion_tokens = _usage_numbers(
        usage
    )
    total["calls"] = total.get("calls", 0) + 1
    total["cache_hit"] = total.get("cache_hit", 0) + cache_hit
    total["cache_miss"] = total.get("cache_miss", 0) + cache_miss
    total["prompt_tokens"] = total.get("prompt_tokens", 0) + prompt_tokens
    total["completion_tokens"] = (
        total.get("completion_tokens", 0) + completion_tokens
    )


def _log_api_usage(
    session_key: str,
    phase: str,
    usage: Mapping[str, Any],
) -> None:
    cache_hit, cache_miss, prompt_tokens, completion_tokens = _usage_numbers(
        usage
    )
    logger.info(
        f"[deepseek] session={session_key} phase={phase} "
        f"cache_hit={cache_hit} cache_miss={cache_miss} "
        f"prompt_tokens={prompt_tokens} "
        f"completion_tokens={completion_tokens}"
    )


def _log_reply(
    qid: str,
    session_key: str,
    replied: bool,
    reason: str,
    usage: dict[str, int],
    segments: int = 0,
) -> None:
    logger.info(
        f"[chat] reply qid={qid} session={session_key} "
        f"replied={str(replied).lower()} reason={reason} "
        f"segments={segments} api_calls={usage.get('calls', 0)} "
        f"cache_hit={usage.get('cache_hit', 0)} "
        f"cache_miss={usage.get('cache_miss', 0)} "
        f"prompt_tokens={usage.get('prompt_tokens', 0)} "
        f"completion_tokens={usage.get('completion_tokens', 0)}"
    )


def _format_error(exc: DeepSeekError) -> str:
    if exc.status_code == 401:
        return "DeepSeek API Key 无效，请检查 DEEPSEEK_API_KEY。"
    if exc.status_code == 402:
        return "DeepSeek 账户余额不足，请充值后再试。"
    if exc.status_code == 429:
        return "请求太频繁了，请稍后再试。"
    if exc.status_code is not None and exc.status_code >= 500:
        return "DeepSeek 服务暂时不可用，请稍后再试。"

    detail = exc.message.strip()
    if len(detail) > 200:
        detail = f"{detail[:200]}…"
    return f"DeepSeek 请求失败：{detail}"
