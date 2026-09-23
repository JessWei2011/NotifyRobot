import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

def is_common_stock(code: str) -> bool:
    """判斷是否為一般普通股代號 (4位純數字，過濾權證或特別股)"""
    return len(code) == 4 and code.isdigit()

def analyze_watchlist(records: List[Dict[str, Any]], watchlist_items: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """
    自選股比對分析
    :param records: 當日全部上市股票籌碼資料
    :param watchlist_items: [{"code": "2330", "name": "台積電"}, ...]
    :return: 自選股的詳細法人動態
    """
    # 建立以股票代碼為鍵的快速查表
    record_map = {r["code"]: r for r in records}
    results = []

    for item in watchlist_items:
        code = str(item.get("code")).strip()
        custom_name = item.get("name", "")

        if code in record_map:
            stock_data = record_map[code]
            results.append({
                "code": code,
                "name": stock_data["name"] or custom_name,
                "foreign_lots": stock_data["foreign_lots"],
                "trust_lots": stock_data["trust_lots"],
                "dealer_lots": stock_data["dealer_lots"],
                "total_lots": stock_data["total_lots"],
            })
        else:
            results.append({
                "code": code,
                "name": custom_name or "未取得名稱",
                "foreign_lots": 0,
                "trust_lots": 0,
                "dealer_lots": 0,
                "total_lots": 0,
                "not_found": True
            })

    return results


def add_margin_data(items: List[Dict[str, Any]], margin_balances: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """將每日融資餘額附加至自選股結果；無信用交易資料時保持空白。"""
    for item in items:
        item.update(margin_balances.get(item["code"], {}))
    return items

def filter_dual_buyers(records: List[Dict[str, Any]], top_n: int = 10, min_lots: int = 300) -> List[Dict[str, Any]]:
    """
    策略一：外資與投信同步買超 (土洋同步作多)
    條件：
    1. 外資 > 0 且 投信 > 0
    2. 外資 + 投信買超張數合計 >= min_lots
    3. 優先挑選 4 位數之普通股
    4. 依 (外資+投信) 合計買超張數由大到小排序
    """
    candidates = []
    for r in records:
        if not is_common_stock(r["code"]):
            continue

        f_lots = r["foreign_lots"]
        t_lots = r["trust_lots"]

        if f_lots > 0 and t_lots > 0:
            dual_total = f_lots + t_lots
            if dual_total >= min_lots:
                candidates.append({
                    **r,
                    "dual_total": dual_total
                })

    # 依照外資+投信合計買超排序
    candidates.sort(key=lambda x: x["dual_total"], reverse=True)
    return candidates[:top_n]

def filter_total_top_buyers(records: List[Dict[str, Any]], top_n: int = 10) -> List[Dict[str, Any]]:
    """三大法人合計買超 TOP N"""
    candidates = [r for r in records if is_common_stock(r["code"]) and r["total_lots"] > 0]
    candidates.sort(key=lambda x: x["total_lots"], reverse=True)
    return candidates[:top_n]

def filter_dual_top_buyers(records: List[Dict[str, Any]], top_n: int = 10) -> List[Dict[str, Any]]:
    """外資＋投信同步買超 TOP N（土洋合作：外資 > 0 且 投信 > 0）"""
    candidates = []
    for r in records:
        if not is_common_stock(r["code"]):
            continue
        f_lots = r["foreign_lots"]
        t_lots = r["trust_lots"]
        if f_lots > 0 and t_lots > 0:
            candidates.append({**r, "dual_total": f_lots + t_lots})
    candidates.sort(key=lambda x: x["dual_total"], reverse=True)
    return candidates[:top_n]

def filter_foreign_top_buyers(records: List[Dict[str, Any]], top_n: int = 10) -> List[Dict[str, Any]]:
    """外資買超 TOP N"""
    candidates = [r for r in records if is_common_stock(r["code"]) and r["foreign_lots"] > 0]
    candidates.sort(key=lambda x: x["foreign_lots"], reverse=True)
    return candidates[:top_n]

def filter_it_top_buyers(records: List[Dict[str, Any]], top_n: int = 10) -> List[Dict[str, Any]]:
    """投信買超 TOP N"""
    candidates = [
        r for r in records 
        if is_common_stock(r["code"]) and r["trust_lots"] > 0
    ]
    candidates.sort(key=lambda x: x["trust_lots"], reverse=True)
    return candidates[:top_n]

def filter_dual_top_sellers(records: List[Dict[str, Any]], top_n: int = 10) -> List[Dict[str, Any]]:
    """外資＋投信同步賣超 TOP N（土洋同步賣超：外資 < 0 且 投信 < 0）"""
    candidates = []
    for r in records:
        if not is_common_stock(r["code"]):
            continue
        f_lots = r["foreign_lots"]
        t_lots = r["trust_lots"]
        if f_lots < 0 and t_lots < 0:
            candidates.append({**r, "dual_total": f_lots + t_lots})
    candidates.sort(key=lambda x: x["dual_total"])
    return candidates[:top_n]

def filter_foreign_top_sellers(records: List[Dict[str, Any]], top_n: int = 10) -> List[Dict[str, Any]]:
    """外資賣超 TOP N（賣超最多排最前）"""
    candidates = [r for r in records if is_common_stock(r["code"]) and r["foreign_lots"] < 0]
    candidates.sort(key=lambda x: x["foreign_lots"])
    return candidates[:top_n]

def filter_it_top_sellers(records: List[Dict[str, Any]], top_n: int = 10) -> List[Dict[str, Any]]:
    """投信賣超 TOP N（賣超最多排最前）"""
    candidates = [r for r in records if is_common_stock(r["code"]) and r["trust_lots"] < 0]
    candidates.sort(key=lambda x: x["trust_lots"])
    return candidates[:top_n]


def _get_streak(series: List[Dict[str, Any]], key: str) -> tuple[int, int]:
    """由最新交易日往回推算連續買超天數與期間累積買超張數。"""
    streak = 0
    accum_lots = 0
    for item in reversed(series):
        lots = item.get(key, 0)
        if lots > 0:
            streak += 1
            accum_lots += lots
        else:
            break
    return streak, accum_lots


def calculate_consecutive_buyers(
    history_by_code: Dict[str, List[Dict[str, Any]]],
    min_days: int = 5,
    top_n: int = 10,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    計算外資、投信與外資+投信雙連買 >= min_days 的前 top_n 名。
    天數越多名次越高；天數相同時依累積買超張數降序排列。
    """
    foreign_list = []
    trust_list = []
    dual_list = []

    for code, series in history_by_code.items():
        if not is_common_stock(code) or not series:
            continue
        name = series[-1].get("name", code)
        today_record = series[-1]

        f_days, f_accum = _get_streak(series, "foreign_lots")
        t_days, t_accum = _get_streak(series, "trust_lots")

        if f_days >= min_days:
            foreign_list.append({
                "code": code,
                "name": name,
                "days": f_days,
                "accum_lots": f_accum,
                "today_lots": today_record.get("foreign_lots", 0),
            })

        if t_days >= min_days:
            trust_list.append({
                "code": code,
                "name": name,
                "days": t_days,
                "accum_lots": t_accum,
                "today_lots": today_record.get("trust_lots", 0),
            })

        if f_days >= min_days and t_days >= min_days:
            min_days_both = min(f_days, t_days)
            dual_list.append({
                "code": code,
                "name": name,
                "foreign_days": f_days,
                "trust_days": t_days,
                "dual_days": min_days_both,
                "foreign_accum": f_accum,
                "trust_accum": t_accum,
                "total_accum": f_accum + t_accum,
                "today_foreign": today_record.get("foreign_lots", 0),
                "today_trust": today_record.get("trust_lots", 0),
            })

    # 排序：天數越多越優先，天數相同時累積張數多者優先
    foreign_list.sort(key=lambda x: (x["days"], x["accum_lots"]), reverse=True)
    trust_list.sort(key=lambda x: (x["days"], x["accum_lots"]), reverse=True)
    dual_list.sort(key=lambda x: (x["dual_days"], x["foreign_days"] + x["trust_days"], x["total_accum"]), reverse=True)

    return {
        "foreign": foreign_list[:top_n],
        "trust": trust_list[:top_n],
        "dual": dual_list[:top_n],
    }

