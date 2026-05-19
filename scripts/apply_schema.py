"""
Применяет SQL-схему к Supabase напрямую через psycopg.
Использует креды из .env: SUPABASE_PROJECT_REF и SUPABASE_DB_PASSWORD.

Запуск:
  uv run python scripts/apply_schema.py                 # 001_mvp.sql (дефолт)
  uv run python scripts/apply_schema.py 003_schedule    # любое имя из migrations/
"""

import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

REPO = Path(__file__).resolve().parent.parent
load_dotenv(REPO / ".env")

MIGRATIONS_DIR = REPO / "migrations"


def _resolve_schema_path(arg: str | None) -> Path:
    name = arg or "001_mvp"
    candidate = MIGRATIONS_DIR / name
    if candidate.is_file():
        return candidate
    with_ext = MIGRATIONS_DIR / f"{name}.sql"
    if with_ext.is_file():
        return with_ext
    raise FileNotFoundError(
        f"Не нашёл миграцию: пробовал {candidate} и {with_ext}"
    )


def main() -> int:
    schema_path = _resolve_schema_path(sys.argv[1] if len(sys.argv) > 1 else None)
    project_ref = os.environ.get("SUPABASE_PROJECT_REF")
    db_password = os.environ.get("SUPABASE_DB_PASSWORD")
    if not project_ref or not db_password:
        print("ERROR: нужны SUPABASE_PROJECT_REF и SUPABASE_DB_PASSWORD в .env", file=sys.stderr)
        return 1

    # Supabase pooler (читает с любой регион)
    # Прямой хост: db.{ref}.supabase.co:5432
    # Pooler:      aws-0-{region}.pooler.supabase.com:6543 — но регион нужно знать
    # Будем пробовать оба, начиная с прямого
    candidates = [
        {
            "host": f"db.{project_ref}.supabase.co",
            "port": 5432,
            "user": "postgres",
            "dbname": "postgres",
            "password": db_password,
            "sslmode": "require",
        },
        {
            "host": "aws-0-eu-central-1.pooler.supabase.com",
            "port": 6543,
            "user": f"postgres.{project_ref}",
            "dbname": "postgres",
            "password": db_password,
            "sslmode": "require",
        },
        {
            "host": "aws-0-eu-central-1.pooler.supabase.com",
            "port": 5432,
            "user": f"postgres.{project_ref}",
            "dbname": "postgres",
            "password": db_password,
            "sslmode": "require",
        },
    ]

    sql = schema_path.read_text()
    print(f"→ Применяю {schema_path.name} ({len(sql)} символов)…")

    last_err: Exception | None = None
    for conn_kwargs in candidates:
        print(f"  → Пробую {conn_kwargs['host']}:{conn_kwargs['port']}", flush=True)
        try:
            with psycopg.connect(**conn_kwargs, connect_timeout=10) as conn:
                with conn.cursor() as cur:
                    cur.execute(sql)
                conn.commit()
            print(f"✓ Схема применена через {conn_kwargs['host']}", flush=True)
            return 0
        except Exception as e:
            last_err = e
            print(f"  ⚠ {e}", flush=True)
            continue

    print(f"\n✗ Все попытки подключения провалились. Последняя ошибка:\n{last_err}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
