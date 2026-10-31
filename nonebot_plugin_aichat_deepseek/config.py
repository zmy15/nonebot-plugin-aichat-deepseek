"""插件配置。

配置项均通过 .env 提供，例如：

    DEEPSEEK_API_KEY=sk-xxxxxxxx
    DEEPSEEK_API_BASE=https://api.deepseek.com
    DEEPSEEK_MODEL=deepseek-chat

为满足“零配置可加载”要求，DEEPSEEK_API_KEY 允许缺省，
插件仍能正常导入，仅在调用 API 时给出提示。
"""

from nonebot import get_plugin_config
from pydantic import BaseModel, ConfigDict


class Config(BaseModel):
    model_config = ConfigDict(extra="ignore")

    deepseek_api_key: str | None = None
    deepseek_api_base: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    deepseek_timeout: float = 60.0


plugin_config = get_plugin_config(Config)
