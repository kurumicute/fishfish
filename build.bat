@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Run install.bat first.
    goto :end
)
echo Installing build tools ...
".venv\Scripts\python.exe" -m pip install -q "pyinstaller>=6.0"
echo Building release packages ...
".venv\Scripts\python.exe" tools\make_release.py %*
if errorlevel 1 echo [ERROR] Build failed.
:end
endlocal
if /i not "%~1"=="--no-pause" pause
