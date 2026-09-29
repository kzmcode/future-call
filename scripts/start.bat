@echo off
REM Windows: ダブルクリックで起動(F-64)
chcp 65001 >nul
cd /d "%~dp0.."
set ROOT=%CD%

if not exist ".venv\Scripts\activate.bat" (
  echo [error] .venv が見つかりません。先に scripts\setup.bat を実行してください。
  pause
  exit /b 1
)
call ".venv\Scripts\activate.bat"

for /f "tokens=1,2" %%a in ('python -c "import yaml;c=(yaml.safe_load(open('config.yaml',encoding='utf-8')) or {}).get('server',{});print(c.get('host','127.0.0.1'),c.get('port',8000))"') do (
  set HOST=%%a
  set PORT=%%b
)
set URL=http://%HOST%:%PORT%/

if not exist logs mkdir logs
start "future-call-server" /min cmd /c "cd /d %ROOT%\backend && python -m app.main >> ..\logs\server.out 2>&1"

echo サーバーを起動しています... (%URL%)
powershell -NoProfile -Command "for($i=0;$i -lt 120;$i++){ try{ Invoke-WebRequest -UseBasicParsing '%URL%api/health' | Out-Null; exit 0 }catch{ Start-Sleep 1 } }; exit 1"
if errorlevel 1 (
  echo [error] サーバーが起動しませんでした。logs\server.out を確認してください。
  pause
  exit /b 1
)

set CHROME=
for %%p in ("%ProgramFiles%\Google\Chrome\Application\chrome.exe" "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" "%LocalAppData%\Google\Chrome\Application\chrome.exe") do (
  if exist %%p set CHROME=%%~p
)
if "%CHROME%"=="" (
  echo [warn] Chrome が見つかりません。ブラウザで %URL% を開いてください。
  pause
  exit /b 0
)

"%CHROME%" --kiosk --autoplay-policy=no-user-gesture-required --use-fake-ui-for-media-stream --user-data-dir="%ROOT%\.chrome-profile" --no-first-run --no-default-browser-check --disable-session-crashed-bubble --disable-infobars --disable-pinch --overscroll-history-navigation=0 "%URL%"

REM Chrome 終了後にサーバーを停止
taskkill /FI "WINDOWTITLE eq future-call-server*" /T /F >nul 2>&1
