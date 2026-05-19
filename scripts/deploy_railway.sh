#!/usr/bin/env bash
# Деплой бота на Railway через CLI.
#
# Что делает:
# 1. Ставит Railway CLI (если нет)
# 2. Просит пользователя залогиниться (откроется браузер)
# 3. Создаёт проект, прокидывает env-переменные из .env
# 4. Запускает деплой (railway up)
#
# Использование: bash scripts/deploy_railway.sh

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

if [[ ! -f .env ]]; then
  echo "ERROR: нет файла .env. Сначала прогоните scripts/setup_supabase.py и добавьте TELEGRAM_BOT_TOKEN." >&2
  exit 1
fi

# Проверим что критичные переменные есть
for v in TELEGRAM_BOT_TOKEN SUPABASE_URL SUPABASE_SERVICE_KEY; do
  if ! grep -q "^${v}=." .env; then
    echo "ERROR: в .env нет ${v}" >&2
    exit 1
  fi
done

# Установка Railway CLI
if ! command -v railway >/dev/null 2>&1; then
  echo "→ Ставлю Railway CLI…"
  if command -v brew >/dev/null 2>&1; then
    brew install railway
  else
    # Прямой бинарь
    curl -fsSL https://railway.com/install.sh | sh
    export PATH="$HOME/.railway/bin:$PATH"
  fi
fi

# Логин
if ! railway whoami >/dev/null 2>&1; then
  echo "→ Открою браузер для логина в Railway. Авторизуйтесь и вернитесь сюда."
  railway login
fi

# Инициализация проекта (если ещё нет привязки)
if [[ ! -f .railway/project.json && ! -f .railway/.env ]]; then
  echo "→ Создаю проект Railway 'family-assistant'…"
  railway init -n family-assistant
fi

# Прокидываем все переменные из .env в Railway
echo "→ Прокидываю env-переменные…"
while IFS= read -r line; do
  [[ -z "$line" || "$line" == \#* ]] && continue
  if [[ "$line" =~ ^([A-Z_]+)=(.*)$ ]]; then
    key="${BASH_REMATCH[1]}"
    value="${BASH_REMATCH[2]}"
    # SUPABASE_DB_PASSWORD и PROJECT_REF боту не нужны
    case "$key" in
      SUPABASE_DB_PASSWORD|SUPABASE_PROJECT_REF) continue ;;
    esac
    railway variables --set "${key}=${value}" >/dev/null
    echo "  ✓ ${key}"
  fi
done < .env

# Деплой
echo "→ Запускаю railway up (соберётся Docker-образ и задеплоится)…"
railway up --detach

echo ""
echo "✓ Готово. Логи: railway logs"
echo "  Статус:   railway status"
echo "  URL:      railway domain"
