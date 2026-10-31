"""把模型输出整理成适合聊天窗口的纯文本。

- 移除常见的 Markdown 标记，保留文字内容
- 按模型输出的分隔符拆成多条消息
- 过长的单条消息继续按字符数切分
"""

from __future__ import annotations

import html
import re

_FENCED_CODE_RE = re.compile(
    r"(?ms)^[ \t]*(?:```|~~~)[^\n]*\n(.*?)^[ \t]*(?:```|~~~)[ \t]*$"
)
_FENCE_LINE_RE = re.compile(r"(?m)^[ \t]*(?:```|~~~)[^\n]*$")
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\n]*)\)")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\n]+)\)")
_AUTOLINK_RE = re.compile(r"<((?:https?://|mailto:)[^>\s]+)>", re.IGNORECASE)
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"</?[A-Za-z][^>]*>")
_TABLE_LINE_RE = re.compile(r"(?m)^[ \t]*\|.*\|[ \t]*\n?")
_HR_RE = re.compile(
    r"(?m)^[ \t]{0,3}(?:(?:\*[ \t]*){3,}|(?:-[ \t]*){3,}|(?:_[ \t]*){3,})$"
)
_SETEXT_RE = re.compile(r"(?m)^[ \t]{0,3}=+[ \t]*$")
_HEADING_RE = re.compile(r"(?m)^[ \t]{0,3}#{1,6}[ \t]+(.*?)[ \t]*#*[ \t]*$")
_EMPTY_HEADING_RE = re.compile(r"(?m)^[ \t]{0,3}#{1,6}[ \t]*$")
_BLOCKQUOTE_RE = re.compile(r"(?m)^[ \t]{0,3}(?:>[ \t]?)+")
_LIST_RE = re.compile(
    r"(?m)^[ \t]{0,3}(?:[-*+]|\d{1,9}[.)])[ \t]+(?:\[[ xX]\][ \t]+)?"
)
_LINK_REF_RE = re.compile(r"(?m)^[ \t]{0,3}\[[^\]]+\]:[ \t]*\S+.*$")

# 先保护 __init__、deepseek_api_key 这类标识符，避免把下划线当成斜体
_IDENTIFIER_RE = re.compile(
    r"\b(?:__[A-Za-z0-9_]+__|[A-Za-z0-9]+(?:_[A-Za-z0-9]+)+)\b"
)
_PLACEHOLDER_RE = re.compile(r"\x00(\d+)\x00")

_BOLD_STAR_RE = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")
_BOLD_UNDERSCORE_RE = re.compile(r"(?<!\w)__(?=\S)(.+?)(?<=\S)__(?!\w)")
_STRIKE_RE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~")
_ITALIC_STAR_RE = re.compile(r"\*(?=\S)([^*\n]+?)(?<=\S)\*")
_ITALIC_UNDERSCORE_RE = re.compile(r"(?<!\w)_(?=\S)([^_\n]+?)(?<=\S)_(?!\w)")
_ESCAPE_RE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|~>])")
_ESCAPE_PLACEHOLDER_RE = re.compile(r"\x01(\d+)\x01")


def _replace_link(match: re.Match[str]) -> str:
    label = match.group(1).strip()
    url = match.group(2).strip()
    if not label:
        return url
    if label == url:
        return label
    return f"{label}（{url}）"


def _replace_autolink(match: re.Match[str]) -> str:
    return re.sub(r"(?i)^mailto:", "", match.group(1))


def _replace_table_row(match: re.Match[str]) -> str:
    row = match.group(0).strip().strip("|").strip()
    if row and re.fullmatch(r"[\s:|-]+", row) and "-" in row:
        return ""
    cells = [cell.strip() for cell in row.split("|")]
    return "  ".join(cell for cell in cells if cell) + "\n"


def _protect_identifiers(text: str) -> tuple[str, list[str]]:
    protected: list[str] = []

    def replace(match: re.Match[str]) -> str:
        protected.append(match.group(0))
        return f"\x00{len(protected) - 1}\x00"

    return _IDENTIFIER_RE.sub(replace, text), protected


def _protect_escapes(text: str) -> tuple[str, list[str]]:
    protected: list[str] = []

    def replace(match: re.Match[str]) -> str:
        protected.append(match.group(1))
        return f"\x01{len(protected) - 1}\x01"

    return _ESCAPE_RE.sub(replace, text), protected


def strip_markdown(text: str) -> str:
    """移除常见 Markdown 标记，返回纯文本。"""
    if not text:
        return ""

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text, escaped = _protect_escapes(text)

    # 代码块、行内代码：保留内容，去掉围栏和反引号
    text = _FENCED_CODE_RE.sub(lambda match: match.group(1), text)
    text = _FENCE_LINE_RE.sub("", text)
    text = _INLINE_CODE_RE.sub(lambda match: match.group(1), text)
    text = text.replace("`", "")

    # 图片、链接、自动链接、HTML
    text = _IMAGE_RE.sub(lambda match: match.group(1), text)
    text = _LINK_RE.sub(_replace_link, text)
    text = _AUTOLINK_RE.sub(_replace_autolink, text)
    text = _BR_RE.sub("\n", text)
    text = _HTML_TAG_RE.sub("", text)

    # 表格、分隔线、标题、引用、列表、链接定义
    text = _TABLE_LINE_RE.sub(_replace_table_row, text)
    text = _HR_RE.sub("", text)
    text = _SETEXT_RE.sub("", text)
    text = _HEADING_RE.sub(lambda match: match.group(1).strip(), text)
    text = _EMPTY_HEADING_RE.sub("", text)
    text = _BLOCKQUOTE_RE.sub("", text)
    text = _LIST_RE.sub("", text)
    text = _LINK_REF_RE.sub("", text)

    # 加粗、删除线、斜体
    text, protected = _protect_identifiers(text)
    text = _BOLD_STAR_RE.sub(lambda match: match.group(1), text)
    text = _BOLD_UNDERSCORE_RE.sub(lambda match: match.group(1), text)
    text = _STRIKE_RE.sub(lambda match: match.group(1), text)
    text = _ITALIC_STAR_RE.sub(lambda match: match.group(1), text)
    text = _ITALIC_UNDERSCORE_RE.sub(lambda match: match.group(1), text)
    text = _PLACEHOLDER_RE.sub(
        lambda match: protected[int(match.group(1))], text
    )

    # 转义字符、HTML 实体、多余空白
    text = _ESCAPE_PLACEHOLDER_RE.sub(
        lambda match: escaped[int(match.group(1))], text
    )
    text = html.unescape(text)
    text = "\n".join(line.strip() for line in text.splitlines())
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_text(text: str, limit: int) -> list[str]:
    """把过长文本按换行或定长切分，尽量不切断整行。"""
    text = text.strip()
    if not text:
        return []
    if limit <= 0:
        return [text]

    chunks: list[str] = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunk = text[:cut].strip()
        if chunk:
            chunks.append(chunk)
        text = text[cut:].lstrip("\n")
    if text.strip():
        chunks.append(text.strip())
    return chunks


def split_reply(
    text: str,
    *,
    delimiter: str = "|||",
    max_segments: int = 4,
    max_length: int = 1000,
    split_paragraphs: bool = False,
) -> list[str]:
    """按分隔符拆分、清理 Markdown，并处理过长消息。"""
    delimiter = delimiter.strip()
    if delimiter and delimiter in text:
        parts = text.split(delimiter)
    else:
        parts = [text]
        if split_paragraphs:
            paragraphs = [
                part for part in re.split(r"\n{2,}", text) if part.strip()
            ]
            if len(paragraphs) > 1:
                parts = paragraphs

    if max_segments > 0 and len(parts) > max_segments:
        head = parts[: max_segments - 1]
        tail = " ".join(
            part.strip() for part in parts[max_segments - 1 :] if part.strip()
        )
        parts = [*head, tail]

    messages: list[str] = []
    for part in parts:
        cleaned = strip_markdown(part)
        if cleaned:
            messages.extend(split_text(cleaned, max_length))
    return messages
