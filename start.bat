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

echo [1/3] Syncing dependencies...
uv sync

echo [2/3] Starting server (first run downloads models, 1-3 min)...
start "AP CSA Server" cmd /k "uv run uvicorn main:app --port 8000"

echo [3/3] Waiting for server to be ready...
:wait
curl -s --connect-timeout 3 --max-time 3 http://localhost:8000/health >nul 2>&1
if errorlevel 1 (
    timeout /t 2 /nobreak >nul
    goto wait
)

echo Server ready. Opening browser...
start "" http://localhost:8000
echo.
echo To stop: press Ctrl+C in the "AP CSA Server" window.
pause
