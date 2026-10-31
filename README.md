# nonebot-plugin-aichat-deepseek

基于 [DeepSeek](https://www.deepseek.com/) API 的 NoneBot2 私聊 AI 对话插件。

私聊机器人直接发送消息即可开始对话，**不需要任何命令前缀**；群聊消息不会触发。

## 功能

- 仅响应 OneBot V11 私聊消息，无需 `/` 等前缀
- 多轮上下文（默认加载最近 30 轮，按用户隔离）
- 当前上下文持久化到 SQLite，启动时自动加载历史
- 历史聊天记录复用同一数据库，模型可调用 `query_chat_history` 查询过去聊过什么
- 长期记忆：自动保存用户信息、偏好、习惯等，并在后续对话中注入 system 指令
- 未压缩消息超过 30 轮时，自动把最早 20 条消息压缩成摘要，放到 system 指令之后
- 自动移除 Markdown 标记，只发送纯文本
- 模型用 `|||` 分隔多条消息，插件按随机间隔逐条发送，更像真人聊天
- 回复过长时自动分段发送
- 未配置 Key、Key 无效、余额不足、限流、超时等场景有中文提示
- 保留 `/ping` 命令用于检查插件是否在线

## 安装

使用 nb-cli 安装：

```
nb plugin install nonebot-plugin-aichat-deepseek
```

或使用 pip：

```
pip install nonebot-plugin-aichat-deepseek
```

## 配置

在 `.env` 中填写，至少需要 `DEEPSEEK_API_KEY`：

```dotenv
DEEPSEEK_API_KEY=sk-xxxxxxxx
DEEPSEEK_MODEL=deepseek-flash
DEEPSEEK_DB_PATH=data/nonebot_plugin_aichat_deepseek/chat.db
DEEPSEEK_TOOLS_ENABLED=true
DEEPSEEK_TOOL_MAX_ROUNDS=3
DEEPSEEK_MEMORY_ENABLED=true
DEEPSEEK_MEMORY_MAX_ITEMS=20
DEEPSEEK_MEMORY_MAX_CHARS=1000
DEEPSEEK_HISTORY_TURNS=30
DEEPSEEK_COMPRESSION_TRIGGER_TURNS=30
DEEPSEEK_COMPRESSION_BATCH_MESSAGES=20
DEEPSEEK_SPLIT_DELIMITER=|||
DEEPSEEK_REPLY_INTERVAL=1.0
```

| 配置项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `DEEPSEEK_API_KEY` | `str \| None` | `None` | DeepSeek API Key；缺失时私聊会提示配置 |
| `DEEPSEEK_API_BASE` | `str` | `https://api.deepseek.com` | API 地址，可替换为兼容代理 |
| `DEEPSEEK_MODEL` | `str` | `deepseek-flash` | 模型名，可选 `deepseek-flash`、`deepseek-v4-pro` |
| `DEEPSEEK_DB_PATH` | `str` | `data/nonebot_plugin_aichat_deepseek/chat.db` | SQLite 数据库路径，相对路径基于机器人启动目录 |
| `DEEPSEEK_TOOLS_ENABLED` | `bool` | `True` | 是否允许模型调用工具 |
| `DEEPSEEK_TOOL_MAX_ROUNDS` | `int` | `3` | 单次回复最多允许几轮工具调用 |
| `DEEPSEEK_MEMORY_ENABLED` | `bool` | `True` | 是否启用长期记忆的保存、查询和注入 |
| `DEEPSEEK_MEMORY_MAX_ITEMS` | `int` | `20` | 每次最多注入多少条长期记忆 |
| `DEEPSEEK_MEMORY_MAX_CHARS` | `int` | `1000` | 注入长期记忆的字符预算 |
| `DEEPSEEK_TIMEOUT` | `float` | `60.0` | 单次请求超时（秒） |
| `DEEPSEEK_SYSTEM_PROMPT` | `str` | 内置中文助手提示词 | 人设提示词；插件会自动追加纯文本与分隔符输出要求 |
| `DEEPSEEK_TEMPERATURE` | `float` | `1.0` | 采样温度，范围 0–2 |
| `DEEPSEEK_MAX_TOKENS` | `int \| None` | `None` | 最大输出 token 数，不填使用服务端默认值 |
| `DEEPSEEK_THINKING` | `bool \| None` | `None` | 是否开启思考模式；`None` 表示不发送该字段、使用服务端默认值 |
| `DEEPSEEK_HISTORY_TURNS` | `int` | `30` | 每次加载最近多少轮上下文，`0` 表示不加载（对话仍会入库） |
| `DEEPSEEK_COMPRESSION_TRIGGER_TURNS` | `int` | `30` | 未压缩消息超过多少轮时触发压缩，`0` 表示关闭 |
| `DEEPSEEK_COMPRESSION_BATCH_MESSAGES` | `int` | `20` | 每次压缩最早多少条消息（用户和 AI 各算一条） |
| `DEEPSEEK_SPLIT_DELIMITER` | `str` | `\|\|\|` | 模型用于分隔多条消息的标记 |
| `DEEPSEEK_REPLY_INTERVAL` | `float` | `1.0` | 多条消息之间的基础间隔（秒） |
| `DEEPSEEK_REPLY_INTERVAL_JITTER` | `float` | `0.3` | 间隔随机抖动范围（±秒），设为 0 则使用固定间隔 |
| `DEEPSEEK_REPLY_MAX_SEGMENTS` | `int` | `4` | 单次最多发送几条消息，超出部分合并到最后一条 |
| `DEEPSEEK_REPLY_MAX_LENGTH` | `int` | `1000` | 单条回复最大字符数，超出后分段发送 |

> 模型名请以 [DeepSeek 官方文档](https://api-docs.deepseek.com/zh-cn/quick_start/pricing) 为准。
> 默认使用 `deepseek-flash`；需要更强推理能力时可改为 `deepseek-v4-pro`。
> 如果希望更快回复，可设置 `DEEPSEEK_THINKING=false` 关闭思考模式。

## 使用

1. 启动 NoneBot 并连接 OneBot V11 实现（如 NapCat）。
2. 私聊机器人，直接发送任意文本，例如：

```
你好，介绍一下你自己
```

3. 继续发送消息即可进行多轮对话；对话会实时写入本地 SQLite，重启后自动加载。

插件会自动在系统提示词后追加输出约束：模型只输出纯文本，并用 `|||` 把回复拆成多条短消息。发送前还会移除残留的 Markdown 标记，并按照配置的间隔逐条发送，模拟真人分条聊天的节奏。可以通过 `DEEPSEEK_SPLIT_DELIMITER` 更换分隔符，或把 `DEEPSEEK_REPLY_INTERVAL` 设为 `0` 关闭间隔。

群聊中发送的消息不会触发本插件；以 `/` 开头的消息会交给命令处理器，不会进入对话。

## 数据存储与上下文压缩

- 当前上下文数据库默认位于 `data/nonebot_plugin_aichat_deepseek/chat.db`，启动时自动创建表并加载未压缩的历史消息和摘要。
- 每完成一轮问答，用户消息和 AI 原始回复会立即写入 `messages` 表。
- 未压缩消息超过 `DEEPSEEK_COMPRESSION_TRIGGER_TURNS` 轮（默认 30 轮）时，插件会把最早 `DEEPSEEK_COMPRESSION_BATCH_MESSAGES` 条（默认 20 条）交给模型压缩成摘要，保存到 `summaries` 表，并在后续请求中放到 system 指令之后。
- 被压缩的消息不会删除，只是标记为 `compressed = 1`，便于保留原始记录；可用 `sqlite3` 直接查看。
- `query_chat_history` 工具直接查询同一个 `messages` 表，因此可以检索到包括已压缩消息在内的完整历史。
- `messages.created_at` 以 UTC 保存；工具输入和返回的时间统一按 UTC+8 解释和展示。
- 长期记忆保存在同一数据库的 `memories` 表中，按 `session_key` 隔离。
- 数据库为明文存储，请自行做好备份和访问权限控制。

## 长期记忆

- 当用户提到长期稳定的个人信息、偏好、习惯、关系或重要事实时，模型会调用 `save_user_memory` 保存。
- 每轮请求会把该用户最近最多 `DEEPSEEK_MEMORY_MAX_ITEMS` 条记忆注入 system 指令，受 `DEEPSEEK_MEMORY_MAX_CHARS` 字符预算限制。
- 记忆分类：`profile`（个人信息）、`preference`（偏好）、`habit`（习惯）、`relationship`（关系）、`fact`（事实）。
- 用户要求忘记时，模型可调用 `delete_user_memory`；需要查找更早记忆时调用 `search_user_memory`。
- 记忆只属于当前 `session_key`，不会跨用户读取。

## 工具调用

启用 `DEEPSEEK_TOOLS_ENABLED` 后，模型会获得以下工具（记忆相关工具还要求 `DEEPSEEK_MEMORY_ENABLED=true`）：

| 工具 | 说明 |
| --- | --- |
| `query_chat_history` | 查询当前私聊用户过去的聊天记录 |
| `save_user_memory` | 保存用户长期信息、偏好等 |
| `search_user_memory` | 搜索已保存的长期记忆 |
| `delete_user_memory` | 删除某条长期记忆 |

### `query_chat_history`

参数（时间均按 UTC+8）：

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `keyword` | `string` | 可选，按关键词搜索用户或 AI 的消息内容 |
| `start_time` | `string` | 可选，开始时间，`YYYY-MM-DD` 或 `YYYY-MM-DD HH:MM:SS` |
| `end_time` | `string` | 可选，结束时间；只写日期时包含当天 23:59:59 |
| `limit` | `integer` | 可选，返回 1–20 条，默认 10 |

关键词和时间范围可以单独使用，也可以组合查询。例如：

- 只看关键词：`keyword="猫"`
- 只看时间：`start_time="2026-10-01", end_time="2026-10-07"`
- 组合：`keyword="猫", start_time="2026-10-01", end_time="2026-10-07"`

系统提示中会附带当前 UTC+8 时间，模型遇到“昨天”“上周”等相对时间时会先换算成具体日期再查询。

- 只能查询当前 `session_key` 对应的用户，不能跨用户查询。
- 工具结果会裁剪过长的消息内容，避免占用过多上下文。
- 单次回复最多进行 `DEEPSEEK_TOOL_MAX_ROUNDS` 轮工具调用，超过后强制模型输出最终回复。
- 是否调用工具由模型根据用户问题自行决定。
- 工具调用格式参考 [DeepSeek Tool Calls 文档](https://api-docs.deepseek.com/zh-cn/guides/tool_calls)。

### `save_user_memory`

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `content` | `string` | 必填，要记住的内容，建议用第三人称简短描述 |
| `category` | `string` | 可选，`profile` / `preference` / `habit` / `relationship` / `fact`，默认 `fact` |

### `search_user_memory`

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `keyword` | `string` | 可选，按关键词搜索记忆内容 |
| `limit` | `integer` | 可选，返回 1–20 条，默认 10 |

### `delete_user_memory`

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `memory_id` | `integer` | 必填，要删除的记忆 ID，可从注入记忆的 `#id` 或搜索工具结果中获得 |

## 命令

| 命令 | 说明 |
| --- | --- |
| `/ping` | 检查插件是否在线，回复 `pong` |

## 开发与测试

```powershell
pip install -e ".[dev]"
pytest
```

## 支持的适配器

- OneBot V11（`nonebot-adapter-onebot`）

## 参考

- [NoneBot2 插件编写文档](https://nonebot.dev/docs/tutorial/create-plugin)
- [DeepSeek Chat Completions API](https://api-docs.deepseek.com/zh-cn/api/create-chat-completion)
- [DeepSeek Tool Calls](https://api-docs.deepseek.com/zh-cn/guides/tool_calls)

## 许可协议

MIT
