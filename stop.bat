@echo off
echo Stopping AP CSA server + tunnel...
taskkill /F /IM natapp.exe >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8000 ^| findstr LISTENING') do taskkill /F /PID %%a >nul 2>&1
echo Done.
pause
