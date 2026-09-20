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
import platform
import random
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
from src.fetcher import get_latest_institutional_data, get_latest_market_institutional_amounts, get_margin_balances
from src.analyzer import add_margin_data, analyze_watchlist, filter_dual_buyers, filter_it_top_buyers
from src.notifier import (
    answer_callback_query,
    format_market_institutional_amount_message,
    format_big_holder_message,
    format_screener_message,
    format_watchlist_message,
    get_updates,
    send_discord_message,
    send_telegram_message,
)
from src.state import NotificationState
from src.events import collect_corporate_action_events, collect_monthly_revenue_events, collect_watchlist_events, collect_morning_calendar, format_morning_calendar, get_active_disposition_periods
from src.holdings import get_stock_holdings
from src.big_holders import build_big_holder_rows, fetch_big_holder_snapshot, load_previous_snapshot, save_snapshot

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


def get_watchlist(config):
    """合併手動自選股與永豐唯讀持股；同步失敗時仍保留手動清單。"""
    configured = config.get("watchlist", [])
    holdings_cfg = config.get("holdings", {})
    if holdings_cfg.get("source") != "shioaji":
        return configured
    try:
        holdings = get_stock_holdings()
        logger.info("已從 Shioaji 同步 %s 檔非 ETF 持股", len(holdings))
        merged = {str(item.get("code", "")).strip(): item for item in configured}
        for holding in holdings:
            code = str(holding.get("code", "")).strip()
            existing = merged.get(code, {})
            holding_name = str(holding.get("name", "")).strip()
            # Shioaji 合約有時只回傳代號；已有手動名稱時應優先保留。
            if existing and (not holding_name or holding_name == code):
                merged[code] = existing
            else:
                merged[code] = holding
        return list(merged.values())
    except Exception as exc:
        if holdings_cfg.get("fallback_to_config", True):
            logger.warning("Shioaji 持股同步失敗，暫用 config.json 自選股：%s", exc)
            return configured
        raise RuntimeError(f"Shioaji 持股同步失敗：{exc}") from exc


def get_notification_channels(config):
    """讀取通知通道開關；至少保留一個通道才會推播。"""
    channels = config.get("channels", {})
    return channels.get("telegram_enabled", True), channels.get("discord_enabled", bool(os.getenv("DISCORD_WEBHOOK_URL")))


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
    telegram_enabled: bool = True,
    discord_enabled: bool = True,
) -> bool:
    if state.was_sent(trade_date, report_type) and not force:
        logger.info("略過已成功推播的 %s（%s）；需要重送可加 --force", trade_date, report_type)
        return True

    message_id = None
    delivered = False
    if telegram_enabled:
        result = send_telegram_message(
            token, chat_id, text,
            reply_markup=acknowledgement_keyboard(trade_date, report_type) if enable_ack_button else None,
            max_retries=max_retries,
        )
        if result.success:
            message_id, delivered = result.message_id, True
        else:
            logger.error("%s Telegram 推播失敗：%s", report_type, result.error)
    if discord_enabled:
        discord_url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
        discord_result = send_discord_message(discord_url, text, max_retries=max_retries)
        if discord_result.success:
            message_id, delivered = discord_result.message_id or message_id, True
        else:
            logger.error("%s Discord 同步失敗：%s", report_type, discord_result.error)
    if not delivered or message_id is None:
        logger.error("%s 沒有成功送達任何啟用的通知通道", report_type)
        return False
    state.record_delivery(trade_date, report_type, message_id)
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
    parser.add_argument("--big-holder-report", action="store_true", help="推送自選股集保大戶週報")
    parser.add_argument("--test-discord", action="store_true", help="發送 Discord Webhook 連線測試")
    parser.add_argument("--heartbeat-discord", action="store_true", help="發送 Discord 主機心跳通知")
    args = parser.parse_args()

    config = load_config()
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    telegram_enabled, discord_enabled = get_notification_channels(config)

    if args.test_discord:
        result = send_discord_message(
            os.getenv("DISCORD_WEBHOOK_URL", "").strip(),
            "✅ *【Discord 通知測試】*\nWebhook 已連線成功。後續台股報告會同步推播到這個頻道。",
        )
        if not result.success:
            logger.error("Discord 測試失敗：%s", result.error)
            return 1
        return 0

    if args.heartbeat_discord:
        notification_cfg = config.get("notification", {})
        heartbeat_cfg = config.get("discord_heartbeat", {})
        if not heartbeat_cfg.get("enabled", notification_cfg.get("send_discord_heartbeat", True)):
            logger.info("Discord 主機心跳通知已關閉")
            return 0
        now = datetime.datetime.now().astimezone()
        quotes = [str(quote).strip() for quote in heartbeat_cfg.get("quotes", []) if str(quote).strip()]
        quote = random.choice(quotes) if quotes else "穩健累積，時間會放大你的成果。"
        default_template = (
            "💓 *【NotifyRobot 主機心跳】*\n"
            "🖥️ 主機：`{hostname}`\n"
            "🕒 時間：`{time}`\n"
            "✅ 排程已啟動，NotifyRobot 正常執行中。"
        )
        message = str(heartbeat_cfg.get("message", default_template)).replace(
            "{hostname}", platform.node() or "unknown"
        ).replace("{time}", now.strftime("%Y-%m-%d %H:%M:%S %Z")).replace("{quote}", quote)
        if args.dry_run:
            print(message)
            return 0
        result = send_discord_message(
            os.getenv("DISCORD_HEARTBEAT_WEBHOOK_URL", "").strip(),
            message,
            max_retries=notification_cfg.get("max_retries", 3),
        )
        if not result.success:
            logger.error("Discord 主機心跳發送失敗：%s", result.error)
            return 1
        return 0

    if args.big_holder_report:
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        notification_cfg = config.get("notification", {})
        if not notification_cfg.get("send_big_holder_report", True):
            logger.info("大戶籌碼週報已關閉")
            return 0
        watchlist = get_watchlist(config)
        codes = {str(item.get("code", "")).strip() for item in watchlist}
        # Shioaji 合約偶爾只回傳代號；以交易所盤後資料補齊週報顯示名稱。
        try:
            _, market_records = get_latest_institutional_data()
            market_names = {str(row["code"]).strip(): str(row["name"]).strip() for row in market_records}
            watchlist = [
                {**item, "name": market_names.get(str(item.get("code", "")).strip(), item.get("name", ""))}
                for item in watchlist
            ]
        except Exception as exc:
            logger.warning("無法以盤後資料補齊大戶週報名稱，沿用既有名稱：%s", exc)
        try:
            report_date, snapshot = fetch_big_holder_snapshot(codes)
        except Exception as exc:
            logger.error("取得集保大戶資料失敗：%s", exc)
            return 1
        snapshot_path = BASE_DIR / "data" / "big_holder_snapshot.json"
        previous = load_previous_snapshot(snapshot_path)
        rows = build_big_holder_rows(watchlist, snapshot, previous)
        message = format_big_holder_message(report_date, previous.get("date") if previous else None, rows)
        if args.dry_run:
            print(message)
            return 0
        if not telegram_enabled and not discord_enabled:
            logger.error("Telegram 與 Discord 通知皆已關閉")
            return 1
        if telegram_enabled and (not token or not chat_id):
            logger.error("Telegram 已啟用但未設定 TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID")
            return 1
        state = NotificationState(BASE_DIR / "data" / "notification_state.sqlite3")
        delivered = send_report(
            token, chat_id, report_date, "big_holders", message, state, args.force,
            notification_cfg.get("enable_ack_button", False), notification_cfg.get("max_retries", 3), telegram_enabled, discord_enabled,
        )
        if delivered:
            save_snapshot(snapshot_path, report_date, snapshot)
        return 0 if delivered else 1

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
        if not telegram_enabled and not discord_enabled:
            logger.error("Telegram 與 Discord 通知皆已關閉")
            return 1
        if telegram_enabled and (not token or not chat_id):
            logger.error("Telegram 已啟用但未設定 TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID")
            return 1
        notification_cfg = config.get("notification", {})
        if not notification_cfg.get("send_event_alerts", True):
            logger.info("自選股事件通知已關閉")
            return 0
        codes = {str(item.get("code", "")).strip() for item in get_watchlist(config)}
        state = NotificationState(BASE_DIR / "data" / "notification_state.sqlite3")
        sent = 0
        for event in [
            *collect_watchlist_events(codes),
            *collect_corporate_action_events(codes),
            *collect_monthly_revenue_events(codes),
        ]:
            if "disposition_id" in event:
                state.track_disposition(
                    event["disposition_id"], event["market"], event["code"], event["name"],
                    event["start_date"], event["end_date"], event["reason"],
                )
            if state.event_was_notified(event["id"]):
                continue
            if args.dry_run:
                print(event["text"] + "\n")
                sent += 1
                continue
            delivered = False
            if telegram_enabled:
                delivered = send_telegram_message(token, chat_id, event["text"], max_retries=notification_cfg.get("max_retries", 3)).success
            if discord_enabled:
                delivered = send_discord_message(os.getenv("DISCORD_WEBHOOK_URL", "").strip(), event["text"], max_retries=notification_cfg.get("max_retries", 3)).success or delivered
            if delivered:
                state.record_event_notification(event["id"])
                sent += 1
            else:
                logger.error("事件通知發送失敗：%s", result.error)
        for disposition_id, market, code, name, start_date, end_date, reason in state.pending_disposition_exits(datetime.date.today().isoformat()):
            text = (
                f"🟢 *【處置結束｜{market}】*\n📌 *{code} {name}*\n"
                f"處置期間 `{start_date}` ～ `{end_date}` 已結束。"
            )
            if args.dry_run:
                print(text + "\n")
                sent += 1
                continue
            delivered = False
            if telegram_enabled:
                delivered = send_telegram_message(token, chat_id, text, max_retries=notification_cfg.get("max_retries", 3)).success
            if discord_enabled:
                delivered = send_discord_message(os.getenv("DISCORD_WEBHOOK_URL", "").strip(), text, max_retries=notification_cfg.get("max_retries", 3)).success or delivered
            if delivered:
                state.record_disposition_exit(disposition_id)
                sent += 1
            else:
                logger.error("處置結束通知發送失敗：%s", result.error)
        logger.info("自選股事件檢查完成，新通知 %s 則", sent)
        return 0

    if args.morning_calendar:
        try:
            start_date = datetime.datetime.strptime(args.date, "%Y%m%d").date() if args.date else datetime.date.today()
        except ValueError:
            logger.error("行事曆日期格式錯誤，請使用 YYYYMMDD")
            return 1
        codes = {str(item.get("code", "")).strip() for item in get_watchlist(config)}
        items = collect_morning_calendar(codes, start_date)
        if not items:
            logger.info("未來 7 天沒有已公告的自選股行事")
            return 0
        message = format_morning_calendar(start_date, items)
        if args.dry_run:
            print(message)
            return 0
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        notification_cfg = config.get("notification", {})
        if not notification_cfg.get("send_morning_calendar", True):
            logger.info("開盤前行事曆推播已關閉")
            return 0
        state = NotificationState(BASE_DIR / "data" / "notification_state.sqlite3")
        trade_date = start_date.strftime("%Y%m%d")
        return 0 if send_report(
            token, chat_id, trade_date, "morning_calendar", message, state, args.force,
            notification_cfg.get("enable_ack_button", True), notification_cfg.get("max_retries", 3), telegram_enabled, discord_enabled,
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
        notification_cfg = config.get("notification", {})
        if not notification_cfg.get("send_market_amount_summary", True):
            logger.info("上市大盤法人金額推播已關閉")
            return 0
        state = NotificationState(BASE_DIR / "data" / "notification_state.sqlite3")
        return 0 if send_report(
            token, chat_id, trade_date, "market_amount", message, state, args.force,
            notification_cfg.get("enable_ack_button", True), notification_cfg.get("max_retries", 3), telegram_enabled, discord_enabled,
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
    watchlist_items = get_watchlist(config)
    watchlist_results = analyze_watchlist(records, watchlist_items)
    if config.get("notification", {}).get("send_daily_margin", True):
        watchlist_results = add_margin_data(watchlist_results, get_margin_balances(trade_date))
    disposition_periods = get_active_disposition_periods({item["code"] for item in watchlist_results})
    for item in watchlist_results:
        if period := disposition_periods.get(item["code"]):
            item["disposition_period"] = period
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

    if not telegram_enabled and not discord_enabled:
        logger.warning("Telegram 與 Discord 通知皆已關閉。")
        return 1
    if telegram_enabled and (not token or not chat_id):
        logger.warning("Telegram 已啟用但未設定 Token 或 Chat ID。")
        return 1

    notification_cfg = config.get("notification", {})
    enable_ack_button = notification_cfg.get("enable_ack_button", True)
    max_retries = notification_cfg.get("max_retries", 3)
    state = NotificationState(BASE_DIR / "data" / "notification_state.sqlite3")
    sent_ok = True

    # 發送自選股
    if notification_cfg.get("send_watchlist", True):
        logger.info("正在推送自選股分析報告至 Telegram...")
        sent_ok &= send_report(token, chat_id, trade_date, "watchlist", watchlist_msg, state, args.force, enable_ack_button, max_retries, telegram_enabled, discord_enabled)

    # 發送策略選股
    if notification_cfg.get("send_screener", True):
        logger.info("正在推送籌碼策略榜單至 Telegram...")
        if screener_cfg.get("enable_dual_buyers", True) or screener_cfg.get("enable_it_top", True):
            sent_ok &= send_report(token, chat_id, trade_date, "screener", screener_msg, state, args.force, enable_ack_button, max_retries, telegram_enabled, discord_enabled)

    if not sent_ok:
        logger.error("=== 部分或全部推播失敗 ===")
        return 1
    logger.info("=== 籌碼分析與推播程序完成 ===")
    return 0

if __name__ == "__main__":
    sys.exit(main())
