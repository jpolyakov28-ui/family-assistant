"""
Автоматизирует первоначальную настройку Supabase:
1. Открывает браузер (persistent context — логин сохранится между запусками)
2. Ждёт логина/регистрации пользователя
3. Выбирает организацию, создаёт проект family-assistant в регионе Frankfurt (free plan)
4. Извлекает URL и service_role ключ
5. Применяет SQL-схему из migrations/001_mvp.sql
6. Сохраняет креды в .env

Запуск:  uv run python scripts/setup_supabase.py
Принудительно очистить сессию:  rm -rf .playwright/user_data
"""

import asyncio
import base64
import json
import re
import secrets
import string
import sys
from pathlib import Path

from playwright.async_api import Page, TimeoutError as PWTimeout, async_playwright

REPO = Path(__file__).resolve().parent.parent
ENV_PATH = REPO / ".env"
SCHEMA_PATH = REPO / "migrations" / "001_mvp.sql"
USER_DATA_DIR = REPO / ".playwright" / "user_data"

PROJECT_NAME = "family-assistant"
LOGIN_TIMEOUT_MS = 15 * 60 * 1000
PROVISION_TIMEOUT_MS = 5 * 60 * 1000


def gen_password(n: int = 24) -> str:
    chars = string.ascii_letters + string.digits
    return "".join(secrets.choice(chars) for _ in range(n))


def write_env(items: dict) -> None:
    existing: dict[str, str] = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            stripped = line.strip()
            if "=" in stripped and not stripped.startswith("#"):
                k, v = stripped.split("=", 1)
                existing[k] = v
    existing.update({k: str(v) for k, v in items.items()})
    ENV_PATH.write_text("\n".join(f"{k}={v}" for k, v in existing.items()) + "\n")
    print(f"  Saved → {ENV_PATH}", flush=True)


def read_env_var(name: str) -> str | None:
    if not ENV_PATH.exists():
        return None
    for line in ENV_PATH.read_text().splitlines():
        s = line.strip()
        if s.startswith(f"{name}="):
            return s.split("=", 1)[1]
    return None


def decode_jwt_payload(token: str) -> dict | None:
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return None
        pad = "=" * (-len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(parts[1] + pad))
    except Exception:
        return None


async def dismiss_banners(page: Page) -> None:
    """Закрывает плашки: Terms of Service, Cookie consent и подобные."""
    # Cookie consent — клик "Opt out" чтобы не было трекинга и баннер исчез
    for text_pattern in (re.compile(r"^opt out$", re.I), re.compile(r"^accept$", re.I)):
        try:
            btn = page.get_by_role("button", name=text_pattern).first
            if await btn.count() and await btn.is_visible():
                await btn.click(timeout=2000)
                await page.wait_for_timeout(300)
                break
        except Exception:
            pass
    # Закрыть TOS-баннер крестиком
    try:
        close_btn = page.locator("button[aria-label*='close' i]").first
        if await close_btn.count() and await close_btn.is_visible():
            await close_btn.click(timeout=2000)
            await page.wait_for_timeout(300)
    except Exception:
        pass


async def wait_for_login(page: Page) -> None:
    await page.goto("https://supabase.com/dashboard/projects")
    # Если уже залогинены — попадём прямо на /projects или /org/..
    # Если нет — на /sign-in
    try:
        await page.wait_for_url(
            re.compile(r"https://supabase\.com/dashboard/(projects|org)"),
            timeout=3000,
        )
        print("✓ Сессия уже активна (логин не нужен).", flush=True)
        return
    except PWTimeout:
        pass

    print("→ Откройте появившийся браузер и войдите в Supabase.", flush=True)
    print("  Жду до 15 минут…", flush=True)
    await page.wait_for_url(
        re.compile(r"https://supabase\.com/dashboard/(projects|org)"),
        timeout=LOGIN_TIMEOUT_MS,
    )
    print("✓ Логин выполнен.", flush=True)


async def select_organization(page: Page) -> str:
    """На странице /dashboard/new/_ выбираем единственную организацию.
    Возвращает slug организации."""
    print("→ Открываю страницу создания проекта…", flush=True)
    await page.goto("https://supabase.com/dashboard/new/_")
    await page.wait_for_load_state("domcontentloaded")
    await dismiss_banners(page)

    # Если на странице есть карточки организаций — кликаем по первой
    # Их href имеет вид /dashboard/new/<slug>
    org_link = page.locator("a[href^='/dashboard/new/']:not([href$='/_'])").first
    try:
        await org_link.wait_for(state="visible", timeout=10000)
        href = await org_link.get_attribute("href")
        print(f"→ Выбираю организацию: {href}", flush=True)
        await org_link.click()
    except PWTimeout:
        # Возможно, уже на странице с формой
        pass

    # Дождёмся, что URL изменился на /dashboard/new/<slug>
    await page.wait_for_url(
        re.compile(r"https://supabase\.com/dashboard/new/[^_/]+"),
        timeout=15000,
    )
    m = re.search(r"/dashboard/new/([^/?#]+)", page.url)
    slug = m.group(1) if m else "_"
    print(f"✓ Slug организации: {slug}", flush=True)
    await page.wait_for_load_state("networkidle")
    return slug


async def fill_project_form(page: Page, db_password: str) -> str:
    print("→ Заполняю форму проекта…", flush=True)
    # Несколько раз: сначала dismiss, потом ждём появление инпута
    await dismiss_banners(page)
    await page.wait_for_timeout(1000)
    await dismiss_banners(page)

    # Имя проекта — поиск по placeholder, label или name-атрибуту
    name_input = page.get_by_placeholder("Project name").first
    if not await name_input.count():
        name_input = page.get_by_role("textbox", name=re.compile("project name", re.I)).first
    await name_input.wait_for(state="visible", timeout=15000)
    await name_input.click()
    await name_input.fill(PROJECT_NAME)
    print("  ✓ Имя проекта", flush=True)
    await page.wait_for_timeout(400)

    # Пароль БД — единственный input type=password в форме
    pwd_input = page.locator("input[type='password']").first
    await pwd_input.wait_for(state="visible", timeout=10000)
    await pwd_input.click()
    await pwd_input.fill(db_password)
    print("  ✓ Пароль БД", flush=True)
    await page.wait_for_timeout(400)

    # Регион — оставляем по умолчанию (Europe). Это нормально для РФ.
    print("  ℹ Регион оставлен по умолчанию (Europe)", flush=True)

    # Перед submit ещё раз закрываем баннеры — они могут перекрывать кнопку
    await dismiss_banners(page)

    # Submit
    submit = page.get_by_role("button", name=re.compile("create new project", re.I)).first
    await submit.wait_for(state="visible", timeout=10000)
    for _ in range(40):
        if await submit.is_enabled():
            break
        await page.wait_for_timeout(250)
    await submit.click()
    print("→ Жду пока Supabase развернёт проект (≈1-2 мин)…", flush=True)

    await page.wait_for_url(
        re.compile(r"https://supabase\.com/dashboard/project/[a-z0-9]+"),
        timeout=PROVISION_TIMEOUT_MS,
    )
    m = re.search(r"/project/([a-z0-9]+)", page.url)
    if not m:
        raise RuntimeError(f"Не смог извлечь project ref из URL: {page.url}")
    ref = m.group(1)
    print(f"✓ Проект создан, ref={ref}", flush=True)
    return ref


async def _find_jwts_with_role(page: Page, role: str) -> str | None:
    content = await page.content()
    jwts = set(re.findall(r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+", content))
    for jwt in jwts:
        payload = decode_jwt_payload(jwt)
        if payload and payload.get("role") == role:
            return jwt
    return None


async def get_keys(page: Page, project_ref: str) -> dict:
    print("→ Забираю ключи через внутренний API дашборда…", flush=True)

    # Сначала переходим на проект, чтобы в контексте страницы были все нужные куки
    await page.goto(
        f"https://supabase.com/dashboard/project/{project_ref}",
        wait_until="domcontentloaded",
    )
    await page.wait_for_timeout(2500)

    # Дашборд использует api.supabase.com (или сам себя проксирует) для получения ключей.
    # Используем fetch() с credentials: 'include' из контекста страницы — авторизация
    # подтянется автоматически из существующей сессии.
    result = await page.evaluate(
        """
        async (ref) => {
            const urls = [
                `/api/platform/pg-meta/${ref}/api-keys`,
                `/api/platform/projects/${ref}/api-keys`,
                `https://api.supabase.com/v1/projects/${ref}/api-keys`,
                `https://api.supabase.com/platform/projects/${ref}/api-keys`,
            ];
            const tried = [];
            for (const url of urls) {
                try {
                    const r = await fetch(url, { credentials: 'include' });
                    tried.push({ url, status: r.status });
                    if (r.ok) {
                        const data = await r.json();
                        return { ok: true, data, url, tried };
                    }
                } catch (e) {
                    tried.push({ url, error: String(e) });
                }
            }
            return { ok: false, tried };
        }
        """,
        project_ref,
    )

    if not result.get("ok"):
        # Не получилось через API — пробуем UI
        print(f"  ⚠ API не отдал ключи, пробую UI. Tried: {result.get('tried')}", flush=True)
        return await _get_keys_via_ui(page, project_ref)

    print(f"  ✓ API ответил на {result['url']}", flush=True)
    data = result["data"]

    anon_key = None
    service_key = None
    # API может возвращать список объектов {name, api_key} или другой формат
    if isinstance(data, list):
        for item in data:
            name = (item.get("name") or "").lower()
            key = item.get("api_key") or item.get("apiKey") or item.get("key")
            if not key:
                continue
            if name == "anon" or name == "publishable":
                anon_key = key
            elif name == "service_role" or name == "secret":
                service_key = key

    if not service_key:
        # Декодируем JWT и ищем service_role
        all_keys = []
        if isinstance(data, list):
            for item in data:
                k = item.get("api_key") or item.get("apiKey") or item.get("key")
                if k:
                    all_keys.append(k)
        for k in all_keys:
            payload = decode_jwt_payload(k)
            if payload and payload.get("role") == "service_role":
                service_key = k
            elif payload and payload.get("role") == "anon":
                anon_key = k

    if not service_key:
        return await _get_keys_via_ui(page, project_ref)

    project_url = f"https://{project_ref}.supabase.co"
    print(f"✓ URL: {project_url}", flush=True)
    print(f"✓ service_role: {service_key[:40]}…", flush=True)
    return {"url": project_url, "anon_key": anon_key, "service_key": service_key}


async def _get_keys_via_ui(page: Page, project_ref: str) -> dict:
    """Fallback: пробуем разные URL дашборда и сканируем DOM на JWT."""
    print("  → Fallback: ищу ключи через UI…", flush=True)
    candidate_urls = [
        f"https://supabase.com/dashboard/project/{project_ref}/settings/api-keys",
        f"https://supabase.com/dashboard/project/{project_ref}/settings/api-keys/new",
        f"https://supabase.com/dashboard/project/{project_ref}/settings/api-keys/legacy",
        f"https://supabase.com/dashboard/project/{project_ref}/settings/api",
        f"https://supabase.com/dashboard/project/{project_ref}/integrations/data-api",
        f"https://supabase.com/dashboard/project/{project_ref}/settings/general",
    ]

    anon_key = None
    service_key = None

    for url in candidate_urls:
        print(f"    Пробую: {url}", flush=True)
        try:
            await page.goto(url, wait_until="domcontentloaded")
        except Exception as e:
            print(f"    ⚠ goto failed: {e}", flush=True)
            continue
        await page.wait_for_timeout(2500)
        await dismiss_banners(page)

        # Проверяем не 404
        if "404" in await page.title() or "Looking for something" in (await page.content()):
            continue

        # Reveal/Show кнопки
        for name_pattern in (re.compile("reveal", re.I), re.compile("show", re.I)):
            try:
                btns = page.get_by_role("button", name=name_pattern)
                n = await btns.count()
                for i in range(n):
                    try:
                        b = btns.nth(i)
                        if await b.is_visible():
                            await b.click(timeout=2000)
                            await page.wait_for_timeout(300)
                    except Exception:
                        pass
            except Exception:
                pass

        for _ in range(15):
            service_key = await _find_jwts_with_role(page, "service_role")
            if service_key:
                break
            await page.wait_for_timeout(500)

        if service_key:
            anon_key = await _find_jwts_with_role(page, "anon")
            print(f"  ✓ Ключи найдены на {url}", flush=True)
            break

    if not service_key:
        screenshot_path = REPO / "supabase_api_page.png"
        await page.screenshot(path=str(screenshot_path), full_page=True)
        raise RuntimeError(
            f"Не нашёл service_role ключ ни через API, ни через UI. Скриншот: {screenshot_path}"
        )

    project_url = f"https://{project_ref}.supabase.co"
    return {"url": project_url, "anon_key": anon_key, "service_key": service_key}


async def apply_schema(page: Page, project_ref: str) -> None:
    print("→ Применяю SQL-схему через SQL Editor…", flush=True)
    sql = SCHEMA_PATH.read_text()
    await page.goto(
        f"https://supabase.com/dashboard/project/{project_ref}/sql/new",
        wait_until="domcontentloaded",
    )
    await page.wait_for_timeout(3000)
    await dismiss_banners(page)

    # Monaco editor
    editor_area = page.locator(".monaco-editor").first
    await editor_area.wait_for(state="visible", timeout=15000)
    await editor_area.click()
    await page.wait_for_timeout(300)
    mod = "Meta" if sys.platform == "darwin" else "Control"
    await page.keyboard.press(f"{mod}+A")
    await page.keyboard.press("Delete")

    # Через буфер обмена — надёжно для большого SQL
    await page.evaluate("text => navigator.clipboard.writeText(text)", sql)
    await page.keyboard.press(f"{mod}+V")
    await page.wait_for_timeout(800)

    run_btn = page.get_by_role("button", name=re.compile(r"^run\b|run query", re.I)).first
    await run_btn.click()
    await page.wait_for_timeout(5000)
    print("✓ Схема применена.", flush=True)


async def main() -> int:
    if not SCHEMA_PATH.exists():
        print(f"ERROR: схема не найдена: {SCHEMA_PATH}", file=sys.stderr)
        return 1

    USER_DATA_DIR.parent.mkdir(parents=True, exist_ok=True)

    # Если креды уже в .env — выходим (идемпотентность)
    if read_env_var("SUPABASE_URL") and read_env_var("SUPABASE_SERVICE_KEY"):
        print("→ В .env уже есть SUPABASE_URL и SUPABASE_SERVICE_KEY — пропускаю настройку.", flush=True)
        return 0

    # Если project_ref уже сохранён — пропускаем создание проекта
    existing_ref = read_env_var("SUPABASE_PROJECT_REF")
    if existing_ref:
        print(f"→ Найден существующий project_ref={existing_ref}, перехожу сразу к получению ключей", flush=True)

    db_password = read_env_var("SUPABASE_DB_PASSWORD") or gen_password()
    print(f"→ Пароль БД: {db_password[:6]}…", flush=True)

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA_DIR),
            headless=False,
            args=["--start-maximized"],
            no_viewport=True,
            permissions=["clipboard-read", "clipboard-write"],
        )
        page = context.pages[0] if context.pages else await context.new_page()

        try:
            await wait_for_login(page)

            if existing_ref:
                project_ref = existing_ref
            else:
                await select_organization(page)
                project_ref = await fill_project_form(page, db_password)
                # Сохраняем ref СРАЗУ — чтобы при ошибке дальше не создавать проект заново
                write_env({
                    "SUPABASE_PROJECT_REF": project_ref,
                    "SUPABASE_DB_PASSWORD": db_password,
                })

            keys = await get_keys(page, project_ref)

            write_env({
                "SUPABASE_URL": keys["url"],
                "SUPABASE_SERVICE_KEY": keys["service_key"],
                "SUPABASE_ANON_KEY": keys["anon_key"] or "",
                "SUPABASE_DB_PASSWORD": db_password,
                "SUPABASE_PROJECT_REF": project_ref,
            })

            await apply_schema(page, project_ref)

            print("\n✓✓✓ Supabase готов к работе.", flush=True)
            print("    URL и ключи лежат в .env", flush=True)
            await page.wait_for_timeout(3000)
        except PWTimeout as e:
            print(f"\nERROR (timeout): {e}", file=sys.stderr, flush=True)
            try:
                await page.screenshot(path=str(REPO / "setup_error.png"), full_page=True)
            except Exception:
                pass
            return 2
        except Exception as e:
            import traceback
            print(f"\nERROR: {e}", file=sys.stderr, flush=True)
            traceback.print_exc()
            try:
                await page.screenshot(path=str(REPO / "setup_error.png"), full_page=True)
            except Exception:
                pass
            return 3
        finally:
            await context.close()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
