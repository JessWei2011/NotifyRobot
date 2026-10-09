"""台股交易日與行事曆公用函式。"""

from __future__ import annotations

import datetime
import logging
from typing import Set

import requests

logger = logging.getLogger(__name__)

TWSE_HOLIDAY_URL = "https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule?response=json"

# 快取當年度已知的國定/市場休市日 (格式: YYYY-MM-DD)
_HOLIDAY_CACHE: dict[int, Set[str]] = {}


def fetch_market_holidays(year: int) -> Set[str]:
    """向證交所 API 查詢指定年度的市場休市日（包含國定假日、補假、農曆年無交易日等）。"""
    if year in _HOLIDAY_CACHE:
        return _HOLIDAY_CACHE[year]

    holidays: Set[str] = set()
    try:
        res = requests.get(TWSE_HOLIDAY_URL, timeout=10)
        if res.status_code == 200:
            data = res.json()
            for row in data.get("data", []):
                # row 格式: [日期, 名稱, 說明]
                if len(row) >= 2:
                    d_str = str(row[0]).strip()
                    desc = str(row[1]).strip()

                    # 證交所 API 的規則：除了「開始交易日」和「最後交易日」外，所有列出的日期皆為不交易/休市日
                    if "開始交易" in desc or "最後交易" in desc:
                        continue

                    holidays.add(d_str)

            _HOLIDAY_CACHE[year] = holidays
            logger.info("已取得 TWSE %d 年度休市行事曆，共 %d 個非交易日", year, len(holidays))
    except Exception as exc:
        logger.warning("查詢 TWSE 休市行事曆失敗：%s，將僅以週末判定", exc)

    return holidays


def is_trading_day(d: datetime.date) -> bool:
    """判斷指定日期是否為台股交易日（週一至週五且非休市日）。"""
    if d.weekday() >= 5:  # 5=週六, 6=週日
        return False
    holidays = fetch_market_holidays(d.year)
    return d.isoformat() not in holidays


def get_last_trading_day_of_week(ref_date: datetime.date) -> datetime.date:
    """取得指定日期所在該週（週一至週日）的最後一個台股交易日。

    例如：
    - 一般週：週五開盤，則最後交易日為週五。
    - 連假週：若週五放假，則最後交易日為週四。
    - 若週四週五放假，則最後交易日為週三。
    """
    # 找到該週的週一
    monday = ref_date - datetime.timedelta(days=ref_date.weekday())
    # 從週五往前回溯到週一
    for i in range(4, -1, -1):
        candidate = monday + datetime.timedelta(days=i)
        if is_trading_day(candidate):
            return candidate
    return monday


def should_monitor_big_holders_today(target_date: datetime.date | None = None) -> bool:
    """判斷今日是否應該啟動集保資料監聽。

    原則：
    1. 當天為本週的最後一個交易日（收盤後開始監聽）。
    2. 或當天在該週最後交易日之後（例如放假第一天或週六備援），若當週尚未推播則持續監聽。
    """
    today = target_date or datetime.date.today()
    last_trading_day = get_last_trading_day_of_week(today)

    # 今天是最後交易日或已過最後交易日（且在該週內）
    return today >= last_trading_day
