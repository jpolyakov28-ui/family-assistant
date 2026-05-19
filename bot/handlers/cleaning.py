"""Генеральная уборка: список действий на каждый день недели."""

from __future__ import annotations

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
    add_cleaning_item,
    get_cleaning_plan,
    get_user_by_telegram_id,
    list_cleaning_plans,
    remove_cleaning_item,
)
from bot.handlers.common import cancel_kb

router = Router()


class CleaningAdd(StatesGroup):
    item = State()


_DAY_NAMES_RU = {
    "MO": "Пн", "TU": "Вт", "WE": "Ср", "TH": "Чт", "FR": "Пт", "SA": "Сб", "SU": "Вс",
}
_DAY_NAMES_FULL = {
    "MO": "Понедельник", "TU": "Вторник", "WE": "Среда", "TH": "Четверг",
    "FR": "Пятница", "SA": "Суббота", "SU": "Воскресенье",
}


def _root_kb() -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, 7, 2):
        pair = WEEKDAY_CODES[i:i + 2]
        rows.append([
            InlineKeyboardButton(text=_DAY_NAMES_FULL[c], callback_data=f"clean:day:{c}")
            for c in pair
        ])
    rows.append([InlineKeyboardButton(text="⬅️ Семейный ассистент", callback_data="home:show")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _render_week() -> str:
    plans = {p["weekday"]: p for p in list_cleaning_plans()}
    lines = ["<b>🧹 Гениальная уборка — на неделю</b>", ""]
    for code in WEEKDAY_CODES:
        plan = plans.get(code) or {}
        items = plan.get("items") or []
        lines.append(f"<b>{_DAY_NAMES_FULL[code]}</b>")
        if items:
            for it in items:
                lines.append(f"  • {it}")
        else:
            lines.append("  —")
        lines.append("")
    return "\n".join(lines).rstrip()


@router.message(Command("cleaning"))
async def cmd_cleaning(message: Message) -> None:
    user = get_user_by_telegram_id(message.from_user.id)
    if not user:
        await message.answer("Сначала зарегистрируйся: /start")
        return
    await message.answer(_render_week(), parse_mode="HTML", reply_markup=_root_kb())


@router.callback_query(F.data == "clean:open")
async def cb_open(callback: CallbackQuery) -> None:
    await callback.answer()
    try:
        await callback.message.edit_text(_render_week(), parse_mode="HTML", reply_markup=_root_kb())
    except Exception:
        await callback.message.answer(_render_week(), parse_mode="HTML", reply_markup=_root_kb())


# ---------- экран одного дня ----------

def _day_kb(weekday: str, items: list[str]) -> InlineKeyboardMarkup:
    rows = []
    for idx, _ in enumerate(items):
        rows.append([InlineKeyboardButton(
            text=f"🗑 {idx + 1}",
            callback_data=f"clean:rmask:{weekday}:{idx}",
        )])
    rows.append([InlineKeyboardButton(text="➕ Добавить пункт", callback_data=f"clean:add:{weekday}")])
    rows.append([InlineKeyboardButton(text="← Назад", callback_data="clean:open")])
    rows.append([InlineKeyboardButton(text="⬅️ Семейный ассистент", callback_data="home:show")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _render_day(weekday: str) -> tuple[str, list[str]]:
    plan = get_cleaning_plan(weekday) or {}
    items: list[str] = list(plan.get("items") or [])
    if not items:
        body = "—"
    else:
        body = "\n".join(f"{idx + 1}. {it}" for idx, it in enumerate(items))
    text = f"<b>🧹 {_DAY_NAMES_FULL[weekday]}</b>\n\n{body}"
    return text, items


@router.callback_query(F.data.startswith("clean:day:"))
async def cb_day(callback: CallbackQuery) -> None:
    weekday = callback.data.split(":", 2)[2]
    if weekday not in WEEKDAY_CODES:
        await callback.answer("Бяка", show_alert=True)
        return
    text, items = _render_day(weekday)
    await callback.answer()
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=_day_kb(weekday, items))
    except Exception:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=_day_kb(weekday, items))


@router.callback_query(F.data.startswith("clean:add:"))
async def cb_add(callback: CallbackQuery, state: FSMContext) -> None:
    weekday = callback.data.split(":", 2)[2]
    if weekday not in WEEKDAY_CODES:
        await callback.answer("Бяка", show_alert=True)
        return
    await state.update_data(clean_weekday=weekday)
    await state.set_state(CleaningAdd.item)
    await callback.answer()
    await callback.message.answer(
        f"Что добавить в «{_DAY_NAMES_FULL[weekday]}»? Напиши коротко (например, «Мойка полов»).",
        reply_markup=cancel_kb(),
    )


@router.message(CleaningAdd.item, F.text)
async def on_item(message: Message, state: FSMContext) -> None:
    item = (message.text or "").strip()
    if not item or len(item) > 200:
        await message.answer("От 1 до 200 символов.")
        return
    data = await state.get_data()
    weekday = data.get("clean_weekday")
    if not weekday:
        await state.clear()
        return
    add_cleaning_item(weekday, item)
    await state.clear()
    text, items = _render_day(weekday)
    await message.answer(text, parse_mode="HTML", reply_markup=_day_kb(weekday, items))


@router.callback_query(F.data.startswith("clean:rmask:"))
async def cb_rmask(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    weekday, idx_str = parts[2], parts[3]
    try:
        idx = int(idx_str)
    except ValueError:
        await callback.answer("Бяка", show_alert=True)
        return
    plan = get_cleaning_plan(weekday) or {}
    items = list(plan.get("items") or [])
    if not (0 <= idx < len(items)):
        await callback.answer("Пункт уже удалён", show_alert=True)
        return
    await callback.answer()
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🗑 Да, удалить", callback_data=f"clean:rmyes:{weekday}:{idx}"),
        InlineKeyboardButton(text="← Отмена", callback_data=f"clean:day:{weekday}"),
    ]])
    try:
        await callback.message.edit_text(
            f"Удалить «{items[idx]}»?", reply_markup=kb
        )
    except Exception:
        await callback.message.answer(f"Удалить «{items[idx]}»?", reply_markup=kb)


@router.callback_query(F.data.startswith("clean:rmyes:"))
async def cb_rmyes(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    weekday, idx_str = parts[2], parts[3]
    try:
        idx = int(idx_str)
    except ValueError:
        await callback.answer("Бяка", show_alert=True)
        return
    remove_cleaning_item(weekday, idx)
    await callback.answer("Удалено")
    text, items = _render_day(weekday)
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=_day_kb(weekday, items))
    except Exception:
        pass
