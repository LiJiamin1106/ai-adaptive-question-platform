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

REM Read ACCESS_TOKEN / NATAPP_AUTHTOKEN from .env
set "ACCESS_TOKEN="
set "NATAPP_AUTHTOKEN="
for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
    if "%%a"=="ACCESS_TOKEN" set "ACCESS_TOKEN=%%b"
    if "%%a"=="NATAPP_AUTHTOKEN" set "NATAPP_AUTHTOKEN=%%b"
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
if not defined NATAPP_AUTHTOKEN goto skip_tunnel

REM Locate natapp: prefer project-dir natapp.exe, else require it on PATH
set "NATAPP_CMD=natapp"
if exist "%~dp0natapp.exe" (
    set "NATAPP_CMD=%~dp0natapp.exe"
) else (
    where natapp >nul 2>&1
    if errorlevel 1 goto skip_tunnel
)

if exist natapp.log del natapp.log
start "AP CSA Tunnel" cmd /k "%NATAPP_CMD% -authtoken=%NATAPP_AUTHTOKEN% > natapp.log 2>&1"

echo Waiting for public URL...
set /a TUNNEL_TRIES=0
:tunnel_wait
timeout /t 2 /nobreak >nul
set /a TUNNEL_TRIES+=1
if not exist natapp.log goto tunnel_retry
findstr /c:"Forwarding" natapp.log >nul 2>&1
if not errorlevel 1 goto tunnel_ready
:tunnel_retry
if %TUNNEL_TRIES% geq 30 goto tunnel_timeout
goto tunnel_wait

:tunnel_ready
echo.
echo Local server: http://localhost:8000
for /f "delims=" %%a in ('uv run python tunnel_url.py') do set PUBLIC_LINK=%%a
echo Public link ^(share this^):
echo   %PUBLIC_LINK%
echo.
goto open_browser

:tunnel_timeout
echo.
echo [WARN] Tunnel URL not detected within 60s -- check natapp.log for errors.
echo Local server: http://localhost:8000
goto open_browser

:skip_tunnel
echo [WARN] Skipping tunnel (local only). To enable it:
echo   1. create a Web tunnel on https://natapp.cn, paste authtoken into .env as NATAPP_AUTHTOKEN=...
echo   2. download natapp.exe and put it in this folder ^(or add to PATH^)
echo.
echo Local server: http://localhost:8000

:open_browser
if defined ACCESS_TOKEN (
    start "" "http://localhost:8000/?token=%ACCESS_TOKEN%"
) else (
    start "" http://localhost:8000
)
echo To stop: run stop.bat
pause
