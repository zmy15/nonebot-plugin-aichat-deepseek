"""nonebot-plugin-aichat-deepseek.

基于 DeepSeek API 的 NoneBot2 对话插件。

当前提供 /ping 命令用于验证插件加载；接入对话功能时，
建议在 data_source.py 中使用 AsyncOpenAI 调用 DeepSeek。
"""

from nonebot import on_command
from nonebot.adapters import Message
from nonebot.params import CommandArg
from nonebot.plugin import PluginMetadata

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="DeepSeek 对话",
    description="基于 DeepSeek API 的 AI 对话插件",
    usage="发送 /ping 检查插件是否在线",
    type="application",
    homepage="https://github.com/zmy15/nonebot-plugin-aichat-deepseek",
    config=Config,
    supported_adapters={"~onebot.v11"},
)

ping = on_command("ping", priority=5, block=True)


@ping.handle()
async def handle_ping(args: Message = CommandArg()) -> None:
    await ping.finish("pong")
