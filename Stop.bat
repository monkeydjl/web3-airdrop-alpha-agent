@echo off
title Web3 Airdrop Alpha - Stop Services

echo.
echo ========================================
echo  Web3 Airdrop Alpha Agent System
echo  Stop Services Script
echo ========================================
echo.

echo [1/3] Finding backend processes (port 8002)...
REM Locate the backend by PORT, not by image name: tasklist shows
REM python.exe (uvicorn is only a command-line argument), so filtering
REM by "uvicorn" never matches -- the old version never stopped it.
REM ("reboot" silently became a second instance on the same port.)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8002" ^| findstr "LISTENING"') do (
    echo [INFO] Stopping backend process %%a
    taskkill /F /T /PID %%a >nul 2>&1
)
echo [OK] Backend service stopped
echo.

echo [2/3] Finding frontend processes...
REM LISTENING filter is mandatory: on an ESTABLISHED line the PID is the
REM OTHER end of the connection -- typically the user's own browser.
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":3002" ^| findstr "LISTENING"') do (
    echo [INFO] Stopping frontend process %%a
    taskkill /F /T /PID %%a >nul 2>&1
)
echo [OK] Frontend service stopped
echo.

echo [3/3] Cleanup complete
echo.
echo ========================================
echo  All services stopped
echo ========================================
echo.
pause
