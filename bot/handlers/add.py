"""Мастер /add — добавление задачи или повторяющегося пункта расписания через FSM."""

import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

from aiogram import F, Router

log = logging.getLogger(__name__)
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.datetime_utils import format_human, parse_human_datetime
from bot.db import WEEKDAY_CODES, create_task, get_user_by_telegram_id, list_users
from bot.handlers.common import HOME_BUTTON, cancel_button, cancel_kb

router = Router()


class AddTask(StatesGroup):
    title = State()
    kind = State()
    category = State()  # общий шаг — и для разовых, и для повторяющихся
    # one-off ветка
    visibility = State()
    assignees = State()
    due_at = State()
    due_date_only = State()  # пользователь вводит только дату; due_has_time=false
    lead = State()
    # recurring ветка
    rec_visibility = State()
    rec_assignees = State()
    rec_days = State()
    rec_specific_dates = State()
    rec_time = State()


# ---------- общие клавиатуры ----------

def _kind_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📌 Разовая задача / событие", callback_data="kind:oneoff")],
            [InlineKeyboardButton(text="🔁 Повторяющийся пункт", callback_data="kind:recurring")],
            [cancel_button()],
            [HOME_BUTTON],
        ]
    )


def _visibility_kb(prefix: str = "vis") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔒 Только мне", callback_data=f"{prefix}:private")],
            [InlineKeyboardButton(text="👥 Конкретным людям", callback_data=f"{prefix}:assignees")],
            [InlineKeyboardButton(text="👨‍👩‍👧‍👦 Всей семье", callback_data=f"{prefix}:family")],
            [cancel_button()],
            [HOME_BUTTON],
        ]
    )


def _assignees_kb(users: list[dict], selected: set[str], prefix: str = "asn") -> InlineKeyboardMarkup:
    rows = []
    for u in users:
        mark = "✅" if u["id"] in selected else "▫️"
        rows.append([
            InlineKeyboardButton(
                text=f"{mark} {u['name']}",
                callback_data=f"{prefix}:{u['id']}",
            )
        ])
    rows.append([InlineKeyboardButton(text="▶️ Готово", callback_data=f"{prefix}:done")])
    rows.append([cancel_button()])
    rows.append([HOME_BUTTON])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------- one-off клавиатуры ----------

def _due_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📅 Только дата (без времени)", callback_data="due:dateonly")],
            [InlineKeyboardButton(text="🕐 Дата и время", callback_data="due:datetime")],
            [cancel_button()],
            [HOME_BUTTON],
        ]
    )


def _lead_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔔 Только в момент", callback_data="lead:0")],
            [
                InlineKeyboardButton(text="+ за 15 мин", callback_data="lead:15"),
                InlineKeyboardButton(text="+ за час", callback_data="lead:60"),
            ],
            [
                InlineKeyboardButton(text="+ за день", callback_data="lead:1440"),
                InlineKeyboardButton(text="+ за день и час", callback_data="lead:1440_60"),
            ],
            [cancel_button()],
            [HOME_BUTTON],
        ]
    )


# ---------- recurring клавиатуры ----------

def _category_kb(include_routine: bool = True) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if include_routine:
        rows.append([InlineKeyboardButton(text="🏠 Рутина (семейная база)", callback_data="cat:routine")])
    rows += [
        [InlineKeyboardButton(text="📚 Занятие", callback_data="cat:lesson")],
        [InlineKeyboardButton(text="🚗 Поездка", callback_data="cat:trip")],
        [InlineKeyboardButton(text="💼 Работа", callback_data="cat:work")],
        [InlineKeyboardButton(text="🎉 Поздравления", callback_data="cat:congrats")],
        [InlineKeyboardButton(text="🛒 Покупки", callback_data="cat:shopping")],
        [InlineKeyboardButton(text="🏠 Дом", callback_data="cat:home")],
        [InlineKeyboardButton(text="🚙 Машина", callback_data="cat:car")],
        [InlineKeyboardButton(text="📌 Иное", callback_data="cat:other")],
        [cancel_button()],
        [HOME_BUTTON],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


_PRESET_TO_DAYS = {
    "everyday": list(WEEKDAY_CODES),
    "weekdays": ["MO", "TU", "WE", "TH", "FR"],
    "weekends": ["SA", "SU"],
}
_DAY_NAMES_SHORT = {"MO": "Пн", "TU": "Вт", "WE": "Ср", "TH": "Чт", "FR": "Пт", "SA": "Сб", "SU": "Вс"}


def _days_kb(selected: list[str]) -> InlineKeyboardMarkup:
    selected_set = set(selected)
    rows = [
        [
            InlineKeyboardButton(text="🌍 Каждый день", callback_data="days:preset:everyday"),
            InlineKeyboardButton(text="💼 По будням", callback_data="days:preset:weekdays"),
        ],
        [InlineKeyboardButton(text="🎉 По выходным", callback_data="days:preset:weekends")],
        [InlineKeyboardButton(text="📅 По конкретным дням", callback_data="days:specific")],
    ]
    day_row = []
    for code in WEEKDAY_CODES:
        mark = "✅" if code in selected_set else "▫️"
        day_row.append(InlineKeyboardButton(
            text=f"{mark} {_DAY_NAMES_SHORT[code]}",
            callback_data=f"days:toggle:{code}",
        ))
    rows.append(day_row)
    rows.append([InlineKeyboardButton(text="▶️ Готово", callback_data="days:done")])
    rows.append([cancel_button()])
    rows.append([HOME_BUTTON])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------- entry ----------

@router.message(Command("add"))
async def cmd_add(message: Message, state: FSMContext) -> None:
    user = get_user_by_telegram_id(message.from_user.id)
    if not user:
        await message.answer("Сначала зарегистрируйся: /start")
        return
    await state.clear()
    await state.update_data(user_db_id=user["id"], user_tz=user["timezone"])
    await message.answer(
        "Что добавить? Напиши коротко (например: «Английский»).",
        reply_markup=cancel_kb(),
    )
    await state.set_state(AddTask.title)


@router.message(AddTask.title, F.text)
async def add_title(message: Message, state: FSMContext) -> None:
    title = (message.text or "").strip()
    if not title or len(title) > 200:
        await message.answer("Заголовок должен быть от 1 до 200 символов.")
        return
    await state.update_data(title=title)
    await message.answer("Какой это пункт?", reply_markup=_kind_kb())
    await state.set_state(AddTask.kind)


@router.callback_query(AddTask.kind, F.data.startswith("kind:"))
async def add_kind(callback: CallbackQuery, state: FSMContext) -> None:
    kind = callback.data.split(":", 1)[1]
    await state.update_data(kind=kind)
    await callback.answer()
    await callback.message.edit_text(
        "К какой категории относится задача?",
        reply_markup=_category_kb(include_routine=(kind == "recurring")),
    )
    await state.set_state(AddTask.category)


# ---------- one-off ветка ----------

@router.callback_query(AddTask.visibility, F.data.startswith("vis:"))
async def add_visibility(callback: CallbackQuery, state: FSMContext) -> None:
    vis = callback.data.split(":", 1)[1]
    await state.update_data(visibility=vis)
    await callback.answer()

    data = await state.get_data()

    if vis == "private":
        await state.update_data(assignee_ids=[data["user_db_id"]])
        await callback.message.edit_text(
            "Только тебе.\n\nКогда сделать? Например: «завтра 9:00», «пт 18», «15.05», или выбери ниже.",
            reply_markup=_due_kb(),
        )
        await state.set_state(AddTask.due_at)
    elif vis == "family":
        await state.update_data(assignee_ids=[])
        await callback.message.edit_text(
            "Видно всей семье.\n\nКогда? Например: «завтра 9:00», «пт 18», «15.05», или выбери ниже.",
            reply_markup=_due_kb(),
        )
        await state.set_state(AddTask.due_at)
    else:
        users = list_users()
        await state.update_data(_users_cache=users, selected_ids=[])
        await callback.message.edit_text(
            "Кому показать? Отметь людей и нажми «Готово».",
            reply_markup=_assignees_kb(users, set(), "asn"),
        )
        await state.set_state(AddTask.assignees)


@router.callback_query(AddTask.assignees, F.data.startswith("asn:"))
async def add_assignee(callback: CallbackQuery, state: FSMContext) -> None:
    payload = callback.data.split(":", 1)[1]
    data = await state.get_data()
    selected: list[str] = list(data.get("selected_ids", []))
    users: list[dict] = data.get("_users_cache", [])

    if payload == "done":
        if not selected:
            await callback.answer("Выбери хотя бы одного человека.", show_alert=True)
            return
        await state.update_data(assignee_ids=selected)
        await callback.answer()
        await callback.message.edit_text(
            f"Назначено: {len(selected)} чел.\n\nКогда? Например: «завтра 9:00», «пт 18», «15.05», или выбери ниже.",
            reply_markup=_due_kb(),
        )
        await state.set_state(AddTask.due_at)
        return

    uid = payload
    if uid in selected:
        selected.remove(uid)
    else:
        selected.append(uid)
    await state.update_data(selected_ids=selected)
    await callback.message.edit_reply_markup(
        reply_markup=_assignees_kb(users, set(selected), "asn")
    )
    await callback.answer()


@router.callback_query(AddTask.due_at, F.data == "due:datetime")
async def add_due_datetime_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await callback.message.edit_text(
        "Введи дату и время. Примеры:\n"
        "<code>завтра 9:00</code>\n"
        "<code>пт 18:00</code>\n"
        "<code>15.05 14:30</code>\n\n"
        "Или напиши «без срока», если конкретного срока нет.",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )


@router.callback_query(AddTask.due_at, F.data == "due:dateonly")
async def add_due_dateonly_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await callback.message.edit_text(
        "На какую дату? Например: «завтра», «пт», «15.05» (без указания времени).",
        reply_markup=cancel_kb(),
    )
    await state.set_state(AddTask.due_date_only)


@router.message(AddTask.due_date_only, F.text)
async def add_due_dateonly(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    tz = data["user_tz"]
    text = (message.text or "").strip()
    dt = parse_human_datetime(text, tz=tz)
    if not dt:
        await message.answer("Не понял дату. Примеры: «завтра», «пт», «15.05».")
        return
    # Сдвигаем на начало суток в локальной TZ
    local_midnight = dt.astimezone(ZoneInfo(tz)).replace(hour=0, minute=0, second=0, microsecond=0)
    await _save_oneoff(message, state, due_at=local_midnight, due_has_time=False, lead_minutes=[])


@router.message(AddTask.due_at, F.text)
async def add_due_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    tz = data["user_tz"]
    text = (message.text or "").strip()
    if text.lower() in {"без срока", "-", "нет"}:
        await _save_oneoff(message, state, due_at=None, due_has_time=True, lead_minutes=[])
        return

    dt = parse_human_datetime(text, tz=tz)
    if not dt:
        await message.answer(
            "Не понял дату. Примеры: «завтра 9:00», «пт 18:00», «15.05 14», «послезавтра», «Без срока»."
        )
        return
    await state.update_data(due_at_iso=dt.isoformat())
    await message.answer(
        f"Срок: <i>{format_human(dt, tz)}</i>.\n\nКогда напомнить?",
        parse_mode="HTML",
        reply_markup=_lead_kb(),
    )
    await state.set_state(AddTask.lead)


@router.message(AddTask.lead, F.text)
async def add_lead_text(message: Message, state: FSMContext) -> None:
    await message.answer("Выбери вариант напоминания кнопкой выше 👆", reply_markup=_lead_kb())


@router.callback_query(AddTask.lead, F.data.startswith("lead:"))
async def add_lead(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()  # всегда отвечаем первым, иначе Telegram покажет «что-то пошло не так»
    payload = callback.data.split(":", 1)[1]
    pre = [int(x) for x in payload.split("_") if x.isdigit() and int(x) > 0]
    lead_minutes = sorted(set(pre + [0]), reverse=True)

    data = await state.get_data()
    due_at_iso = data.get("due_at_iso")
    if not due_at_iso:
        await callback.message.answer(
            "⚠️ Потерялись данные о сроке. Начни заново: /add"
        )
        await state.clear()
        return
    due_at = datetime.fromisoformat(due_at_iso)
    try:
        await _save_oneoff(callback.message, state, due_at=due_at, due_has_time=True, lead_minutes=lead_minutes)
    except Exception as exc:
        log.exception("_save_oneoff failed: %s", exc)
        await callback.message.answer(
            "⚠️ Не удалось сохранить задачу. Попробуй ещё раз или начни заново: /add"
        )
        await state.clear()


@router.callback_query(F.data.startswith("lead:"))
async def add_lead_stale(callback: CallbackQuery) -> None:
    """Ловит устаревшие кнопки напоминания (например, после перезагрузки бота)."""
    await callback.answer(
        "Сессия устарела — начни добавление заново через /add",
        show_alert=True,
    )


async def _save_oneoff(message: Message, state: FSMContext, *, due_at, due_has_time: bool, lead_minutes: list[int]) -> None:
    data = await state.get_data()
    tz = data["user_tz"]
    visibility = data["visibility"]
    assignee_ids = data.get("assignee_ids", [])

    task_type = "reminder" if (due_at and due_has_time) else "todo"

    create_task(
        task_type=task_type,
        title=data["title"],
        created_by=data["user_db_id"],
        visibility=visibility,
        category=data.get("category"),
        due_at=due_at,
        due_has_time=due_has_time,
        assignee_user_ids=assignee_ids,
        lead_minutes=lead_minutes,
    )

    if due_at and due_has_time:
        when = format_human(due_at, tz)
    elif due_at and not due_has_time:
        local = due_at.astimezone(ZoneInfo(tz))
        when = f"на {local.strftime('%d.%m')} (без времени)"
    else:
        when = "без срока"

    vis_label = {
        "private": "🔒 только тебе",
        "assignees": f"👥 для {len(assignee_ids)} чел.",
        "family": "👨‍👩‍👧‍👦 всей семье",
    }[visibility]
    lead_label = _lead_summary(lead_minutes) if lead_minutes else ""
    await message.answer(
        f"✓ Сохранено: <b>{data['title']}</b>\n   {vis_label} • {when}{lead_label}",
        parse_mode="HTML",
    )
    await state.clear()


def _lead_summary(lead_minutes: list[int]) -> str:
    extra = [m for m in lead_minutes if m > 0]
    if not extra:
        return ""
    parts = []
    for m in extra:
        if m % 1440 == 0:
            d = m // 1440
            parts.append(f"за {d} дн" if d > 1 else "за день")
        elif m % 60 == 0:
            parts.append(f"за {m // 60} ч")
        else:
            parts.append(f"за {m} мин")
    return f" • 🔔 {', '.join(parts)}"


# ---------- recurring ветка ----------

@router.callback_query(AddTask.category, F.data.startswith("cat:"))
async def add_category(callback: CallbackQuery, state: FSMContext) -> None:
    cat = callback.data.split(":", 1)[1]
    await state.update_data(category=cat)
    await callback.answer()
    data = await state.get_data()

    if data.get("kind") == "oneoff":
        await callback.message.edit_text(
            "Кто должен это видеть?", reply_markup=_visibility_kb("vis")
        )
        await state.set_state(AddTask.visibility)
    else:
        hint = "Видимость — обычно «всей семье» для рутины." if cat == "routine" else "Кому это видно?"
        await callback.message.edit_text(hint, reply_markup=_visibility_kb("rvis"))
        await state.set_state(AddTask.rec_visibility)


@router.callback_query(AddTask.rec_visibility, F.data.startswith("rvis:"))
async def rec_visibility(callback: CallbackQuery, state: FSMContext) -> None:
    vis = callback.data.split(":", 1)[1]
    await state.update_data(visibility=vis)
    await callback.answer()

    data = await state.get_data()
    if vis == "private":
        await state.update_data(assignee_ids=[data["user_db_id"]])
        await callback.message.edit_text(
            "Только тебе.\n\nВ какие дни повторять?",
            reply_markup=_days_kb([]),
        )
        await state.update_data(selected_days=[])
        await state.set_state(AddTask.rec_days)
    elif vis == "family":
        await state.update_data(assignee_ids=[])
        await callback.message.edit_text(
            "Видно всей семье.\n\nВ какие дни повторять?",
            reply_markup=_days_kb([]),
        )
        await state.update_data(selected_days=[])
        await state.set_state(AddTask.rec_days)
    else:
        users = list_users()
        await state.update_data(_users_cache=users, selected_ids=[])
        await callback.message.edit_text(
            "Кому показать? Отметь людей и нажми «Готово».",
            reply_markup=_assignees_kb(users, set(), "rasn"),
        )
        await state.set_state(AddTask.rec_assignees)


@router.callback_query(AddTask.rec_assignees, F.data.startswith("rasn:"))
async def rec_assignees(callback: CallbackQuery, state: FSMContext) -> None:
    payload = callback.data.split(":", 1)[1]
    data = await state.get_data()
    selected: list[str] = list(data.get("selected_ids", []))
    users: list[dict] = data.get("_users_cache", [])

    if payload == "done":
        if not selected:
            await callback.answer("Выбери хотя бы одного человека.", show_alert=True)
            return
        await state.update_data(assignee_ids=selected, selected_days=[])
        await callback.answer()
        await callback.message.edit_text(
            f"Назначено: {len(selected)} чел.\n\nВ какие дни повторять?",
            reply_markup=_days_kb([]),
        )
        await state.set_state(AddTask.rec_days)
        return

    uid = payload
    if uid in selected:
        selected.remove(uid)
    else:
        selected.append(uid)
    await state.update_data(selected_ids=selected)
    await callback.message.edit_reply_markup(
        reply_markup=_assignees_kb(users, set(selected), "rasn")
    )
    await callback.answer()


@router.callback_query(AddTask.rec_days, F.data.startswith("days:"))
async def rec_days(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    data = await state.get_data()
    selected: list[str] = list(data.get("selected_days", []))

    action = parts[1]
    if action == "preset" and len(parts) >= 3:
        selected = list(_PRESET_TO_DAYS.get(parts[2], []))
    elif action == "toggle" and len(parts) >= 3:
        code = parts[2]
        if code in selected:
            selected.remove(code)
        else:
            selected.append(code)
        selected = [c for c in WEEKDAY_CODES if c in selected]
    elif action == "specific":
        await callback.answer()
        await callback.message.edit_text(
            "В какие даты? Перечисли через запятую, например:\n"
            "<code>15.05, 22.05, 5.06</code>\n"
            "или одна дата: <code>15.05</code>",
            parse_mode="HTML",
            reply_markup=cancel_kb(),
        )
        await state.set_state(AddTask.rec_specific_dates)
        return
    elif action == "done":
        if not selected:
            await callback.answer("Выбери хотя бы один день.", show_alert=True)
            return
        await state.update_data(selected_days=selected)
        await callback.answer()
        await callback.message.edit_text(
            "Во сколько начинается? Напиши время в формате <b>HH:MM</b> (например, 08:00).",
            parse_mode="HTML",
            reply_markup=cancel_kb(),
        )
        await state.set_state(AddTask.rec_time)
        return
    else:
        await callback.answer()
        return

    await state.update_data(selected_days=selected)
    await callback.message.edit_reply_markup(reply_markup=_days_kb(selected))
    await callback.answer()


@router.message(AddTask.rec_specific_dates, F.text)
async def rec_specific_dates(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    tz = data["user_tz"]
    raw = (message.text or "").strip()
    parts = [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
    if not parts:
        await message.answer("Не понял. Пример: 15.05, 22.05, 5.06.")
        return

    dates: list[str] = []
    for p in parts:
        dt = parse_human_datetime(p, tz=tz)
        if not dt:
            await message.answer(f"Не понял дату «{p}». Используй формат «15.05» или «завтра».")
            return
        dates.append(dt.astimezone(ZoneInfo(tz)).date().isoformat())

    # de-dup, sort
    dates = sorted(set(dates))
    await state.update_data(specific_dates=dates, selected_days=[])
    await message.answer(
        f"Даты: {len(dates)} шт.\n\nВо сколько? Напиши время в формате <b>HH:MM</b>.",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )
    await state.set_state(AddTask.rec_time)


@router.message(AddTask.rec_time, F.text)
async def rec_time(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    try:
        hh_str, mm_str = text.split(":", 1)
        hh, mm = int(hh_str), int(mm_str)
        if not (0 <= hh < 24 and 0 <= mm < 60):
            raise ValueError
    except ValueError:
        await message.answer("Не понял время. Формат: HH:MM, например 08:00.")
        return

    time_local = f"{hh:02d}:{mm:02d}"
    data = await state.get_data()
    tz = data["user_tz"]
    specific_dates: list[str] = data.get("specific_dates") or []
    days: list[str] = data.get("selected_days") or []

    vis_label = {
        "private": "🔒 только тебе",
        "assignees": f"👥 для {len(data.get('assignee_ids', []))} чел.",
        "family": "👨‍👩‍👧‍👦 всей семье",
    }[data["visibility"]]

    if specific_dates:
        tzinfo = ZoneInfo(tz)
        for iso_date in specific_dates:
            d = datetime.fromisoformat(iso_date).date()
            due_at = datetime.combine(d, time(hh, mm), tzinfo=tzinfo)
            create_task(
                task_type="event",
                title=data["title"],
                created_by=data["user_db_id"],
                visibility=data["visibility"],
                category=data["category"],
                due_at=due_at,
                due_has_time=True,
                assignee_user_ids=data.get("assignee_ids", []),
            )
        await message.answer(
            f"✓ Сохранено: <b>{data['title']}</b>\n   {vis_label} • {time_local} • {len(specific_dates)} дат(ы)",
            parse_mode="HTML",
        )
    else:
        recurrence = "WEEKLY:" + ",".join(days)
        create_task(
            task_type="event",
            title=data["title"],
            created_by=data["user_db_id"],
            visibility=data["visibility"],
            category=data["category"],
            recurrence=recurrence,
            time_local=time_local,
            assignee_user_ids=data.get("assignee_ids", []),
        )
        days_label = ", ".join(_DAY_NAMES_SHORT[c] for c in days)
        await message.answer(
            f"✓ Сохранено: <b>{data['title']}</b>\n   {vis_label} • {time_local} • {days_label}",
            parse_mode="HTML",
        )

    await state.clear()
