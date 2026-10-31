"""基于 nonebot-plugin-apscheduler 的定时任务支持。

定时任务不依赖事件响应器，任务执行时只能通过 OneBot API 主动发送消息
或戳一戳。调度器使用默认的内存 JobStore，机器人重启后未执行的任务会丢失。
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from nonebot import get_bot, logger, require

from .config import plugin_config
from .history import UTC8

_scheduler: Any | None = None
_followup_tokens: dict[str, str] = {}

try:
    require("nonebot_plugin_apscheduler")
    from nonebot_plugin_apscheduler import scheduler as _scheduler
except Exception as exc:
    logger.warning(
        "定时任务功能不可用，请安装 nonebot-plugin-apscheduler："
        f"{exc.__class__.__name__}"
    )


def get_scheduler() -> Any | None:
    """返回 APScheduler 调度器；未安装插件时为 ``None``。"""
    return _scheduler


def new_job_id(self_id: str, user_id: int) -> str:
    return f"aichat:{self_id}:{user_id}:{uuid.uuid4().hex[:8]}"


def task_prefix(self_id: str, user_id: int) -> str:
    return f"aichat:{self_id}:{user_id}:"


def parse_run_at(value: str) -> datetime:
    text = value.strip().replace("/", "-")
    if not text:
        raise ValueError("run_at 不能为空")
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"

    try:
        moment = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(
            "run_at 格式无效，请使用 UTC+8 的 "
            "YYYY-MM-DD HH:MM:SS 或 ISO 格式"
        ) from exc

    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC8)
    return moment.astimezone(UTC8)


def parse_schedule_time(args: Mapping[str, Any]) -> datetime:
    now = datetime.now(UTC8)
    max_delay = plugin_config.deepseek_scheduler_max_delay_seconds
    delay_value = args.get("delay_seconds")
    run_at_value = args.get("run_at")

    if delay_value is not None and run_at_value is not None:
        raise ValueError("delay_seconds 和 run_at 只能提供一个")
    if delay_value is None and run_at_value is None:
        raise ValueError("delay_seconds 和 run_at 至少提供一个")

    if delay_value is not None:
        try:
            delay = int(delay_value)
        except (TypeError, ValueError) as exc:
            raise ValueError("delay_seconds 必须是整数") from exc
        if delay < 1 or delay > max_delay:
            raise ValueError(
                f"delay_seconds 必须在 1 到 {max_delay} 之间"
            )
        return now + timedelta(seconds=delay)

    if not isinstance(run_at_value, str):
        raise ValueError("run_at 必须是字符串")
    run_date = parse_run_at(run_at_value)
    if run_date <= now:
        raise ValueError("run_at 必须晚于当前时间")
    if (run_date - now).total_seconds() > max_delay:
        raise ValueError(f"run_at 最远只能设置到 {max_delay} 秒后")
    return run_date


def job_run_at(job: Any) -> datetime | None:
    value = getattr(job, "next_run_time", None)
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC8)
    return value.astimezone(UTC8)


def owns_job(job: Any, self_id: str, user_id: int) -> bool:
    job_id = getattr(job, "id", "")
    if not isinstance(job_id, str) or not job_id.startswith(
        task_prefix(self_id, user_id)
    ):
        return False
    kwargs = getattr(job, "kwargs", None)
    if not isinstance(kwargs, dict):
        return False
    return (
        str(kwargs.get("self_id")) == self_id
        and str(kwargs.get("user_id")) == str(user_id)
    )


def describe_job(job: Any) -> dict[str, Any]:
    kwargs = getattr(job, "kwargs", None)
    if not isinstance(kwargs, dict):
        kwargs = {}
    run_at = job_run_at(job)
    return {
        "job_id": getattr(job, "id", ""),
        "action": kwargs.get("action"),
        "topic": kwargs.get("topic") or None,
        "run_at": run_at.strftime("%Y-%m-%d %H:%M:%S") if run_at else None,
    }


def find_job(scheduler: Any, job_id: str) -> Any | None:
    get_job = getattr(scheduler, "get_job", None)
    if callable(get_job):
        try:
            return get_job(job_id)
        except Exception:
            return None

    get_jobs = getattr(scheduler, "get_jobs", None)
    if not callable(get_jobs):
        return None
    try:
        jobs = get_jobs()
    except Exception:
        return None
    for job in jobs:
        if getattr(job, "id", "") == job_id:
            return job
    return None


def list_user_jobs(
    scheduler: Any,
    self_id: str,
    user_id: int,
) -> list[Any]:
    get_jobs = getattr(scheduler, "get_jobs", None)
    if not callable(get_jobs):
        return []
    try:
        jobs = get_jobs()
    except Exception:
        return []
    return [
        job
        for job in jobs
        if owns_job(job, self_id, user_id)
    ]


async def run_scheduled_task(
    *,
    job_id: str,
    self_id: str,
    user_id: int,
    action: str,
    topic: str = "",
) -> None:
    """执行一个到期任务：主动发起聊天或戳一戳。"""
    try:
        bot = get_bot(self_id)
    except Exception:
        logger.warning(
            f"[scheduler] 机器人未连接，跳过任务 job={job_id} user={user_id}"
        )
        return

    if action == "chat":
        from .chat import proactive_reply

        async def send(message: str) -> None:
            await bot.call_api(
                "send_private_msg",
                user_id=user_id,
                message=message,
            )

        try:
            await proactive_reply(f"{self_id}:{user_id}", topic, send)
            logger.info(
                f"[scheduler] 已主动发起聊天 job={job_id} user={user_id} "
                f"topic_len={len(topic)}"
            )
        except Exception:
            logger.exception(f"[scheduler] 主动聊天失败 job={job_id}")
        return

    if action == "poke":
        try:
            await bot.call_api("friend_poke", user_id=user_id)
            logger.info(f"[scheduler] 已戳一戳 job={job_id} user={user_id}")
        except Exception:
            try:
                await bot.call_api("send_poke", user_id=user_id)
                logger.info(
                    f"[scheduler] 已戳一戳（send_poke）job={job_id} "
                    f"user={user_id}"
                )
            except Exception:
                logger.exception(f"[scheduler] 戳一戳失败 job={job_id}")
        return

    logger.warning(f"[scheduler] 未知任务类型 job={job_id} action={action}")


def add_scheduled_job(
    scheduler: Any,
    *,
    job_id: str,
    self_id: str,
    user_id: int,
    action: str,
    topic: str,
    run_date: datetime,
) -> None:
    scheduler.add_job(
        run_scheduled_task,
        "date",
        run_date=run_date,
        id=job_id,
        kwargs={
            "job_id": job_id,
            "self_id": self_id,
            "user_id": user_id,
            "action": action,
            "topic": topic,
        },
        replace_existing=True,
        misfire_grace_time=300,
    )


def _followup_job_id(session_key: str) -> str:
    return f"aichat-followup:{session_key}"


def schedule_followup(
    scheduler: Any,
    *,
    session_key: str,
    self_id: str,
    user_id: int,
    delay_seconds: int,
    token: str,
) -> None:
    """用户一段时间没回复时，补发一句追问。"""
    run_date = datetime.now(UTC8) + timedelta(seconds=delay_seconds)
    _followup_tokens[session_key] = token
    scheduler.add_job(
        run_followup_task,
        "date",
        run_date=run_date,
        id=_followup_job_id(session_key),
        kwargs={
            "session_key": session_key,
            "self_id": self_id,
            "user_id": user_id,
            "token": token,
        },
        replace_existing=True,
        misfire_grace_time=300,
    )


def cancel_followup(scheduler: Any | None, session_key: str) -> None:
    """用户回复或戳一戳后取消待执行的追问。"""
    _followup_tokens.pop(session_key, None)
    if scheduler is None:
        return
    try:
        scheduler.remove_job(_followup_job_id(session_key))
    except Exception:
        pass


async def run_followup_task(
    *,
    session_key: str,
    self_id: str,
    user_id: int,
    token: str,
) -> None:
    if _followup_tokens.get(session_key) != token:
        logger.info(f"[scheduler] 追问已取消 session={session_key}")
        return
    _followup_tokens.pop(session_key, None)

    try:
        bot = get_bot(self_id)
    except Exception:
        logger.warning(
            f"[scheduler] 机器人未连接，跳过追问 session={session_key}"
        )
        return

    async def send(message: str) -> None:
        await bot.call_api(
            "send_private_msg",
            user_id=user_id,
            message=message,
        )

    from .chat import followup_reply

    try:
        await followup_reply(session_key, send)
        logger.info(f"[scheduler] 已发送未回复追问 session={session_key}")
    except Exception:
        logger.exception(f"[scheduler] 发送追问失败 session={session_key}")
