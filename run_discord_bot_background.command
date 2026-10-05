#!/bin/zsh
# 在 macOS Finder 雙擊此檔，即可在完全無終端機視窗、不佔用 Dock 的情況下於背景啟動 Discord 機器人。

SCRIPT_DIR="${0:A:h}"
cd "$SCRIPT_DIR" || exit 1

PID_FILE="$SCRIPT_DIR/.discord_bot.pid"
LOG_FILE="$SCRIPT_DIR/bot.log"
PYTHON_EXEC="$(command -v python3 2>/dev/null || true)"

if [[ -z "$PYTHON_EXEC" ]]; then
  osascript -e 'display alert "錯誤" message "找不到 python3，請先確認 Python 環境。"'
  exit 1
fi

# 檢查是否已經在運行
if [[ -f "$PID_FILE" ]]; then
  EXISTING_PID=$(cat "$PID_FILE")
  if ps -p "$EXISTING_PID" > /dev/null 2>&1; then
    osascript -e "display notification \"Discord 機器人已在背景運行中 (PID: $EXISTING_PID)\" with title \"NotifyRobot\""
    exit 0
  fi
fi

# 在背景啟動並記錄 PID
nohup "$PYTHON_EXEC" run_bot.py >> "$LOG_FILE" 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > "$PID_FILE"

# 發送 macOS 原生系統通知提醒使用者
osascript -e "display notification \"Discord 機器人已於背景啟動 (PID: $NEW_PID)\" with title \"NotifyRobot 已上線\""
exit 0
