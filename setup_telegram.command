#!/bin/zsh
# 在 macOS Finder 直接雙擊此檔，測試 Telegram 並取得 Chat ID。

set -u

SCRIPT_DIR="${0:A:h}"
PYTHON_EXEC="$(command -v python3 2>/dev/null || true)"

print "\n🤖 Telegram 設定助手\n"

if [[ -z "$PYTHON_EXEC" ]]; then
  print "❌ 找不到 python3。請先安裝 Python 3。"
  read "?按 Enter 關閉視窗..."
  exit 1
fi

if [[ ! -f "$SCRIPT_DIR/.env" ]]; then
  print "❌ 尚未建立 .env。請先從 .env.example 複製並填入 Bot Token。"
  read "?按 Enter 關閉視窗..."
  exit 1
fi

cd "$SCRIPT_DIR" || exit 1
"$PYTHON_EXEC" test_telegram.py
EXIT_CODE=$?

read "?按 Enter 關閉視窗..."
exit $EXIT_CODE
