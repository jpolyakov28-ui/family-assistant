import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")


def _require(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"Required env var {name} is missing. Check .env")
    return val


TELEGRAM_BOT_TOKEN = _require("TELEGRAM_BOT_TOKEN")
SUPABASE_URL = _require("SUPABASE_URL")
SUPABASE_SERVICE_KEY = _require("SUPABASE_SERVICE_KEY")

DEFAULT_TZ = os.environ.get("DEFAULT_TZ", "Europe/Moscow")

# Опциональный — если задан, бот понимает свободный текст через Claude.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip() or None

_allowed = os.environ.get("ALLOWED_TELEGRAM_IDS", "").strip()
ALLOWED_TELEGRAM_IDS: set[int] = (
    {int(x.strip()) for x in _allowed.split(",") if x.strip()}
    if _allowed
    else set()
)
