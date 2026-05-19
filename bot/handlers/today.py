"""Клавиатура задачи и обработчики действий: «Готово», будильник, «Отложить»."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot.datetime_utils import format_human
from bot.db import (
    get_task,
    get_user_by_telegram_id,
    mark_task_done,
    set_task_alarm,
    snooze_task,
)

router = Router()


def _task_keyboard(task: dict) -> InlineKeyboardMarkup:
    """Клавиатура задачи: «Готово» + будильник (если у задачи есть срок)."""
    task_id = task["id"]
    row = [InlineKeyboardButton(text="✅ Готово", callback_data=f"done:{task_id}")]
    if task.get("due_at"):
        icon = "🔔" if task.get("alarm") else "⏰"
        row.append(InlineKeyboardButton(text=icon, callback_data=f"alarm:{task_id}"))
    return InlineKeyboardMarkup(inline_keyboard=[row])


def _format_task(task: dict, tz: str) -> str:
    title = task["title"]
    when = ""
    if task.get("due_at"):
        dt = datetime.fromisoformat(task["due_at"].replace("Z", "+00:00"))
        when = f" — <i>{format_human(dt, tz)}</i>"
    visibility_marker = {"private": "🔒", "assignees": "", "family": "👨‍👩‍👧‍👦"}.get(
        task.get("visibility", ""), ""
    )
    marker = f"{visibility_marker} " if visibility_marker else ""
    return f"{marker}{title}{when}"


@router.callback_query(F.data.startswith("done:"))
async def handle_done(callback: CallbackQuery) -> None:
    task_id = callback.data.split(":", 1)[1]
    mark_task_done(task_id)
    await callback.answer("Готово ✓")
    if callback.message:
        try:
            await callback.message.edit_text(
                f"~~{callback.message.html_text}~~\n\n<b>✓ Выполнено</b>",
                parse_mode="HTML",
            )
        except Exception:
            await callback.message.edit_reply_markup(reply_markup=None)


@router.callback_query(F.data.startswith("alarm:"))
async def handle_alarm(callback: CallbackQuery) -> None:
    task_id = callback.data.split(":", 1)[1]
    task = get_task(task_id)
    if not task:
        await callback.answer("Не нашёл задачу", show_alert=True)
        return
    if not task.get("due_at"):
        await callback.answer("У задачи нет времени — будильник недоступен", show_alert=True)
        return

    new_state = not task.get("alarm")
    set_task_alarm(task_id, new_state)
    if new_state:
        await callback.answer("⏰ Будильник включён — буду звонить, пока не нажмёшь «Готово»")
    else:
        await callback.answer("🔕 Будильник выключен")

    task["alarm"] = new_state
    if callback.message:
        try:
            await callback.message.edit_reply_markup(reply_markup=_task_keyboard(task))
        except Exception:
            pass


@router.callback_query(F.data.startswith("snz:"))
async def handle_snooze(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Не понял команду", show_alert=True)
        return
    _, task_id, when = parts

    user = get_user_by_telegram_id(callback.from_user.id)
    tz = user["timezone"] if user else "Europe/Moscow"
    tzinfo = ZoneInfo(tz)
    now = datetime.now(tzinfo)

    if when == "tomorrow":
        new_due = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    else:
        try:
            minutes = int(when)
        except ValueError:
            await callback.answer("Не понял время", show_alert=True)
            return
        new_due = now + timedelta(minutes=minutes)

    snooze_task(task_id, new_due)

    task = get_task(task_id)
    title = task["title"] if task else "задача"
    await callback.answer(f"Перенёс: {format_human(new_due, tz)}")
    if callback.message:
        try:
            await callback.message.edit_text(
                f"💤 <b>{title}</b>\nНапомню {format_human(new_due, tz)}",
                parse_mode="HTML",
            )
        except Exception:
            await callback.message.edit_reply_markup(reply_markup=None)
