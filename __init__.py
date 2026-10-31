"""nonebot-plugin-aichat-deepseek（骨架）。

当前只提供 /ping 命令，用于验证项目可运行。
后续可在此包内补充：
    - config.py   : 插件配置（Pydantic 模型）
    - data_source.py : 调用 DeepSeek API 的逻辑
    - handlers.py : 对话事件处理
"""

from nonebot import on_command
from nonebot.params import CommandArg
from nonebot.adapters import Message

ping = on_command("ping", priority=5, block=True)


@ping.handle()
async def handle_ping(args: Message = CommandArg()) -> None:
    await ping.finish("pong")
