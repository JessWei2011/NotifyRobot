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
                elif any(word in subject for word in ("財務報告", "第1季", "第2季", "第3季", "第4季", "通報", "提報董事會", "決議通過")):
                    title = "財報／財務報告公告"
                elif any(word in subject for word in ("自結", "損益")):
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
    """讀取官方最新月營收，僅針對自選股「當日（或最近發布日）最新出表」之營收發送一次性公告提醒。"""
    events: List[Dict[str, str]] = []
    today_dt = datetime.date.today()
    # 台灣官方「出表日期」為民國年月日格式，如 1151006
    roc_year = today_dt.year - 1911
    today_roc = f"{roc_year}{today_dt.month:02d}{today_dt.day:02d}"
    
    # 計算期望之最新月營收月份（上個月），如 10 月發布 9 月營收 (11509)
    first_of_month = today_dt.replace(day=1)
    last_month_dt = first_of_month - datetime.timedelta(days=1)
    expected_month_roc = f"{last_month_dt.year - 1911}{last_month_dt.month:02d}"

    sources = [
        ("上市", False, f"{TWSE}/opendata/t187ap05_L"),
        ("上櫃", True, f"{TPEX}/t187ap05_R"),
    ]
    for market, is_tpex, url in sources:
        for item in _fetch(url, tpex=is_tpex):
            code = _value(item, "公司代號", "Code", "SecuritiesCompanyCode")
            if code not in watchlist_codes:
                continue
            month = _value(item, "資料年月").strip()
            report_date = _value(item, "出表日期").strip()

            # 核心防呆：
            # 1. 資料年月必須至少是最近一個月的月營收（避免交易所歷史舊資料如 8 月營收重複推送）
            if month < expected_month_roc:
                continue

            # 2. 出表日期必須是當日發布，或是當月新申報（若為舊出表日則不應視為今日新公告）
            if report_date and report_date != today_roc:
                continue

            name = _value(item, "公司名稱", "Name", "CompanyName")
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


def _fetch_earnings_calls(watchlist_codes: Set[str]) -> List[Dict[str, str]]:
    """爬取 Yahoo 股市法人說明會行事曆中屬於自選股的法說會日程。"""
    url = "https://tw.stock.yahoo.com/calendar/earnings-call"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }
    calls: List[Dict[str, str]] = []
    try:
        from bs4 import BeautifulSoup
        resp = requests.get(url, headers=headers, timeout=20)
        if resp.status_code != 200:
            logger.warning("法說會行事曆抓取失敗 (HTTP %s)", resp.status_code)
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
        links = soup.find_all("a", href=lambda h: h and "/quote/" in h)
        for a in links:
            m = re.search(r"/quote/([0-9]{4,6})", a.get("href", ""))
            if not m:
                continue
            code = m.group(1)
            if code not in watchlist_codes:
                continue
            row = a.find_parent("li") or a.find_parent("div", class_=lambda c: c and any(k in str(c).lower() for k in ("table", "row", "item")))
            if not row:
                continue
            text = row.get_text(" | ", strip=True)
            parts = [p.strip() for p in text.split("|") if p.strip()]
            dt_str = next((p for p in parts if re.search(r"\d{4}/\d{2}/\d{2}", p)), "")
            if not dt_str:
                continue
            # dt_str format: "YYYY/MM/DD HH:MM" or "YYYY/MM/DD"
            date_part = dt_str.split()[0].replace("/", "-")
            time_part = dt_str.split()[1] if len(dt_str.split()) > 1 else ""
            name = a.get_text(strip=True) or (parts[0] if parts else code)
            desc = parts[-1] if len(parts) >= 4 else "法人說明會"
            calls.append({
                "code": code,
                "name": name,
                "date": date_part,
                "time": time_part,
                "desc": desc,
            })
    except Exception as exc:
        logger.warning("爬取法人說明會行事曆時發生例外：%s", exc)
    return calls


def collect_morning_calendar(watchlist_codes: Set[str], start_date: datetime.date, days: int = 7) -> List[str]:
    """取得未來指定天數內、已公告的自選股除權息與法說會行事。"""
    end_date = start_date + datetime.timedelta(days=days)
    items: List[str] = []

    # 1. 除權、除息／配息行事
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

    # 2. 法人說明會 (法說會) 行事
    for call in _fetch_earnings_calls(watchlist_codes):
        try:
            event_date = datetime.date.fromisoformat(call["date"])
        except ValueError:
            continue
        if start_date <= event_date <= end_date:
            time_info = f" {call['time']}" if call["time"] else ""
            is_today = "【今日】" if event_date == start_date else ""
            items.append(
                f"🎤 `{call['date']}{time_info}`｜*{call['code']} {call['name']}* {is_today}法人說明會：{call['desc']}"
            )

    # 3. 每月 10 號為上月營收申報法定截止日（檢查當月及次月 10 號是否落在提醒區間）
    this_month_deadline = start_date.replace(day=10)
    next_month = start_date.replace(day=28) + datetime.timedelta(days=4)
    next_month_deadline = next_month.replace(day=10)
    for deadline in (this_month_deadline, next_month_deadline):
        if start_date <= deadline <= end_date:
            items.append(f"📅 `{deadline.isoformat()}`｜上月營收申報截止提醒（實際以公開資訊觀測站公告為準）")

    # 4. 法定季報與年報申報截止日提醒（Q1: 5/15, Q2: 8/14, Q3: 11/14, 年報/Q4: 3/31）
    current_year = start_date.year
    report_deadlines = [
        (datetime.date(current_year, 3, 31), f"{current_year - 1} 年度財報申報截止"),
        (datetime.date(current_year, 5, 15), f"{current_year} 年 Q1 第一季財報申報截止"),
        (datetime.date(current_year, 8, 14), f"{current_year} 年 Q2 第二季財報申報截止"),
        (datetime.date(current_year, 11, 14), f"{current_year} 年 Q3 第三季財報申報截止"),
        (datetime.date(current_year + 1, 3, 31), f"{current_year} 年度財報申報截止"),
    ]
    for dl_date, desc in report_deadlines:
        if start_date <= dl_date <= end_date:
            items.append(f"📊 `{dl_date.isoformat()}`｜【重大財報期限】{desc}")

    return sorted(items)


def format_morning_calendar(start_date: datetime.date, items: List[str]) -> str:
    calendar_items = items or ["📭 今日無已公告的自選股行事。"]
    lines = [
        "🌅 *【自選股開盤前行事曆】*",
        f"📅 範圍：`{start_date.isoformat()}` 起 7 天",
        "──────────────────────",
        *calendar_items,
        "──────────────────────",
        "💡 包含自選股法說會日程、除權息、營收申報與季報財報法定截止期限。",
    ]
    return "\n".join(lines)

