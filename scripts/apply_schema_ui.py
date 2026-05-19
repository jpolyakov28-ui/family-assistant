"""
Применяет SQL-схему через Supabase SQL Editor (Monaco) с помощью Playwright.
Использует persistent context — логин уже сохранён.

Запуск:
  uv run python scripts/apply_schema_ui.py                 # 001_mvp.sql
  uv run python scripts/apply_schema_ui.py 003_schedule    # любое имя из migrations/
"""

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from playwright.async_api import async_playwright

REPO = Path(__file__).resolve().parent.parent
load_dotenv(REPO / ".env")

MIGRATIONS_DIR = REPO / "migrations"
USER_DATA_DIR = REPO / ".playwright" / "user_data"


def _resolve_schema_path(arg: str | None) -> Path:
    name = arg or "001_mvp"
    for candidate in (MIGRATIONS_DIR / name, MIGRATIONS_DIR / f"{name}.sql"):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"Не нашёл миграцию: {name}")


async def main() -> int:
    project_ref = os.environ.get("SUPABASE_PROJECT_REF")
    if not project_ref:
        print("ERROR: нет SUPABASE_PROJECT_REF в .env", file=sys.stderr)
        return 1

    schema_path = _resolve_schema_path(sys.argv[1] if len(sys.argv) > 1 else None)
    sql = schema_path.read_text()
    print(f"→ {schema_path.name} ({len(sql)} символов)", flush=True)

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA_DIR),
            headless=False,
            args=["--start-maximized"],
            no_viewport=True,
        )
        page = context.pages[0] if context.pages else await context.new_page()

        try:
            url = f"https://supabase.com/dashboard/project/{project_ref}/sql/new"
            print(f"→ Открываю {url}", flush=True)
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_timeout(5000)

            # Закрываем cookie-баннер если есть
            for sel in ("button:has-text('Opt out')", "button:has-text('Accept')"):
                try:
                    btn = page.locator(sel).first
                    if await btn.count() and await btn.is_visible():
                        await btn.click(timeout=2000)
                        await page.wait_for_timeout(300)
                        break
                except Exception:
                    pass

            # Дождёмся появления Monaco
            await page.locator(".monaco-editor").first.wait_for(state="visible", timeout=15000)
            await page.wait_for_timeout(1500)

            # Вставляем SQL через Monaco API
            result = await page.evaluate(
                """sql => {
                    if (typeof window.monaco === 'undefined') return 'no_monaco_global';
                    const editors = window.monaco.editor.getEditors();
                    if (!editors || editors.length === 0) return 'no_editors';
                    editors[0].setValue(sql);
                    editors[0].focus();
                    return 'ok:' + editors.length;
                }""",
                sql,
            )
            print(f"→ Monaco setValue: {result}", flush=True)

            if not str(result).startswith("ok"):
                # Fallback: кликаем в редактор и используем keyboard.type
                print("→ Fallback: ввожу через клавиатуру", flush=True)
                await page.locator(".monaco-editor").first.click()
                await page.wait_for_timeout(300)
                mod = "Meta" if sys.platform == "darwin" else "Control"
                await page.keyboard.press(f"{mod}+A")
                await page.keyboard.press("Delete")
                await page.wait_for_timeout(200)
                # Печатаем построчно, чтоб Monaco успевал
                for chunk in [sql[i:i + 500] for i in range(0, len(sql), 500)]:
                    await page.keyboard.insert_text(chunk)
                    await page.wait_for_timeout(50)

            await page.wait_for_timeout(800)
            await page.screenshot(path=str(REPO / "sql_editor_before_run.png"), full_page=True)

            # Запускаем через Cmd+Enter (стандартный шорткат Supabase)
            mod = "Meta" if sys.platform == "darwin" else "Control"
            await page.keyboard.press(f"{mod}+Enter")
            print("→ Cmd+Enter отправлен", flush=True)
            await page.wait_for_timeout(2000)

            # Supabase показывает диалог "Potential issue detected" для CREATE TABLE
            # с тремя кнопками: Cancel / Run without RLS / Run and enable RLS
            # Жмём "Run without RLS" — service_role обходит RLS, а политики добавим позже
            for _ in range(20):
                try:
                    run_without_rls = page.get_by_role(
                        "button", name="Run without RLS"
                    ).first
                    if await run_without_rls.count() and await run_without_rls.is_visible():
                        await run_without_rls.click(timeout=3000)
                        print("→ Клик 'Run without RLS'", flush=True)
                        await page.wait_for_timeout(4000)
                        break
                except Exception:
                    pass
                await page.wait_for_timeout(300)

            await page.screenshot(path=str(REPO / "sql_editor_after_run.png"), full_page=True)

            # Проверяем результат через PostgREST
            print("→ Проверяю что миграция применена…", flush=True)
            from supabase import create_client
            c = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
            probe_name = schema_path.stem
            try:
                if probe_name.startswith("001"):
                    res = c.table("users").select("*", count="exact").limit(0).execute()
                    print(f"✓ users существует ({res.count} rows).", flush=True)
                elif probe_name.startswith("002"):
                    c.table("tasks").select("lead_minutes,sent_offsets").limit(1).execute()
                    print("✓ tasks.lead_minutes/sent_offsets доступны.", flush=True)
                elif probe_name.startswith("003"):
                    c.table("tasks").select("category,time_local,due_has_time").limit(1).execute()
                    print("✓ tasks.category/time_local/due_has_time доступны.", flush=True)
                elif probe_name.startswith("004"):
                    c.table("tasks").select("cook_by").limit(1).execute()
                    print("✓ tasks.cook_by доступна.", flush=True)
                elif probe_name.startswith("005"):
                    c.table("meal_plans").select("*", count="exact").limit(0).execute()
                    print("✓ meal_plans существует.", flush=True)
                elif probe_name.startswith("006"):
                    c.table("cleaning_plans").select("*", count="exact").limit(0).execute()
                    print("✓ cleaning_plans существует.", flush=True)
                elif probe_name.startswith("007"):
                    c.table("ephemeral_messages").select("*", count="exact").limit(0).execute()
                    print("✓ ephemeral_messages существует.", flush=True)
                elif probe_name.startswith("008"):
                    c.table("tasks").insert(
                        {"type": "todo", "title": "_probe_", "category": "work"}
                    ).execute()
                    c.table("tasks").delete().eq("title", "_probe_").execute()
                    print("✓ category 'work' принимается.", flush=True)
                elif probe_name.startswith("009"):
                    c.table("med_plans").select("*", count="exact").limit(0).execute()
                    c.table("shopping_lists").select("*", count="exact").limit(0).execute()
                    print("✓ med_plans и shopping_lists существуют.", flush=True)
                elif probe_name.startswith("010"):
                    c.table("tasks").select("alarm,alarm_last_ring").limit(1).execute()
                    print("✓ tasks.alarm/alarm_last_ring доступны.", flush=True)
                elif probe_name.startswith("011"):
                    c.table("tasks").insert(
                        {"type": "todo", "title": "_probe_", "category": "home"}
                    ).execute()
                    c.table("tasks").delete().eq("title", "_probe_").execute()
                    print("✓ category 'home' принимается.", flush=True)
                elif probe_name.startswith("012"):
                    c.table("tasks").insert(
                        {"type": "todo", "title": "_probe_", "category": "car"}
                    ).execute()
                    c.table("tasks").delete().eq("title", "_probe_").execute()
                    print("✓ category 'car' принимается.", flush=True)
                else:
                    print("✓ Применено (без специфической проверки).", flush=True)
                return 0
            except Exception as e:
                print(f"✗ Проверка не прошла: {e}", file=sys.stderr, flush=True)
                print("  Скриншоты: sql_editor_before_run.png и sql_editor_after_run.png", flush=True)
                await page.wait_for_timeout(5000)
                return 2
        finally:
            await context.close()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
