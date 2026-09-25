#!/usr/bin/env python3
"""
NotifyRobot Discord 互動指令機器人啟動腳本
功能：
  支援在 Discord 輸入指令隨時查詢個股資訊：
  - /stock <代號>：查詢即時行情價量與三大法人盤後籌碼
  - /news <代號> ：爬取最新新聞並由 AI 總結重點動態（利多/利空/核心題材）
  - /alert <代號>：查注意、警告、處置（處置起訖日期不管是否已進入皆完整印出）
  - /alart <代號>：同 /alert
  - /chip <代號> ：整理除中實戶外的籌碼資訊，並由本地 Qwen 給出專業短期趨勢評價
"""

import os
import sys
import logging
from pathlib import Path

# 設定 Windows 控制台編碼
if sys.platform == "win32":
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.stderr and hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent

def load_simple_env(env_path: Path):
    """原生輕量載入 .env 檔案"""
    if not env_path.exists():
        return
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key, val = key.strip(), val.strip()
            if val.startswith('"') and val.endswith('"'):
                val = val[1:-1]
            elif val.startswith("'") and val.endswith("'"):
                val = val[1:-1]
            os.environ.setdefault(key, val)

load_simple_env(BASE_DIR / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from src.bot_service import start_discord_bot

if __name__ == "__main__":
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        print("❌ 錯誤：未在 .env 設定 DISCORD_BOT_TOKEN，無法啟動 Discord 機器人。")
        sys.exit(1)

    print("🤖 正在啟動 NotifyRobot Discord 互動機器人...")
    try:
        start_discord_bot(token)
    except KeyboardInterrupt:
        print("\n👋 Discord 機器人已正常停止。")
