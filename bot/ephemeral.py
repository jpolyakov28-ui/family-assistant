"""Самоочистка чата: сообщения бота и пользователя удаляются через час.

Напоминания (с кнопкой snooze) не трогаем — их легко пропустить.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.methods import SendMessage
from aiogram.types import InlineKeyboardMarkup, Message, TelegramObject

from bot.db import add_ephemeral_message, delete_ephemeral_records, list_expired_ephemeral

log = logging.getLogger(__name__)

TTL = timedelta(hours=1)


def _register(chat_id: int, message_id: int) -> None:
    try:
        add_ephemeral_message(chat_id, message_id)
    except Exception as e:  # запись в БД не должна ломать доставку сообщения
        log.warning("ephemeral register failed: %s", e)


def _is_reminder(method: SendMessage) -> bool:
    """Напоминание = сообщение с кнопкой snooze (callback snz:...)."""
    markup = getattr(method, "reply_markup", None)
    if not isinstance(markup, InlineKeyboardMarkup):
        return False
    for row in markup.inline_keyboard:
        for btn in row:
            if btn.callback_data and btn.callback_data.startswith("snz:"):
                return True
    return False


class TrackOutgoingMiddleware(BaseRequestMiddleware):
    """Регистрирует исходящие сообщения бота на авто-удаление."""

    async def __call__(self, make_request, bot, method):
        response = await make_request(bot, method)
        # response — уже распарсенный результат метода (для SendMessage это Message).
        try:
            if isinstance(method, SendMessage) and not _is_reminder(method):
                if isinstance(response, Message):
                    _register(response.chat.id, response.message_id)
        except Exception as e:
            log.warning("ephemeral outgoing hook failed: %s", e)
        return response


class TrackIncomingMiddleware(BaseMiddleware):
    """Регистрирует входящие сообщения пользователя на авто-удаление."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message):
            _register(event.chat.id, event.message_id)
        return await handler(event, data)


async def purge_expired(bot: Bot) -> None:
    """Удаляет из чата сообщения старше TTL. Вызывается планировщиком раз в минуту."""
    cutoff = datetime.now(timezone.utc) - TTL
    try:
        rows = list_expired_ephemeral(cutoff)
    except Exception as e:
        log.warning("ephemeral purge: list failed: %s", e)
        return

    done_ids: list[str] = []
    for row in rows:
        try:
            await bot.delete_message(row["chat_id"], row["message_id"])
        except Exception:
            # уже удалено вручную / старше 48ч — запись всё равно убираем
            pass
        done_ids.append(row["id"])

    if done_ids:
        try:
            delete_ephemeral_records(done_ids)
        except Exception as e:
            log.warning("ephemeral purge: cleanup failed: %s", e)


def setup_ephemeral(dp, bot: Bot) -> None:
    """Навешивает middleware на входящие апдейты и исходящие запросы."""
    bot.session.middleware(TrackOutgoingMiddleware())
    # outer_middleware — срабатывает для каждого сообщения до фильтрации
    # (inner middleware на dp.message не вызывается: хендлеры — в дочернем роутере).
    dp.message.outer_middleware(TrackIncomingMiddleware())
