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

    # 群聊：只处理指定群，@ 必回，非 @ 按概率随机参与
    deepseek_group_enabled: bool = True
    # 群号，支持逗号/空格分隔，例如 123456 或 [123456, 789012]
    deepseek_group_ids: str = ""
    deepseek_group_reply_probability: float = Field(
        default=0.2, ge=0, le=1
    )
    deepseek_group_reply_cooldown: float = Field(default=60.0, ge=0)
    # 没有 @ 但消息里提到机器人昵称/群名片/别名时也回复
    deepseek_group_mention_reply: bool = True
    # 额外的机器人称呼，支持逗号/空格/顿号分隔；
    # 不填时自动使用登录昵称和群名片
    deepseek_group_bot_names: str = ""
    # 群聊上下文：关闭压缩时才按这个条数截取最近消息
    deepseek_group_history_messages: int = Field(default=50, ge=1)

    # 群聊上下文压缩：默认每积累 200 条消息压缩一次；
    # 估算 token 超过 900k 时也会触发压缩；压缩结果不超过 10k token。
    deepseek_group_compression_enabled: bool = True
    deepseek_group_compression_batch_messages: int = Field(
        default=200, ge=1
    )
    deepseek_group_compression_trigger_tokens: int = Field(
        default=900_000, ge=1
    )
    deepseek_group_compression_summary_max_tokens: int = Field(
        default=10_000, ge=1
    )
    # 二级压缩时至少合并多少段旧摘要（不足时合并全部）
    deepseek_group_compression_merge_summaries: int = Field(
        default=4, ge=2
    )

    # 工具调用
    deepseek_tools_enabled: bool = True
    deepseek_tool_max_rounds: int = Field(default=3, ge=1)
    # 戳一戳工具与戳一戳事件响应
    deepseek_poke_enabled: bool = True
    # 撤回自己最近发送的消息
    deepseek_recall_enabled: bool = True

    # 长期记忆
    deepseek_memory_enabled: bool = True
    deepseek_memory_max_items: int = Field(default=20, ge=1, le=50)
    deepseek_memory_max_chars: int = Field(default=1000, ge=1)

    # 单个私聊用户的自定义 system 提示词
    deepseek_custom_prompt_enabled: bool = True
    deepseek_custom_prompt_max_chars: int = Field(default=2000, ge=1)

    # 联网搜索（DeepSeek Search API）
    deepseek_search_enabled: bool = True
    deepseek_search_default_count: int = Field(default=5, ge=1, le=50)

    # 定时任务（nonebot-plugin-apscheduler）
    deepseek_scheduler_enabled: bool = True
    # 单个任务最长延迟，默认 7 天
    deepseek_scheduler_max_delay_seconds: int = Field(
        default=604800, ge=1
    )
    # 每个用户最多同时保留多少个定时任务
    deepseek_scheduler_max_jobs: int = Field(default=5, ge=1)
    # 提问后用户一段时间没回复，自动再补一句
    deepseek_followup_enabled: bool = True
    deepseek_followup_delay_seconds: int = Field(default=600, ge=1)

    # 表情包：自动收藏私聊收到的表情包，供模型按含义查询和发送
    deepseek_sticker_enabled: bool = True
    # 表情包图片保存目录。相对路径基于机器人启动目录
    deepseek_sticker_dir: str = "data/nonebot_plugin_aichat_deepseek/stickers"
    # 单条消息最多自动收藏几个表情包
    deepseek_sticker_max_count: int = Field(default=4, ge=1)
    # 查询表情包时最多返回多少条
    deepseek_sticker_search_limit: int = Field(default=10, ge=1, le=20)

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
    # 模型没有输出分隔符时，按空行段落拆成多条消息
    deepseek_split_paragraphs: bool = True
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
