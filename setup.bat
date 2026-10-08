@echo off
rem One-time setup: creates a private Python environment (.venv) with the packages ChainKit needs.
rem Safe to run again (repairs or updates the environment).
setlocal
cd /d "%~dp0"
set "PYCHECK=import sys; sys.exit(sys.version_info[:2] < (3, 11))"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "%PYCHECK%" >nul 2>nul || (
        echo The existing .venv does not work with Python 3.11+ - creating it again...
        rmdir /s /q ".venv"
    )
)
if exist ".venv\Scripts\python.exe" goto venv_ok
set "PY="
where py >nul 2>nul && py -3 -c "%PYCHECK%" >nul 2>nul && set "PY=py -3"
if not defined PY python -c "%PYCHECK%" >nul 2>nul && set "PY=python"
if not defined PY (
    echo Python 3.11 or newer is required.
    where py >nul 2>nul && py -3 --version 2>nul
    python --version 2>nul
    echo Install it from https://www.python.org/downloads/  ^(tick "Add python.exe to PATH"^), then run setup.bat again.
    pause & exit /b 1
)
echo Creating Python environment...
%PY% -m venv .venv || (
    echo Could not create the Python environment in "%~dp0.venv".
    pause & exit /b 1
)
:venv_ok
echo Installing Python packages...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul 2>nul
".venv\Scripts\python.exe" -m pip install -r requirements.txt || (
    echo.
    echo Installing the Python packages failed - see the messages above.
    echo Check the internet connection, then run setup.bat again.
    pause & exit /b 1
)
echo.
echo Setup complete. Start ChainKit with ChainKit.bat
if not "%CHAINKIT_NO_PAUSE%"=="1" if not defined CI pause
