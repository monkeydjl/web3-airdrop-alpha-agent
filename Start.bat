@echo off
chcp 65001 >nul
title Web3 Airdrop Alpha - 一键启动

echo.
echo ========================================
echo  Web3 Airdrop Alpha Agent System
echo  一键启动脚本
echo ========================================
echo.

REM 检查 Python
echo [1/6] 检查 Python 环境...
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.10+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

python --version
echo [✓] Python 环境正常
echo.

REM 检查依赖
echo [2/6] 检查后端依赖...
cd /d "%~dp0backend"

if not exist "venv\" (
    echo [提示] 首次运行，创建虚拟环境...
    python -m venv venv
    if errorlevel 1 (
        echo [错误] 创建虚拟环境失败
        pause
        exit /b 1
    )
    echo [✓] 虚拟环境创建成功
)

echo [提示] 激活虚拟环境...
call venv\Scripts\activate.bat

echo [提示] 安装/更新依赖...
pip install -e . >nul 2>&1
if errorlevel 1 (
    echo [警告] 依赖安装可能有问题，尝试继续...
) else (
    echo [✓] 依赖安装完成
)
echo.

REM 初始化数据库
echo [3/6] 初始化数据库...
if not exist "data\" (
    mkdir data
    echo [✓] 创建数据目录
)
echo [✓] 数据库就绪
echo.

REM 启动后端
echo [4/6] 启动后端服务...
start "后端 API" cmd /k "cd /d %~dp0backend && call venv\Scripts\activate.bat && echo [✓] 后端服务启动中... && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"

echo [提示] 等待后端服务启动...
timeout /t 3 /nobreak >nul
echo [✓] 后端服务已启动
echo.

REM 检查前端
echo [5/6] 准备前端界面...
cd /d "%~dp0frontend"
if not exist "index.html" (
    echo [错误] 前端文件不存在
    pause
    exit /b 1
)
echo [✓] 前端文件就绪
echo.

REM 启动前端（使用 Python HTTP 服务器）
echo [6/6] 启动前端服务...
start "前端界面" cmd /k "cd /d %~dp0frontend && echo [✓] 前端服务启动中... && python -m http.server 3000"

timeout /t 2 /nobreak >nul
echo [✓] 前端服务已启动
echo.

REM 打开浏览器
echo ========================================
echo  启动完成！
echo ========================================
echo.
echo  后端 API:  http://localhost:8000
echo  API 文档:  http://localhost:8000/docs
echo  前端界面:  http://localhost:3000
echo.
echo  按任意键打开前端界面...
echo  (关闭此窗口不会停止服务)
echo ========================================
pause >nul

start http://localhost:3000

echo.
echo [提示] 前端界面已在浏览器中打开
echo [提示] 后端和前端服务在独立窗口运行
echo [提示] 关闭独立窗口可停止对应服务
echo.
pause
