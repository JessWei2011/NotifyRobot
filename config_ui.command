#!/bin/zsh
# Finder 雙擊後開啟本機自選股設定頁。

set -u
SCRIPT_DIR="${0:A:h}"
PYTHON_EXEC="$(command -v python3 2>/dev/null || true)"

if [[ -z "$PYTHON_EXEC" ]]; then
  print "❌ 找不到 python3。"
  read "?按 Enter 關閉視窗..."
  exit 1
fi

cd "$SCRIPT_DIR" || exit 1
open "http://127.0.0.1:8765"
"$PYTHON_EXEC" config_app.py
