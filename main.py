#!/usr/bin/env python3
"""
台股收盤籌碼 Telegram 自動推播主程式
執行方式：
  python3 main.py             # 正常執行 (發送推播)
  python3 main.py --dry-run   # 測試模式 (僅在終端機列印，不發送推播)
  python3 main.py --date 20240412 # 指定日期回測
"""

import os
import sys
import json
import argparse
import datetime
import logging
from pathlib import Path

# 設定基本路徑
BASE_DIR = Path(__file__).resolve().parent

def load_simple_env(env_path: Path):
    """原生輕量載入 .env 檔案，免安裝額外套件"""
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

# 引入內部模組
from src.fetcher import get_latest_institutional_data, get_latest_market_institutional_amounts
from src.analyzer import analyze_watchlist, filter_dual_buyers, filter_it_top_buyers
from src.notifier import (
    answer_callback_query,
    format_market_institutional_amount_message,
    format_screener_message,
    format_watchlist_message,
    get_updates,
    send_telegram_message,
)
from src.state import NotificationState
from src.events import collect_watchlist_events, collect_morning_calendar, format_morning_calendar

# 設定日誌格式
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("tw_stock_bot")

def load_config():
    config_path = BASE_DIR / "config.json"
    if not config_path.exists():
        logger.error(f"找不到設定檔: {config_path}")
        sys.exit(1)
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def acknowledgement_keyboard(trade_date: str, report_type: str):
    return {
        "inline_keyboard": [[{
            "text": "✅ 已收到",
            "callback_data": f"ack:{trade_date}:{report_type}",
        }]]
    }


def sync_acknowledgements(token: str, state: NotificationState) -> int:
    """同步使用者按下「已收到」的紀錄；可安全重複執行。"""
    updates = get_updates(token, state.get_offset())
    acknowledged = 0
    for update in updates:
        update_id = update.get("update_id")
        callback = update.get("callback_query", {})
        callback_data = callback.get("data", "")
        parts = callback_data.split(":")
        if len(parts) == 3 and parts[0] == "ack":
            _, trade_date, report_type = parts
            if state.acknowledge(trade_date, report_type):
                acknowledged += 1
                answer_callback_query(token, callback.get("id", ""), "已記錄，謝謝確認！")
        if isinstance(update_id, int):
            state.set_offset(update_id + 1)
    return acknowledged


def send_report(
    token: str,
    chat_id: str,
    trade_date: str,
    report_type: str,
    text: str,
    state: NotificationState,
    force: bool,
    enable_ack_button: bool,
    max_retries: int,
) -> bool:
    if state.was_sent(trade_date, report_type) and not force:
        logger.info("略過已成功推播的 %s（%s）；需要重送可加 --force", trade_date, report_type)
        return True

    result = send_telegram_message(
        token,
        chat_id,
        text,
        reply_markup=acknowledgement_keyboard(trade_date, report_type) if enable_ack_button else None,
        max_retries=max_retries,
    )
    if not result.success or result.message_id is None:
        logger.error("%s 推播未成功：%s", report_type, result.error)
        return False

    state.record_delivery(trade_date, report_type, result.message_id)
    return True

def main():
    parser = argparse.ArgumentParser(description="台股盤後籌碼自動推播系統")
    parser.add_argument("--dry-run", action="store_true", help="純列印測試，不實際發送 Telegram 訊息")
    parser.add_argument("--date", type=str, default=None, help="指定抓取日期 (格式: YYYYMMDD)")
    parser.add_argument("--force", action="store_true", help="即使同交易日已推播，也強制重新發送")
    parser.add_argument("--check-acks", action="store_true", help="只同步使用者按下「已收到」的紀錄")
    parser.add_argument("--market-summary", action="store_true", help="只推送上市大盤三大法人買賣超金額")
    parser.add_argument("--check-events", action="store_true", help="檢查自選股重大訊息、注意與處置事件")
    parser.add_argument("--morning-calendar", action="store_true", help="推送自選股開盤前行事曆")
    args = parser.parse_args()

    config = load_config()
    token = os.getenv("TELEGRAM_BOT_TOKEN")

    if args.check_acks:
        if not token:
            logger.error("未設定 TELEGRAM_BOT_TOKEN，無法同步確認紀錄")
            return 1
        state = NotificationState(BASE_DIR / "data" / "notification_state.sqlite3")
        count = sync_acknowledgements(token, state)
        logger.info("已同步 %s 筆確認紀錄", count)
        return 0

    if args.check_events:
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if not token or not chat_id:
            logger.error("未設定 TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID")
            return 1
        notification_cfg = config.get("notification", {})
        if not notification_cfg.get("send_event_alerts", True):
            logger.info("自選股事件通知已關閉")
            return 0
        codes = {str(item.get("code", "")).strip() for item in config.get("watchlist", [])}
        state = NotificationState(BASE_DIR / "data" / "notification_state.sqlite3")
        sent = 0
        for event in collect_watchlist_events(codes):
            if state.event_was_notified(event["id"]):
                continue
            if args.dry_run:
                print(event["text"] + "\n")
                sent += 1
                continue
            result = send_telegram_message(token, chat_id, event["text"], max_retries=notification_cfg.get("max_retries", 3))
            if result.success:
                state.record_event_notification(event["id"])
                sent += 1
            else:
                logger.error("事件通知發送失敗：%s", result.error)
        logger.info("自選股事件檢查完成，新通知 %s 則", sent)
        return 0

    if args.morning_calendar:
        try:
            start_date = datetime.datetime.strptime(args.date, "%Y%m%d").date() if args.date else datetime.date.today()
        except ValueError:
            logger.error("行事曆日期格式錯誤，請使用 YYYYMMDD")
            return 1
        codes = {str(item.get("code", "")).strip() for item in config.get("watchlist", [])}
        items = collect_morning_calendar(codes, start_date)
        if not items:
            logger.info("未來 7 天沒有已公告的自選股行事")
            return 0
        message = format_morning_calendar(start_date, items)
        if args.dry_run:
            print(message)
            return 0
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if not token or not chat_id:
            logger.error("未設定 TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID")
            return 1
        notification_cfg = config.get("notification", {})
        if not notification_cfg.get("send_morning_calendar", True):
            logger.info("開盤前行事曆推播已關閉")
            return 0
        state = NotificationState(BASE_DIR / "data" / "notification_state.sqlite3")
        trade_date = start_date.strftime("%Y%m%d")
        return 0 if send_report(
            token, chat_id, trade_date, "morning_calendar", message, state, args.force,
            notification_cfg.get("enable_ack_button", True), notification_cfg.get("max_retries", 3),
        ) else 1

    if args.market_summary:
        try:
            trade_date, summary = get_latest_market_institutional_amounts(args.date)
        except Exception as exc:
            logger.error("獲取上市大盤法人金額失敗: %s", exc)
            return 1
        message = format_market_institutional_amount_message(trade_date, summary)
        if args.dry_run:
            print(message)
            return 0
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if not token or not chat_id:
            logger.error("未設定 TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID")
            return 1
        notification_cfg = config.get("notification", {})
        if not notification_cfg.get("send_market_amount_summary", True):
            logger.info("上市大盤法人金額推播已關閉")
            return 0
        state = NotificationState(BASE_DIR / "data" / "notification_state.sqlite3")
        return 0 if send_report(
            token, chat_id, trade_date, "market_amount", message, state, args.force,
            notification_cfg.get("enable_ack_button", True), notification_cfg.get("max_retries", 3),
        ) else 1

    logger.info("=== 開始執行台股盤後籌碼分析 ===")

    # 1. 抓取三大法人籌碼資料
    try:
        trade_date, records = get_latest_institutional_data(args.date)
        logger.info(f"獲取交易日 [{trade_date}] 資料完成，共計 {len(records)} 檔上市與上櫃證券")
    except Exception as e:
        logger.error(f"獲取資料失敗: {e}")
        return 1

    # 2. 自選股分析
    watchlist_items = config.get("watchlist", [])
    watchlist_results = analyze_watchlist(records, watchlist_items)
    watchlist_msg = format_watchlist_message(trade_date, watchlist_results)

    # 3. 策略選股分析
    screener_cfg = config.get("screener", {})
    top_n = screener_cfg.get("top_n", 10)
    min_lots = screener_cfg.get("min_lots", 300)

    dual_buyers = (
        filter_dual_buyers(records, top_n=top_n, min_lots=min_lots)
        if screener_cfg.get("enable_dual_buyers", True) else []
    )
    it_buyers = (
        filter_it_top_buyers(records, top_n=top_n)
        if screener_cfg.get("enable_it_top", True) else []
    )
    screener_msg = format_screener_message(
        trade_date,
        dual_buyers,
        it_buyers,
        show_dual_buyers=screener_cfg.get("enable_dual_buyers", True),
        show_it_buyers=screener_cfg.get("enable_it_top", True),
    )

    # 4. 輸出或推播
    if args.dry_run:
        print("\n" + "=" * 50)
        print("🔍 【Dry Run 預覽：自選股訊息】")
        print("=" * 50)
        print(watchlist_msg)
        print("\n" + "=" * 50)
        print("🔍 【Dry Run 預覽：策略選股訊息】")
        print("=" * 50)
        print(screener_msg)
        print("=" * 50 + "\n")
        logger.info("Dry run 執行完畢，未發送推播。")
        return 0

    # 正式推播流程
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        logger.warning("未偵測到 Telegram Bot Token 或 Chat ID！請檢查 .env 設定檔。")
        print("\n⚠️ 提示：若尚未設定 Telegram，可加上 --dry-run 在終端機查看結果：")
        print("   python3 main.py --dry-run\n")
        return 1

    notification_cfg = config.get("notification", {})
    enable_ack_button = notification_cfg.get("enable_ack_button", True)
    max_retries = notification_cfg.get("max_retries", 3)
    state = NotificationState(BASE_DIR / "data" / "notification_state.sqlite3")
    sent_ok = True

    # 發送自選股
    if notification_cfg.get("send_watchlist", True):
        logger.info("正在推送自選股分析報告至 Telegram...")
        sent_ok &= send_report(token, chat_id, trade_date, "watchlist", watchlist_msg, state, args.force, enable_ack_button, max_retries)

    # 發送策略選股
    if notification_cfg.get("send_screener", True):
        logger.info("正在推送籌碼策略榜單至 Telegram...")
        if screener_cfg.get("enable_dual_buyers", True) or screener_cfg.get("enable_it_top", True):
            sent_ok &= send_report(token, chat_id, trade_date, "screener", screener_msg, state, args.force, enable_ack_button, max_retries)

    if not sent_ok:
        logger.error("=== 部分或全部推播失敗 ===")
        return 1
    logger.info("=== 籌碼分析與推播程序完成 ===")
    return 0

if __name__ == "__main__":
    sys.exit(main())
