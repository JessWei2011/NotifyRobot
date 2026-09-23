#!/usr/bin/env python3
"""
Telegram Bot 快速連線測試小工具
用途：幫助新手檢測 Telegram Token 是否正確、自動找尋 Chat ID、並發送測試 Hello 訊息。
"""

import os
import sys
from pathlib import Path

if sys.platform == "win32":
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.stderr and hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 輕量載入 .env
def load_simple_env(env_path: Path):
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

load_simple_env(Path(__file__).resolve().parent / ".env")

from src.notifier import send_telegram_message, get_latest_chat_id

def main():
    print("=" * 50)
    print("🤖 Telegram Bot 連線測試助手")
    print("=" * 50)

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or token == "your_bot_token_here":
        print("❌ 請先在 .env 檔案中設定 TELEGRAM_BOT_TOKEN！")
        print("💡 如何取得？請在 Telegram 搜尋 @BotFather，輸入 /newbot 即可建立並取得 Token。")
        sys.exit(1)

    print(f"✅ 讀取到 Token: {token[:6]}...{token[-4:]}")

    if not chat_id or chat_id == "your_chat_id_here":
        print("\n🔍 正在為你尋找 Chat ID...")
        print("👉 請先在 Telegram 開啟你的機器人，隨意傳送一句話（例如：hi）給它！")
        input("傳送完成後，請按 [Enter] 繼續...")
        
        detected_id = get_latest_chat_id(token)
        if detected_id:
            print(f"🎉 成功偵測到你的 Chat ID: {detected_id}")
            print(f"👉 請將 TELEGRAM_CHAT_ID={detected_id} 填入 .env 檔案中！")
            chat_id = detected_id
        else:
            print("❌ 仍未偵測到訊息，請確認有在 Telegram 傳訊息給機器人，或可使用 @userinfobot 查詢你的 ID。")
            sys.exit(1)

    print(f"\n📨 正在向 Chat ID ({chat_id}) 發送測試訊息...")
    test_msg = (
        "🚀 *【台股籌碼推播機器人測試成功】*\n\n"
        "恭喜！你的 Telegram Bot 已成功與本機 Python 程式串接！\n"
        "接下來每日盤後即可收到專屬籌碼分析報告。"
    )

    result = send_telegram_message(token, chat_id, test_msg)
    if result.success:
        print("✨ 測試訊息發送成功！請檢查你的手機 Telegram！")
    else:
        print("❌ 發送失敗，請確認 Token 與 Chat ID 是否正確。")

if __name__ == "__main__":
    main()
