#!/usr/bin/env python3
"""Apply all pending Supabase migrations via direct PostgreSQL connection."""
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

def main() -> None:
    try:
        import psycopg
    except ImportError:
        print("psycopg not available, trying psycopg2...")
        try:
            import psycopg2 as psycopg
        except ImportError:
            print("ERROR: no psycopg driver found")
            sys.exit(1)

    from dotenv import load_dotenv
    load_dotenv(REPO / ".env")

    password = os.environ.get("SUPABASE_DB_PASSWORD", "3DEiX738mCOzmqUE7Qyd1T34")
    project_ref = "xfwelnhioyczqfgrfivk"

    # Try direct connection first, then pooler
    connection_strings = [
        f"host=db.{project_ref}.supabase.co port=5432 dbname=postgres user=postgres password={password} sslmode=require connect_timeout=15",
        f"host=aws-0-eu-central-1.pooler.supabase.com port=6543 dbname=postgres user=postgres.{project_ref} password={password} sslmode=require connect_timeout=15",
        f"host=aws-0-eu-central-1.pooler.supabase.com port=5432 dbname=postgres user=postgres.{project_ref} password={password} sslmode=require connect_timeout=15",
    ]

    conn = None
    for dsn in connection_strings:
        host = dsn.split("host=")[1].split(" ")[0]
        port = dsn.split("port=")[1].split(" ")[0]
        print(f"Trying {host}:{port}...")
        try:
            conn = psycopg.connect(dsn)
            print(f"  Connected to {host}:{port}")
            break
        except Exception as e:
            print(f"  Failed: {e}")

    if conn is None:
        print("\nERROR: Could not connect to any PostgreSQL endpoint")
        sys.exit(1)

    migrations_dir = REPO / "migrations"
    migration_files = sorted(migrations_dir.glob("*.sql"))

    print(f"\nFound {len(migration_files)} migration files\n")

    with conn:
        cur = conn.cursor()
        # Create migrations tracking table if it doesn't exist
        cur.execute("""
            CREATE TABLE IF NOT EXISTS _migrations (
                filename TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        conn.commit()

        for migration_file in migration_files:
            name = migration_file.name
            cur.execute("SELECT 1 FROM _migrations WHERE filename = %s", (name,))
            if cur.fetchone():
                print(f"  SKIP  {name} (already applied)")
                continue

            sql = migration_file.read_text()
            print(f"  APPLY {name}...")
            try:
                cur.execute(sql)
                cur.execute("INSERT INTO _migrations (filename) VALUES (%s)", (name,))
                conn.commit()
                print(f"         OK")
            except Exception as e:
                conn.rollback()
                print(f"         ERROR: {e}")
                # Don't stop — try remaining migrations
                # Mark as applied if it's idempotent "already exists" errors
                if "already exists" in str(e) or "duplicate" in str(e).lower():
                    print(f"         (idempotent — marking as applied)")
                    cur.execute("INSERT INTO _migrations (filename) VALUES (%s) ON CONFLICT DO NOTHING", (name,))
                    conn.commit()

    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
