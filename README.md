# nonebot-plugin-aichat-deepseek

基于 [DeepSeek](https://www.deepseek.com/) API 的 NoneBot2 私聊 AI 对话插件。

私聊机器人直接发送消息即可开始对话，**不需要任何命令前缀**；群聊消息不会触发。

## 功能

- 仅响应 OneBot V11 私聊消息，无需 `/` 等前缀
- 多轮上下文（默认保留最近 5 轮，按用户隔离）
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
DEEPSEEK_SPLIT_DELIMITER=|||
DEEPSEEK_REPLY_INTERVAL=1.0
```

| 配置项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `DEEPSEEK_API_KEY` | `str \| None` | `None` | DeepSeek API Key；缺失时私聊会提示配置 |
| `DEEPSEEK_API_BASE` | `str` | `https://api.deepseek.com` | API 地址，可替换为兼容代理 |
| `DEEPSEEK_MODEL` | `str` | `deepseek-flash` | 模型名，可选 `deepseek-flash`、`deepseek-v4-pro` |
| `DEEPSEEK_TIMEOUT` | `float` | `60.0` | 单次请求超时（秒） |
| `DEEPSEEK_SYSTEM_PROMPT` | `str` | 内置中文助手提示词 | 人设提示词；插件会自动追加纯文本与分隔符输出要求 |
| `DEEPSEEK_TEMPERATURE` | `float` | `1.0` | 采样温度，范围 0–2 |
| `DEEPSEEK_MAX_TOKENS` | `int \| None` | `None` | 最大输出 token 数，不填使用服务端默认值 |
| `DEEPSEEK_THINKING` | `bool \| None` | `None` | 是否开启思考模式；`None` 表示不发送该字段、使用服务端默认值 |
| `DEEPSEEK_HISTORY_TURNS` | `int` | `5` | 保留的上下文轮数（一问一答为一轮），`0` 表示不保留 |
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

3. 继续发送消息即可进行多轮对话；上下文只保存在内存中，重启机器人后清空。

插件会自动在系统提示词后追加输出约束：模型只输出纯文本，并用 `|||` 把回复拆成多条短消息。发送前还会移除残留的 Markdown 标记，并按照配置的间隔逐条发送，模拟真人分条聊天的节奏。可以通过 `DEEPSEEK_SPLIT_DELIMITER` 更换分隔符，或把 `DEEPSEEK_REPLY_INTERVAL` 设为 `0` 关闭间隔。

群聊中发送的消息不会触发本插件；以 `/` 开头的消息会交给命令处理器，不会进入对话。

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

## 许可协议

MIT
