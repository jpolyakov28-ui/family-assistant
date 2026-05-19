"""Общие команды — help, cancel — и общий виджет отмены пошагового ввода."""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

HOME_BUTTON = InlineKeyboardButton(text="⬅️ Семейный ассистент", callback_data="home:show")

router = Router()

CANCEL_CB = "cancel:fsm"


def cancel_button() -> InlineKeyboardButton:
    """Кнопка отмены пошагового ввода — добавляется в клавиатуры FSM-шагов."""
    return InlineKeyboardButton(text="✖️ Отмена", callback_data=CANCEL_CB)


def cancel_kb() -> InlineKeyboardMarkup:
    """Клавиатура с кнопками отмены и возврата домой — для текстовых шагов ввода."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [cancel_button()],
        [HOME_BUTTON],
    ])


def with_cancel(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    """Собрать клавиатуру и дописать строку с кнопкой отмены."""
    return InlineKeyboardMarkup(inline_keyboard=[*rows, [cancel_button()]])


@router.callback_query(F.data == CANCEL_CB)
async def cb_cancel_fsm(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer("Отменено")
    try:
        await callback.message.edit_text("✖️ Отменено.")
    except Exception:
        await callback.message.answer("✖️ Отменено.")


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    if current is None:
        await message.answer("Ничего не отменяю — нет активной операции.")
        return
    await state.clear()
    await message.answer("Отменил.")


HELP_TEXT = (
    "<b>Семейный ассистент</b>\n\n"
    "• /home — главное меню\n"
    "• /tasks — задачи (сегодня / семейные / неделя / месяц / год)\n"
    "• /schedule — расписание дня\n"
    "• /menu — продуктовое меню на неделю\n"
    "• /cleaning — гениальная уборка по дням\n"
    "• /meds — лекарства и БАДы\n"
    "• /shopping — списки покупок\n"
    "• /add — добавить задачу или пункт расписания\n"
    "• /edit_routine — редактировать семейную базу\n\n"
    "<i>Во время пошагового ввода жми «✖️ Отмена», чтобы прервать.</i>"
)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT, parse_mode="HTML")
