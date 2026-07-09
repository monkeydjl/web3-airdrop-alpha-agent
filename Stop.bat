@echo off
chcp 65001 >nul
title Web3 Airdrop Alpha - 停止服务

echo.
echo ========================================
echo  Web3 Airdrop Alpha Agent System
echo  停止服务脚本
echo ========================================
echo.

echo [1/3] 查找后端进程...
for /f "tokens=2" %%a in ('tasklist ^| findstr /i "uvicorn"') do (
    echo [提示] 停止后端进程 %%a
    taskkill /F /PID %%a >nul 2>&1
)
echo [✓] 后端服务已停止
echo.

echo [2/3] 查找前端进程...
for /f "tokens=2" %%a in ('netstat -ano ^| findstr ":3000"') do (
    echo [提示] 停止前端进程 %%a
    taskkill /F /PID %%a >nul 2>&1
)
echo [✓] 前端服务已停止
echo.

echo [3/3] 清理完成
echo.
echo ========================================
echo  所有服务已停止
echo ========================================
echo.
pause
