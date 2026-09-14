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

def filter_it_top_buyers(records: List[Dict[str, Any]], top_n: int = 10) -> List[Dict[str, Any]]:
    """
    策略二：投信買超前 N 大強勢股
    條件：
    1. 投信買超張數 > 0
    2. 優先挑選 4 位數之普通股
    3. 依投信買超張數由大到小排序
    """
    candidates = [
        r for r in records 
        if is_common_stock(r["code"]) and r["trust_lots"] > 0
    ]
    candidates.sort(key=lambda x: x["trust_lots"], reverse=True)
    return candidates[:top_n]
