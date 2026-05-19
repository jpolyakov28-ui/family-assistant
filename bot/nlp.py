"""Понимание свободного текста через Claude Haiku.

Принимает фразу вроде «купи молоко завтра в 12, напомни за час»,
возвращает структуру: title, due_at, lead_minutes, visibility.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from anthropic import Anthropic

from bot.config import ANTHROPIC_API_KEY

log = logging.getLogger(__name__)

_client: Anthropic | None = None


def is_available() -> bool:
    return ANTHROPIC_API_KEY is not None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


@dataclass
class ParsedTask:
    title: str
    due_at: datetime | None  # aware, в таймзоне пользователя
    lead_minutes: list[int]  # минуты ДО due_at: [60, 0] = за час и в момент
    visibility: str  # "private" | "family"


SYSTEM_PROMPT = """Ты помощник, который превращает фразу пользователя на русском языке в структуру задачи для семейного бота-напоминалки.

Извлеки из фразы:

1. **title** — краткая суть дела БЕЗ даты, времени и слов о напоминании. Сохрани форму как у пользователя (повелительная — оставь повелительной, существительное — существительным). Первая буква заглавная. Без точки в конце.

2. **due_at** — момент, когда задачу нужно сделать, в формате ISO 8601 с таймзоной. Если пользователь не указал срок — null.
   - «завтра 12», «завтра в 12:00» → завтра 12:00 по локальной таймзоне
   - «через 30 минут» → текущее время + 30 мин
   - «в пятницу», «в пт» → ближайшая будущая пятница, дефолтное время 09:00
   - «15 мая», «15.05» → ближайшее будущее 15 мая, дефолтное время 09:00
   - «в 18:00» (без даты) → ближайшее 18:00 (сегодня если ещё не прошло, иначе завтра)
   - «утром» = 09:00, «днём» = 13:00, «вечером» = 19:00, «ночью» = 22:00
   - Если время не указано вообще, но указана дата — ставь 09:00.

3. **lead_minutes** — за сколько минут ДО due_at прислать предварительные напоминания. Это список чисел.
   - Если due_at = null → пустой список [].
   - Если есть due_at и пользователь НЕ просил напомнить заранее → [0] (только в момент).
   - «напомни за час» → [60, 0]
   - «за 15 минут до» → [15, 0]
   - «за день и за час» → [1440, 60, 0]
   - Всегда добавляй 0 в конец, если due_at != null, кроме случая когда пользователь явно сказал «не напоминай в момент» или «только заранее».

4. **visibility** — кому видна задача:
   - "family" — если в фразе есть «всем», «семье», «общая», «общее», «для всех»
   - "private" — во всех остальных случаях (по умолчанию)

Если фразу совсем не получается разобрать как задачу (например, это вопрос, приветствие, бессмыслица), верни title="" — бот покажет пользователю подсказку.

Отвечай СТРОГО валидным JSON, без markdown-обёрток, без комментариев."""


_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "due_at": {"type": ["string", "null"]},
        "lead_minutes": {
            "type": "array",
            "items": {"type": "integer", "minimum": 0},
        },
        "visibility": {"type": "string", "enum": ["private", "family"]},
    },
    "required": ["title", "due_at", "lead_minutes", "visibility"],
    "additionalProperties": False,
}


def parse_freetext(text: str, tz: str = "Europe/Moscow") -> ParsedTask | None:
    """Возвращает ParsedTask или None если LLM не отвечает / не распарсил."""
    if not is_available():
        return None

    tzinfo = ZoneInfo(tz)
    now_local = datetime.now(tzinfo)
    weekdays_ru = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
    user_context = (
        f"Текущее время пользователя: {now_local.isoformat()} "
        f"({weekdays_ru[now_local.weekday()]}).\n"
        f"Таймзона: {tz}.\n\n"
        f"Фраза пользователя: {text}"
    )

    try:
        resp = _get_client().messages.create(
            model="claude-haiku-4-5",
            max_tokens=512,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_context}],
            output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
        )
    except Exception as e:
        log.warning("NLP call failed: %s", e)
        return None

    raw = next((b.text for b in resp.content if b.type == "text"), None)
    if not raw:
        return None

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("NLP returned non-JSON: %r", raw)
        return None

    title = (data.get("title") or "").strip()
    if not title:
        return None

    due_raw = data.get("due_at")
    due_at: datetime | None = None
    if due_raw:
        try:
            due_at = datetime.fromisoformat(due_raw)
            if due_at.tzinfo is None:
                due_at = due_at.replace(tzinfo=tzinfo)
        except ValueError:
            log.warning("NLP returned bad due_at: %r", due_raw)

    lead = data.get("lead_minutes") or []
    lead = sorted({int(x) for x in lead if isinstance(x, int) and x >= 0}, reverse=True)
    if due_at is None:
        lead = []
    elif not lead:
        lead = [0]

    visibility = data.get("visibility") or "private"
    if visibility not in {"private", "family"}:
        visibility = "private"

    return ParsedTask(title=title[:200], due_at=due_at, lead_minutes=lead, visibility=visibility)
