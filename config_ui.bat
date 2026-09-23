@echo off
setlocal
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

where python >nul 2>nul
if %errorlevel% neq 0 (
    where py >nul 2>nul
    if %errorlevel% neq 0 (
        echo [ERROR] Python not found. Please install Python 3.
        pause
        exit /b 1
    ) else (
        set "PYTHON_EXEC=py -3"
    )
) else (
    set "PYTHON_EXEC=python"
)

echo Starting configuration UI at http://127.0.0.1:8765
start http://127.0.0.1:8765
%PYTHON_EXEC% config_app.py
pause
