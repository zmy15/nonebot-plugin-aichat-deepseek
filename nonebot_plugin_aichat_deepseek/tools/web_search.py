"""``web_search`` 工具的定义与实现。"""

from __future__ import annotations

import json
from typing import Any

from ..config import plugin_config
from .base import Tool, ToolContext, clip, error, make_definition

NAME = "web_search"

MAX_QUERY_CHARS = 128
MAX_COUNT = 50
MAX_SNIPPET_CHARS = 400
MAX_SUMMARY_CHARS = 1000
MAX_CONTENT_CHARS = 3000

DEFINITION = make_definition(
    NAME,
    "联网搜索网页。用户询问实时信息、新闻、价格、天气、最近发生的事件，"
    "或你需要最新资料、不确定答案时调用。"
    "query 支持 site:、-site:、引号、lang:、after:、before: 等搜索语法。"
    "默认只返回摘要；需要网页正文时把 need_content 设为 true。",
    {
        "query": {
            "type": "string",
            "description": (
                "搜索词，1-128 个字符。支持 site:、-site:、引号、"
                "lang:、after:、before: 等语法。"
            ),
        },
        "count": {
            "type": "integer",
            "description": "可选，返回条数，1-50，默认 5。",
        },
        "need_content": {
            "type": "boolean",
            "description": (
                "可选，是否返回网页正文。默认 false，只返回摘要；"
                "摘要不够时再设为 true。"
            ),
        },
        "ori_question": {
            "type": "string",
            "description": (
                "可选，触发搜索的用户原始问题，1-128 个字符，"
                "有助于搜索引擎理解意图。"
            ),
        },
    },
    required=("query",),
)


def _format_error(exc: Exception) -> str:
    status = getattr(exc, "status_code", None)
    detail = str(exc).strip() or exc.__class__.__name__

    if status == 401:
        return "网页搜索 API Key 无效，请检查 DEEPSEEK_API_KEY。"
    if status == 402:
        return "DeepSeek 账户余额不足，请充值后再试。"
    if status == 429:
        return "网页搜索请求太频繁，请稍后再试。"
    if status is not None and status >= 500:
        return "网页搜索服务暂时不可用，请稍后再试。"
    if status == 400:
        return f"网页搜索参数不合法：{detail[:200]}"
    return f"网页搜索失败：{detail[:200]}"


def _format_results(
    data: dict[str, Any], *, need_content: bool
) -> dict[str, Any]:
    results = data.get("results")
    if not isinstance(results, list):
        return {"error": "网页搜索返回了无法解析的结果"}

    items: list[dict[str, Any]] = []
    for row in results:
        if not isinstance(row, dict):
            continue
        item: dict[str, Any] = {
            "title": str(row.get("title") or ""),
            "url": str(row.get("url") or ""),
            "snippet": clip(str(row.get("snippet") or ""), MAX_SNIPPET_CHARS),
            "summary": clip(str(row.get("summary") or ""), MAX_SUMMARY_CHARS),
        }
        if row.get("site_name"):
            item["site_name"] = row["site_name"]
        if row.get("date"):
            item["date"] = row["date"]
        if isinstance(row.get("authority"), int):
            item["authority"] = row["authority"]
        score = row.get("rerank_score")
        if isinstance(score, (int, float)):
            item["rerank_score"] = score
        if need_content:
            item["content"] = clip(
                str(row.get("content") or ""), MAX_CONTENT_CHARS
            )
        items.append(item)

    payload: dict[str, Any] = {"count": len(items), "results": items}
    if not items:
        payload["message"] = "没有找到相关结果"
    return payload


async def execute(args: dict[str, Any], ctx: ToolContext) -> str:
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        return error("query 不能为空")
    query = query.strip()
    if len(query) > MAX_QUERY_CHARS:
        return error(f"query 过长，最多 {MAX_QUERY_CHARS} 个字符")

    count_value = args.get(
        "count", plugin_config.deepseek_search_default_count
    )
    try:
        count = int(count_value)
    except (TypeError, ValueError):
        return error("count 必须是整数")
    count = max(1, min(count, MAX_COUNT))

    need_content = args.get("need_content", False)
    if not isinstance(need_content, bool):
        return error("need_content 必须是布尔值")

    ori_question = args.get("ori_question")
    if ori_question is not None:
        if not isinstance(ori_question, str):
            return error("ori_question 必须是字符串")
        ori_question = ori_question.strip() or None
        if ori_question and len(ori_question) > MAX_QUERY_CHARS:
            return error(
                f"ori_question 过长，最多 {MAX_QUERY_CHARS} 个字符"
            )

    if ctx.search_web is None:
        return error("联网搜索服务未配置，请检查 DEEPSEEK_API_KEY")

    try:
        data = await ctx.search_web(
            query,
            count=count,
            need_content=need_content,
            ori_question=ori_question,
            session_key=ctx.session_key,
        )
    except Exception as exc:
        return error(_format_error(exc))

    if not isinstance(data, dict):
        return error("网页搜索返回了无法解析的结果")

    payload = _format_results(data, need_content=need_content)
    if "error" in payload:
        return error(str(payload["error"]))
    payload["query"] = query
    return json.dumps(payload, ensure_ascii=False)


TOOL = Tool(
    name=NAME,
    definition=DEFINITION,
    handler=execute,
    group="search",
    enabled=lambda: plugin_config.deepseek_search_enabled,
)
