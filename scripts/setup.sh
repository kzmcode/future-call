#!/usr/bin/env bash
# セットアップスクリプト (macOS / Linux)。何度実行しても安全です。
set -e
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
echo "=== 未来の自分からの電話: セットアップ開始 ==="
echo "場所: $ROOT"

# 1. 仮想環境
if [ -x ".venv/bin/python" ] && .venv/bin/python -c 'import sys; sys.exit(0 if sys.version_info[:2]==(3,10) else 1)'; then
  echo "[1/5] .venv (Python 3.10) は作成済みです。"
else
  echo "[1/5] Python 3.10 の仮想環境 .venv を作成します..."
  if command -v uv >/dev/null 2>&1; then
    uv venv --python 3.10 --seed --clear .venv
  elif command -v python3.10 >/dev/null 2>&1; then
    rm -rf .venv
    python3.10 -m venv .venv
  else
    echo "エラー: Python 3.10 が見つかりません。"
    echo "  次のどちらかを実行してからやり直してください:"
    echo "    brew install uv        (推奨)"
    echo "    brew install python@3.10"
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

# 3. 重量依存
echo "[3/5] 音声モデル用ライブラリをインストールします (数分〜十数分かかります)..."
if "$PY" -m pip install -r requirements-models.txt; then
  echo "    OpenVoice を単独でインストールします (--no-deps: 依存の衝突を避けるため)..."
  "$PY" -m pip install --no-deps git+https://github.com/myshell-ai/OpenVoice.git || echo "警告: OpenVoice のインストールに失敗。docs/07_troubleshooting.md を参照してください。"
  echo "    unidic (日本語辞書) をダウンロードします..."
  "$PY" -m unidic download || echo "警告: unidic のダウンロードに失敗。後で '.venv/bin/python -m unidic download' を実行してください。"
else
  echo "警告: requirements-models.txt のインストールに失敗しました。"
  echo "  docs/07_troubleshooting.md を参照してください。モックモードなら動かせます。"
fi

# 4. モデル取得
echo "[4/5] モデルをダウンロード/確認します..."
"$PY" scripts/download_models.py || true

# 5. .env
if [ -f .env ]; then
  echo "[5/5] .env は作成済みです。"
elif [ -f .env.example ]; then
  cp .env.example .env
  echo "[5/5] .env を作成しました。GEMINI_API_KEY を書き込んでください (docs/02_gemini_api.md)。"
else
  echo "[5/5] .env.example が見つかりません。手動で .env を作ってください。"
fi

echo ""
echo "=== セットアップ完了 ==="
echo "次のステップ: docs/02_gemini_api.md で APIキーを設定 → scripts/start.command で起動"
