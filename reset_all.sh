#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${ROOT_DIR}"

if [ ! -f ".env" ]; then
  echo "Falta .env en ${ROOT_DIR}."
  echo "Copia primero: cp .env.example .env"
  exit 1
fi

echo "[1/6] Bajando stack y borrando volumenes..."
docker compose down -v --remove-orphans

echo "[2/6] Subiendo dependencias base..."
docker compose up -d --build db rabbitmq lab

echo "[3/6] Subiendo web..."
docker compose up -d --build web

echo "[4/6] Ejecutando migraciones..."
docker compose exec -T web python manage.py migrate --noinput

echo "[5/6] Sembrando dispositivos desde .env..."
docker compose exec -T web python manage.py seed_devices

echo "[6/6] Subiendo worker..."
docker compose up -d --build worker

echo "Listo. UI: http://localhost:8000/devices/ui/ops/"
