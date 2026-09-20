"""集保戶股權分散表：每週大戶籌碼快照與比較。"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests
import urllib3


TDCC_URL = "https://smart.tdcc.com.tw/opendata/getOD.ashx?id=1-5"
TDCC_ARCHIVE_URL = "https://raw.githubusercontent.com/wirelessr/tdcc-opendata-archive/main/snapshots/{year}/{date}.csv"
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _number(value: object) -> float:
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _parse_big_holder_snapshot(text: str, codes: set[str] | None = None) -> tuple[str, dict[str, dict[str, Any]]]:
    """將集保 CSV 轉為 400~999 張及千張以上兩組快照。"""
    rows = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    result: dict[str, dict[str, Any]] = {}
    report_date = ""
    for row in rows:
        code = str(row.get("證券代號", "")).strip()
        if codes is not None and code not in codes:
            continue
        report_date = str(row.get("資料日期", "")).strip() or report_date
        level = int(_number(row.get("持股分級")))
        if level not in {11, 12, 13, 14}:
            continue
        stock = result.setdefault(
            code,
            {
                "name": str(row.get("證券名稱", "")).strip() or code,
                "holders_400": 0,
                "shares_400": 0,
                "ratio_400": 0.0,
                "holders_1000": 0,
                "shares_1000": 0,
                "ratio_1000": 0.0,
            },
        )
        if level in {11, 12, 13}:
            stock["holders_400"] += int(_number(row.get("人數")))
            stock["shares_400"] += int(_number(row.get("股數")))
            stock["ratio_400"] += _number(row.get("占集保庫存數比例%"))
        else:
            stock["holders_1000"] += int(_number(row.get("人數")))
            stock["shares_1000"] += int(_number(row.get("股數")))
            stock["ratio_1000"] += _number(row.get("占集保庫存數比例%"))
    if not report_date:
        raise RuntimeError("集保資料未包含指定自選股，無法建立大戶快照")
    return report_date, result


def fetch_big_holder_snapshot(codes: set[str] | None = None) -> tuple[str, dict[str, dict[str, Any]]]:
    """取得集保最新週資料；``codes=None`` 時保留全市場資料。"""
    response = requests.get(TDCC_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=45, verify=False)
    response.raise_for_status()
    return _parse_big_holder_snapshot(response.text, codes)


def fetch_previous_market_snapshot(report_date: str) -> tuple[str, dict[str, dict[str, Any]]]:
    """由每週原始 CSV 封存回補上一個可用集保資料日（最多往前兩週）。"""
    try:
        latest = datetime.strptime(report_date, "%Y%m%d").date()
    except ValueError as exc:
        raise RuntimeError(f"集保資料日期格式錯誤：{report_date}") from exc

    for days_back in range(1, 15):
        candidate = latest - timedelta(days=days_back)
        url = TDCC_ARCHIVE_URL.format(year=candidate.year, date=candidate.isoformat())
        response = requests.get(url, headers={"User-Agent": "NotifyRobot/1.0"}, timeout=45)
        if response.status_code == 404:
            continue
        response.raise_for_status()
        archived_date, snapshot = _parse_big_holder_snapshot(response.text)
        if archived_date < report_date:
            return archived_date, snapshot
    raise RuntimeError(f"找不到 {report_date} 前一週的集保全市場快照")


def load_previous_snapshot(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def save_snapshot(path: Path, report_date: str, stocks: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"date": report_date, "stocks": stocks}, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def build_big_holder_rows(
    watchlist: list[dict[str, str]],
    current: dict[str, dict[str, Any]],
    previous: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    previous_stocks = (previous or {}).get("stocks", {})
    rows: list[dict[str, Any]] = []
    for item in watchlist:
        code = str(item.get("code", "")).strip()
        if code not in current:
            continue
        stock = current[code]
        old = previous_stocks.get(code)
        # 快照只用於數值比較；名稱應以 config／永豐等較可靠的自選股來源為準。
        row = {**stock, "code": code, "name": item.get("name", code)}
        for group in ("400", "1000"):
            row[f"lots_{group}"] = round(stock[f"shares_{group}"] / 1000)
            row[f"ratio_change_{group}"] = None if old is None else stock[f"ratio_{group}"] - _number(old.get(f"ratio_{group}"))
            row[f"holders_change_{group}"] = None if old is None else stock[f"holders_{group}"] - int(_number(old.get(f"holders_{group}")))
        rows.append(row)
    return rows


def build_big_holder_rankings(
    current: dict[str, dict[str, Any]],
    previous: dict[str, Any] | None,
    limit: int = 10,
    allowed_codes: set[str] | None = None,
) -> dict[str, list[dict[str, Any]]] | None:
    """依本週持股比例增幅，產生 400~999 張及千張大戶全市場排行。"""
    previous_stocks = (previous or {}).get("stocks", {})
    if not previous_stocks:
        return None

    rankings: dict[str, list[dict[str, Any]]] = {}
    for group in ("400", "1000"):
        changes: list[dict[str, Any]] = []
        for code, stock in current.items():
            # 全市場排行維持「個股」範圍，排除 ETF、權證、債券與其他非普通股商品。
            if not (code.isdigit() and len(code) == 4):
                continue
            if allowed_codes is not None and code not in allowed_codes:
                continue
            old = previous_stocks.get(code)
            if old is None:
                continue
            change = stock[f"ratio_{group}"] - _number(old.get(f"ratio_{group}"))
            if change <= 0:
                continue
            changes.append(
                {
                    "code": code,
                    "name": str(stock.get("name", code)).strip() or code,
                    "ratio": stock[f"ratio_{group}"],
                    "change": change,
                }
            )
        rankings[group] = sorted(changes, key=lambda item: item["change"], reverse=True)[:limit]
    return rankings
