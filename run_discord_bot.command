#!/bin/zsh
# 在 macOS Finder 直接雙擊此檔，即可啟動 Discord 互動機器人常駐服務。

set -u

SCRIPT_DIR="${0:A:h}"
PYTHON_EXEC="$(command -v python3 2>/dev/null || true)"

print "\n🤖 啟動 NotifyRobot Discord 互動指令機器人"
print "專案位置：$SCRIPT_DIR\n"

if [[ -z "$PYTHON_EXEC" ]]; then
  print "❌ 找不到 python3。請先安裝 Python 3。"
  read "?按 Enter 關閉視窗..."
  exit 1
fi

if [[ ! -f "$SCRIPT_DIR/.env" ]]; then
  print "❌ 尚未設定 .env。"
  read "?按 Enter 關閉視窗..."
  exit 1
fi

cd "$SCRIPT_DIR" || exit 1
"$PYTHON_EXEC" run_bot.py
EXIT_CODE=$?

read "?按 Enter 關閉視窗..."
exit $EXIT_CODE
