#!/usr/bin/env bash
# Sobe o Barbearia Magno em desenvolvimento (cria/atualiza o venv na primeira vez).
# Uso: ./scripts/run.sh [--reload]
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -x venv/bin/python ]; then
  echo "[magno] criando venv..."
  python3 -m venv venv
fi
./venv/bin/pip install -q --upgrade pip
./venv/bin/pip install -q -r requirements.txt

if [ -f .env.local ]; then
  set -a; . ./.env.local; set +a
fi

PORTA="${MAGNO_PORTA:-8100}"
echo "[magno] http://127.0.0.1:${PORTA}"
exec ./venv/bin/uvicorn server.main:app --host 127.0.0.1 --port "${PORTA}" "$@"
