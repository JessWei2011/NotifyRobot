@echo off
chcp 65001 >nul
echo.
echo ==============================================
echo    NotifyRobot Discord 互動機器人
echo ==============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [X] 找不到 Python，請先安裝 Python 並加入 PATH。
    pause
    exit /b 1
)

python run_bot.py
pause
