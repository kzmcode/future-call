@echo off
chcp 65001 >nul
rem セットアップスクリプト (Windows)。何度実行しても安全です。
cd /d "%~dp0\.."
echo === 未来の自分からの電話: セットアップ開始 ===

if exist ".venv\Scripts\python.exe" (
  echo [1/5] .venv は作成済みです。
) else (
  echo [1/5] Python 3.10 の仮想環境 .venv を作成します...
  where uv >nul 2>nul
  if not errorlevel 1 (
    uv venv --python 3.10 --seed .venv
  ) else (
    py -3.10 -m venv .venv
    if errorlevel 1 (
      echo エラー: Python 3.10 が見つかりません。https://www.python.org/downloads/ から 3.10 を入れるか、uv を入れてください。
      pause
      exit /b 1
    )
  )
)
set PY=.venv\Scripts\python.exe

rem pip が無い venv (uv venv を --seed 無しで作った場合など) を補う
%PY% -m pip --version >nul 2>nul
if errorlevel 1 (
  echo     pip が見つからないため、導入します...
  %PY% -m ensurepip --upgrade >nul 2>nul
  if errorlevel 1 (
    where uv >nul 2>nul
    if not errorlevel 1 (
      uv pip install --python %PY% pip
    )
  )
  %PY% -m pip --version >nul 2>nul
  if errorlevel 1 (
    echo エラー: .venv に pip を導入できませんでした。
    echo   .venv フォルダを削除してから、もう一度実行してください: rmdir /s /q .venv
    pause
    exit /b 1
  )
)

echo [2/5] 基本ライブラリをインストールします (requirements.txt)...
%PY% -m pip install --upgrade pip
%PY% -m pip install -r requirements.txt
if errorlevel 1 (
  echo エラー: インストールに失敗しました。
  pause
  exit /b 1
)

echo [3/5] 音声モデル用ライブラリをインストールします (数分〜十数分かかります)...
%PY% -m pip install -r requirements-models.txt
if errorlevel 1 (
  echo 警告: requirements-models.txt のインストールに失敗しました。docs\07_troubleshooting.md を参照してください。
) else (
  echo OpenVoice を単独でインストールします (--no-deps)...
  %PY% -m pip install --no-deps git+https://github.com/myshell-ai/OpenVoice.git@74a1d147b17a8c3092dd5430504bd83ef6c7eb23
  echo unidic をダウンロードします...
  %PY% -m unidic download
)

echo [4/5] モデルをダウンロード/確認します...
%PY% scripts\download_models.py

if exist ".env" (
  echo [5/5] .env は作成済みです。
) else (
  if exist ".env.example" (
    copy .env.example .env >nul
    echo [5/5] .env を作成しました。GEMINI_API_KEY を書き込んでください。
  ) else (
    echo [5/5] .env.example が見つかりません。手動で .env を作ってください。
  )
)

echo.
echo === セットアップ完了 ===
pause
