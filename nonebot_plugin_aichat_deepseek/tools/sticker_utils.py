"""表情包工具共享的长度限制和标签规范化。"""

from __future__ import annotations

import re
from typing import Any

MAX_STICKER_DESCRIPTION_CHARS = 200
MAX_STICKER_TAGS_CHARS = 200


def normalize_tags(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("tags 必须是字符串")

    parts = [
        part.strip()
        for part in re.split(r"[,，、\s]+", value)
        if part.strip()
    ]
    tags = ",".join(dict.fromkeys(parts))
    if len(tags) > MAX_STICKER_TAGS_CHARS:
        raise ValueError(f"tags 最多 {MAX_STICKER_TAGS_CHARS} 字")
    return tags
