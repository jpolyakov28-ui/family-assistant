"""Главное меню — inline-экран в ленте чата (показывается при /start и /home)."""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

log = logging.getLogger(__name__)

from bot.db import get_user_by_telegram_id, list_family_routine_events
from bot.handlers.add import AddTask
from bot.handlers.cleaning import _render_week as _cleaning_week
from bot.handlers.cleaning import _root_kb as _cleaning_kb
from bot.handlers.common import HELP_TEXT, cancel_kb
from bot.handlers.edit import _list_kb as _edit_list_kb
from bot.handlers.meds import _root_kb as _meds_kb
from bot.handlers.menu import _menu_kb as _menu_menu_kb
from bot.handlers.menu import _render_week as _menu_week
from bot.handlers.schedule import _menu_kb as _schedule_kb
from bot.handlers.shopping import _root_kb as _shopping_kb
from bot.handlers.tasks import _menu_kb as _tasks_kb

router = Router()

HOME_TEXT = "🧑‍🎨 <b>Семейный ассистент</b>"


def _home_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📋 Задачи", callback_data="home:tasks"),
                InlineKeyboardButton(text="🗓 Расписание", callback_data="home:schedule"),
            ],
            [
                InlineKeyboardButton(text="🍽 Меню недели", callback_data="home:menu"),
                InlineKeyboardButton(text="🧹 Уборка", callback_data="home:cleaning"),
            ],
            [
                InlineKeyboardButton(text="💊 Лекарства и БАДы", callback_data="home:meds"),
                InlineKeyboardButton(text="🛒 Покупки", callback_data="home:shopping"),
            ],
            [InlineKeyboardButton(text="━━━ ⚙️ Настройка ━━━", callback_data="home:noop")],
            [InlineKeyboardButton(text="➕ Добавить задачу", callback_data="home:add")],
            [
                InlineKeyboardButton(text="🏠 Семейная база", callback_data="home:edit"),
                InlineKeyboardButton(text="❓ Справка", callback_data="home:help"),
            ],
        ]
    )


async def send_home(message: Message) -> None:
    await message.answer(HOME_TEXT, parse_mode="HTML", reply_markup=_home_kb())


async def broadcast_home(bot: Bot, telegram_ids: list[int]) -> None:
    """Отправляет свежий экран «Семейный ассистент» каждому пользователю.
    Вызывается при старте бота, чтобы экран всегда был последним сообщением.
    """
    for tid in telegram_ids:
        try:
            await bot.send_message(
                chat_id=tid,
                text=HOME_TEXT,
                parse_mode="HTML",
                reply_markup=_home_kb(),
            )
        except Exception as e:
            log.warning("startup home to %s failed: %s", tid, e)


@router.message(Command("home"))
async def cmd_home(message: Message) -> None:
    user = get_user_by_telegram_id(message.from_user.id)
    if not user:
        await message.answer("Сначала зарегистрируйся: /start")
        return
    await send_home(message)


@router.callback_query(F.data == "home:noop")
async def cb_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(F.data == "home:show")
async def cb_show(callback: CallbackQuery, state: FSMContext) -> None:
    """Возврат к главному меню из любого раздела."""
    await state.clear()
    await callback.answer()
    try:
        await callback.message.edit_text(HOME_TEXT, parse_mode="HTML", reply_markup=_home_kb())
    except Exception:
        await callback.message.answer(HOME_TEXT, parse_mode="HTML", reply_markup=_home_kb())


@router.callback_query(F.data == "home:tasks")
async def cb_tasks(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.answer("Что показать?", reply_markup=_tasks_kb())


@router.callback_query(F.data == "home:schedule")
async def cb_schedule(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.answer("Расписание дня. Что показать?", reply_markup=_schedule_kb())


@router.callback_query(F.data == "home:menu")
async def cb_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.answer(_menu_week(), parse_mode="HTML", reply_markup=_menu_menu_kb())


@router.callback_query(F.data == "home:cleaning")
async def cb_cleaning(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.answer(_cleaning_week(), parse_mode="HTML", reply_markup=_cleaning_kb())


@router.callback_query(F.data == "home:meds")
async def cb_meds(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.answer(
        "<b>💊 Лекарства и БАДы</b>\n\nКого открыть?",
        parse_mode="HTML",
        reply_markup=_meds_kb(),
    )


@router.callback_query(F.data == "home:shopping")
async def cb_shopping(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.answer(
        "<b>🛒 Покупки</b>\n\nЧей список открыть?",
        parse_mode="HTML",
        reply_markup=_shopping_kb(),
    )


@router.callback_query(F.data == "home:help")
async def cb_help(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.answer(HELP_TEXT, parse_mode="HTML")


@router.callback_query(F.data == "home:edit")
async def cb_edit(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    items = list_family_routine_events()
    items.sort(key=lambda x: x.get("time_local") or "")
    await callback.message.answer(
        "Семейная база. Выбери пункт для редактирования или добавь новый:",
        reply_markup=_edit_list_kb(items, with_add=True),
    )


@router.callback_query(F.data == "home:add")
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
