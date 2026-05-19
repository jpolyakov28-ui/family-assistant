"""Команда /schedule — таймлайн дня. Семейная база + личные пункты + задачи."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.db import (
    WEEKDAY_CODES,
    create_task,
    get_user_by_telegram_id,
    list_family_routine_events,
    list_schedule_for_user,
    list_users,
)

router = Router()

_WEEKDAY_NAMES_RU = [
    "понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье",
]
_MONTHS_RU = [
    "", "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]

_CATEGORY_ICON = {
    "lesson": "📚",
    "trip": "🚗",
    "other": "📌",
}
_TYPE_ICON = {
    "todo": "✅",
    "reminder": "🔔",
    "event": "📌",
}

_DEFAULT_ROUTINE = [
    ("07:00", "Подъём"),
    ("07:10", "Водные процедуры"),
    ("07:20", "Зарядка"),
    ("08:00", "Завтрак"),
    ("13:00", "Обед"),
    ("16:00", "Полдник"),
    ("19:00", "Ужин"),
]
_DEFAULT_ROUTINE_RECURRENCE = "WEEKLY:MO,TU,WE,TH,FR,SA,SU"


def _menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📅 Сегодня", callback_data="sch:today"),
                InlineKeyboardButton(text="📆 Завтра", callback_data="sch:tomorrow"),
            ],
            [InlineKeyboardButton(text="📋 На неделю", callback_data="sch:week")],
            [InlineKeyboardButton(text="⬅️ Семейный ассистент", callback_data="home:show")],
        ]
    )


def _icon_for(item: dict) -> str:
    category = item.get("category")
    if category == "routine":
        return ""  # семейная рутина — без иконки, чтобы не перегружать
    if category and category in _CATEGORY_ICON:
        return _CATEGORY_ICON[category]
    return _TYPE_ICON.get(item.get("type", ""), "•")


def _format_header(target_date: date, today: date) -> str:
    weekday = _WEEKDAY_NAMES_RU[target_date.weekday()]
    delta = (target_date - today).days
    if delta == 0:
        prefix = "Сегодня"
    elif delta == 1:
        prefix = "Завтра"
    else:
        prefix = weekday.capitalize()
    return f"📅 <b>{prefix}, {target_date.day} {_MONTHS_RU[target_date.month]}</b> ({weekday})"


def _cook_suffix(item: dict, weekday_code: str, name_by_id: dict[str, str]) -> str:
    cook_by = item.get("cook_by") or {}
    user_id = cook_by.get(weekday_code)
    if not user_id:
        return ""
    name = name_by_id.get(user_id)
    if not name:
        return ""
    return f" 👩‍🍳 {name}"


def _render_day(target_date: date, today: date, payload: dict[str, list[dict]]) -> str:
    timed = payload["timed"]
    untimed = payload["untimed"]
    if not timed and not untimed:
        return f"{_format_header(target_date, today)}\n\nПусто. Добавь пункт через /add."

    weekday_code = WEEKDAY_CODES[target_date.weekday()]
    name_by_id = {u["id"]: u["name"] for u in list_users()}

    lines = [_format_header(target_date, today), ""]
    for item in timed:
        t: datetime = item["local_dt"]
        title = item["title"]
        icon = _icon_for(item)
        cook = _cook_suffix(item, weekday_code, name_by_id)
        line = f"🕐 {t.strftime('%H:%M')} — {title}"
        if icon:
            line += f" {icon}"
        line += cook
        lines.append(line)

    if untimed:
        lines.append("")
        lines.append("<i>— Без времени —</i>")
        for item in untimed:
            icon = _icon_for(item) or "•"
            lines.append(f"{icon} {item['title']}")

    return "\n".join(lines)


def _day_edit_kb(target_date: date) -> InlineKeyboardMarkup:
    weekday_code = WEEKDAY_CODES[target_date.weekday()]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🥣 Обед в меню", callback_data=f"menu:slot:{weekday_code}:lunch"),
                InlineKeyboardButton(text="🍴 Ужин в меню", callback_data=f"menu:slot:{weekday_code}:dinner"),
            ],
            [InlineKeyboardButton(
                text="✏️ Редактировать пункты этого дня",
                callback_data=f"editlist:day:{target_date.isoformat()}",
            )],
        ]
    )


async def _show_day(message: Message, telegram_id: int, target_date: date) -> None:
    user = get_user_by_telegram_id(telegram_id)
    if not user:
        await message.answer("Сначала зарегистрируйся: /start")
        return
    tz = user["timezone"]
    today = datetime.now(ZoneInfo(tz)).date()
    payload = list_schedule_for_user(user["id"], target_date, tz)
    await message.answer(
        _render_day(target_date, today, payload),
        parse_mode="HTML",
        reply_markup=_day_edit_kb(target_date),
    )


@router.message(Command("schedule"))
async def cmd_schedule(message: Message) -> None:
    user = get_user_by_telegram_id(message.from_user.id)
    if not user:
        await message.answer("Сначала зарегистрируйся: /start")
        return
    await message.answer(
        "Расписание дня. Что показать?",
        reply_markup=_menu_kb(),
    )


@router.callback_query(F.data == "sch:today")
async def cb_today(callback: CallbackQuery) -> None:
    user = get_user_by_telegram_id(callback.from_user.id)
    tz = user["timezone"] if user else "Europe/Moscow"
    today = datetime.now(ZoneInfo(tz)).date()
    await callback.answer()
    await _show_day(callback.message, callback.from_user.id, today)


@router.callback_query(F.data == "sch:tomorrow")
async def cb_tomorrow(callback: CallbackQuery) -> None:
    user = get_user_by_telegram_id(callback.from_user.id)
    tz = user["timezone"] if user else "Europe/Moscow"
    tomorrow = datetime.now(ZoneInfo(tz)).date() + timedelta(days=1)
    await callback.answer()
    await _show_day(callback.message, callback.from_user.id, tomorrow)


@router.callback_query(F.data == "sch:week")
async def cb_week(callback: CallbackQuery) -> None:
    user = get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("Сначала зарегистрируйся: /start", show_alert=True)
        return
    tz = user["timezone"]
    today = datetime.now(ZoneInfo(tz)).date()
    await callback.answer()
    for offset in range(7):
        day = today + timedelta(days=offset)
        payload = list_schedule_for_user(user["id"], day, tz)
        await callback.message.answer(_render_day(day, today, payload), parse_mode="HTML")


@router.callback_query(F.data == "sch:init")
async def cb_init(callback: CallbackQuery) -> None:
    await callback.answer()
    await _init_routine(callback.message, callback.from_user.id)


@router.message(Command("init_routine"))
async def cmd_init_routine(message: Message) -> None:
    await _init_routine(message, message.from_user.id)


async def _init_routine(message: Message, telegram_id: int) -> None:
    user = get_user_by_telegram_id(telegram_id)
    if not user:
        await message.answer("Сначала зарегистрируйся: /start")
        return

    existing = list_family_routine_events()
    if existing:
        await message.answer(
            f"Семейная база уже создана ({len(existing)} пунктов). "
            f"Редактируй или добавляй через /add."
        )
        return

    created = 0
    for time_local, title in _DEFAULT_ROUTINE:
        create_task(
            task_type="event",
            title=title,
            created_by=user["id"],
            visibility="family",
            category="routine",
            recurrence=_DEFAULT_ROUTINE_RECURRENCE,
            time_local=time_local,
        )
        created += 1

    await message.answer(
        f"✓ Сохранено: семейная база, {created} пунктов. Открой /schedule, чтобы посмотреть."
    )
