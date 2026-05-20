"""Продуктовое меню на неделю: обед + ужин на каждый день + список покупок."""

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
    clear_meal_plan,
    get_meal_plan,
    get_user_by_telegram_id,
    list_meal_plans,
    upsert_meal_plan,
)
from bot.handlers.common import cancel_kb

router = Router()


class MealEdit(StatesGroup):
    dish = State()
    ingredients = State()


_DAY_NAMES_RU = {
    "MO": "Пн", "TU": "Вт", "WE": "Ср", "TH": "Чт", "FR": "Пт", "SA": "Сб", "SU": "Вс",
}
_DAY_NAMES_FULL = {
    "MO": "Понедельник", "TU": "Вторник", "WE": "Среда", "TH": "Четверг",
    "FR": "Пятница", "SA": "Суббота", "SU": "Воскресенье",
}
_MEAL_LABEL = {"lunch": "Обед", "dinner": "Ужин"}
_MEAL_ICON = {"lunch": "🥣", "dinner": "🍴"}


# ---------- корневой экран ----------

def _menu_kb() -> InlineKeyboardMarkup:
    rows = []
    for code in WEEKDAY_CODES:
        rows.append([
            InlineKeyboardButton(text=f"{_DAY_NAMES_RU[code]} 🥣", callback_data=f"menu:slot:{code}:lunch"),
            InlineKeyboardButton(text=f"{_DAY_NAMES_RU[code]} 🍴", callback_data=f"menu:slot:{code}:dinner"),
        ])
    rows.append([InlineKeyboardButton(text="📖 Книга рецептов", callback_data="rcb:cats")])
    rows.append([InlineKeyboardButton(text="🛒 Список покупок", callback_data="menu:shop")])
    rows.append([InlineKeyboardButton(text="⬅️ Семейный ассистент", callback_data="home:show")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _render_week() -> str:
    plans = list_meal_plans()
    by_key = {(p["weekday"], p["meal"]): p for p in plans}
    lines = ["<b>🍽 Меню на неделю</b>", ""]
    for code in WEEKDAY_CODES:
        lines.append(f"<b>{_DAY_NAMES_FULL[code]}</b>")
        for meal in ("lunch", "dinner"):
            slot = by_key.get((code, meal))
            dish = (slot or {}).get("dish") or "—"
            lines.append(f"  {_MEAL_ICON[meal]} {_MEAL_LABEL[meal]}: {dish}")
        lines.append("")
    return "\n".join(lines).rstrip()


@router.message(Command("menu"))
async def cmd_menu(message: Message) -> None:
    user = get_user_by_telegram_id(message.from_user.id)
    if not user:
        await message.answer("Сначала зарегистрируйся: /start")
        return
    await message.answer(_render_week(), parse_mode="HTML", reply_markup=_menu_kb())


@router.callback_query(F.data == "menu:open")
async def cb_menu_open(callback: CallbackQuery) -> None:
    await callback.answer()
    try:
        await callback.message.edit_text(_render_week(), parse_mode="HTML", reply_markup=_menu_kb())
    except Exception:
        await callback.message.answer(_render_week(), parse_mode="HTML", reply_markup=_menu_kb())


# ---------- экран одного слота ----------

def _slot_kb(weekday: str, meal: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Блюдо", callback_data=f"menu:dish:{weekday}:{meal}")],
            [InlineKeyboardButton(text="✏️ Ингредиенты", callback_data=f"menu:ing:{weekday}:{meal}")],
            [InlineKeyboardButton(text="📖 Из книги рецептов", callback_data=f"rcp:cats:{weekday}:{meal}")],
            [InlineKeyboardButton(text="🗑 Очистить", callback_data=f"menu:clearask:{weekday}:{meal}")],
            [InlineKeyboardButton(text="← К меню", callback_data="menu:open")],
            [InlineKeyboardButton(text="⬅️ Семейный ассистент", callback_data="home:show")],
        ]
    )


def _render_slot(weekday: str, meal: str) -> str:
    slot = get_meal_plan(weekday, meal) or {}
    dish = slot.get("dish") or "—"
    ingredients = slot.get("ingredients") or []
    ing_line = ", ".join(ingredients) if ingredients else "—"
    return (
        f"<b>{_DAY_NAMES_FULL[weekday]} — {_MEAL_LABEL[meal].lower()}</b>\n"
        f"\n"
        f"{_MEAL_ICON[meal]} Блюдо: {dish}\n"
        f"🧺 Ингредиенты: {ing_line}"
    )


@router.callback_query(F.data.startswith("menu:slot:"))
async def cb_slot(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    weekday, meal = parts[2], parts[3]
    if weekday not in WEEKDAY_CODES or meal not in ("lunch", "dinner"):
        await callback.answer("Бяка", show_alert=True)
        return
    await callback.answer()
    try:
        await callback.message.edit_text(
            _render_slot(weekday, meal),
            parse_mode="HTML",
            reply_markup=_slot_kb(weekday, meal),
        )
    except Exception:
        await callback.message.answer(
            _render_slot(weekday, meal),
            parse_mode="HTML",
            reply_markup=_slot_kb(weekday, meal),
        )


@router.callback_query(F.data.startswith("menu:dish:"))
async def cb_set_dish(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    weekday, meal = parts[2], parts[3]
    await state.update_data(meal_weekday=weekday, meal_meal=meal)
    await state.set_state(MealEdit.dish)
    await callback.answer()
    await callback.message.answer(
        f"Название блюда для «{_DAY_NAMES_FULL[weekday]} — {_MEAL_LABEL[meal].lower()}»?",
        reply_markup=cancel_kb(),
    )


@router.message(MealEdit.dish, F.text)
async def on_dish(message: Message, state: FSMContext) -> None:
    title = (message.text or "").strip()
    if not title or len(title) > 200:
        await message.answer("От 1 до 200 символов.")
        return
    data = await state.get_data()
    weekday, meal = data.get("meal_weekday"), data.get("meal_meal")
    if not weekday or not meal:
        await state.clear()
        return
    upsert_meal_plan(weekday, meal, dish=title)
    await state.clear()
    await message.answer(
        _render_slot(weekday, meal),
        parse_mode="HTML",
        reply_markup=_slot_kb(weekday, meal),
    )


@router.callback_query(F.data.startswith("menu:ing:"))
async def cb_set_ing(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    weekday, meal = parts[2], parts[3]
    await state.update_data(meal_weekday=weekday, meal_meal=meal)
    await state.set_state(MealEdit.ingredients)
    await callback.answer()
    await callback.message.answer(
        "Перечисли ингредиенты через запятую.\n"
        "Например: <code>свёкла, капуста, говядина, картошка</code>\n"
        "Чтобы очистить — напиши <code>-</code>.",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )


@router.message(MealEdit.ingredients, F.text)
async def on_ingredients(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    data = await state.get_data()
    weekday, meal = data.get("meal_weekday"), data.get("meal_meal")
    if not weekday or not meal:
        await state.clear()
        return
    if raw == "-":
        ingredients: list[str] = []
    else:
        ingredients = [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
    upsert_meal_plan(weekday, meal, ingredients=ingredients)
    await state.clear()
    await message.answer(
        _render_slot(weekday, meal),
        parse_mode="HTML",
        reply_markup=_slot_kb(weekday, meal),
    )


@router.callback_query(F.data.startswith("menu:clearask:"))
async def cb_clearask(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    weekday, meal = parts[2], parts[3]
    await callback.answer()
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🗑 Да, очистить", callback_data=f"menu:clearyes:{weekday}:{meal}"),
        InlineKeyboardButton(text="← Отмена", callback_data=f"menu:slot:{weekday}:{meal}"),
    ]])
    try:
        await callback.message.edit_text(
            f"Очистить блюдо и ингредиенты — {_DAY_NAMES_FULL[weekday]}, "
            f"{_MEAL_LABEL[meal].lower()}?",
            reply_markup=kb,
        )
    except Exception:
        await callback.message.answer("Очистить слот?", reply_markup=kb)


@router.callback_query(F.data.startswith("menu:clearyes:"))
async def cb_clearyes(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    weekday, meal = parts[2], parts[3]
    clear_meal_plan(weekday, meal)
    await callback.answer("Очищено")
    try:
        await callback.message.edit_text(
            _render_slot(weekday, meal),
            parse_mode="HTML",
            reply_markup=_slot_kb(weekday, meal),
        )
    except Exception:
        pass


# ---------- список покупок ----------

@router.callback_query(F.data == "menu:shop")
async def cb_shop(callback: CallbackQuery) -> None:
    plans = list_meal_plans()
    counter: dict[str, int] = {}
    order: list[str] = []  # для стабильного порядка по первому появлению
    for p in plans:
        for ing in (p.get("ingredients") or []):
            key = ing.strip().lower()
            if not key:
                continue
            if key not in counter:
                counter[key] = 0
                order.append(ing.strip())
            counter[key] += 1

    if not order:
        text = "🛒 <b>Список покупок</b>\n\nПока пусто — заполни ингредиенты в слотах меню."
    else:
        # сортируем по убыванию частоты, потом по алфавиту
        sorted_items = sorted(order, key=lambda x: (-counter[x.lower()], x.lower()))
        lines = ["🛒 <b>Список покупок</b>", ""]
        for item in sorted_items:
            n = counter[item.lower()]
            suffix = f" ×{n}" if n > 1 else ""
            lines.append(f"• {item}{suffix}")
        text = "\n".join(lines)

    await callback.answer()
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="← К меню", callback_data="menu:open")],
            [InlineKeyboardButton(text="⬅️ Семейный ассистент", callback_data="home:show")],
        ]
    )
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
