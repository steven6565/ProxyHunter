@echo off
REM Proxy Hunter installer for Windows 10/11
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python 3.11+ is required. Install it from https://www.python.org/downloads/
    exit /b 1
)

echo ==^> Creating virtual environment
python -m venv .venv
if errorlevel 1 (
    echo Failed to create virtual environment.
    exit /b 1
)

call .venv\Scripts\activate.bat
python -m pip install --disable-pip-version-check --upgrade pip
python -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 exit /b 1

if not exist output mkdir output
if not exist output\protocols mkdir output\protocols
if not exist output\countries mkdir output\countries
if not exist output\filters mkdir output\filters
if not exist output\logs mkdir output\logs
if not exist data mkdir data

echo.
echo Install complete. Start with:
echo   .venv\Scripts\python.exe main.py
pause
