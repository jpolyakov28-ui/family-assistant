"""Лекарства и БАДы: на каждого члена семьи — завтрак/обед/ужин."""

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

from bot.db import FAMILY_MEMBERS, get_med_plan, get_user_by_telegram_id, set_med_items
from bot.handlers.common import cancel_kb

router = Router()


class MedEdit(StatesGroup):
    items = State()


_MEALS = ("breakfast", "lunch", "dinner")
_MEAL_LABEL = {"breakfast": "Завтрак", "lunch": "Обед", "dinner": "Ужин"}
_MEAL_ICON = {"breakfast": "🌅", "lunch": "🥣", "dinner": "🌙"}


def _root_kb() -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, len(FAMILY_MEMBERS), 2):
        rows.append([
            InlineKeyboardButton(text=FAMILY_MEMBERS[j], callback_data=f"meds:person:{j}")
            for j in range(i, min(i + 2, len(FAMILY_MEMBERS)))
        ])
    rows.append([InlineKeyboardButton(text="⬅️ Семейный ассистент", callback_data="home:show")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("meds"))
async def cmd_meds(message: Message) -> None:
    user = get_user_by_telegram_id(message.from_user.id)
    if not user:
        await message.answer("Сначала зарегистрируйся: /start")
        return
    await message.answer(
        "<b>💊 Лекарства и БАДы</b>\n\nКого открыть?",
        parse_mode="HTML",
        reply_markup=_root_kb(),
    )


@router.callback_query(F.data == "meds:open")
async def cb_open(callback: CallbackQuery) -> None:
    await callback.answer()
    try:
        await callback.message.edit_text(
            "<b>💊 Лекарства и БАДы</b>\n\nКого открыть?",
            parse_mode="HTML",
            reply_markup=_root_kb(),
        )
    except Exception:
        await callback.message.answer(
            "<b>💊 Лекарства и БАДы</b>\n\nКого открыть?",
            parse_mode="HTML",
            reply_markup=_root_kb(),
        )


# ---------- экран человека ----------

def _person_kb(idx: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=f"✏️ {_MEAL_LABEL[meal]}",
            callback_data=f"meds:edit:{idx}:{meal}",
        )]
        for meal in _MEALS
    ]
    rows.append([InlineKeyboardButton(text="← К списку", callback_data="meds:open")])
    rows.append([InlineKeyboardButton(text="⬅️ Семейный ассистент", callback_data="home:show")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _render_person(idx: int) -> str:
    person = FAMILY_MEMBERS[idx]
    lines = [f"<b>💊 {person}</b>", ""]
    for meal in _MEALS:
        plan = get_med_plan(person, meal) or {}
        items = plan.get("items") or []
        body = ", ".join(items) if items else "—"
        lines.append(f"{_MEAL_ICON[meal]} {_MEAL_LABEL[meal]}: {body}")
    return "\n".join(lines)


@router.callback_query(F.data.startswith("meds:person:"))
async def cb_person(callback: CallbackQuery) -> None:
    try:
        idx = int(callback.data.split(":")[2])
        FAMILY_MEMBERS[idx]
    except (ValueError, IndexError):
        await callback.answer("Не нашёл", show_alert=True)
        return
    await callback.answer()
    try:
        await callback.message.edit_text(
            _render_person(idx), parse_mode="HTML", reply_markup=_person_kb(idx)
        )
    except Exception:
        await callback.message.answer(
            _render_person(idx), parse_mode="HTML", reply_markup=_person_kb(idx)
        )


@router.callback_query(F.data.startswith("meds:edit:"))
async def cb_edit(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    try:
        idx = int(parts[2])
        meal = parts[3]
        person = FAMILY_MEMBERS[idx]
    except (ValueError, IndexError):
        await callback.answer("Не нашёл", show_alert=True)
        return
    if meal not in _MEALS:
        await callback.answer("Не нашёл", show_alert=True)
        return
    await state.update_data(med_idx=idx, med_meal=meal)
    await state.set_state(MedEdit.items)
    await callback.answer()
    await callback.message.answer(
        f"Лекарства/БАДы для «{person} — {_MEAL_LABEL[meal].lower()}».\n"
        "Перечисли через запятую (например: <code>Аспирин, Магний B6, Витамин D</code>).\n"
        "Чтобы очистить — напиши <code>-</code>.",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )


@router.message(MedEdit.items, F.text)
async def on_items(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    data = await state.get_data()
    idx, meal = data.get("med_idx"), data.get("med_meal")
    if idx is None or not meal:
        await state.clear()
        return
    if raw == "-":
        items: list[str] = []
    else:
        items = [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
    set_med_items(FAMILY_MEMBERS[idx], meal, items)
    await state.clear()
    await message.answer(
        _render_person(idx), parse_mode="HTML", reply_markup=_person_kb(idx)
    )
