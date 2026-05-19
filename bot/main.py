"""Точка входа: запуск бота + планировщика."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, ErrorEvent

from bot.config import TELEGRAM_BOT_TOKEN
from bot.ephemeral import setup_ephemeral
from bot.handlers import router
from bot.scheduler import start_scheduler

BOT_COMMANDS = [
    BotCommand(command="tasks", description="Задачи"),
    BotCommand(command="schedule", description="Расписание дня"),
    BotCommand(command="menu", description="Меню на неделю"),
    BotCommand(command="cleaning", description="Гениальная уборка"),
    BotCommand(command="meds", description="Лекарства и БАДы"),
    BotCommand(command="shopping", description="Покупки"),
    BotCommand(command="add", description="⚙️ Добавить задачу"),
    BotCommand(command="edit_routine", description="⚙️ Редактировать семейную базу"),
    BotCommand(command="help", description="⚙️ Справка"),
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)


async def main() -> None:
    bot = Bot(
        token=TELEGRAM_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    @dp.error()
    async def on_error(event: ErrorEvent) -> None:
        """Любая необработанная ошибка хендлера — лог + понятный ответ пользователю."""
        log.exception("Unhandled handler error", exc_info=event.exception)
        update = event.update
        chat_id = None
        if update.callback_query:
            # Отвечаем на callback немедленно — иначе Telegram покажет «что-то пошло не так»
            try:
                await update.callback_query.answer()
            except Exception:
                pass
            if update.callback_query.message:
                chat_id = update.callback_query.message.chat.id
        elif update.message:
            chat_id = update.message.chat.id
        if chat_id:
            try:
                await bot.send_message(
                    chat_id,
                    "⚠️ Что-то пошло не так. Попробуй ещё раз через пару секунд.",
                )
            except Exception:
                pass

    setup_ephemeral(dp, bot)

    scheduler = start_scheduler(bot)
    try:
        await bot.set_my_commands(BOT_COMMANDS)
        log.info("Bot starting…")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
