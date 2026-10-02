#!/usr/bin/env bash
# セットアップスクリプト (macOS / Linux)。何度実行しても安全です。
set -e
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
echo "=== 未来の自分からの電話: セットアップ開始 ==="
echo "場所: $ROOT"

# 1. 仮想環境
if [ -x ".venv/bin/python" ] && .venv/bin/python -c 'import sys; sys.exit(0 if sys.version_info[:2]==(3,11) else 1)'; then
  echo "[1/5] .venv (Python 3.11) は作成済みです。"
else
  echo "[1/5] Python 3.11 の仮想環境 .venv を作成します..."
  if command -v uv >/dev/null 2>&1; then
    uv venv --python 3.11 --seed --clear .venv
  elif command -v python3.11 >/dev/null 2>&1; then
    rm -rf .venv
    python3.11 -m venv .venv
  else
    echo "エラー: Python 3.11 が見つかりません。"
    echo "  次のどちらかを実行してからやり直してください:"
    echo "    brew install uv        (推奨)"
    echo "    brew install python@3.11"
    exit 1
  fi
fi
PY=".venv/bin/python"

# pip が無い venv (uv venv を --seed 無しで作った場合など) を補う
if ! "$PY" -m pip --version >/dev/null 2>&1; then
  echo "    pip が見つからないため、導入します..."
  if ! "$PY" -m ensurepip --upgrade >/dev/null 2>&1; then
    if command -v uv >/dev/null 2>&1; then
      uv pip install --python "$PY" pip || true
    fi
  fi
  if ! "$PY" -m pip --version >/dev/null 2>&1; then
    echo "エラー: .venv に pip を導入できませんでした。"
    echo "  .venv フォルダを削除してから、もう一度実行してください:"
    echo "    rm -rf .venv && scripts/setup.sh"
    exit 1
  fi
fi

# 2. pip 更新と軽量依存
echo "[2/5] 基本ライブラリをインストールします (requirements.txt)..."
"$PY" -m pip install --upgrade pip
"$PY" -m pip install -r requirements.txt

# 3. 重量依存 (Chatterbox / faster-whisper。すべてローカルで動作)
echo "[3/5] 音声モデル用ライブラリをインストールします (数分〜十数分かかります)..."
if ! "$PY" -m pip install -r requirements-chatterbox.txt; then
  echo "警告: requirements-chatterbox.txt のインストールに失敗しました。"
  echo "  docs/07_troubleshooting.md を参照してください。モックモードなら動かせます。"
fi

# ローカル LLM (Ollama)
if command -v ollama >/dev/null 2>&1; then
  MODEL=$(grep -E '^[[:space:]]+model:' config.yaml | sed -n 1p | awk '{print $2}')
  MODEL=${MODEL:-gemma3:12b}
  echo "    Ollama モデル $MODEL を取得します..."
  ollama pull "$MODEL" || echo "警告: ollama pull に失敗。Ollama アプリを起動してから 'ollama pull $MODEL' を実行してください。"
else
  echo "警告: Ollama が見つかりません。 brew install ollama で入れてください(未導入でもテンプレートで動きます)。"
fi

# 4. モデル取得
echo "[4/5] モデルをダウンロード/確認します..."
"$PY" scripts/download_models.py || true

# 5. .env
if [ -f .env ]; then
  echo "[5/5] .env は作成済みです。"
elif [ -f .env.example ]; then
  cp .env.example .env
  echo "[5/5] .env を作成しました(ローカル運用では設定不要です)。"
else
  echo "[5/5] .env.example が見つかりません。手動で .env を作ってください。"
fi

echo ""
echo "=== セットアップ完了 ==="
echo "次のステップ: scripts/start.command で起動(ローカル完結。APIキー不要)"
