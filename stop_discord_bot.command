#!/bin/zsh
# 在 macOS Finder 雙擊此檔，即可停止背景運行的 Discord 機器人。

SCRIPT_DIR="${0:A:h}"
cd "$SCRIPT_DIR" || exit 1

PID_FILE="$SCRIPT_DIR/.discord_bot.pid"

STOPPED=0

if [[ -f "$PID_FILE" ]]; then
  EXISTING_PID=$(cat "$PID_FILE")
  if ps -p "$EXISTING_PID" > /dev/null 2>&1; then
    kill "$EXISTING_PID" 2>/dev/null
    STOPPED=1
  fi
  rm -f "$PID_FILE"
fi

# 雙重確認是否還有殘留的 run_bot.py 進程
pkill -f "run_bot.py" 2>/dev/null && STOPPED=1

if [[ $STOPPED -eq 1 ]]; then
  osascript -e 'display notification "Discord 機器人已成功停止。" with title "NotifyRobot 已關閉"'
else
  osascript -e 'display notification "目前沒有正在運行的 Discord 機器人。" with title "NotifyRobot"'
fi

exit 0
