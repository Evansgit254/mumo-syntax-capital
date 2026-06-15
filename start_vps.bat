@echo off
echo ========================================================
echo Pure Quant Mumo Syntax & Capital - Windows VPS Startup
echo ========================================================
echo.

:: Check for Python
python --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python is not installed or not in PATH.
    echo Please install Python 3.10+ and check "Add Python to PATH".
    pause
    exit /b
)

:: Create Virtual Environment
IF NOT EXIST ".venv" (
    echo [SETUP] Creating virtual environment...
    python -m venv .venv
)

:: Activate Virtual Environment
echo [SETUP] Activating virtual environment...
call .venv\Scripts\activate.bat

:: Install Dependencies
echo [SETUP] Installing dependencies...
pip install -r requirements.txt

echo.
echo ========================================================
echo SYSTEM IS READY
echo ========================================================
echo.
echo Please ensure your local MT5 Terminal is running and logged in.
echo.
echo Starting Admin Dashboard (Port 5000)...
start /B python admin_server.py

echo Starting SMC Signal Tracker Engine...
python signal_tracker.py

pause
