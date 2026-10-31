"""nonebot-plugin-aichat-deepseek.

基于 DeepSeek API 的 NoneBot2 私聊对话插件：私聊机器人直接发送消息即可，
无需任何命令前缀；群聊消息不会触发对话。
"""

from nonebot import on_command
from nonebot.adapters import Message
from nonebot.params import CommandArg
from nonebot.plugin import PluginMetadata

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="DeepSeek 对话",
    description="基于 DeepSeek API 的 AI 私聊/群聊对话插件，无需命令前缀",
    usage=(
        "私聊机器人直接发送消息即可开始对话，支持多轮上下文。\n"
        "群聊中 @ 机器人会回复，也会按概率随机参与；"
        "群聊上下文按群保存，成员记忆按 QQ 区分，并有一份整群共享记忆；"
        "群聊支持戳一戳、联网搜索，所有私聊和群聊共用全局表情库。\n"
        "回复会自动去除 Markdown 并按真人节奏分条发送。\n"
        "对话历史保存到本地数据库，默认超过 30 轮自动压缩摘要。\n"
        "模型可调用 query_chat_history 查询历史聊天记录（UTC+8）。\n"
        "会长期记住用户的信息、偏好等，并在后续对话中自动使用。\n"
        "私聊可以直接发送图片，由 deepseek-flash 进行图像理解。\n"
        "连续发送的多条消息会先聚合，判断完整后再回复。\n"
        "也可以用自然语言设置只属于自己的 system 提示词或人设。\n"
        "模型可以联网搜索实时信息、新闻等网页内容。\n"
        "模型可以自己安排定时主动聊天或定时戳一戳，到点后由 AI 主动联系用户；"
        "也可以查看、取消或修改定时任务。\n"
        "AI 提问后用户一段时间没回复时，会自动再补一句。\n"
        "模型可以戳一戳用户，用户戳机器人时也会得到回应，并可以戳回去。\n"
        "私聊发送表情包会自动收藏，模型可以按含义查询并发送。\n"
        "发送 /ping 可检查插件是否在线。\n"
        "发送 /清空 可清空当前用户的对话上下文，"
        "也支持 /清除、/重置、/clear、/reset 等别名。"
    ),
    type="application",
    homepage="https://github.com/zmy15/nonebot-plugin-aichat-deepseek",
    config=Config,
    supported_adapters={"~onebot.v11"},
)

from .chat import private_chat  # noqa: E402,F401

__all__ = ["private_chat"]

ping = on_command("ping", priority=5, block=True)


@ping.handle()
async def handle_ping(args: Message = CommandArg()) -> None:
    await ping.finish("pong")
