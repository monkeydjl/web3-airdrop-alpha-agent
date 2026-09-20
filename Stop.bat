@echo off
chcp 65001 >nul
title Web3 Airdrop Alpha - Stop Services

echo.
echo ========================================
echo  Web3 Airdrop Alpha Agent System
echo  Stop Services Script
echo ========================================
echo.

echo [1/3] Finding backend processes (port 8002)...
REM 按**端口**找后端：tasklist 的映像名是 python.exe，按 "uvicorn" 找永远
REM 匹配不到（那是命令行参数，tasklist 不显示）—— 旧写法等于从不停止后端，
REM 「重启」变成第二个实例绑同一个端口，流量仍进旧进程。
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8002" ^| findstr "LISTENING"') do (
    echo [INFO] Stopping backend process %%a
    taskkill /F /T /PID %%a >nul 2>&1
)
echo [OK] Backend service stopped
echo.

echo [2/3] Finding frontend processes...
REM 必须过滤 LISTENING：established 连接行的 PID 是连接的另一端 ——
REM 典型就是用户自己的浏览器，不加过滤会把浏览器一起杀掉。
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
