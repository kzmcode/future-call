#!/usr/bin/env bash
# ワンクリック起動(F-64): サーバー起動 -> /api/health 待機 -> Chrome をキオスク表示。
# Chrome を閉じるとサーバーも停止します。
set -u
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

if [ -f .venv/bin/activate ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
else
  echo "[error] .venv が見つかりません。先に scripts/setup.sh を実行してください。"
  exit 1
fi

read -r HOST PORT < <(python - <<'PY'
import yaml
c = (yaml.safe_load(open("config.yaml", encoding="utf-8")) or {}).get("server", {})
print(c.get("host", "127.0.0.1"), c.get("port", 8000))
PY
)
URL="http://${HOST}:${PORT}/"

mkdir -p logs
( cd backend && exec python -m app.main ) >> logs/server.out 2>&1 &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null' EXIT INT TERM

echo "サーバーを起動しています... (${URL})"
for _ in $(seq 1 120); do
  if curl -fs "${URL}api/health" >/dev/null 2>&1; then READY=1; break; fi
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then echo "[error] サーバーが終了しました。logs/server.out を確認してください。"; exit 1; fi
  sleep 1
done
if [ "${READY:-0}" != 1 ]; then echo "[error] サーバーが起動しませんでした。"; exit 1; fi

CHROME=""
for c in "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
         "$(command -v google-chrome 2>/dev/null)" "$(command -v google-chrome-stable 2>/dev/null)" \
         "$(command -v chromium 2>/dev/null)" "$(command -v chromium-browser 2>/dev/null)"; do
  if [ -n "$c" ] && [ -x "$c" ]; then CHROME="$c"; break; fi
done
if [ -z "$CHROME" ]; then
  echo "[warn] Chrome が見つかりません。ブラウザで ${URL} を開いてください。Ctrl+C で終了します。"
  wait "$SERVER_PID"; exit 0
fi

"$CHROME" --kiosk --autoplay-policy=no-user-gesture-required --use-fake-ui-for-media-stream \
  --user-data-dir="${ROOT}/.chrome-profile" --no-first-run --no-default-browser-check \
  --disable-session-crashed-bubble --disable-infobars --disable-pinch --overscroll-history-navigation=0 \
  "${URL}"
echo "Chrome が終了しました。サーバーを停止します。"
