# nonebot-plugin-aichat-deepseek

基于 [DeepSeek](https://www.deepseek.com/) API 的 NoneBot2 AI 对话插件。

当前为骨架版本，提供 `/ping` 命令；对话能力接入中。

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

在 `.env` 中填写（均可不填，缺省时插件仍可正常加载）：

| 配置项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `DEEPSEEK_API_KEY` | `str \| None` | `None` | DeepSeek API Key，缺失时仅提示未配置 |
| `DEEPSEEK_API_BASE` | `str` | `https://api.deepseek.com` | API 地址 |
| `DEEPSEEK_MODEL` | `str` | `deepseek-chat` | 使用的模型 |
| `DEEPSEEK_TIMEOUT` | `float` | `60.0` | 请求超时（秒） |

## 使用

| 命令 | 说明 |
| --- | --- |
| `/ping` | 检查插件是否在线，回复 `pong` |

## 支持的适配器

- OneBot V11（`nonebot-adapter-onebot`）

## 许可协议

MIT
