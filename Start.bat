@echo off
chcp 65001 >nul
title Web3 Airdrop Alpha - Startup

echo.
echo ========================================
echo  Web3 Airdrop Alpha Agent System
echo  One-Click Startup Script
echo ========================================
echo.

REM Check Python
echo [1/6] Checking Python environment...
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.10+
    echo Download: https://www.python.org/downloads/
    pause
    exit /b 1
)

python --version
echo [OK] Python environment ready
echo.

REM Check dependencies
echo [2/6] Checking backend dependencies...
cd /d "%~dp0backend"

if not exist "venv" (
    echo [INFO] First run, creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created
)

echo [INFO] Activating virtual environment...
call venv\Scripts\activate.bat

echo [INFO] Installing/updating dependencies (this may take a minute)...
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies
    echo [INFO] Trying alternative installation method...
    pip install fastapi uvicorn[standard] pydantic pydantic-settings structlog apscheduler httpx prometheus-client pandas openpyxl python-multipart pytest pytest-asyncio pytest-cov
    if errorlevel 1 (
        echo [ERROR] Dependency installation failed
        pause
        exit /b 1
    )
)
echo [OK] Dependencies installed
echo.

REM Initialize database
echo [3/6] Initializing database...
if not exist "data\" (
    mkdir data
    echo [OK] Created data directory
)
echo [OK] Database ready
echo.

REM Start backend
echo [4/6] Starting backend service...
start "Backend API" cmd /k "cd /d "%~dp0backend" && call venv\Scripts\activate.bat && echo [OK] Backend starting... && uvicorn app.main:app --reload --host 0.0.0.0 --port 8002"

echo [INFO] Waiting for backend to start...
timeout /t 3 /nobreak >nul
echo [OK] Backend service started
echo.

REM Check Node.js
where node >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js not found. Please install Node.js 18+ to run the Next.js dashboard.
    echo Download: https://nodejs.org/
    pause
    exit /b 1
)

REM Check frontend
echo [5/6] Preparing frontend interface...
cd /d "%~dp0frontend-next"
if not exist "node_modules" (
    echo [INFO] Installing frontend dependencies ^(this may take a minute^)...
    call npm install
    if errorlevel 1 (
        echo [ERROR] Failed to install frontend dependencies
        pause
        exit /b 1
    )
)
echo [OK] Frontend dependencies ready
echo.

REM Start frontend (Next.js dev server)
echo [6/6] Starting frontend service...
start "Frontend UI" cmd /k "cd /d "%~dp0frontend-next" && echo [OK] Frontend starting... && npm run dev"

timeout /t 4 /nobreak >nul
echo [OK] Frontend service started
echo.

REM Open browser
echo ========================================
echo  Startup Complete!
echo ========================================
echo.
echo  Backend API:  http://localhost:8002
echo  API Docs:     http://localhost:8002/docs
echo  Frontend UI:  http://localhost:3002
echo.
echo  Press any key to open frontend in browser...
echo  (Closing this window will NOT stop services)
echo ========================================
pause >nul

start http://localhost:3002

echo.
echo [INFO] Frontend opened in browser
echo [INFO] Backend and frontend running in separate windows
echo [INFO] Close those windows to stop services
echo.
pause
