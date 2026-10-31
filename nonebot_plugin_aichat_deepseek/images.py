"""从 OneBot 图片消息段中获取图片内容。

OneBot 的 image 段通常提供 ``url`` 或 ``file`` 字段，可能是 http(s) 链接、
本地路径、``file://``、``base64://`` 或 data URL。该模块负责统一解析并
校验图片格式，供 Files API 上传使用。
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import unquote, urlparse

import httpx


class ImageError(RuntimeError):
    """图片获取或格式校验失败。"""


@dataclass(slots=True)
class ImagePayload:
    data: bytes
    filename: str
    content_type: str


def _detect_type(data: bytes) -> tuple[str, str] | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg", "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png", "image/png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif", "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", "image/webp"
    return None


def _decode_base64(payload: str) -> bytes:
    try:
        return base64.b64decode(payload)
    except (binascii.Error, ValueError) as exc:
        raise ImageError("图片 base64 数据无效") from exc


def _filename_from_source(source: str, extension: str) -> str:
    if source.startswith(("http://", "https://")):
        name = Path(urlparse(source).path).name
    elif source.startswith("data:") or source.startswith("base64://"):
        name = ""
    else:
        name = Path(source).name

    stem = Path(name).stem if name else "image"
    return f"{stem or 'image'}.{extension}"


async def _download(
    url: str,
    *,
    timeout: float,
    transport: httpx.AsyncBaseTransport | None,
) -> bytes:
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            transport=transport,
        ) as client:
            response = await client.get(url)
    except httpx.TimeoutException as exc:
        raise ImageError("下载图片超时") from exc
    except httpx.HTTPError as exc:
        raise ImageError(f"下载图片失败：{exc.__class__.__name__}") from exc

    if response.status_code >= 400:
        raise ImageError(f"下载图片失败：HTTP {response.status_code}")
    return response.content


def _read_local_file(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ImageError(f"读取本地图片失败：{exc.__class__.__name__}") from exc


async def _load_source(
    source: str,
    *,
    timeout: float,
    transport: httpx.AsyncBaseTransport | None,
) -> bytes:
    if source.startswith("data:"):
        header, separator, payload = source.partition(",")
        if not separator or "base64" not in header.lower():
            raise ImageError("图片 data URL 格式无效")
        return _decode_base64(payload)

    if source.startswith("base64://"):
        return _decode_base64(source[len("base64://") :])

    if source.startswith(("http://", "https://")):
        return await _download(source, timeout=timeout, transport=transport)

    if source.startswith("file://"):
        parsed = urlparse(source)
        path = unquote(parsed.path)
        if parsed.netloc:
            path = f"//{parsed.netloc}{path}"
        if len(path) > 2 and path[0] == "/" and path[2] == ":":
            path = path[1:]
        local_path = Path(path)
    else:
        local_path = Path(source).expanduser()

    if not local_path.exists():
        raise ImageError("无法获取图片内容，请重试或换一张图片")
    if not local_path.is_file():
        raise ImageError("图片路径不是文件")
    return _read_local_file(local_path)


async def fetch_image(
    segment: Mapping[str, Any],
    *,
    timeout: float = 60.0,
    max_bytes: int = 64 * 1024 * 1024,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ImagePayload:
    """解析 OneBot image 消息段，返回图片字节和类型信息。"""
    source = segment.get("url") or segment.get("file") or segment.get("path")
    if not isinstance(source, str) or not source.strip():
        raise ImageError("图片消息缺少可用的 url/file 字段")

    content = await _load_source(
        source.strip(),
        timeout=timeout,
        transport=transport,
    )
    if not content:
        raise ImageError("图片内容为空")
    if len(content) > max_bytes:
        raise ImageError(
            f"图片过大，最大支持 {max_bytes // (1024 * 1024)} MiB"
        )

    detected = _detect_type(content)
    if detected is None:
        raise ImageError("仅支持 JPEG、PNG、GIF、WebP 图片")

    extension, content_type = detected
    return ImagePayload(
        data=content,
        filename=_filename_from_source(source, extension),
        content_type=content_type,
    )
