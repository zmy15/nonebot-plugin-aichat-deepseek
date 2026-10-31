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
    description="基于 DeepSeek API 的 AI 私聊对话插件，无需命令前缀",
    usage=(
        "私聊机器人直接发送消息即可开始对话，支持多轮上下文。\n"
        "发送 /ping 可检查插件是否在线。"
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
