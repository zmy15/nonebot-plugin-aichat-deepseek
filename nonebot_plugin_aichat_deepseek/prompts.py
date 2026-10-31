"""system 提示词拼装：人设、输出规则、摘要和长期记忆。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .config import plugin_config
from .history import UTC8
from .tools import MEMORY_CATEGORY_LABELS


def _memory_lines(memories: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    used_chars = 0
    for memory in memories:
        label = MEMORY_CATEGORY_LABELS.get(
            memory["category"], memory["category"]
        )
        line = f"- #{memory['id']} [{label}] {memory['content']}"
        max_chars = plugin_config.deepseek_memory_max_chars
        if used_chars + len(line) + 1 > max_chars:
            break
        lines.append(line)
        used_chars += len(line) + 1
    return lines


def _build_system_prompt(
    summary: str = "",
    memories: list[dict[str, Any]] | None = None,
    user_prompt: str = "",
    *,
    group: bool = False,
) -> str:
    """在用户配置的人设之后追加输出约束、自定义指令、摘要和长期记忆。"""
    persona = plugin_config.deepseek_system_prompt.strip()
    delimiter = plugin_config.deepseek_split_delimiter.strip() or "|||"
    rules = (
        "输出要求：\n"
        "1. 只输出纯文本，不要使用任何 Markdown 格式"
        "（标题、加粗、斜体、代码块、引用、列表、表格、链接等）。\n"
        "2. 优先分成多条短消息发送，每条都像真人随口聊天："
        "一句话不要太长，句末可以不带标点，不要写成一大段。\n"
        f"3. 多条消息之间用 {delimiter} 分隔；"
        "不要在回复中解释或提到分隔符。\n"
    )
    if group:
        today = datetime.now(UTC8).strftime("%Y-%m-%d")
        rules += (
            f"\n群聊规则：当前日期是 {today}（UTC+8）。"
            "你会看到“昵称(QQ)：内容”格式的群消息；"
            "像群成员一样自然地参与聊天，不要复述所有人的话，"
            "不要假装知道未提供的信息；需要称呼某人时直接写昵称。"
            "群成员可能直接叫你的昵称、群名片或别名来和你说话，"
            "即使没有 @ 你，也是在和你说话。"
            "更早的群聊消息会被压缩成【群聊历史摘要】，"
            "摘要内容视为你已经知道的群聊背景。"
        )
        if (
            plugin_config.deepseek_tools_enabled
            and plugin_config.deepseek_memory_enabled
        ):
            rules += (
                "\n群聊记忆：当前发言人的个人信息用 save_user_memory 保存，"
                "整个群共享的信息用 save_group_memory 保存；"
                "需要回忆时用 search_user_memory 或 search_group_memory；"
                "删除时用 delete_user_memory 或 delete_group_memory。"
                "不要把单个成员的私人信息写进群聊记忆。"
            )
        if (
            plugin_config.deepseek_tools_enabled
            and plugin_config.deepseek_search_enabled
        ):
            rules += (
                "\n群里聊到实时信息、新闻、价格、天气或你不确定的内容时，"
                "可以调用 web_search 查询，不要凭记忆编造。"
            )
        if (
            plugin_config.deepseek_tools_enabled
            and plugin_config.deepseek_poke_enabled
        ):
            rules += (
                "\n群里可以用 poke_user 戳一戳当前发言人，"
                "表达提醒、调侃或互动；不要连续频繁戳同一个人。"
            )
        if (
            plugin_config.deepseek_tools_enabled
            and plugin_config.deepseek_sticker_enabled
        ):
            rules += (
                "\n所有私聊和群聊共用同一个表情库，不按用户或群隔离。"
                "本轮收到表情包时，消息里会给出表情包 ID；"
                "如果用户说明了含义，调用 describe_sticker 记录，"
                "没有说明就不要凭空猜测。聊天中可以根据气氛主动调用 "
                "send_sticker 发送合适的表情包；不确定有哪些可选时，"
                "先调用 search_stickers 查看。"
            )
        prompt = f"{persona}\n\n{rules}" if persona else rules
        if summary:
            prompt = f"{prompt}\n\n【历史对话摘要】\n{summary}"
        return prompt

    if plugin_config.deepseek_tools_enabled:
        now = datetime.now(UTC8).strftime("%Y-%m-%d")
        rules += (
            f"\n4. 当前日期是 {now}（UTC+8）。"
            "用户询问以前聊过什么、回忆之前的内容时，"
            "调用 query_chat_history 工具查询；"
            "提到“昨天”等相对时间时先换算成日期，不要编造。"
        )

    if (
        plugin_config.deepseek_tools_enabled
        and plugin_config.deepseek_memory_enabled
    ):
        rules += (
            "\n5. 当用户提到长期稳定的个人信息、偏好、习惯、关系或重要事实"
            "（例如“我叫…”“我喜欢…”“我住在…”“记住…”），"
            "或明确要求你记住时，必须调用 save_user_memory 保存；"
            "不要保存一次性、临时的内容。"
            "\n6. 用户要求忘记某条记忆时调用 delete_user_memory；"
            "需要查找更早的记忆时调用 search_user_memory。"
        )

    if (
        plugin_config.deepseek_tools_enabled
        and plugin_config.deepseek_search_enabled
    ):
        rules += (
            "\n当用户询问实时信息、新闻、价格、天气、最近发生的事件，"
            "或你不确定、需要最新资料时，调用 web_search 搜索网页；"
            "不要凭记忆编造实时信息。"
        )

    if (
        plugin_config.deepseek_tools_enabled
        and plugin_config.deepseek_scheduler_enabled
    ):
        rules += (
            "\n每次回复时都主动判断：是否适合在稍后找用户聊天或戳一戳，"
            "不需要用户提出“定时”或“提醒我”的要求。"
            "例如用户说要去忙、吃饭、睡觉、出门，"
            "或聊天告一段落时，可以调用 schedule_task "
            "安排稍后关心或问候；"
            "不要每次对话都安排，也不要连续安排多个。"
            "到点后由你根据上下文、人设和记忆主动生成消息，"
            "不是发送固定文本。只作用于当前私聊用户，"
            "不要编造任务已创建，任务保存在内存中，"
            "机器人重启后会丢失。"
            "用户要查看、取消或修改定时任务时，分别调用 "
            "list_scheduled_tasks、cancel_scheduled_task、"
            "update_scheduled_task；只能操作当前用户自己的任务。"
        )

    if (
        plugin_config.deepseek_tools_enabled
        and plugin_config.deepseek_scheduler_enabled
        and plugin_config.deepseek_followup_enabled
    ):
        rules += (
            "\n当你向用户提问后，如果用户一段时间没有回复，"
            "插件会自动让你再补一句；追问由插件自动处理，"
            "不需要你调用 schedule_task 另外安排。"
        )

    if (
        plugin_config.deepseek_tools_enabled
        and plugin_config.deepseek_custom_prompt_enabled
    ):
        rules += (
            "\n用户明确要求改变人设、语气、回复风格或记住专属设定时，"
            "调用 set_user_system_prompt 保存；"
            "询问当前设定时调用 get_user_system_prompt；"
            "要求恢复默认时调用 clear_user_system_prompt。"
        )

    if (
        plugin_config.deepseek_tools_enabled
        and plugin_config.deepseek_poke_enabled
    ):
        rules += (
            "\n用户要求你戳一戳、提醒或互动时，调用 poke_user；"
            "不要等用户开口，聊天气氛合适时主动戳一戳；"
            "用户戳你时，也可以戳回去。"
        )

    if (
        plugin_config.deepseek_tools_enabled
        and plugin_config.deepseek_sticker_enabled
    ):
        rules += (
            "\n用户发送表情包时，插件会把它存入表情库并在消息中给出"
            "表情包 ID。如果你能根据图片判断它表达的情绪或含义，"
            "调用 describe_sticker 记录一两个词的简短含义；"
            "用户说明了含义时以用户说明为准。"
            "不要等用户明确要求，聊天中可以根据情绪主动调用 "
            "send_sticker 发送合适的表情包，"
            "把表情包当成日常表达方式之一；"
            "不确定有哪些表情可选时，先调用 search_stickers 查看。"
        )

    prompt = f"{persona}\n\n{rules}" if persona else rules
    custom = user_prompt.strip()
    if plugin_config.deepseek_custom_prompt_enabled and custom:
        prompt = (
            f"{prompt}\n\n【用户自定义指令】\n{custom}\n"
            "请在不违反上面的输出格式要求的前提下优先遵守这些指令。"
        )
    if summary:
        prompt = f"{prompt}\n\n【历史对话摘要】\n{summary}"

    if memories:
        lines = _memory_lines(memories)
        if lines:
            prompt = f"{prompt}\n\n【用户长期记忆】\n" + "\n".join(lines)

    return prompt
