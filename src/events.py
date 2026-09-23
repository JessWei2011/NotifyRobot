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


def _is_within_recent_calendar_days(value: str, days: int = 2) -> bool:
    """判斷公告日期是否落在今天起往回的指定日曆日範圍內。"""
    try:
        announcement_date = datetime.date.fromisoformat(_roc_to_iso(value))
    except ValueError:
        return False
    age = (datetime.date.today() - announcement_date).days
    return 0 <= age < days


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
                announcement_date = _value(item, "發言日期", "Date")
                if not _is_within_recent_calendar_days(announcement_date):
                    continue
                when = announcement_date + " " + _value(item, "發言時間", "Time")
                if any(word in subject for word in ("法人說明會", "法說會", "業績發表會")):
                    title = "法說會公告"
                elif "自結" in subject:
                    title = "自結損益公告"
                else:
                    title = "自選股重大訊息"
                events.append({"id": _id("major", market, code, when, subject), "text": f"📣 *【{title}｜{market}】*\n📌 *{code} {name}*\n🕒 {when.strip()}\n{subject}"})
            elif kind == "attention":
                detail = _value(item, "TradingInfoForAttention", "TradingInformation", "注意交易資訊")
                date = _value(item, "Date", "公告日期")
                events.append({"id": _id("attention", market, code, date, detail), "text": f"⚠️ *【注意股票｜{market}】*\n📌 *{code} {name}*\n{detail}"})
            else:
                period = _value(item, "DispositionPeriod", "處置期間")
                start, end = _period(period)
                reason = _value(item, "ReasonsOfDisposition", "DispositionReasons", "處置原因")
                base = _id("disposal", market, code, start, end)
                tracking = {
                    "disposition_id": base,
                    "market": market,
                    "code": code,
                    "name": name,
                    "start_date": start,
                    "end_date": end,
                    "reason": reason,
                }
                if start > today:
                    events.append({"id": base + ":notice", "text": f"🚨 *【即將處置｜{market}】*\n📌 *{code} {name}*\n📅 處置期間：`{start}` ～ `{end}`\n原因：{reason}", **tracking})
                elif start == today:
                    events.append({"id": base + ":start", "text": f"🔴 *【處置開始｜{market}】*\n📌 *{code} {name}*\n今日起進入處置，預計至 `{end}`。", **tracking})
                elif start < today == end:
                    events.append({"id": base + ":last_day", "text": f"🟠 *【處置結束日｜{market}】*\n📌 *{code} {name}*\n📅 處置將於今日 `{end}` 結束；若無延長，明日恢復正常交易。", **tracking})
    return events


def collect_monthly_revenue_events(watchlist_codes: Set[str]) -> List[Dict[str, str]]:
    """讀取官方最新月營收，並為自選股建立一次性公告提醒。"""
    events: List[Dict[str, str]] = []
    sources = [
        ("上市", False, f"{TWSE}/opendata/t187ap05_L"),
        ("上櫃", True, f"{TPEX}/t187ap05_R"),
    ]
    for market, is_tpex, url in sources:
        for item in _fetch(url, tpex=is_tpex):
            code = _value(item, "公司代號", "Code", "SecuritiesCompanyCode")
            if code not in watchlist_codes:
                continue
            name = _value(item, "公司名稱", "Name", "CompanyName")
            month = _value(item, "資料年月")
            report_date = _value(item, "出表日期")
            revenue = _value(item, "營業收入-當月營收")
            mom = _value(item, "營業收入-上月比較增減(%)")
            yoy = _value(item, "營業收入-去年同月增減(%)")
            event_id = _id("monthly_revenue", market, code, month, revenue)
            events.append({
                "id": event_id,
                "text": (
                    f"💰 *【月營收公告｜{market}】*\n"
                    f"📌 *{code} {name}*\n"
                    f"📅 資料年月：`{month}`｜公告日：`{report_date}`\n"
                    f"當月營收：`{revenue}`\n"
                    f"月增：`{mom}%`｜年增：`{yoy}%`"
                ),
            })
    return events


def get_active_disposition_periods(watchlist_codes: Set[str]) -> Dict[str, tuple[str, str]]:
    """回傳目前處置中的自選股與其期間，供每日個股報告標示使用。"""
    periods: Dict[str, tuple[str, str]] = {}
    today = datetime.date.today().isoformat()
    for _market, is_tpex, url in (
        ("上市", False, f"{TWSE}/announcement/punish"),
        ("上櫃", True, f"{TPEX}/tpex_disposal_information"),
    ):
        for item in _fetch(url, tpex=is_tpex):
            code = _value(item, "Code", "SecuritiesCompanyCode", "公司代號")
            if code not in watchlist_codes:
                continue
            start, end = _period(_value(item, "DispositionPeriod", "處置期間"))
            if start <= today <= end:
                periods[code] = (start, end)
    return periods


def _has_amount(value: str) -> bool:
    """判斷官方欄位是否為非零金額或配股比率。"""
    try:
        return float(value.replace(",", "")) != 0
    except (ValueError, AttributeError):
        return bool(value and value != "0")


def _corporate_actions(watchlist_codes: Set[str]) -> List[Dict[str, str]]:
    """讀取自選股的除權、除息與股利資料。"""
    actions: List[Dict[str, str]] = []
    sources = [
        ("上市", False, f"{TWSE}/exchangeReport/TWT48U_ALL"),
        ("上櫃", True, f"{TPEX}/tpex_exright_prepost"),
    ]
    for market, is_tpex, url in sources:
        for item in _fetch(url, tpex=is_tpex):
            code = _value(item, "Code", "SecuritiesCompanyCode")
            if code not in watchlist_codes:
                continue
            date = _roc_to_iso(_value(item, "Date", "ExRrightsExDividendDate"))
            name = _value(item, "Name", "CompanyName")
            cash = _value(item, "CashDividend")
            stock = _value(item, "StockDividendRatio")
            labels = []
            if _has_amount(cash):
                labels.append("除息／配息")
            if _has_amount(stock):
                labels.append("除權")
            actions.append({
                "market": market,
                "code": code,
                "name": name,
                "date": date,
                "label": "／".join(labels) or _value(item, "Exdividend", "ExRrightsExDividend") or "除權／息",
                "cash": cash,
                "stock": stock,
            })
    return actions


def _corporate_action_detail(action: Dict[str, str]) -> str:
    details = []
    if _has_amount(action["cash"]):
        details.append(f"現金股利 `{action['cash']}` 元")
    if _has_amount(action["stock"]):
        details.append(f"股票股利 `{action['stock']}`")
    return "；".join(details) or "詳細條件請以交易所公告為準"


def collect_corporate_action_events(watchlist_codes: Set[str]) -> List[Dict[str, str]]:
    """回傳今天除權／息的自選股一次性提醒。"""
    today = datetime.date.today().isoformat()
    events = []
    for action in _corporate_actions(watchlist_codes):
        if action["date"] != today:
            continue
        event_id = _id("corporate_action", action["market"], action["code"], action["date"], action["label"])
        events.append({
            "id": event_id,
            "text": (
                f"🟡 *【今日{action['label']}提醒｜{action['market']}】*\n"
                f"📌 *{action['code']} {action['name']}*\n"
                f"📅 日期：`{action['date']}`\n"
                f"{_corporate_action_detail(action)}"
            ),
        })
    return events


def collect_morning_calendar(watchlist_codes: Set[str], start_date: datetime.date, days: int = 7) -> List[str]:
    """取得未來指定天數內、已公告的自選股除權息行事。"""
    end_date = start_date + datetime.timedelta(days=days)
    items: List[str] = []
    for action in _corporate_actions(watchlist_codes):
        try:
            event_date = datetime.date.fromisoformat(action["date"])
        except ValueError:
            continue
        if start_date <= event_date <= end_date:
            items.append(
                f"📌 `{action['date']}`｜*{action['code']} {action['name']}*"
                f"（{action['market']}）{action['label']}：{_corporate_action_detail(action)}"
            )

    next_month = start_date.replace(day=1) + datetime.timedelta(days=32)
    revenue_deadline = next_month.replace(day=10)
    if start_date <= revenue_deadline <= end_date:
        items.append(f"📅 `{revenue_deadline.isoformat()}`｜上月營收申報截止提醒（實際以公開資訊觀測站公告為準）")
    return sorted(items)


def format_morning_calendar(start_date: datetime.date, items: List[str]) -> str:
    calendar_items = items or ["📭 今日無已公告的自選股行事。"]
    lines = [
        "🌅 *【自選股開盤前行事曆】*",
        f"📅 範圍：`{start_date.isoformat()}` 起 7 天",
        "──────────────────────",
        *calendar_items,
        "──────────────────────",
        "💡 僅列已公告的自選股除權、除息／配息與申報期限；日期以公司正式公告為準。",
    ]
    return "\n".join(lines)
