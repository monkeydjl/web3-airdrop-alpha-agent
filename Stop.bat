@echo off
chcp 65001 >nul
title Web3 Airdrop Alpha - Stop Services

echo.
echo ========================================
echo  Web3 Airdrop Alpha Agent System
echo  Stop Services Script
echo ========================================
echo.

echo [1/3] Finding backend processes...
for /f "tokens=2" %%a in ('tasklist ^| findstr /i "uvicorn"') do (
    echo [INFO] Stopping backend process %%a
    taskkill /F /PID %%a >nul 2>&1
)
echo [OK] Backend service stopped
echo.

echo [2/3] Finding frontend processes...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":3002"') do (
    echo [INFO] Stopping frontend process %%a
    taskkill /F /PID %%a >nul 2>&1
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
