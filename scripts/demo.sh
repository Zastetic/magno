#!/usr/bin/env bash
# Sobe uma URL pública temporária do layout/sistema, para mostrar de fora de casa.
# O endereço vale enquanto este processo estiver rodando (Ctrl+C encerra).
# Uso: ./scripts/demo.sh [porta]
set -euo pipefail
cd "$(dirname "$0")/.."
PORTA="${1:-8100}"
LOG=/tmp/magno-demo-tunnel.log

if ! curl -s -o /dev/null --max-time 2 "http://127.0.0.1:${PORTA}/api/saude"; then
  echo "[demo] servidor não está na ${PORTA} — suba com ./scripts/run.sh em outro terminal"
  exit 1
fi

echo "[demo] abrindo túnel temporário para 127.0.0.1:${PORTA}..."
"$HOME/.local/bin/cloudflared" tunnel --no-autoupdate --url "http://127.0.0.1:${PORTA}" > "$LOG" 2>&1 &
TUNEL=$!
trap 'kill $TUNEL 2>/dev/null || true' EXIT

for _ in $(seq 1 30); do
  URL=$(grep -oE "https://[a-z0-9-]+\.trycloudflare\.com" "$LOG" | head -1 || true)
  [ -n "${URL:-}" ] && break
  sleep 1
done

if [ -z "${URL:-}" ]; then
  echo "[demo] não consegui obter a URL. Log: $LOG"
  exit 1
fi

echo
echo "  Site:   ${URL}/"
echo "  Outra:  ${URL}/index-b.html"
echo "  Status: ${URL}/status.html"
echo
echo "[demo] deixe este terminal aberto. Ctrl+C derruba o link."
wait $TUNEL
