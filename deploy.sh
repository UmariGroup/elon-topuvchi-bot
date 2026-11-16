#!/usr/bin/env bash
# Serverga chiqarish / yangilash. Serverda, loyiha papkasida ishga tushiring:
#     ./deploy.sh
# Birinchi marta: .env yaratadi va Telegram akkauntga kirishni so'raydi.
# Keyingi marta: kodni yangilab, servislarni qayta ko'taradi.
set -euo pipefail
cd "$(dirname "$0")"

command -v docker >/dev/null || { echo "Docker o'rnatilmagan"; exit 1; }
docker compose version >/dev/null || { echo "Docker Compose (v2) o'rnatilmagan"; exit 1; }

if [ -d .git ]; then
  git pull --ff-only
fi

if [ ! -f .env ]; then
  cp .env.example .env
  chmod 600 .env
  echo ".env yaratildi. Uni to'ldiring (nano .env) va ./deploy.sh ni qayta ishga tushiring."
  exit 1
fi

missing=$(grep -E '^(TELEGRAM_BOT_TOKEN|TG_API_ID|TG_API_HASH|ANTHROPIC_API_KEY|ADMIN_IDS|POSTGRES_PASSWORD)=$' .env | cut -d= -f1 || true)
if [ -n "$missing" ]; then
  echo ".env da to'ldirilmagan: $missing"
  exit 1
fi
if grep -q 'POSTGRES_PASSWORD_QIYMATI' .env; then
  echo ".env: DATABASE_URL ichidagi POSTGRES_PASSWORD_QIYMATI ni haqiqiy parol bilan almashtiring"
  exit 1
fi

docker compose build

# Telegram session hali yo'q bo'lsa — bir martalik kirish (telefon raqam va kod so'raladi)
if ! docker compose run --rm --no-deps collector test -s /data/collector.session 2>/dev/null; then
  docker compose up -d db
  echo "Collector Telegram akkauntiga kirish (alohida SIM-karta bilan!)"
  docker compose run --rm collector python -m elon.collector.login
fi

docker compose up -d
sleep 5
docker compose ps
echo
echo "Loglar: docker compose logs -f bot collector"
