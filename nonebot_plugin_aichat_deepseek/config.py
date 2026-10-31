"""插件配置。

配置项均通过 .env 提供，例如：

    DEEPSEEK_API_KEY=sk-xxxxxxxx
    DEEPSEEK_API_BASE=https://api.deepseek.com
    DEEPSEEK_MODEL=deepseek-flash

为满足“零配置可加载”要求，DEEPSEEK_API_KEY 允许缺省，
插件仍能正常导入，仅在私聊调用 API 时提示未配置。
"""

from nonebot import get_plugin_config
from pydantic import BaseModel, ConfigDict, Field


class Config(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # API 连接
    deepseek_api_key: str | None = None
    deepseek_api_base: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"
    deepseek_timeout: float = Field(default=60.0, gt=0)

    # 数据存储（SQLite）。相对路径基于机器人启动目录
    deepseek_db_path: str = "data/nonebot_plugin_aichat_deepseek/chat.db"

    # 工具调用
    deepseek_tools_enabled: bool = True
    deepseek_tool_max_rounds: int = Field(default=3, ge=1)

    # 长期记忆
    deepseek_memory_enabled: bool = True
    deepseek_memory_max_items: int = Field(default=20, ge=1, le=50)
    deepseek_memory_max_chars: int = Field(default=1000, ge=1)

    # 图片理解（Files API）
    deepseek_image_enabled: bool = True
    deepseek_image_max_bytes: int = Field(
        default=64 * 1024 * 1024,
        ge=1,
    )
    deepseek_image_max_count: int = Field(default=4, ge=1)
    deepseek_image_timeout: float = Field(default=60.0, gt=0)
    # 0 表示不设置过期时间（永久有效）
    deepseek_image_expire_seconds: int = Field(
        default=86400,
        ge=0,
        le=2592000,
    )

    # 生成参数
    deepseek_system_prompt: str = (
        "你是一个乐于助人的 AI 助手，请使用简体中文回答用户的问题。"
    )
    deepseek_temperature: float = Field(default=1.0, ge=0, le=2)
    deepseek_max_tokens: int | None = Field(default=None, ge=1)
    # None 表示不发送 thinking 字段，使用服务端默认值；
    # True / False 分别显式开启 / 关闭思考模式。
    deepseek_thinking: bool | None = None

    # 对话上下文：每次最多加载最近多少轮（一问一答为一轮）；
    # 0 表示不加载上下文，但对话仍会写入数据库
    deepseek_history_turns: int = Field(default=30, ge=0)
    # 未压缩消息超过 trigger_turns 轮时，把最早的一批消息压缩成摘要；
    # trigger_turns=0 表示关闭自动压缩。
    deepseek_compression_trigger_turns: int = Field(default=30, ge=0)
    # 每次压缩的消息条数（用户消息和 AI 回复各算一条）
    deepseek_compression_batch_messages: int = Field(default=20, ge=1)

    # 消息聚合：把用户连续发送的多条消息合并后，再判断是否完整
    deepseek_aggregate_messages: bool = True
    deepseek_debounce_seconds: float = Field(default=1.2, ge=0)
    deepseek_debounce_jitter: float = Field(default=0.4, ge=0)
    deepseek_completeness_check: bool = True

    # 输出格式：模型用该分隔符把回复拆成多条消息发送
    deepseek_split_delimiter: str = Field(default="|||", min_length=1)
    # 首次回复前的随机延迟（秒）及抖动范围（±秒）
    deepseek_reply_delay: float = Field(default=1.0, ge=0)
    deepseek_reply_delay_jitter: float = Field(default=0.5, ge=0)
    # 多条消息之间的发送间隔（秒），以及随机抖动范围（±秒）
    deepseek_reply_interval: float = Field(default=1.0, ge=0)
    deepseek_reply_interval_jitter: float = Field(default=0.3, ge=0)
    # 单次最多发送几条消息，超出的部分合并到最后一条
    deepseek_reply_max_segments: int = Field(default=4, ge=1)

    # 单条回复的最大字符数，超出后分段发送（QQ 单条消息有字节上限，不宜过大）
    deepseek_reply_max_length: int = Field(default=1000, ge=1)


plugin_config = get_plugin_config(Config)
