#!/bin/zsh
# 在 macOS Finder 直接雙擊此檔，即可執行一次正式推播。

set -u

SCRIPT_DIR="${0:A:h}"
PYTHON_EXEC="$(command -v python3 2>/dev/null || true)"

print "\n📈 台股盤後籌碼通知器"
print "專案位置：$SCRIPT_DIR\n"

if [[ -z "$PYTHON_EXEC" ]]; then
  print "❌ 找不到 python3。請先安裝 Python 3。"
  read "?按 Enter 關閉視窗..."
  exit 1
fi

if [[ ! -f "$SCRIPT_DIR/.env" ]]; then
  print "❌ 尚未設定 .env。"
  print "請先複製 .env.example 為 .env，並填入 Telegram Token 和 Chat ID。"
  read "?按 Enter 關閉視窗..."
  exit 1
fi

if ! "$PYTHON_EXEC" -c 'import requests' 2>/dev/null; then
  print "❌ 缺少 Python 套件 requests。"
  print "請在終端機執行：$PYTHON_EXEC -m pip install -r $SCRIPT_DIR/requirements.txt"
  read "?按 Enter 關閉視窗..."
  exit 1
fi

cd "$SCRIPT_DIR" || exit 1
"$PYTHON_EXEC" main.py
EXIT_CODE=$?

if [[ $EXIT_CODE -eq 0 ]]; then
  print "\n✅ 執行完成。"
else
  print "\n❌ 執行失敗（代碼：$EXIT_CODE）。請查看上方訊息。"
fi

read "?按 Enter 關閉視窗..."
exit $EXIT_CODE
