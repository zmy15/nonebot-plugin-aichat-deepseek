"""粗略的 token 估算与截断工具。

DeepSeek 没有提供本地分词器，这里用字符数做保守估算：
非 ASCII 字符按 1 token/字，ASCII 字符按约 3.5 字符/token。
它只用于触发上下文压缩和保证摘要不超过预算，不追求与真实
分词结果完全一致。
"""

from __future__ import annotations

import math


def estimate_tokens(text: str) -> int:
    """估算一段文本的 token 数。"""
    if not text:
        return 0
    non_ascii = 0
    for char in text:
        if ord(char) > 127:
            non_ascii += 1
    ascii_count = len(text) - non_ascii
    return max(1, math.ceil(non_ascii + ascii_count / 3.5))


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """把文本裁剪到 ``max_tokens`` 以内，保留结尾省略号。"""
    text = text.strip()
    if max_tokens <= 0:
        return ""
    if estimate_tokens(text) <= max_tokens:
        return text

    budget = max(0, max_tokens - 1)
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if estimate_tokens(text[:middle]) <= budget:
            low = middle
        else:
            high = middle - 1
    return text[:low].rstrip() + "…"
