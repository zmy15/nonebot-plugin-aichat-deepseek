"""表情包识别、落盘与发送辅助。

OneBot 11 的图片消息段：

- 接收时 ``sub_type`` 为 1（表情包）、3（斗图）、7（贴图）等，``summary``
  可能是 ``[动画表情]``；商城表情通常也会转换成带 ``emoji_id`` 的 image 段。
- 发送时 image 段的 ``file`` 支持本地路径、``file://``、``http(s)://`` 和
  ``base64://``。这里优先使用本地文件 URI，失败后退回 base64。
"""

from __future__ import annotations

import base64
import hashlib
import re
from pathlib import Path
from typing import Any, Mapping

from nonebot import logger

from .config import plugin_config
from .history import ConversationStore
from .images import ImagePayload

# 1 表情包、3 斗图、7 贴图都按表情包处理
_STICKER_SUB_TYPES = frozenset({1, 3, 7})
_STICKER_SAVE_HINT_RE = re.compile(
    r"(?:记住|收藏|保存|存下|存).{0,8}(?:表情包?|表情)|这个表情包?"
)
_MIME_EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
}


class StickerError(RuntimeError):
    """表情包保存或发送失败。"""


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def is_sticker_image(segment: Mapping[str, Any], text: str = "") -> bool:
    """判断一个 image 段的数据是否应当作为表情包收藏。"""
    sub_type = _as_int(segment.get("sub_type"))
    if sub_type is None:
        sub_type = _as_int(segment.get("subType"))
    if sub_type in _STICKER_SUB_TYPES:
        return True

    summary = segment.get("summary")
    if isinstance(summary, str) and "表情" in summary:
        return True

    if any(
        segment.get(field)
        for field in ("emoji_id", "emoji_package_id", "key")
    ):
        return True

    # 客户端没有标记类型时，允许用户用自然语言明确要求收藏
    return bool(text and _STICKER_SAVE_HINT_RE.search(text))


def sticker_directory() -> Path:
    path = Path(plugin_config.deepseek_sticker_dir).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def _extension(payload: ImagePayload) -> str:
    return _MIME_EXTENSIONS.get(payload.content_type, "png")


def save_sticker_payload(
    store: ConversationStore,
    session_key: str,
    payload: ImagePayload,
) -> dict[str, Any]:
    """把表情包图片写入本地目录，并在数据库中登记含义元数据。"""
    digest = hashlib.sha256(payload.data).hexdigest()
    directory = sticker_directory()
    directory.mkdir(parents=True, exist_ok=True)

    path = directory / f"{digest}.{_extension(payload)}"
    if not path.exists() or path.stat().st_size == 0:
        path.write_bytes(payload.data)

    return store.add_sticker(
        session_key,
        digest,
        path.resolve(),
        mime=payload.content_type,
        source="user",
    )


def build_sticker_prompt_note(records: list[dict[str, Any]]) -> str:
    """生成附加在用户消息后的表情包提示，告诉模型本轮入库的 ID。"""
    if not records:
        return ""

    ids = "、".join(f"#{record['id']}" for record in records)
    undescribed = [
        f"#{record['id']}"
        for record in records
        if not record.get("description")
    ]
    note = f"（本轮收到 {len(records)} 个表情包，已存入表情库：{ids}。"
    if undescribed:
        note += (
            f"其中 {'、'.join(undescribed)} 还没有记录含义，"
            "请先根据图片内容调用 describe_sticker 记录简短含义；"
        )
    else:
        note += "这些表情包的含义之前已经记录；"
    note += (
        "如果用户说明了含义，以用户说明为准。"
        "需要发表情包时调用 send_sticker。）"
    )
    return note


async def _send_image(
    bot: Any,
    user_id: int | None,
    file_value: str,
    *,
    group_id: int | None = None,
) -> None:
    if group_id is not None:
        await bot.call_api(
            "send_group_msg",
            group_id=group_id,
            message=[{"type": "image", "data": {"file": file_value}}],
        )
        return
    await bot.call_api(
        "send_private_msg",
        user_id=user_id,
        message=[{"type": "image", "data": {"file": file_value}}],
    )


async def send_sticker_image(
    bot: Any,
    user_id: int | None,
    file_path: str | Path,
    *,
    group_id: int | None = None,
) -> str:
    """发送本地表情包图片到私聊或群聊，返回实际使用的发送方式。"""
    path = Path(file_path).expanduser()
    if not path.is_file():
        raise StickerError("表情包文件不存在，可能已被移动或删除")

    try:
        await _send_image(
            bot,
            user_id,
            path.resolve().as_uri(),
            group_id=group_id,
        )
        return "file_uri"
    except Exception as first_error:
        logger.warning(
            f"表情包 file:// 发送失败，尝试 base64："
            f"{first_error.__class__.__name__}"
        )

    try:
        data = path.read_bytes()
        await _send_image(
            bot,
            user_id,
            f"base64://{base64.b64encode(data).decode()}",
            group_id=group_id,
        )
        return "base64"
    except Exception as second_error:
        raise StickerError(
            f"发送表情包失败：{second_error.__class__.__name__}"
        ) from second_error
