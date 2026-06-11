"""Планировщик напоминаний на APScheduler.

Раз в минуту проверяет все открытые задачи с due_at:
для каждого offset из lead_minutes (минут ДО due_at), который ещё не был отправлен,
вычисляет время выстрела и шлёт напоминание, если оно попало в прошедшую минуту.

Если lead_minutes пуст — единственное напоминание уходит в момент due_at (offset=0).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.datetime_utils import format_human
from bot.db import get_client, list_users, mark_offset_sent
from bot.ephemeral import purge_expired

log = logging.getLogger(__name__)


def reminder_kb(task_id: str) -> InlineKeyboardMarkup:
    """Клавиатура напоминания: Готово + быстрые snooze."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Готово", callback_data=f"done:{task_id}")],
            [
                InlineKeyboardButton(text="💤 +15м", callback_data=f"snz:{task_id}:15"),
                InlineKeyboardButton(text="💤 +1ч", callback_data=f"snz:{task_id}:60"),
                InlineKeyboardButton(text="💤 завтра 9:00", callback_data=f"snz:{task_id}:tomorrow"),
            ],
        ]
    )


def _format_lead(offset: int) -> str:
    if offset == 0:
        return "сейчас"
    if offset < 60:
        return f"за {offset} мин"
    if offset % 1440 == 0:
        d = offset // 1440
        return f"за {d} дн" if d > 1 else "за день"
    if offset % 60 == 0:
        h = offset // 60
        return f"за {h} ч"
    return f"за {offset} мин"


async def _send_due_reminders(bot: Bot) -> None:
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(seconds=60)
    window_end = now + timedelta(seconds=30)

    client = get_client()
    res = (
        client.table("tasks")
        .select("*")
        .eq("status", "open")
        .not_.is_("due_at", "null")
        .execute()
    )
    tasks = res.data or []

    for task in tasks:
        due_at = datetime.fromisoformat(task["due_at"].replace("Z", "+00:00"))
        lead = list(task.get("lead_minutes") or [])
        if not lead:
            lead = [0]
        sent = set(task.get("sent_offsets") or [])

        for offset in lead:
            if offset in sent:
                continue
            fire_at = due_at - timedelta(minutes=offset)
            if not (window_start <= fire_at <= window_end):
                continue

            await _fire_reminder(bot, task, offset, due_at)
            mark_offset_sent(task["id"], offset)
            sent.add(offset)


async def _fire_reminder(bot: Bot, task: dict, offset: int, due_at: datetime) -> None:
    recipients = await _recipients_for_task(task)
    title = task["title"]
    when_str = format_human(due_at)
    lead_label = _format_lead(offset)

    if offset == 0:
        text = f"🔔 <b>{title}</b>\n<i>{when_str}</i>"
    else:
        text = f"⏰ <b>{title}</b>\nЧерез {lead_label.removeprefix('за ')}: <i>{when_str}</i>"

    for telegram_id in recipients:
        try:
            await bot.send_message(
                chat_id=telegram_id,
                text=text,
                parse_mode="HTML",
                reply_markup=reminder_kb(task["id"]),
            )
        except Exception as e:
            log.warning("Failed to send reminder to %s: %s", telegram_id, e)


ALARM_REPEAT = timedelta(minutes=10)


async def _ring_alarms(bot: Bot) -> None:
    """Будильник: для открытых задач с alarm=true и наступившим сроком
    шлёт напоминание и повторяет каждые ALARM_REPEAT, пока задача не закрыта."""
    now = datetime.now(timezone.utc)
    client = get_client()
    res = (
        client.table("tasks")
        .select("*")
        .eq("status", "open")
        .eq("alarm", True)
        .not_.is_("due_at", "null")
        .execute()
    )
    for task in res.data or []:
        due_at = datetime.fromisoformat(task["due_at"].replace("Z", "+00:00"))
        if due_at > now:
            continue  # срок ещё не наступил

        last_raw = task.get("alarm_last_ring")
        if last_raw:
            last = datetime.fromisoformat(last_raw.replace("Z", "+00:00"))
            if now - last < ALARM_REPEAT:
                continue

        await _fire_alarm(bot, task)
        client.table("tasks").update(
            {"alarm_last_ring": now.isoformat()}
        ).eq("id", task["id"]).execute()


async def _fire_alarm(bot: Bot, task: dict) -> None:
    recipients = await _recipients_for_task(task)
    text = (
        f"⏰ <b>Будильник: {task['title']}</b>\n"
        f"Нажми «Готово», чтобы выключить."
    )
    for telegram_id in recipients:
        try:
            await bot.send_message(
                chat_id=telegram_id,
                text=text,
                parse_mode="HTML",
                reply_markup=reminder_kb(task["id"]),
            )
        except Exception as e:
            log.warning("Failed to send alarm to %s: %s", telegram_id, e)


async def _recipients_for_task(task: dict) -> list[int]:
    client = get_client()
    visibility = task.get("visibility", "assignees")

    if visibility == "family":
        return [u["telegram_id"] for u in list_users() if u["telegram_id"]]

    res = (
        client.table("task_assignees")
        .select("user_id")
        .eq("task_id", task["id"])
        .execute()
    )
    user_ids = [r["user_id"] for r in (res.data or [])]
    if not user_ids:
        return []
    users_res = (
        client.table("users")
        .select("telegram_id")
        .in_("id", user_ids)
        .execute()
    )
    return [u["telegram_id"] for u in (users_res.data or []) if u["telegram_id"]]


def start_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _send_due_reminders,
        "interval",
        seconds=60,
        args=[bot],
        id="due_reminders",
        next_run_time=datetime.now(),
    )
    scheduler.add_job(
        purge_expired,
        "interval",
        seconds=60,
        args=[bot],
        id="purge_ephemeral",
    )
    scheduler.add_job(
        _ring_alarms,
        "interval",
        seconds=60,
        args=[bot],
        id="ring_alarms",
        next_run_time=datetime.now(),
    )
    scheduler.start()
    log.info("Scheduler started")
    return scheduler
