@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

where python >/dev/null 2>nul
if errorlevel 1 (
    echo [ERROR] python not found. Install Python 3.11+ and enable "Add to PATH".
    goto :end
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/2] Creating virtual environment .venv ...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        goto :end
    )
)

echo [2/2] Installing dependencies ...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Package installation failed. Check your network and retry.
    goto :end
)

echo.
echo Done. Run run.bat to start reading.

:end
endlocal
if /i not "%~1"=="--no-pause" pause
