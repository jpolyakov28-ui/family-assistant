"""Команда /tasks — единый вход для задач: на сегодня / семейные / неделя / месяц."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.db import get_user_by_telegram_id, list_tasks_for_user
from bot.handlers.add import AddTask
from bot.handlers.common import cancel_kb
from bot.handlers.today import _format_task, _task_keyboard

router = Router()

_WEEKDAY_NAMES_RU = [
    "Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье",
]
_WEEKDAY_SHORT_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
_MONTHS_RU = [
    "", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]


def _menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📋 Мои на сегодня", callback_data="tsk:today")],
            [InlineKeyboardButton(text="👨‍👩‍👧‍👦 Семейные на сегодня", callback_data="tsk:family")],
            [InlineKeyboardButton(text="🗓 На неделю", callback_data="tsk:week")],
            [InlineKeyboardButton(text="📅 На месяц", callback_data="tsk:month")],
            [InlineKeyboardButton(text="📆 На год", callback_data="tsk:year")],
            [InlineKeyboardButton(text="➕ Добавить задачу", callback_data="tsk:add")],
            [InlineKeyboardButton(text="⬅️ Семейный ассистент", callback_data="home:show")],
        ]
    )


@router.message(Command("tasks"))
async def cmd_tasks(message: Message) -> None:
    user = get_user_by_telegram_id(message.from_user.id)
    if not user:
        await message.answer("Сначала зарегистрируйся: /start")
        return
    await message.answer("Что показать?", reply_markup=_menu_kb())


async def _render_today(message: Message, telegram_id: int, *, only_family: bool) -> None:
    user = get_user_by_telegram_id(telegram_id)
    if not user:
        await message.answer("Сначала зарегистрируйся: /start")
        return
    tz = user["timezone"]
    tzinfo = ZoneInfo(tz)
    now = datetime.now(tzinfo)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    tasks = list_tasks_for_user(
        user["id"], due_from=start, due_to=end,
        include_family=True, only_open=True,
    )
    if only_family:
        tasks = [t for t in tasks if t.get("visibility") == "family"]
    if not tasks:
        await message.answer(
            "На сегодня ничего нет 🎉" if not only_family else "Семейных задач на сегодня нет."
        )
        return
    header = "<b>📋 На сегодня:</b>" if not only_family else "<b>👨‍👩‍👧‍👦 Семейные на сегодня:</b>"
    await message.answer(header, parse_mode="HTML")
    for t in tasks:
        await message.answer(
            _format_task(t, tz),
            parse_mode="HTML",
            reply_markup=_task_keyboard(t),
        )


async def _render_range(message: Message, telegram_id: int, days: int, header_text: str) -> None:
    user = get_user_by_telegram_id(telegram_id)
    if not user:
        await message.answer("Сначала зарегистрируйся: /start")
        return
    tz = user["timezone"]
    tzinfo = ZoneInfo(tz)
    now = datetime.now(tzinfo)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=days)
    tasks = list_tasks_for_user(
        user["id"], due_from=start, due_to=end,
        include_family=True, only_open=True,
    )
    if not tasks:
        await message.answer(f"{header_text} задач нет 🎉")
        return
    by_day: dict[int, list[dict]] = {}
    for t in tasks:
        dt = datetime.fromisoformat(t["due_at"].replace("Z", "+00:00")).astimezone(tzinfo)
        day_index = (dt.date() - start.date()).days
        by_day.setdefault(day_index, []).append(t)
    await message.answer(f"<b>{header_text}</b>", parse_mode="HTML")
    for day_index in sorted(by_day.keys()):
        day_date = (start + timedelta(days=day_index)).date()
        weekday_name = _WEEKDAY_NAMES_RU[day_date.weekday()]
        if day_index == 0:
            head = f"<b>{weekday_name}, {day_date.strftime('%d.%m')} — сегодня</b>"
        elif day_index == 1:
            head = f"<b>{weekday_name}, {day_date.strftime('%d.%m')} — завтра</b>"
        else:
            head = f"<b>{weekday_name}, {day_date.strftime('%d.%m')}</b>"
        await message.answer(head, parse_mode="HTML")
        for t in by_day[day_index]:
            await message.answer(
                _format_task(t, tz),
                parse_mode="HTML",
                reply_markup=_task_keyboard(t),
            )


@router.callback_query(F.data == "tsk:today")
async def cb_today(callback: CallbackQuery) -> None:
    await callback.answer()
    await _render_today(callback.message, callback.from_user.id, only_family=False)


@router.callback_query(F.data == "tsk:family")
async def cb_family(callback: CallbackQuery) -> None:
    await callback.answer()
    await _render_today(callback.message, callback.from_user.id, only_family=True)


@router.callback_query(F.data == "tsk:week")
async def cb_week(callback: CallbackQuery) -> None:
    await callback.answer()
    await _render_range(callback.message, callback.from_user.id, days=7, header_text="🗓 На неделю:")


@router.callback_query(F.data == "tsk:month")
async def cb_month(callback: CallbackQuery) -> None:
    await callback.answer()
    await _render_range(callback.message, callback.from_user.id, days=30, header_text="📅 На месяц:")


async def _render_year(message: Message, telegram_id: int) -> None:
    user = get_user_by_telegram_id(telegram_id)
    if not user:
        await message.answer("Сначала зарегистрируйся: /start")
        return
    tz = user["timezone"]
    tzinfo = ZoneInfo(tz)
    now = datetime.now(tzinfo)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=365)
    tasks = list_tasks_for_user(
        user["id"], due_from=start, due_to=end,
        include_family=True, only_open=True,
    )
    if not tasks:
        await message.answer("На год задач нет 🎉")
        return

    by_month: dict[tuple, list] = {}
    for t in tasks:
        dt = datetime.fromisoformat(t["due_at"].replace("Z", "+00:00")).astimezone(tzinfo)
        key = (dt.year, dt.month)
        by_month.setdefault(key, []).append((dt, t))

    for (year, month), items in sorted(by_month.items()):
        await message.answer(
            f"<b>📅 {_MONTHS_RU[month]} {year}</b>",
            parse_mode="HTML",
        )
        for dt, t in items:
            day_short = _WEEKDAY_SHORT_RU[dt.weekday()]
            if t.get("due_has_time"):
                date_line = f"<b>{dt.day:02d}.{month:02d}  {day_short}  {dt.strftime('%H:%M')}</b>"
            else:
                date_line = f"<b>{dt.day:02d}.{month:02d}  {day_short}</b>"
            visibility_marker = {"private": "🔒", "family": "👨‍👩‍👧‍👦"}.get(t.get("visibility", ""), "")
            title_line = f"{visibility_marker} {t['title']}" if visibility_marker else t["title"]
            await message.answer(
                f"{date_line}\n{title_line}",
                parse_mode="HTML",
                reply_markup=_task_keyboard(t),
            )


@router.callback_query(F.data == "tsk:year")
async def cb_year(callback: CallbackQuery) -> None:
    await callback.answer()
    await _render_year(callback.message, callback.from_user.id)


@router.callback_query(F.data == "tsk:add")
async def cb_add(callback: CallbackQuery, state: FSMContext) -> None:
    user = get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("Сначала /start", show_alert=True)
        return
    await callback.answer()
    await state.clear()
    await state.update_data(user_db_id=user["id"], user_tz=user["timezone"])
    await callback.message.answer(
        "Что добавить? Напиши коротко (например: «Английский»).",
        reply_markup=cancel_kb(),
    )
    await state.set_state(AddTask.title)
