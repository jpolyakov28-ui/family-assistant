"""Книга рецептов: просмотр, добавление, редактирование, удаление.

Callback-префиксы:
  rcb:*  — browse-режим (из корня «Меню на неделю»)
  rcp:*  — pick-режим (выбор рецепта для слота меню)
"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.db import delete_recipe, get_recipe, list_recipes, upsert_meal_plan, upsert_recipe
from bot.handlers.common import cancel_kb

log = logging.getLogger(__name__)
router = Router()

CATEGORIES: dict[str, str] = {
    "soup":   "🍲 Супы",
    "hot":    "🍖 Горячие блюда",
    "salad":  "🥗 Салаты",
    "baking": "🥐 Выпечка",
}


class RecipeAdd(StatesGroup):
    name = State()
    category = State()
    ingredients = State()
    instructions = State()


class RecipeEdit(StatesGroup):
    name = State()
    ingredients = State()
    instructions = State()


# ---------- render helpers ----------

def _render_recipe(recipe: dict) -> str:
    name = recipe["name"]
    cat_label = CATEGORIES.get(recipe.get("category", ""), "")
    ingredients = recipe.get("ingredients") or []
    instructions = (recipe.get("instructions") or "").strip()
    ing_text = ", ".join(ingredients) if ingredients else "—"
    inst_text = instructions if instructions else "—"
    return (
        f"<b>{name}</b>  <i>{cat_label}</i>\n\n"
        f"🧺 <b>Ингредиенты:</b>\n{ing_text}\n\n"
        f"👨‍🍳 <b>Приготовление:</b>\n{inst_text}"
    )


# ---------- keyboard helpers ----------

def _cats_kb_browse() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=label, callback_data=f"rcb:cat:{cat}")]
        for cat, label in CATEGORIES.items()
    ]
    rows.append([InlineKeyboardButton(text="➕ Добавить рецепт", callback_data="rcb:add")])
    rows.append([InlineKeyboardButton(text="← К меню", callback_data="menu:open")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _cats_kb_pick(weekday: str, meal: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=label, callback_data=f"rcp:cat:{cat}:{weekday}:{meal}")]
        for cat, label in CATEGORIES.items()
    ]
    rows.append([InlineKeyboardButton(text="← Назад", callback_data=f"menu:slot:{weekday}:{meal}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _recipes_kb_browse(recipes: list[dict], category: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=r["name"], callback_data=f"rcb:view:{r['id']}")]
        for r in recipes
    ]
    rows.append([InlineKeyboardButton(text="➕ Добавить", callback_data=f"rcb:add:{category}")])
    rows.append([InlineKeyboardButton(text="← Назад", callback_data="rcb:cats")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _recipes_kb_pick(
    recipes: list[dict], category: str, weekday: str, meal: str
) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=r["name"], callback_data=f"rcp:{r['id']}:{weekday}:{meal}")]
        for r in recipes
    ]
    rows.append([InlineKeyboardButton(text="← Назад", callback_data=f"rcp:cats:{weekday}:{meal}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _recipe_view_kb(recipe: dict) -> InlineKeyboardMarkup:
    rid = recipe["id"]
    cat = recipe["category"]
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✏️ Название", callback_data=f"rcb:editname:{rid}"),
            InlineKeyboardButton(text="✏️ Ингредиенты", callback_data=f"rcb:editing:{rid}"),
        ],
        [
            InlineKeyboardButton(text="✏️ Рецепт", callback_data=f"rcb:editinst:{rid}"),
            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"rcb:delask:{rid}"),
        ],
        [InlineKeyboardButton(text="← Назад", callback_data=f"rcb:cat:{cat}")],
        [InlineKeyboardButton(text="⬅️ Семейный ассистент", callback_data="home:show")],
    ])


async def _show_recipe(target: CallbackQuery | Message, recipe: dict) -> None:
    text = _render_recipe(recipe)
    kb = _recipe_view_kb(recipe)
    if isinstance(target, CallbackQuery):
        try:
            await target.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        except Exception:
            await target.message.answer(text, parse_mode="HTML", reply_markup=kb)
    else:
        await target.answer(text, parse_mode="HTML", reply_markup=kb)


async def _show_category(target: CallbackQuery, cat: str) -> None:
    recipes = list_recipes(cat)
    label = CATEGORIES[cat]
    text = (
        f"📖 <b>{label}</b>\n\nВыбери блюдо:"
        if recipes
        else f"📖 <b>{label}</b>\n\nПока пусто — добавь первый рецепт!"
    )
    try:
        await target.message.edit_text(text, parse_mode="HTML", reply_markup=_recipes_kb_browse(recipes, cat))
    except Exception:
        await target.message.answer(text, parse_mode="HTML", reply_markup=_recipes_kb_browse(recipes, cat))


# ---------- browse: categories ----------

@router.callback_query(F.data == "rcb:cats")
async def cb_rcb_cats(callback: CallbackQuery) -> None:
    await callback.answer()
    try:
        await callback.message.edit_text(
            "📖 <b>Книга рецептов</b>\n\nВыбери категорию:",
            parse_mode="HTML",
            reply_markup=_cats_kb_browse(),
        )
    except Exception:
        await callback.message.answer(
            "📖 <b>Книга рецептов</b>\n\nВыбери категорию:",
            parse_mode="HTML",
            reply_markup=_cats_kb_browse(),
        )


@router.callback_query(F.data.startswith("rcb:cat:"))
async def cb_rcb_cat(callback: CallbackQuery) -> None:
    cat = callback.data.split(":")[2]
    if cat not in CATEGORIES:
        await callback.answer("Неизвестная категория", show_alert=True)
        return
    await callback.answer()
    await _show_category(callback, cat)


# ---------- browse: view recipe ----------

@router.callback_query(F.data.startswith("rcb:view:"))
async def cb_rcb_view(callback: CallbackQuery) -> None:
    rid = callback.data[len("rcb:view:"):]
    recipe = get_recipe(rid)
    if not recipe:
        await callback.answer("Рецепт не найден", show_alert=True)
        return
    await callback.answer()
    await _show_recipe(callback, recipe)


# ---------- add recipe FSM ----------

@router.callback_query(F.data == "rcb:add")
async def cb_rcb_add(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await state.set_state(RecipeAdd.name)
    await callback.message.answer(
        "📖 <b>Новый рецепт</b>\n\nКак называется блюдо?",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )


@router.callback_query(F.data.startswith("rcb:add:"))
async def cb_rcb_add_cat(callback: CallbackQuery, state: FSMContext) -> None:
    cat = callback.data.split(":")[2]
    if cat not in CATEGORIES:
        await callback.answer("Неизвестная категория", show_alert=True)
        return
    await callback.answer()
    await state.clear()
    await state.update_data(recipe_cat=cat)
    await state.set_state(RecipeAdd.name)
    await callback.message.answer(
        f"📖 <b>Новый рецепт — {CATEGORIES[cat]}</b>\n\nКак называется блюдо?",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )


@router.message(RecipeAdd.name, F.text)
async def on_recipe_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not name or len(name) > 200:
        await message.answer("Название — от 1 до 200 символов.")
        return
    await state.update_data(recipe_name=name)
    data = await state.get_data()
    if data.get("recipe_cat"):
        await state.set_state(RecipeAdd.ingredients)
        await message.answer(
            "🧺 <b>Ингредиенты</b>\n\nПеречисли через запятую.\n"
            "Например: <code>картошка, морковь, лук</code>\n"
            "Или <code>-</code> если пропустить.",
            parse_mode="HTML",
            reply_markup=cancel_kb(),
        )
    else:
        await state.set_state(RecipeAdd.category)
        rows = [
            [InlineKeyboardButton(text=label, callback_data=f"rcb:addcat:{cat}")]
            for cat, label in CATEGORIES.items()
        ]
        await message.answer("Выбери категорию:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(RecipeAdd.category, F.data.startswith("rcb:addcat:"))
async def on_recipe_cat(callback: CallbackQuery, state: FSMContext) -> None:
    cat = callback.data.split(":")[2]
    if cat not in CATEGORIES:
        await callback.answer("Неизвестная категория", show_alert=True)
        return
    await callback.answer()
    await state.update_data(recipe_cat=cat)
    await state.set_state(RecipeAdd.ingredients)
    await callback.message.answer(
        "🧺 <b>Ингредиенты</b>\n\nПеречисли через запятую.\n"
        "Например: <code>картошка, морковь, лук</code>\n"
        "Или <code>-</code> если пропустить.",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )


@router.message(RecipeAdd.ingredients, F.text)
async def on_recipe_ingredients(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    ingredients = (
        [] if raw == "-"
        else [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
    )
    await state.update_data(recipe_ingredients=ingredients)
    await state.set_state(RecipeAdd.instructions)
    await message.answer(
        "👨‍🍳 <b>Способ приготовления</b>\n\nОпиши рецепт. Или <code>-</code> если пропустить.",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )


@router.message(RecipeAdd.instructions, F.text)
async def on_recipe_instructions(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    instructions = "" if raw == "-" else raw
    data = await state.get_data()
    name = data.get("recipe_name", "")
    cat = data.get("recipe_cat", "soup")
    ingredients = data.get("recipe_ingredients", [])
    await state.clear()
    recipe = upsert_recipe(name=name, category=cat, ingredients=ingredients, instructions=instructions)
    await _show_recipe(message, recipe)


# ---------- edit recipe FSM ----------

@router.callback_query(F.data.startswith("rcb:editname:"))
async def cb_editname(callback: CallbackQuery, state: FSMContext) -> None:
    rid = callback.data[len("rcb:editname:"):]
    recipe = get_recipe(rid)
    if not recipe:
        await callback.answer("Рецепт не найден", show_alert=True)
        return
    await callback.answer()
    await state.clear()
    await state.update_data(recipe_id=rid)
    await state.set_state(RecipeEdit.name)
    await callback.message.answer(
        f"Новое название для «{recipe['name']}»:",
        reply_markup=cancel_kb(),
    )


@router.message(RecipeEdit.name, F.text)
async def on_edit_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not name or len(name) > 200:
        await message.answer("Название — от 1 до 200 символов.")
        return
    data = await state.get_data()
    rid = data["recipe_id"]
    await state.clear()
    recipe = upsert_recipe(recipe_id=rid, name=name)
    await _show_recipe(message, recipe)


@router.callback_query(F.data.startswith("rcb:editing:"))
async def cb_editing(callback: CallbackQuery, state: FSMContext) -> None:
    rid = callback.data[len("rcb:editing:"):]
    recipe = get_recipe(rid)
    if not recipe:
        await callback.answer("Рецепт не найден", show_alert=True)
        return
    await callback.answer()
    await state.clear()
    await state.update_data(recipe_id=rid)
    await state.set_state(RecipeEdit.ingredients)
    current = ", ".join(recipe.get("ingredients") or []) or "—"
    await callback.message.answer(
        f"Текущие ингредиенты: <code>{current}</code>\n\n"
        "Введи новые через запятую. Или <code>-</code> чтобы очистить.",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )


@router.message(RecipeEdit.ingredients, F.text)
async def on_edit_ingredients(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    ingredients = (
        [] if raw == "-"
        else [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
    )
    data = await state.get_data()
    rid = data["recipe_id"]
    await state.clear()
    recipe = upsert_recipe(recipe_id=rid, ingredients=ingredients)
    await _show_recipe(message, recipe)


@router.callback_query(F.data.startswith("rcb:editinst:"))
async def cb_editinst(callback: CallbackQuery, state: FSMContext) -> None:
    rid = callback.data[len("rcb:editinst:"):]
    recipe = get_recipe(rid)
    if not recipe:
        await callback.answer("Рецепт не найден", show_alert=True)
        return
    await callback.answer()
    await state.clear()
    await state.update_data(recipe_id=rid)
    await state.set_state(RecipeEdit.instructions)
    await callback.message.answer(
        "Введи способ приготовления. Или <code>-</code> чтобы очистить.",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )


@router.message(RecipeEdit.instructions, F.text)
async def on_edit_instructions(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    instructions = "" if raw == "-" else raw
    data = await state.get_data()
    rid = data["recipe_id"]
    await state.clear()
    recipe = upsert_recipe(recipe_id=rid, instructions=instructions)
    await _show_recipe(message, recipe)


# ---------- delete recipe ----------

@router.callback_query(F.data.startswith("rcb:delask:"))
async def cb_delask(callback: CallbackQuery) -> None:
    rid = callback.data[len("rcb:delask:"):]
    recipe = get_recipe(rid)
    if not recipe:
        await callback.answer("Рецепт не найден", show_alert=True)
        return
    await callback.answer()
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🗑 Да, удалить", callback_data=f"rcb:delyes:{rid}"),
        InlineKeyboardButton(text="← Отмена", callback_data=f"rcb:view:{rid}"),
    ]])
    try:
        await callback.message.edit_text(f"Удалить рецепт «{recipe['name']}»?", reply_markup=kb)
    except Exception:
        await callback.message.answer(f"Удалить рецепт «{recipe['name']}»?", reply_markup=kb)


@router.callback_query(F.data.startswith("rcb:delyes:"))
async def cb_delyes(callback: CallbackQuery) -> None:
    rid = callback.data[len("rcb:delyes:"):]
    recipe = get_recipe(rid)
    cat = recipe["category"] if recipe else "soup"
    delete_recipe(rid)
    await callback.answer("Удалено")
    await _show_category(callback, cat)


# ---------- pick mode (выбор рецепта из слота меню) ----------

@router.callback_query(F.data.startswith("rcp:cats:"))
async def cb_rcp_cats(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")  # ["rcp", "cats", weekday, meal]
    weekday, meal = parts[2], parts[3]
    await callback.answer()
    try:
        await callback.message.edit_text(
            "📖 <b>Книга рецептов</b>\n\nВыбери категорию:",
            parse_mode="HTML",
            reply_markup=_cats_kb_pick(weekday, meal),
        )
    except Exception:
        await callback.message.answer(
            "📖 <b>Книга рецептов</b>\n\nВыбери категорию:",
            parse_mode="HTML",
            reply_markup=_cats_kb_pick(weekday, meal),
        )


@router.callback_query(F.data.startswith("rcp:cat:"))
async def cb_rcp_cat(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")  # ["rcp", "cat", cat, weekday, meal]
    cat, weekday, meal = parts[2], parts[3], parts[4]
    if cat not in CATEGORIES:
        await callback.answer("Неизвестная категория", show_alert=True)
        return
    await callback.answer()
    recipes = list_recipes(cat)
    label = CATEGORIES[cat]
    text = (
        f"📖 <b>{label}</b>\n\nВыбери блюдо:"
        if recipes
        else f"📖 <b>{label}</b>\n\nПока пусто — сначала добавь рецепты через «Книга рецептов»."
    )
    try:
        await callback.message.edit_text(
            text, parse_mode="HTML",
            reply_markup=_recipes_kb_pick(recipes, cat, weekday, meal),
        )
    except Exception:
        await callback.message.answer(
            text, parse_mode="HTML",
            reply_markup=_recipes_kb_pick(recipes, cat, weekday, meal),
        )


@router.callback_query(F.data.startswith("rcp:"))
async def cb_rcp_pick(callback: CallbackQuery) -> None:
    # format: rcp:{uuid}:{weekday}:{meal}
    # split(":") → ["rcp", uuid, weekday, meal]  (uuid has hyphens, not colons)
    parts = callback.data.split(":")
    if len(parts) != 4 or parts[1] in ("cat", "cats"):
        return
    recipe_id, weekday, meal = parts[1], parts[2], parts[3]

    recipe = get_recipe(recipe_id)
    if not recipe:
        await callback.answer("Рецепт не найден", show_alert=True)
        return

    upsert_meal_plan(
        weekday, meal,
        dish=recipe["name"],
        ingredients=list(recipe.get("ingredients") or []),
    )
    await callback.answer(f"✅ {recipe['name']} добавлен")

    # Return to slot view — import here to avoid circular import at module level
    from bot.handlers.menu import _render_slot, _slot_kb
    try:
        await callback.message.edit_text(
            _render_slot(weekday, meal), parse_mode="HTML", reply_markup=_slot_kb(weekday, meal)
        )
    except Exception:
        await callback.message.answer(
            _render_slot(weekday, meal), parse_mode="HTML", reply_markup=_slot_kb(weekday, meal)
        )
