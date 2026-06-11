"""Покупки: общий (семейный) список + персональный на каждого члена семьи."""

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
    FAMILY_MEMBERS,
    add_shopping_item,
    get_shopping_list,
    get_user_by_telegram_id,
    list_shopping_lists,
    remove_shopping_item,
)
from bot.handlers.common import cancel_kb

router = Router()


class ShoppingAdd(StatesGroup):
    item = State()


# idx 0 — общий семейный список, далее — члены семьи.
_OWNERS = ["family", *FAMILY_MEMBERS]
_OWNER_LABEL = ["🏡 Общие (семейные)", *FAMILY_MEMBERS]


def _root_kb() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=_OWNER_LABEL[0], callback_data="shop:list:0")]]
    for i in range(1, len(_OWNERS), 2):
        rows.append([
            InlineKeyboardButton(text=_OWNER_LABEL[j], callback_data=f"shop:list:{j}")
            for j in range(i, min(i + 2, len(_OWNERS)))
        ])
    rows.append([InlineKeyboardButton(text="🛒 ВСЕ ПОКУПКИ", callback_data="shop:all")])
    rows.append([InlineKeyboardButton(text="⬅️ Семейный ассистент", callback_data="home:show")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("shopping"))
async def cmd_shopping(message: Message) -> None:
    user = get_user_by_telegram_id(message.from_user.id)
    if not user:
        await message.answer("Сначала зарегистрируйся: /start")
        return
    await message.answer(
        "<b>🛒 Покупки</b>\n\nЧей список открыть?",
        parse_mode="HTML",
        reply_markup=_root_kb(),
    )


@router.callback_query(F.data == "shop:open")
async def cb_open(callback: CallbackQuery) -> None:
    await callback.answer()
    try:
        await callback.message.edit_text(
            "<b>🛒 Покупки</b>\n\nЧей список открыть?",
            parse_mode="HTML",
            reply_markup=_root_kb(),
        )
    except Exception:
        await callback.message.answer(
            "<b>🛒 Покупки</b>\n\nЧей список открыть?",
            parse_mode="HTML",
            reply_markup=_root_kb(),
        )


# ---------- экран одного списка ----------

def _list_kb(idx: int, items: list[str]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text=f"🗑 {i + 1} Корзина", callback_data=f"shop:rmask:{idx}:{i}"),
            InlineKeyboardButton(text=f"✅ {i + 1} Куплено", callback_data=f"shop:done:{idx}:{i}"),
        ]
        for i in range(len(items))
    ]
    rows.append([InlineKeyboardButton(text="➕ Добавить", callback_data=f"shop:add:{idx}")])
    rows.append([InlineKeyboardButton(text="← Назад", callback_data="shop:open")])
    rows.append([InlineKeyboardButton(text="⬅️ Семейный ассистент", callback_data="home:show")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _render_list(idx: int) -> tuple[str, list[str]]:
    owner = _OWNERS[idx]
    lst = get_shopping_list(owner) or {}
    items: list[str] = list(lst.get("items") or [])
    if items:
        body = "\n".join(f"{i + 1}. {it}" for i, it in enumerate(items))
    else:
        body = "—"
    text = f"<b>🛒 {_OWNER_LABEL[idx]}</b>\n\n{body}"
    return text, items


@router.callback_query(F.data == "shop:all")
async def cb_all(callback: CallbackQuery) -> None:
    plans = {p["owner"]: p for p in list_shopping_lists()}
    lines = ["<b>🛒 ВСЕ ПОКУПКИ</b>", ""]
    any_items = False
    for idx, owner in enumerate(_OWNERS):
        items = (plans.get(owner) or {}).get("items") or []
        if not items:
            continue
        any_items = True
        lines.append(f"<b>{_OWNER_LABEL[idx]}</b>")
        for it in items:
            lines.append(f"• {it}")
        lines.append("")
    text = "\n".join(lines).rstrip() if any_items else "<b>🛒 ВСЕ ПОКУПКИ</b>\n\nПока пусто."
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="← Назад", callback_data="shop:open")],
            [InlineKeyboardButton(text="⬅️ Семейный ассистент", callback_data="home:show")],
        ]
    )
    await callback.answer()
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data.startswith("shop:list:"))
async def cb_list(callback: CallbackQuery) -> None:
    try:
        idx = int(callback.data.split(":")[2])
        _OWNERS[idx]
    except (ValueError, IndexError):
        await callback.answer("Не нашёл", show_alert=True)
        return
    text, items = _render_list(idx)
    await callback.answer()
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=_list_kb(idx, items))
    except Exception:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=_list_kb(idx, items))


@router.callback_query(F.data.startswith("shop:add:"))
async def cb_add(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        idx = int(callback.data.split(":")[2])
        _OWNERS[idx]
    except (ValueError, IndexError):
        await callback.answer("Не нашёл", show_alert=True)
        return
    await state.update_data(shop_idx=idx)
    await state.set_state(ShoppingAdd.item)
    await callback.answer()
    await callback.message.answer(
        f"Что добавить в список «{_OWNER_LABEL[idx]}»? Напиши коротко (можно несколько через запятую).",
        reply_markup=cancel_kb(),
    )


@router.message(ShoppingAdd.item, F.text)
async def on_item(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    data = await state.get_data()
    idx = data.get("shop_idx")
    if idx is None:
        await state.clear()
        return
    items = [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
    if not items:
        await message.answer("Пусто. Напиши, что купить.")
        return
    for it in items:
        add_shopping_item(_OWNERS[idx], it)
    await state.clear()
    text, lst_items = _render_list(idx)
    await message.answer(text, parse_mode="HTML", reply_markup=_list_kb(idx, lst_items))


@router.callback_query(F.data.startswith("shop:done:"))
async def cb_done(callback: CallbackQuery) -> None:
    """Купили — удалить пункт сразу, без подтверждения."""
    parts = callback.data.split(":")
    try:
        idx = int(parts[2])
        item_i = int(parts[3])
        _OWNERS[idx]
    except (ValueError, IndexError):
        await callback.answer("Не нашёл", show_alert=True)
        return
    items = list((get_shopping_list(_OWNERS[idx]) or {}).get("items") or [])
    if not (0 <= item_i < len(items)):
        await callback.answer("Пункт уже удалён", show_alert=True)
        return
    remove_shopping_item(_OWNERS[idx], item_i)
    await callback.answer("✅ Куплено!")
    text, new_items = _render_list(idx)
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=_list_kb(idx, new_items))
    except Exception:
        pass


@router.callback_query(F.data.startswith("shop:rmask:"))
async def cb_rmask(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    try:
        idx = int(parts[2])
        item_i = int(parts[3])
        owner = _OWNERS[idx]
    except (ValueError, IndexError):
        await callback.answer("Не нашёл", show_alert=True)
        return
    items = list((get_shopping_list(owner) or {}).get("items") or [])
    if not (0 <= item_i < len(items)):
        await callback.answer("Пункт уже удалён", show_alert=True)
        return
    await callback.answer()
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🗑 Да, удалить", callback_data=f"shop:rmyes:{idx}:{item_i}"),
        InlineKeyboardButton(text="← Отмена", callback_data=f"shop:list:{idx}"),
    ]])
    try:
        await callback.message.edit_text(f"Удалить «{items[item_i]}»?", reply_markup=kb)
    except Exception:
        await callback.message.answer(f"Удалить «{items[item_i]}»?", reply_markup=kb)


@router.callback_query(F.data.startswith("shop:rmyes:"))
async def cb_rmyes(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    try:
        idx = int(parts[2])
        item_i = int(parts[3])
        _OWNERS[idx]
    except (ValueError, IndexError):
        await callback.answer("Не нашёл", show_alert=True)
        return
    remove_shopping_item(_OWNERS[idx], item_i)
    await callback.answer("Удалено")
    text, items = _render_list(idx)
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=_list_kb(idx, items))
    except Exception:
        pass
