"""自選股重大訊息、注意與處置警示。"""

import datetime
import hashlib
import logging
import re
import time
from typing import Any, Dict, List, Set

import certifi
import requests

logger = logging.getLogger(__name__)

TWSE = "https://openapi.twse.com.tw/v1"
TPEX = "https://www.tpex.org.tw/openapi/v1"


def _fetch(url: str, *, tpex: bool = False) -> List[Dict[str, Any]]:
    for attempt in range(3):
        try:
            response = requests.get(url, timeout=20, verify=certifi.where() if tpex else True)
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, list) else []
        except requests.RequestException as exc:
            if attempt == 2:
                logger.error("讀取事件資料失敗 (%s): %s", url, exc)
            else:
                time.sleep(attempt + 1)
    return []


def _value(item: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        if item.get(key) not in (None, ""):
            return str(item[key]).strip()
    normalized = {str(key).strip(): value for key, value in item.items()}
    for key in keys:
        value = normalized.get(key.strip())
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _id(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _roc_to_iso(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if len(digits) == 7:
        return f"{int(digits[:3]) + 1911:04d}-{digits[3:5]}-{digits[5:7]}"
    return value


def _period(value: str) -> tuple[str, str]:
    parts = re.split(r"[~～]", value)
    return (_roc_to_iso(parts[0]), _roc_to_iso(parts[-1])) if len(parts) == 2 else (value, value)


def collect_watchlist_events(watchlist_codes: Set[str]) -> List[Dict[str, str]]:
    """讀取官方資料並回傳自選股的新公告、注意與處置事件。"""
    events: List[Dict[str, str]] = []
    sources = [
        ("上市", False, f"{TWSE}/opendata/t187ap04_L", "major"),
        ("上櫃", True, f"{TPEX}/mopsfin_t187ap04_O", "major"),
        ("上市", False, f"{TWSE}/announcement/notice", "attention"),
        ("上櫃", True, f"{TPEX}/tpex_trading_warning_information", "attention"),
        ("上市", False, f"{TWSE}/announcement/punish", "disposal"),
        ("上櫃", True, f"{TPEX}/tpex_disposal_information", "disposal"),
    ]
    today = datetime.date.today().isoformat()
    for market, is_tpex, url, kind in sources:
        for item in _fetch(url, tpex=is_tpex):
            code = _value(item, "Code", "SecuritiesCompanyCode", "公司代號")
            if code not in watchlist_codes:
                continue
            name = _value(item, "Name", "CompanyName", "公司名稱")
            if kind == "major":
                subject = _value(item, "主旨", "Subject")
                when = _value(item, "發言日期", "Date") + " " + _value(item, "發言時間", "Time")
                events.append({"id": _id("major", market, code, when, subject), "text": f"📣 *【自選股重大訊息｜{market}】*\n📌 *{code} {name}*\n🕒 {when.strip()}\n{subject}"})
            elif kind == "attention":
                detail = _value(item, "TradingInfoForAttention", "TradingInformation", "注意交易資訊")
                date = _value(item, "Date", "公告日期")
                events.append({"id": _id("attention", market, code, date, detail), "text": f"⚠️ *【注意股票｜{market}】*\n📌 *{code} {name}*\n{detail}"})
            else:
                period = _value(item, "DispositionPeriod", "處置期間")
                start, end = _period(period)
                reason = _value(item, "ReasonsOfDisposition", "DispositionReasons", "處置原因")
                base = _id("disposal", market, code, start, end)
                if start > today:
                    events.append({"id": base + ":notice", "text": f"🚨 *【即將處置｜{market}】*\n📌 *{code} {name}*\n📅 處置期間：`{start}` ～ `{end}`\n原因：{reason}"})
                elif start == today:
                    events.append({"id": base + ":start", "text": f"🔴 *【處置開始｜{market}】*\n📌 *{code} {name}*\n今日起進入處置，預計至 `{end}`。"})
                elif start < today <= end:
                    events.append({"id": base + ":active", "text": f"🔴 *【處置中｜{market}】*\n📌 *{code} {name}*\n📅 處置期間：`{start}` ～ `{end}`\n原因：{reason}"})
    return events


def collect_morning_calendar(watchlist_codes: Set[str], start_date: datetime.date, days: int = 7) -> List[str]:
    """取得未來指定天數內、已公告的自選股除權息行事。"""
    end_date = start_date + datetime.timedelta(days=days)
    items: List[str] = []
    sources = [
        ("上市", False, f"{TWSE}/exchangeReport/TWT48U_ALL"),
        ("上櫃", True, f"{TPEX}/tpex_exright_prepost"),
    ]
    for market, is_tpex, url in sources:
        for item in _fetch(url, tpex=is_tpex):
            code = _value(item, "Code", "SecuritiesCompanyCode")
            if code not in watchlist_codes:
                continue
            date_value = _value(item, "Date", "ExRrightsExDividendDate")
            iso_date = _roc_to_iso(date_value)
            try:
                event_date = datetime.date.fromisoformat(iso_date)
            except ValueError:
                continue
            if not start_date <= event_date <= end_date:
                continue
            name = _value(item, "Name", "CompanyName")
            kind = _value(item, "Exdividend", "ExRrightsExDividend")
            cash = _value(item, "CashDividend") or "0"
            stock = _value(item, "StockDividendRatio") or "0"
            detail = f"現金股利 {cash} 元"
            if stock not in ("0", "0.00000000"):
                detail += f"；股票股利 {stock}"
            items.append(f"📌 `{iso_date}`｜*{code} {name}*（{market}）{kind}：{detail}")

    next_month = start_date.replace(day=1) + datetime.timedelta(days=32)
    revenue_deadline = next_month.replace(day=10)
    if start_date <= revenue_deadline <= end_date:
        items.append(f"📅 `{revenue_deadline.isoformat()}`｜上月營收申報截止提醒（實際以公開資訊觀測站公告為準）")
    return sorted(items)


def format_morning_calendar(start_date: datetime.date, items: List[str]) -> str:
    lines = [
        "🌅 *【自選股開盤前行事曆】*",
        f"📅 範圍：`{start_date.isoformat()}` 起 7 天",
        "──────────────────────",
        *items,
        "──────────────────────",
        "💡 僅列已公告的自選股除權息與申報期限；日期以公司正式公告為準。",
    ]
    return "\n".join(lines)
