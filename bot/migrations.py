"""Auto-apply SQL migrations on bot startup via direct PostgreSQL connection."""
from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def _build_dsns(project_ref: str, password: str) -> list[str]:
    """Return candidate DSNs to try in order."""
    pooler_user = f"dbname=postgres user=postgres.{project_ref} password={password} sslmode=require connect_timeout=15"
    # eu-west-1 port 6543 is the confirmed working endpoint for this project
    primary = f"host=aws-0-eu-west-1.pooler.supabase.com port=6543 {pooler_user}"
    fallback_regions = ["eu-central-1", "us-east-1", "eu-west-2", "us-east-2"]
    fallbacks = [
        f"host=aws-0-{r}.pooler.supabase.com port=6543 {pooler_user}"
        for r in fallback_regions
    ]
    return [primary] + fallbacks


def apply_migrations() -> None:
    """Run all pending migrations. Idempotent — tracks applied files in _migrations table."""
    project_ref = os.environ.get("SUPABASE_PROJECT_REF", "")
    password = os.environ.get("SUPABASE_DB_PASSWORD", "")
    if not project_ref or not password:
        log.warning("SUPABASE_PROJECT_REF or SUPABASE_DB_PASSWORD not set — skipping migrations")
        return

    try:
        import psycopg
    except ImportError:
        log.warning("psycopg not installed — skipping migrations")
        return

    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not migration_files:
        log.info("No migration files found in %s", MIGRATIONS_DIR)
        return

    conn = None
    for dsn in _build_dsns(project_ref, password):
        host = dsn.split("host=")[1].split(" ")[0]
        try:
            # prepare_threshold=None disables prepared statements — required for PgBouncer transaction mode
            conn = psycopg.connect(dsn, prepare_threshold=None)
            log.info("Migrations: connected to %s", host)
            break
        except Exception as exc:
            log.warning("Migrations: %s failed: %s", host, str(exc).split("\n")[0][:200])

    if conn is None:
        log.error("Migrations: could not connect to any PostgreSQL endpoint — skipping")
        return

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS _migrations (
                        filename TEXT PRIMARY KEY,
                        applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)
            conn.commit()

            for mf in migration_files:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1 FROM _migrations WHERE filename = %s", (mf.name,))
                    if cur.fetchone():
                        log.debug("Migrations: %s already applied", mf.name)
                        continue

                sql = mf.read_text()
                log.info("Migrations: applying %s …", mf.name)
                try:
                    with conn.cursor() as cur:
                        cur.execute(sql)
                        cur.execute(
                            "INSERT INTO _migrations (filename) VALUES (%s) ON CONFLICT DO NOTHING",
                            (mf.name,),
                        )
                    conn.commit()
                    log.info("Migrations: %s OK", mf.name)
                except Exception as exc:
                    conn.rollback()
                    log.error("Migrations: %s FAILED: %s", mf.name, exc)
    finally:
        conn.close()
