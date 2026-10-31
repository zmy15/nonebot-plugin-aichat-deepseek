"""对话中固定的提示文本与通用类型。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

Sender = Callable[[str], Awaitable[Any]]

MISSING_API_KEY_TIP = "还没有配置 DEEPSEEK_API_KEY，请先在 .env 中填写后再试。"
IMAGE_DISABLED_TIP = "图片理解功能还没有开启。"
EMPTY_REPLY_TIP = "……"
POKE_PROMPT = "（对方戳了你一下，请用一句简短自然的话回应）"
POKE_BACK_PROMPT = (
    "（对方戳了你一下，请用一句简短自然的话回应；"
    "也可以调用 poke_user 戳回去。）"
)
COMPLETENESS_SYSTEM_PROMPT = (
    "你是一个消息完整性判断器。用户可能把同一句话拆成多条发送。\n"
    "下面会给出最近对话和当前拼接后的用户消息。"
    "请结合上下文判断当前消息是否已经表达完整、可以正常回答。\n"
    "如果明显还没说完，例如只有开场白、句子中断、以“然后/因为/我想问”等结尾，"
    "只输出 INCOMPLETE。\n"
    "否则只输出 COMPLETE。\n"
    "不要回答用户的问题，不要解释。"
)
SUMMARY_SYSTEM_PROMPT = (
    "你是一个对话摘要助手。请把用户与 AI 的对话压缩成一段简洁的中文摘要，"
    "保留关键事实、用户偏好、约定和未完成事项；不要编造，不要使用 Markdown。"
)
