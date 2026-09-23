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

if not exist ".env" (
    echo [ERROR] .env file not found. Please copy .env.example to .env.
    pause
    exit /b 1
)

%PYTHON_EXEC% main.py %*
set "EXIT_CODE=%errorlevel%"

if "%~1"=="" pause
exit /b %EXIT_CODE%
