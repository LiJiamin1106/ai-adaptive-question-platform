@echo off
cd /d "%~dp0"

echo ==========================================
echo   AP CSA Question Assistant
echo ==========================================
echo.

where uv >nul 2>&1
if errorlevel 1 (
    echo [ERROR] uv not found. Install: https://docs.astral.sh/uv/
    pause
    exit /b 1
)

echo [1/4] Syncing dependencies...
uv sync

echo [2/4] Starting server...
start "AP CSA Server" cmd /k "uv run uvicorn main:app --port 8000"

echo [3/4] Waiting for server ready...
:wait
curl -s --connect-timeout 3 --max-time 3 http://localhost:8000/health >nul 2>&1
if errorlevel 1 (
    timeout /t 2 /nobreak >nul
    goto wait
)

echo [4/4] Starting tunnel...
if exist cloudflared.log del cloudflared.log
start "AP CSA Tunnel" cmd /k "cloudflared tunnel --url http://localhost:8000 > cloudflared.log 2>&1"

echo Waiting for public URL...
:tunnel_wait
timeout /t 2 /nobreak >nul
if not exist cloudflared.log goto tunnel_wait
findstr /c:"trycloudflare.com" cloudflared.log >nul 2>&1
if errorlevel 1 goto tunnel_wait

echo.
echo Local server: http://localhost:8000
for /f "delims=" %%a in ('uv run python tunnel_url.py') do set PUBLIC_LINK=%%a
echo Public link ^(share this^):
echo   %PUBLIC_LINK%
echo.

start "" http://localhost:8000
echo To stop: run stop.bat
pause
