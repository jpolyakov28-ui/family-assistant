"""Регистрация пользователя через /start."""

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from bot.config import ALLOWED_TELEGRAM_IDS, DEFAULT_TZ
from bot.db import create_user, get_user_by_telegram_id
from bot.handlers.home import send_home

router = Router()


class Registration(StatesGroup):
    waiting_for_name = State()


@router.message(CommandStart())
async def handle_start(message: Message, state: FSMContext) -> None:
    tg_id = message.from_user.id
    if ALLOWED_TELEGRAM_IDS and tg_id not in ALLOWED_TELEGRAM_IDS:
        await message.answer(
            "Этот бот закрыт для семьи. Если вас должны были подключить — "
            f"перешлите этот код администратору: <code>{tg_id}</code>",
            parse_mode="HTML",
        )
        return

    user = get_user_by_telegram_id(tg_id)
    if user:
        await message.answer(f"Привет, {user['name']}! Я тебя помню.")
        await send_home(message)
        return

    await message.answer(
        "Привет! Я семейный ассистент.\n\n"
        "Как мне тебя называть? Напиши имя одним словом (например: Лёня, Мама, Полина)."
    )
    await state.set_state(Registration.waiting_for_name)


@router.message(Registration.waiting_for_name, F.text)
async def handle_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not name or len(name) > 40:
        await message.answer("Имя должно быть от 1 до 40 символов. Попробуй ещё раз.")
        return

    user = create_user(
        telegram_id=message.from_user.id,
        name=name,
        timezone=DEFAULT_TZ,
    )
    await state.clear()
    await message.answer(f"Готово, {user['name']}! Рад знакомству.")
    await send_home(message)
