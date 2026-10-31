# nonebot-plugin-aichat-deepseek

基于 [DeepSeek](https://www.deepseek.com/) API 的 NoneBot2 私聊 AI 对话插件。

私聊机器人直接发送消息即可开始对话，**不需要任何命令前缀**；群聊消息不会触发。

## 功能

- 仅响应 OneBot V11 私聊消息，无需 `/` 等前缀
- 多轮上下文（默认加载最近 30 轮，按用户隔离）
- 当前上下文持久化到 SQLite，启动时自动加载历史
- 历史聊天记录复用同一数据库，模型可调用 `query_chat_history` 查询过去聊过什么
- 长期记忆：自动保存用户信息、偏好、习惯等，并在后续对话中注入 system 指令
- 单个用户自定义 system 提示词：通过工具保存专属人设、语气或回复风格
- `/清空` 命令：清空当前私聊用户的对话上下文
- 戳一戳：模型可调用工具戳用户；用户戳机器人时也会用 AI 回应
- 连续消息聚合：用户分多次发送的一句话会合并；AI 判断不完整时先不回复，等提问完整
- 回复抖动：首条回复前有随机停顿，多条回复之间也有随机间隔
- 支持私聊图片理解：图片经 Files API 上传后以 `file_id` 交给 `deepseek-flash` 分析
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
DEEPSEEK_SYSTEM_PROMPT="你是一个乐于助人的 AI 助手，请使用简体中文回答用户的问题。"
DEEPSEEK_DB_PATH=data/nonebot_plugin_aichat_deepseek/chat.db
DEEPSEEK_TOOLS_ENABLED=true
DEEPSEEK_TOOL_MAX_ROUNDS=3
DEEPSEEK_POKE_ENABLED=true
DEEPSEEK_MEMORY_ENABLED=true
DEEPSEEK_MEMORY_MAX_ITEMS=20
DEEPSEEK_MEMORY_MAX_CHARS=1000
DEEPSEEK_CUSTOM_PROMPT_ENABLED=true
DEEPSEEK_CUSTOM_PROMPT_MAX_CHARS=2000
DEEPSEEK_IMAGE_ENABLED=true
DEEPSEEK_IMAGE_MAX_COUNT=4
DEEPSEEK_IMAGE_EXPIRE_SECONDS=86400
DEEPSEEK_AGGREGATE_MESSAGES=true
DEEPSEEK_DEBOUNCE_SECONDS=1.2
DEEPSEEK_DEBOUNCE_JITTER=0.4
DEEPSEEK_COMPLETENESS_CHECK=true
DEEPSEEK_REPLY_DELAY=1.0
DEEPSEEK_REPLY_DELAY_JITTER=0.5
DEEPSEEK_HISTORY_TURNS=30
DEEPSEEK_COMPRESSION_TRIGGER_TURNS=30
DEEPSEEK_COMPRESSION_BATCH_MESSAGES=20
DEEPSEEK_SPLIT_DELIMITER=|||
DEEPSEEK_SPLIT_PARAGRAPHS=true
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
| `DEEPSEEK_POKE_ENABLED` | `bool` | `True` | 是否启用戳一戳工具和戳一戳事件回应 |
| `DEEPSEEK_MEMORY_ENABLED` | `bool` | `True` | 是否启用长期记忆的保存、查询和注入 |
| `DEEPSEEK_MEMORY_MAX_ITEMS` | `int` | `20` | 每次最多注入多少条长期记忆 |
| `DEEPSEEK_MEMORY_MAX_CHARS` | `int` | `1000` | 注入长期记忆的字符预算 |
| `DEEPSEEK_CUSTOM_PROMPT_ENABLED` | `bool` | `True` | 是否允许单个用户通过工具自定义 system 提示词 |
| `DEEPSEEK_CUSTOM_PROMPT_MAX_CHARS` | `int` | `2000` | 单个用户自定义提示词的最大字符数 |
| `DEEPSEEK_IMAGE_ENABLED` | `bool` | `True` | 是否启用私聊图片理解 |
| `DEEPSEEK_IMAGE_MAX_BYTES` | `int` | `67108864` | 单张图片最大字节数（64 MiB） |
| `DEEPSEEK_IMAGE_MAX_COUNT` | `int` | `4` | 单条消息最多处理几张图片 |
| `DEEPSEEK_IMAGE_TIMEOUT` | `float` | `60.0` | 下载图片超时（秒） |
| `DEEPSEEK_IMAGE_EXPIRE_SECONDS` | `int` | `86400` | 上传文件有效期（秒），`0` 表示永久有效 |
| `DEEPSEEK_AGGREGATE_MESSAGES` | `bool` | `True` | 是否把用户连续发送的多条消息聚合后再处理 |
| `DEEPSEEK_DEBOUNCE_SECONDS` | `float` | `1.2` | 最后一条消息后等待多久再判断是否完整（秒） |
| `DEEPSEEK_DEBOUNCE_JITTER` | `float` | `0.4` | 聚合等待时间的随机抖动范围（±秒） |
| `DEEPSEEK_COMPLETENESS_CHECK` | `bool` | `True` | 是否用一次模型调用判断消息是否完整 |
| `DEEPSEEK_REPLY_DELAY` | `float` | `1.0` | 首条回复前的随机延迟（秒） |
| `DEEPSEEK_REPLY_DELAY_JITTER` | `float` | `0.5` | 首条回复延迟的随机抖动范围（±秒） |
| `DEEPSEEK_TIMEOUT` | `float` | `60.0` | 单次请求超时（秒） |
| `DEEPSEEK_SYSTEM_PROMPT` | `str` | `你是一个乐于助人的 AI 助手，请使用简体中文回答用户的问题。` | 默认 system 角色身份提示词；插件会自动追加纯文本与分隔符输出要求 |
| `DEEPSEEK_TEMPERATURE` | `float` | `1.0` | 采样温度，范围 0–2 |
| `DEEPSEEK_MAX_TOKENS` | `int \| None` | `None` | 最大输出 token 数，不填使用服务端默认值 |
| `DEEPSEEK_THINKING` | `bool \| None` | `None` | 是否开启思考模式；`None` 表示不发送该字段、使用服务端默认值 |
| `DEEPSEEK_HISTORY_TURNS` | `int` | `30` | 每次加载最近多少轮上下文，`0` 表示不加载（对话仍会入库） |
| `DEEPSEEK_COMPRESSION_TRIGGER_TURNS` | `int` | `30` | 未压缩消息超过多少轮时触发压缩，`0` 表示关闭 |
| `DEEPSEEK_COMPRESSION_BATCH_MESSAGES` | `int` | `20` | 每次压缩最早多少条消息（用户和 AI 各算一条） |
| `DEEPSEEK_SPLIT_DELIMITER` | `str` | `\|\|\|` | 模型用于分隔多条消息的标记 |
| `DEEPSEEK_SPLIT_PARAGRAPHS` | `bool` | `True` | 模型没有输出分隔符时，是否按空行段落拆成多条消息 |
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

插件会自动在系统提示词后追加输出约束：模型只输出纯文本，优先分成多条短消息，每条像真人聊天，一句话不要太长、句末可以不带标点，并尽量用 `|||` 分隔。如果模型没有输出分隔符，会按空行段落拆分（`DEEPSEEK_SPLIT_PARAGRAPHS`），再按配置的间隔逐条发送。发送前还会移除残留的 Markdown 标记。可以通过 `DEEPSEEK_SPLIT_DELIMITER` 更换分隔符，或把 `DEEPSEEK_REPLY_INTERVAL` 设为 `0` 关闭间隔。

群聊中发送的消息不会触发本插件；以 `/` 开头的消息会交给命令处理器，不会进入对话。

## 消息聚合与回复节奏

用户可能把一句话拆成几条消息发送。插件会把同一个用户连续发送的内容先聚合：

1. 每条新消息都会重置防抖计时器（默认 `1.2` 秒，±`0.4` 秒）；
2. 计时结束后，把这段时间内的文本按换行拼接，图片合并；
3. 如果开启 `DEEPSEEK_COMPLETENESS_CHECK`，用一次模型调用判断消息是否完整；
4. 判断为 `INCOMPLETE` 时不回复、不写入数据库，保留缓冲区等待后续消息；
5. 判断为 `COMPLETE` 时再进入正式对话，并在首条回复前随机等待 `DEEPSEEK_REPLY_DELAY` 左右的时间。

补充说明：

- 带图片的消息直接视为完整，不额外调用完整性判断；
- 判断为不完整后如果没有后续消息，插件会一直保持沉默，这是预期行为；
- 完整性判断会增加一次模型调用，不需要时可关闭；
- 以 `/` 开头的命令消息不进入聚合；
- 聚合状态只在内存中，机器人重启后会丢失；
- 首条回复延迟和多条消息之间的间隔是两套独立配置，分别控制“打字停顿”和“分条发送节奏”。

## 日志

每次用户消息、API 调用、工具调用和最终回复都会记录日志，方便排查“有没有回复”、缓存命中以及工具执行情况。

示例：

```text
[chat] incoming session=12345:67890 text_len=8 images=0 aggregate=True
[chat] aggregated session=12345:67890 text_len=8 images=0
[deepseek-api] start session=12345:67890 phase=reply model=deepseek-flash messages=12 tools=4
[deepseek-api] ok session=12345:67890 phase=reply status=200 duration_ms=1832 cache_hit=512 cache_miss=128 prompt_tokens=640 completion_tokens=96
[tool] start session=12345:67890 name=query_chat_history args_len=27
[tool] done session=12345:67890 name=query_chat_history status=ok duration_ms=3 result_chars=184
[deepseek] session=12345:67890 phase=reply cache_hit=512 cache_miss=128 prompt_tokens=640 completion_tokens=96
[chat] reply qid=a1b2c3d4 session=12345:67890 replied=true reason=ok segments=2 api_calls=1 cache_hit=512 cache_miss=128 prompt_tokens=640 completion_tokens=96
```

- `incoming`：收到一条用户消息，记录文本长度和图片数量；
- `question`：一次完整提问开始处理，带 `qid`；
- `aggregated`：连续消息聚合完成后进入处理；
- `deepseek-api start/ok/error`：每次 Chat Completions / Files API 请求的模型、消息数、工具数、状态码、耗时和缓存命中；
- `tool start/done/error`：每次工具调用的名称、参数长度、执行耗时、结果长度和状态；
- `deepseek`：兼容原有的按阶段 token 统计；
- `reply`：最终是否回复、原因、分条数量、累计 token；
- 判断为不完整时记录 `[chat] no_reply ... reason=incomplete`；
- 未配置 Key、图片错误、API 错误、发送失败等会记录 `replied=false` 及原因。

日志只记录文本长度、图片数量和参数长度，不记录用户完整原文、图片内容或工具参数具体内容。缓存命中取自 DeepSeek 返回的 `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens`（兼容 `prompt_tokens_details.cached_tokens`）。

关于 `cache_hit=0`：

- DeepSeek 的上下文缓存基于**前缀完全匹配**，前缀变化后不会命中；
- 系统提示词里只保留日期（UTC+8），不再包含分钟级时间，避免每分钟都让前缀失效；
- 长期记忆、历史摘要更新后，下一次请求的前缀会变化，出现一次未命中是正常的；
- 完整性判断是较短的独立请求，缓存本身也是“尽力而为”，不保证命中；
- 新会话、首次请求、跨天第一次请求都可能 `cache_hit=0`。

## 图片理解

私聊可以直接发送图片，也可以图片加文字一起发送。

处理流程：

1. 从 OneBot `image` 消息段的 `url` / `file` 字段获取图片，支持 http(s) URL、本地路径、`file://`、`base64://` 和 data URL；
2. 按文件实际内容校验格式：JPEG、PNG、GIF、WebP；
3. 通过 [Files API](https://api-docs.deepseek.com/zh-cn/guides/files_api) 的 `POST /files` 上传，`purpose=user_data`，得到 `file_id`；
4. 在当前 user 消息中放入 `{"type": "file", "file_id": "..."}` 内容块；
5. 图片只随当前请求发送，历史中保存“用户发送了 N 张图片”的标记，不会重复上传。

注意：

- 图片理解目前只有 `deepseek-flash` 支持，`deepseek-v4-pro` 不支持图像输入；
- 单张图片最大 64 MiB，单条消息默认最多 4 张；
- 只发图片不配文字时，插件会自动使用“请描述这张图片/这些图片”作为提示；
- 上传文件默认 24 小时后过期，可通过 `DEEPSEEK_IMAGE_EXPIRE_SECONDS=0` 改为永久有效；
- 格式和限制参考 [图像理解](https://api-docs.deepseek.com/zh-cn/guides/vision)。

## 数据存储与上下文压缩

- 当前上下文数据库默认位于 `data/nonebot_plugin_aichat_deepseek/chat.db`，启动时自动创建表并加载未压缩的历史消息和摘要。
- 每完成一轮问答，用户消息和 AI 原始回复会立即写入 `messages` 表。
- 未压缩消息超过 `DEEPSEEK_COMPRESSION_TRIGGER_TURNS` 轮（默认 30 轮）时，插件会把最早 `DEEPSEEK_COMPRESSION_BATCH_MESSAGES` 条（默认 20 条）交给模型压缩成摘要，保存到 `summaries` 表，并在后续请求中放到 system 指令之后。
- 被压缩的消息不会删除，只是标记为 `compressed = 1`，便于保留原始记录；可用 `sqlite3` 直接查看。
- `query_chat_history` 工具直接查询同一个 `messages` 表，因此可以检索到包括已压缩消息在内的完整历史。
- `messages.created_at` 以 UTC 保存；工具输入和返回的时间统一按 UTC+8 解释和展示。
- 发送 `/清空` 会删除当前用户的 `messages`、`summaries` 和 `memories` 记录，保留 `user_prompts` 中的自定义人设。
- 长期记忆保存在同一数据库的 `memories` 表中，按 `session_key` 隔离。
- 每个用户的自定义 system 提示词保存在同一数据库的 `user_prompts` 表中，同样按 `session_key` 隔离。
- 数据库为明文存储，请自行做好备份和访问权限控制。

## 长期记忆

- 当用户提到长期稳定的个人信息、偏好、习惯、关系或重要事实时，模型会调用 `save_user_memory` 保存。
- 每轮请求会把该用户最近最多 `DEEPSEEK_MEMORY_MAX_ITEMS` 条记忆注入 system 指令，受 `DEEPSEEK_MEMORY_MAX_CHARS` 字符预算限制。
- 记忆分类：`profile`（个人信息）、`preference`（偏好）、`habit`（习惯）、`relationship`（关系）、`fact`（事实）。
- 用户要求忘记时，模型可调用 `delete_user_memory`；需要查找更早记忆时调用 `search_user_memory`。
- 记忆只属于当前 `session_key`，不会跨用户读取。

## 自定义 system 提示词

启用 `DEEPSEEK_CUSTOM_PROMPT_ENABLED` 后，每个私聊用户都可以通过自然语言让模型保存自己的 system 提示词：

```text
以后用简短、傲娇的语气回复我
```

模型会调用 `set_user_system_prompt` 保存。该提示词只对当前 `session_key` 生效，并会追加到 system 消息中的“【用户自定义指令】”部分，位置在输出格式要求之后、历史摘要和长期记忆之前。

- 用户询问当前设定时，模型调用 `get_user_system_prompt`；
- 用户要求恢复默认时，模型调用 `clear_user_system_prompt`；
- 自定义提示词最多 `DEEPSEEK_CUSTOM_PROMPT_MAX_CHARS` 个字符，默认 2000；
- 设置后从下一轮对话开始生效；
- 修改或清除自定义提示词会让缓存前缀变化一次，属于正常现象；
- 提示词只影响当前用户，不会影响其他私聊用户。

## 戳一戳

启用 `DEEPSEEK_POKE_ENABLED` 后支持两种行为：

1. **模型主动戳用户**：用户明确要求“戳我一下”“提醒我”时，模型调用 `poke_user` 工具。
2. **用户戳机器人**：私聊中用户戳机器人时，插件会生成一条 AI 回复，并把这次互动写入当前对话历史。

实现说明：

- `poke_user` 只作用于当前私聊用户，不接受其他用户 ID；
- 优先调用 OneBot V11 的 `friend_poke`，失败时回退到 `send_poke`；
- 只响应私聊里 `target_id == self_id` 的戳一戳事件，群聊戳一戳不处理；
- 戳一戳回应会走正常的模型调用、system 提示词、自定义人设和分条发送流程；
- 如果当前 OneBot 实现不支持相关 API，工具会返回错误，不会影响普通聊天。

## 工具调用

启用 `DEEPSEEK_TOOLS_ENABLED` 后，模型会获得以下工具（记忆相关工具还要求 `DEEPSEEK_MEMORY_ENABLED=true`，自定义提示词工具要求 `DEEPSEEK_CUSTOM_PROMPT_ENABLED=true`）：

| 工具 | 说明 |
| --- | --- |
| `query_chat_history` | 查询当前私聊用户过去的聊天记录 |
| `save_user_memory` | 保存用户长期信息、偏好等 |
| `search_user_memory` | 搜索已保存的长期记忆 |
| `delete_user_memory` | 删除某条长期记忆 |
| `set_user_system_prompt` | 保存当前用户专属的 system 提示词 |
| `get_user_system_prompt` | 查看当前用户的自定义提示词 |
| `clear_user_system_prompt` | 清除当前用户的自定义提示词 |
| `poke_user` | 戳一戳当前私聊用户 |

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

系统提示中会附带当前 UTC+8 日期，模型遇到“昨天”“上周”等相对时间时会先换算成具体日期再查询。

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

### `set_user_system_prompt`

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `content` | `string` | 必填，完整的自定义 system 提示词，最大长度由 `DEEPSEEK_CUSTOM_PROMPT_MAX_CHARS` 控制 |

会覆盖当前用户原来的自定义提示词。

### `get_user_system_prompt`

无参数，返回当前用户已保存的自定义提示词；没有设置时 `content` 为 `null`。

### `clear_user_system_prompt`

无参数，清除当前用户的自定义提示词并恢复默认人设。

### `poke_user`

无参数，戳一戳当前私聊用户。优先调用 `friend_poke`，失败时尝试 `send_poke`。

## 命令

| 命令 | 说明 |
| --- | --- |
| `/ping` | 检查插件是否在线，回复 `pong` |
| `/清空` | 清空当前私聊用户的消息、摘要和长期记忆，保留自定义 system 提示词 |
| `/清除`、`/重置`、`/清空上下文`、`/清除上下文`、`/重置上下文`、`/clear`、`/reset` | `/清空` 的兼容别名 |

`/清空` 及其别名只作用于当前私聊用户，不会影响其他用户。清空后聊天从零开始，自定义人设仍然保留；如果也需要恢复默认人设，可另外让模型调用 `clear_user_system_prompt`。

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
- [DeepSeek Files API](https://api-docs.deepseek.com/zh-cn/guides/files_api)
- [DeepSeek 图像理解](https://api-docs.deepseek.com/zh-cn/guides/vision)

## 许可协议

MIT
