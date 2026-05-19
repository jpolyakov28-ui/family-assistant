"""Редактирование пунктов расписания: время / название / удаление.

Точки входа:
  • /edit_routine — список семейных routine-пунктов
  • callback editlist:day:<YYYY-MM-DD> — список пунктов выбранного дня (из /schedule)
"""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.db import (
    WEEKDAY_CODES,
    create_task,
    delete_task,
    get_task,
    get_user_by_telegram_id,
    list_family_routine_events,
    list_schedule_for_user,
    list_users,
    set_cook_for_weekday,
    update_task_fields,
)
from bot.handlers.common import HOME_BUTTON, cancel_button, cancel_kb

router = Router()


class EditTask(StatesGroup):
    new_time = State()
    new_title = State()


class AddRoutine(StatesGroup):
    title = State()
    days = State()
    time = State()


# ---------- список → выбор задачи ----------

def _list_kb(items: list[dict], with_add: bool = False) -> InlineKeyboardMarkup:
    rows = []
    for it in items:
        time_label = it.get("time_local") or "—"
        if not it.get("time_local") and it.get("due_at"):
            try:
                dt = datetime.fromisoformat(it["due_at"].replace("Z", "+00:00"))
                time_label = dt.strftime("%H:%M")
            except Exception:
                pass
        title = it.get("title", "?")
        rows.append([
            InlineKeyboardButton(
                text=f"{time_label} — {title}"[:60],
                callback_data=f"edit:{it['id']}",
            )
        ])
    if not rows:
        rows.append([InlineKeyboardButton(text="(пусто)", callback_data="edit:noop")])
    if with_add:
        rows.append([InlineKeyboardButton(text="➕ Добавить пункт", callback_data="routine:add")])
    rows.append([InlineKeyboardButton(text="⬅️ Семейный ассистент", callback_data="home:show")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("edit_routine"))
async def cmd_edit_routine(message: Message) -> None:
    user = get_user_by_telegram_id(message.from_user.id)
    if not user:
        await message.answer("Сначала зарегистрируйся: /start")
        return
    items = list_family_routine_events()
    items.sort(key=lambda x: x.get("time_local") or "")
    await message.answer(
        "Семейная база. Выбери пункт для редактирования или добавь новый:",
        reply_markup=_list_kb(items, with_add=True),
    )


@router.callback_query(F.data.startswith("editlist:day:"))
async def cb_edit_day(callback: CallbackQuery) -> None:
    iso = callback.data.split(":", 2)[2]
    try:
        target_date = date.fromisoformat(iso)
    except ValueError:
        await callback.answer("Не понял дату", show_alert=True)
        return
    user = get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("Сначала зарегистрируйся: /start", show_alert=True)
        return
    payload = list_schedule_for_user(user["id"], target_date, user["timezone"])
    items = payload["timed"] + payload["untimed"]
    items.sort(key=lambda x: x.get("time_local") or x.get("due_at") or "")
    await callback.answer()
    if not items:
        await callback.message.answer("На этот день пусто.")
        return
    await callback.message.answer(
        f"Пункты на {target_date.strftime('%d.%m')}. Выбери для редактирования:",
        reply_markup=_list_kb(items),
    )


# ---------- меню действий ----------

_DAY_NAMES_RU = {
    "MO": "Пн", "TU": "Вт", "WE": "Ср", "TH": "Чт", "FR": "Пт", "SA": "Сб", "SU": "Вс",
}


def _actions_kb(task: dict) -> InlineKeyboardMarkup:
    task_id = task["id"]
    rows = [
        [InlineKeyboardButton(text="🕐 Новое время", callback_data=f"eact:time:{task_id}")],
        [InlineKeyboardButton(text="✏️ Переименовать", callback_data=f"eact:title:{task_id}")],
    ]
    if task.get("recurrence"):
        rows.append([InlineKeyboardButton(text="👩‍🍳 Шеф-повар", callback_data=f"cooks:list:{task_id}")])
    rows.append([InlineKeyboardButton(text="🗑 Удалить", callback_data=f"eact:delask:{task_id}")])
    rows.append([InlineKeyboardButton(text="⬅️ Семейный ассистент", callback_data="home:show")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _confirm_delete_kb(task_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🗑 Да, удалить", callback_data=f"eact:delyes:{task_id}"),
                InlineKeyboardButton(text="Отмена", callback_data=f"edit:{task_id}"),
            ],
        ]
    )


@router.callback_query(F.data == "edit:noop")
async def cb_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(F.data.startswith("edit:"))
async def cb_edit_one(callback: CallbackQuery) -> None:
    task_id = callback.data.split(":", 1)[1]
    task = get_task(task_id)
    if not task:
        await callback.answer("Не нашёл пункт", show_alert=True)
        return
    await callback.answer()
    time_label = task.get("time_local")
    if not time_label and task.get("due_at"):
        try:
            dt = datetime.fromisoformat(task["due_at"].replace("Z", "+00:00"))
            time_label = dt.strftime("%H:%M")
        except Exception:
            time_label = "—"
    await callback.message.answer(
        f"<b>{task['title']}</b>\nВремя: {time_label or '—'}\n\nЧто делаем?",
        parse_mode="HTML",
        reply_markup=_actions_kb(task),
    )


@router.callback_query(F.data.startswith("eact:time:"))
async def cb_act_time(callback: CallbackQuery, state: FSMContext) -> None:
    task_id = callback.data.split(":", 2)[2]
    await state.update_data(edit_task_id=task_id)
    await state.set_state(EditTask.new_time)
    await callback.answer()
    await callback.message.answer(
        "Новое время в формате <b>HH:MM</b> (например, 12:30).",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )


@router.message(EditTask.new_time, F.text)
async def on_new_time(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    try:
        hh_str, mm_str = text.split(":", 1)
        hh, mm = int(hh_str), int(mm_str)
        if not (0 <= hh < 24 and 0 <= mm < 60):
            raise ValueError
    except ValueError:
        await message.answer("Не понял время. Формат: HH:MM.")
        return

    data = await state.get_data()
    task_id = data.get("edit_task_id")
    if not task_id:
        await message.answer("Состояние потеряно. Открой /edit_routine заново.")
        await state.clear()
        return

    task = get_task(task_id)
    if not task:
        await message.answer("Пункт уже удалён.")
        await state.clear()
        return

    new_hhmm = f"{hh:02d}:{mm:02d}"
    if task.get("recurrence"):
        update_task_fields(task_id, time_local=new_hhmm)
    elif task.get("due_at"):
        user = get_user_by_telegram_id(message.from_user.id)
        tz = user["timezone"] if user else "Europe/Moscow"
        tzinfo = ZoneInfo(tz)
        dt = datetime.fromisoformat(task["due_at"].replace("Z", "+00:00")).astimezone(tzinfo)
        new_dt = dt.replace(hour=hh, minute=mm, second=0, microsecond=0)
        update_task_fields(task_id, due_at=new_dt.isoformat(), due_has_time=True)
    else:
        await message.answer("У этого пункта нет ни recurrence, ни due_at — нечего менять.")
        await state.clear()
        return

    await message.answer(f"✓ Сохранено: «{task['title']}» — {new_hhmm}")
    await state.clear()


@router.callback_query(F.data.startswith("eact:title:"))
async def cb_act_title(callback: CallbackQuery, state: FSMContext) -> None:
    task_id = callback.data.split(":", 2)[2]
    await state.update_data(edit_task_id=task_id)
    await state.set_state(EditTask.new_title)
    await callback.answer()
    await callback.message.answer("Новое название?", reply_markup=cancel_kb())


@router.message(EditTask.new_title, F.text)
async def on_new_title(message: Message, state: FSMContext) -> None:
    new_title = (message.text or "").strip()
    if not new_title or len(new_title) > 200:
        await message.answer("От 1 до 200 символов.")
        return
    data = await state.get_data()
    task_id = data.get("edit_task_id")
    if not task_id:
        await message.answer("Состояние потеряно. Открой /edit_routine заново.")
        await state.clear()
        return
    update_task_fields(task_id, title=new_title)
    await message.answer(f"✓ Сохранено: {new_title}")
    await state.clear()


@router.callback_query(F.data.startswith("eact:delask:"))
async def cb_act_delask(callback: CallbackQuery) -> None:
    task_id = callback.data.split(":", 2)[2]
    task = get_task(task_id)
    if not task:
        await callback.answer("Уже удалено", show_alert=True)
        return
    await callback.answer()
    await callback.message.answer(
        f"Удалить «{task['title']}»?",
        reply_markup=_confirm_delete_kb(task_id),
    )


@router.callback_query(F.data.startswith("eact:delyes:"))
async def cb_act_delyes(callback: CallbackQuery) -> None:
    task_id = callback.data.split(":", 2)[2]
    task = get_task(task_id)
    title = task["title"] if task else "пункт"
    delete_task(task_id)
    await callback.answer("Удалено")
    try:
        await callback.message.edit_text(f"🗑 Удалено: {title}")
    except Exception:
        pass


# ---------- дежурные по дням недели ----------

def _cooks_list_kb(task: dict) -> InlineKeyboardMarkup:
    cooks: dict[str, str] = task.get("cook_by") or {}
    name_by_id = {u["id"]: u["name"] for u in list_users()}
    rec = (task.get("recurrence") or "").upper()
    active_days = set()
    if rec.startswith("WEEKLY:"):
        active_days = {c.strip() for c in rec.split(":", 1)[1].split(",") if c.strip()}

    rows = []
    for code in WEEKDAY_CODES:
        if active_days and code not in active_days:
            continue
        cook_id = cooks.get(code)
        name = name_by_id.get(cook_id, "—") if cook_id else "—"
        rows.append([
            InlineKeyboardButton(
                text=f"{_DAY_NAMES_RU[code]}: {name}",
                callback_data=f"cooks:pick:{task['id']}:{code}",
            )
        ])
    rows.append([InlineKeyboardButton(text="← Назад", callback_data=f"edit:{task['id']}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _cooks_pick_kb(task_id: str, weekday: str) -> InlineKeyboardMarkup:
    users = list_users()
    # Используем индекс пользователя вместо UUID, чтобы callback_data оставался
    # в пределах 64 байт лимита Telegram (UUID = 36 байт → перелимит).
    rows = [
        [InlineKeyboardButton(
            text=u["name"],
            callback_data=f"cooks:set:{task_id}:{weekday}:{idx}",
        )]
        for idx, u in enumerate(users)
    ]
    rows.append([InlineKeyboardButton(text="❌ Снять дежурство", callback_data=f"cooks:unset:{task_id}:{weekday}")])
    rows.append([InlineKeyboardButton(text="← Назад", callback_data=f"cooks:list:{task_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data.startswith("cooks:list:"))
async def cb_cooks_list(callback: CallbackQuery) -> None:
    task_id = callback.data.split(":", 2)[2]
    task = get_task(task_id)
    if not task:
        await callback.answer("Не нашёл пункт", show_alert=True)
        return
    await callback.answer()
    try:
        await callback.message.edit_text(
            f"<b>{task['title']}</b> — шеф-повар.\nТапни день, чтобы изменить:",
            parse_mode="HTML",
            reply_markup=_cooks_list_kb(task),
        )
    except Exception:
        await callback.message.answer(
            f"<b>{task['title']}</b> — шеф-повар.",
            parse_mode="HTML",
            reply_markup=_cooks_list_kb(task),
        )


@router.callback_query(F.data.startswith("cooks:pick:"))
async def cb_cooks_pick(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    task_id, weekday = parts[2], parts[3]
    await callback.answer()
    try:
        await callback.message.edit_text(
            f"Кого назначить на {_DAY_NAMES_RU.get(weekday, weekday)}?",
            reply_markup=_cooks_pick_kb(task_id, weekday),
        )
    except Exception:
        await callback.message.answer(
            f"Кого назначить на {_DAY_NAMES_RU.get(weekday, weekday)}?",
            reply_markup=_cooks_pick_kb(task_id, weekday),
        )


@router.callback_query(F.data.startswith("cooks:set:"))
async def cb_cooks_set(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    task_id, weekday, user_idx_str = parts[2], parts[3], parts[4]
    try:
        user_idx = int(user_idx_str)
        users = list_users()
        user_id = users[user_idx]["id"]
    except (ValueError, IndexError):
        await callback.answer("Не нашёл пользователя", show_alert=True)
        return
    set_cook_for_weekday(task_id, weekday, user_id)
    await callback.answer("Назначено")
    task = get_task(task_id)
    if task:
        try:
            await callback.message.edit_text(
                f"<b>{task['title']}</b> — шеф-повар.",
                parse_mode="HTML",
                reply_markup=_cooks_list_kb(task),
            )
        except Exception:
            pass


@router.callback_query(F.data.startswith("cooks:unset:"))
async def cb_cooks_unset(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    task_id, weekday = parts[2], parts[3]
    set_cook_for_weekday(task_id, weekday, None)
    await callback.answer("Снято")
    task = get_task(task_id)
    if task:
        try:
            await callback.message.edit_text(
                f"<b>{task['title']}</b> — шеф-повар.",
                parse_mode="HTML",
                reply_markup=_cooks_list_kb(task),
            )
        except Exception:
            pass


# ---------- добавление пункта в семейную базу ----------

_PRESET_DAYS = {
    "everyday": list(WEEKDAY_CODES),
    "weekdays": ["MO", "TU", "WE", "TH", "FR"],
    "weekends": ["SA", "SU"],
}


def _routine_days_kb(selected: list[str]) -> InlineKeyboardMarkup:
    selected_set = set(selected)
    rows = [
        [
            InlineKeyboardButton(text="🌍 Каждый день", callback_data="rdays:preset:everyday"),
            InlineKeyboardButton(text="💼 По будням", callback_data="rdays:preset:weekdays"),
        ],
        [InlineKeyboardButton(text="🎉 По выходным", callback_data="rdays:preset:weekends")],
    ]
    day_row = []
    for code in WEEKDAY_CODES:
        mark = "✅" if code in selected_set else "▫️"
        day_row.append(InlineKeyboardButton(
            text=f"{mark} {_DAY_NAMES_RU[code]}",
            callback_data=f"rdays:toggle:{code}",
        ))
    rows.append(day_row)
    rows.append([InlineKeyboardButton(text="▶️ Готово", callback_data="rdays:done")])
    rows.append([cancel_button()])
    rows.append([HOME_BUTTON])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "routine:add")
async def cb_routine_add(callback: CallbackQuery, state: FSMContext) -> None:
    user = get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("Сначала /start", show_alert=True)
        return
    await state.clear()
    await state.update_data(user_db_id=user["id"])
    await callback.answer()
    await callback.message.answer(
        "Название нового пункта семейной базы (например: «Чай», «Прогулка»).",
        reply_markup=cancel_kb(),
    )
    await state.set_state(AddRoutine.title)


@router.message(AddRoutine.title, F.text)
async def routine_title(message: Message, state: FSMContext) -> None:
    title = (message.text or "").strip()
    if not title or len(title) > 200:
        await message.answer("От 1 до 200 символов.")
        return
    await state.update_data(title=title, selected_days=[])
    await message.answer("В какие дни повторять?", reply_markup=_routine_days_kb([]))
    await state.set_state(AddRoutine.days)


@router.callback_query(AddRoutine.days, F.data.startswith("rdays:"))
async def routine_days(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    data = await state.get_data()
    selected: list[str] = list(data.get("selected_days", []))
    action = parts[1]

    if action == "preset" and len(parts) >= 3:
        selected = list(_PRESET_DAYS.get(parts[2], []))
    elif action == "toggle" and len(parts) >= 3:
        code = parts[2]
        if code in selected:
            selected.remove(code)
        else:
            selected.append(code)
        selected = [c for c in WEEKDAY_CODES if c in selected]
    elif action == "done":
        if not selected:
            await callback.answer("Выбери хотя бы один день.", show_alert=True)
            return
        await state.update_data(selected_days=selected)
        await callback.answer()
        await callback.message.edit_text(
            "Во сколько начинается? Напиши время <b>HH:MM</b> (например, 08:00).",
            parse_mode="HTML",
            reply_markup=cancel_kb(),
        )
        await state.set_state(AddRoutine.time)
        return
    else:
        await callback.answer()
        return

    await state.update_data(selected_days=selected)
    await callback.message.edit_reply_markup(reply_markup=_routine_days_kb(selected))
    await callback.answer()


@router.message(AddRoutine.time, F.text)
async def routine_time(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    try:
        hh_str, mm_str = text.split(":", 1)
        hh, mm = int(hh_str), int(mm_str)
        if not (0 <= hh < 24 and 0 <= mm < 60):
            raise ValueError
    except ValueError:
        await message.answer("Не понял время. Формат: HH:MM.")
        return

    data = await state.get_data()
    days = data.get("selected_days", [])
    time_local = f"{hh:02d}:{mm:02d}"
    recurrence = "WEEKLY:" + ",".join(days)
    create_task(
        task_type="event",
        title=data["title"],
        created_by=data["user_db_id"],
        visibility="family",
        category="routine",
        recurrence=recurrence,
        time_local=time_local,
    )
    days_label = ", ".join(_DAY_NAMES_RU[c] for c in days)
    await message.answer(
        f"✓ Сохранено: <b>{data['title']}</b> — {time_local} ({days_label})",
        parse_mode="HTML",
    )
    await state.clear()
