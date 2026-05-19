"""Свободный текст: «купи молоко завтра в 12, напомни за час» → задача через Claude."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.types import Message

from bot import nlp
from bot.datetime_utils import format_human
from bot.db import create_task, get_user_by_telegram_id

router = Router()


@router.message(StateFilter(None), F.text & ~F.text.startswith("/"))
async def handle_freetext(message: Message) -> None:
    user = get_user_by_telegram_id(message.from_user.id)
    if not user:
        await message.answer("Сначала зарегистрируйся: /start")
        return

    if not nlp.is_available():
        await message.answer(
            "Свободный текст пока не понимаю.\n"
            "Используй /add для пошагового добавления."
        )
        return

    text = (message.text or "").strip()
    if not text:
        return

    parsed = nlp.parse_freetext(text, tz=user["timezone"])
    if not parsed or not parsed.title:
        await message.answer(
            "Не понял. Попробуй так:\n"
            "• «купи молоко завтра в 12»\n"
            "• «позвонить маме в пятницу вечером, напомни за час»\n"
            "• «забрать посылку 15.05, общая»\n\n"
            "Или используй /add для пошагового мастера."
        )
        return

    assignee_ids = [user["id"]] if parsed.visibility == "private" else []
    task_type = "reminder" if parsed.due_at else "todo"

    create_task(
        task_type=task_type,
        title=parsed.title,
        created_by=user["id"],
        visibility=parsed.visibility,
        due_at=parsed.due_at,
        assignee_user_ids=assignee_ids,
        lead_minutes=parsed.lead_minutes,
    )

    when = format_human(parsed.due_at, user["timezone"]) if parsed.due_at else "без срока"
    vis_label = "🔒 только тебе" if parsed.visibility == "private" else "👨‍👩‍👧‍👦 всей семье"
    lead_label = _lead_summary(parsed.lead_minutes)

    await message.answer(
        f"✓ Сохранено: <b>{parsed.title}</b>\n"
        f"   {vis_label} • {when}{lead_label}",
        parse_mode="HTML",
    )


def _lead_summary(lead_minutes: list[int]) -> str:
    extra = [m for m in lead_minutes if m > 0]
    if not extra:
        return ""
    parts = []
    for m in extra:
        if m % 1440 == 0:
            d = m // 1440
            parts.append(f"за {d} дн" if d > 1 else "за день")
        elif m % 60 == 0:
            parts.append(f"за {m // 60} ч")
        else:
            parts.append(f"за {m} мин")
    return f" • 🔔 {', '.join(parts)}"
