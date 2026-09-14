"""集保戶股權分散表：每週大戶籌碼快照與比較。"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

import requests
import urllib3


TDCC_URL = "https://smart.tdcc.com.tw/opendata/getOD.ashx?id=1-5"
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _number(value: object) -> float:
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def fetch_big_holder_snapshot(codes: set[str]) -> tuple[str, dict[str, dict[str, Any]]]:
    """取得集保最新週資料；400~999 張為級距 11~13，千張以上為級距 14。"""
    response = requests.get(TDCC_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=45, verify=False)
    response.raise_for_status()
    rows = csv.DictReader(io.StringIO(response.text.lstrip("\ufeff")))
    result: dict[str, dict[str, Any]] = {}
    report_date = ""
    for row in rows:
        code = str(row.get("證券代號", "")).strip()
        if code not in codes:
            continue
        report_date = str(row.get("資料日期", "")).strip() or report_date
        level = int(_number(row.get("持股分級")))
        if level not in {11, 12, 13, 14}:
            continue
        stock = result.setdefault(code, {"holders_400": 0, "shares_400": 0, "ratio_400": 0.0, "holders_1000": 0, "shares_1000": 0, "ratio_1000": 0.0})
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
        row = {"code": code, "name": item.get("name", code), **stock}
        for group in ("400", "1000"):
            row[f"lots_{group}"] = round(stock[f"shares_{group}"] / 1000)
            row[f"ratio_change_{group}"] = None if old is None else stock[f"ratio_{group}"] - _number(old.get(f"ratio_{group}"))
            row[f"holders_change_{group}"] = None if old is None else stock[f"holders_{group}"] - int(_number(old.get(f"holders_{group}")))
        rows.append(row)
    return rows
