"""Парсинг человеческих дат на русском: 'завтра 9:00', 'сегодня', 'пн 18:00'."""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

WEEKDAYS = {
    "пн": 0, "пон": 0, "понедельник": 0,
    "вт": 1, "вторник": 1,
    "ср": 2, "среда": 2,
    "чт": 3, "четверг": 3,
    "пт": 4, "пятница": 4,
    "сб": 5, "суббота": 5,
    "вс": 6, "воскресенье": 6,
}

_MONTHS_RU = {
    "январь": 1, "января": 1,
    "февраль": 2, "февраля": 2,
    "март": 3, "марта": 3,
    "апрель": 4, "апреля": 4,
    "май": 5, "мая": 5,
    "июнь": 6, "июня": 6,
    "июль": 7, "июля": 7,
    "август": 8, "августа": 8,
    "сентябрь": 9, "сентября": 9,
    "октябрь": 10, "октября": 10,
    "ноябрь": 11, "ноября": 11,
    "декабрь": 12, "декабря": 12,
}
_MONTHS_RE = "|".join(_MONTHS_RU.keys())


def parse_human_datetime(text: str, tz: str = "Europe/Moscow") -> datetime | None:
    """
    Распознаёт строки:
      - 'сегодня', 'сегодня 18:00'
      - 'завтра', 'завтра 9'
      - 'послезавтра 14:30'
      - 'пн 9:00', 'пятница 18'
      - '15.05', '15.05 9:00'
      - '15.05.2026 9:00'
      - '9:00' (на ближайшее время — сегодня или завтра)
    Возвращает aware datetime в указанной таймзоне или None.
    """
    if not text:
        return None
    s = text.strip().lower()
    tzinfo = ZoneInfo(tz)
    now = datetime.now(tzinfo)
    today = now.date()

    # Извлекаем время если есть
    t = _extract_time(s)

    # Дата
    d: date | None = None
    if "послезавтра" in s:
        d = today + timedelta(days=2)
    elif "завтра" in s:
        d = today + timedelta(days=1)
    elif "сегодня" in s:
        d = today
    else:
        # день недели?
        for word, weekday in WEEKDAYS.items():
            if re.search(rf"\b{word}\b", s):
                delta = (weekday - today.weekday()) % 7
                if delta == 0:
                    delta = 7  # ближайший такой день в будущем
                d = today + timedelta(days=delta)
                break

        # дата в формате «8 августа» или «8 августа 2026»
        # Год — только если за цифрами НЕ идёт двоеточие (иначе «10:00» читается как год 10)
        if d is None:
            m = re.search(rf"\b(\d{{1,2}})\s+({_MONTHS_RE})(?:\s+(\d{{2,4}})(?!:))?\b", s)
            if m:
                day = int(m.group(1))
                month = _MONTHS_RU[m.group(2)]
                year = int(m.group(3)) if m.group(3) else today.year
                if year < 100:
                    year += 2000
                try:
                    d = date(year, month, day)
                    if d < today and not m.group(3):
                        d = date(year + 1, month, day)
                except ValueError:
                    return None

        # дата в формате 15.05[.2026]
        if d is None:
            m = re.search(r"\b(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?\b", s)
            if m:
                day, month = int(m.group(1)), int(m.group(2))
                year = int(m.group(3)) if m.group(3) else today.year
                if year < 100:
                    year += 2000
                try:
                    d = date(year, month, day)
                    if d < today and not m.group(3):
                        d = date(year + 1, month, day)
                except ValueError:
                    return None

    if d is None and t is None:
        return None

    # Если только время — выбираем сегодня или завтра
    if d is None and t is not None:
        candidate = datetime.combine(today, t, tzinfo=tzinfo)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate

    if d is not None:
        if t is None:
            t = time(9, 0)  # дефолтное время — 9 утра
        return datetime.combine(d, t, tzinfo=tzinfo)

    return None


def _extract_time(s: str) -> time | None:
    # HH:MM
    m = re.search(r"\b(\d{1,2}):(\d{2})\b", s)
    if m:
        hh, mm = int(m.group(1)), int(m.group(2))
        if 0 <= hh < 24 and 0 <= mm < 60:
            return time(hh, mm)
    # просто HH (если в строке есть слово "час" или "в" перед, или это самостоятельно)
    m = re.search(r"\bв\s*(\d{1,2})(?!\.)\b", s)
    if m:
        hh = int(m.group(1))
        if 0 <= hh < 24:
            return time(hh, 0)
    return None


def format_human(dt: datetime, tz: str = "Europe/Moscow") -> str:
    """Красиво форматирует дату/время для отображения в сообщении."""
    tzinfo = ZoneInfo(tz)
    local = dt.astimezone(tzinfo)
    today = datetime.now(tzinfo).date()
    delta_days = (local.date() - today).days
    if delta_days == 0:
        prefix = "сегодня"
    elif delta_days == 1:
        prefix = "завтра"
    elif delta_days == -1:
        prefix = "вчера"
    elif 2 <= delta_days <= 6:
        weekdays_short = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
        prefix = weekdays_short[local.weekday()]
    else:
        prefix = local.strftime("%d.%m")
    return f"{prefix} {local.strftime('%H:%M')}"
