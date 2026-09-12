import datetime
import logging
import requests
import time
import certifi
from typing import Optional, Tuple, List, Dict, Any

logger = logging.getLogger(__name__)

def _clean_int(val_str: str) -> int:
    """清理逗號字串並轉換為整數"""
    if not val_str:
        return 0
    cleaned = str(val_str).replace(",", "").strip()
    try:
        return int(cleaned)
    except ValueError:
        return 0

def fetch_twse_t86_for_date(date_str: str) -> Optional[List[Dict[str, Any]]]:
    """
    抓取指定日期的證交所 T86 三大法人買賣超日報
    :param date_str: YYYYMMDD 格式字串
    :return: 股票籌碼資料清單，若無資料或尚未產生則回傳 None
    """
    url = f"https://www.twse.com.tw/rwd/zh/fund/T86?date={date_str}&selectType=ALL&response=json"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        res = requests.get(url, headers=headers, timeout=15)
        res.raise_for_status()
        data = res.json()

        if data.get("stat") != "OK":
            logger.info(f"日期 {date_str} 無資料或非交易日: {data.get('stat')}")
            return None

        raw_rows = data.get("data", [])
        parsed_records = []

        for row in raw_rows:
            if len(row) < 19:
                continue

            code = str(row[0]).strip()
            name = str(row[1]).strip()

            # 外陸資買賣超股數(不含外資自營商): index 4
            # 外資自營商買賣超股數: index 7
            # 投信買賣超股數: index 10
            # 自營商買賣超股數: index 11
            # 三大法人買賣超股數: index 18
            foreign_shares = _clean_int(row[4]) + _clean_int(row[7])
            trust_shares = _clean_int(row[10])
            dealer_shares = _clean_int(row[11])
            total_shares = _clean_int(row[18])

            # 換算為張數 (1張 = 1,000股)
            record = {
                "code": code,
                "name": name,
                "foreign_shares": foreign_shares,
                "trust_shares": trust_shares,
                "dealer_shares": dealer_shares,
                "total_shares": total_shares,
                "foreign_lots": round(foreign_shares / 1000),
                "trust_lots": round(trust_shares / 1000),
                "dealer_lots": round(dealer_shares / 1000),
                "total_lots": round(total_shares / 1000),
            }
            parsed_records.append(record)

        logger.info(f"成功取得 {date_str} 盤後籌碼，共 {len(parsed_records)} 檔上市證券")
        return parsed_records

    except Exception as e:
        logger.error(f"抓取 TWSE T86 失敗 ({date_str}): {e}")
        return None


def fetch_tpex_t86_for_date(date_str: str) -> Optional[List[Dict[str, Any]]]:
    """抓取指定日期的櫃買中心上櫃三大法人買賣超日報。"""
    try:
        date = datetime.datetime.strptime(date_str, "%Y%m%d").date()
    except ValueError:
        logger.error("上櫃資料日期格式錯誤: %s", date_str)
        return None

    roc_date = f"{date.year - 1911:03d}/{date.month:02d}/{date.day:02d}"
    url = (
        "https://www.tpex.org.tw/web/stock/3insti/daily_trade/"
        f"3itrade_hedge_result.php?l=zh-tw&o=json&d={roc_date}&s=0,1,8"
    )
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

    try:
        # 明確使用 certifi 的可信憑證庫，並重試暫時性的 TPEX 憑證鏈／連線問題。
        payload = None
        last_error = None
        for attempt in range(3):
            try:
                res = requests.get(url, headers=headers, timeout=15, verify=certifi.where())
                res.raise_for_status()
                payload = res.json()
                break
            except requests.RequestException as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(attempt + 1)
        if payload is None:
            raise last_error or RuntimeError("TPEX 未回傳資料")
        if str(payload.get("stat", "")).lower() != "ok":
            logger.info("日期 %s 無上櫃資料: %s", date_str, payload.get("stat"))
            return None

        tables = payload.get("tables", [])
        rows = tables[0].get("data", []) if tables else []
        parsed_records = []
        for row in rows:
            if len(row) < 24:
                continue
            foreign_shares = _clean_int(row[10])
            trust_shares = _clean_int(row[13])
            dealer_shares = _clean_int(row[22])
            total_shares = _clean_int(row[23])
            parsed_records.append({
                "code": str(row[0]).strip(),
                "name": str(row[1]).strip(),
                "foreign_shares": foreign_shares,
                "trust_shares": trust_shares,
                "dealer_shares": dealer_shares,
                "total_shares": total_shares,
                "foreign_lots": round(foreign_shares / 1000),
                "trust_lots": round(trust_shares / 1000),
                "dealer_lots": round(dealer_shares / 1000),
                "total_lots": round(total_shares / 1000),
            })
        logger.info("成功取得 %s 上櫃籌碼，共 %s 檔證券", date_str, len(parsed_records))
        return parsed_records
    except Exception as exc:
        logger.error("抓取 TPEX 三大法人資料失敗 (%s): %s", date_str, exc)
        return None


def summarize_market_institutional_lots(records: List[Dict[str, Any]]) -> Dict[str, int]:
    """由各上市證券的三大法人買賣超加總，回傳大盤淨買賣超張數。"""
    keys = ("foreign", "trust", "dealer", "total")
    return {
        key: round(sum(record[f"{key}_shares"] for record in records) / 1000)
        for key in keys
    }


def fetch_twse_market_institutional_amounts(date_str: str) -> Optional[Dict[str, int]]:
    """取得上市大盤三大法人的淨買賣超金額（元）。"""
    url = f"https://www.twse.com.tw/rwd/zh/fund/BFI82U?response=json&dayDate={date_str}&type=day"
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        payload = response.json()
        if payload.get("stat") != "OK":
            logger.info("日期 %s 無上市大盤法人金額資料: %s", date_str, payload.get("stat"))
            return None
        values = {
            str(row[0]).strip(): _clean_int(row[3])
            for row in payload.get("data", []) if len(row) >= 4
        }
        foreign = values.get("外資及陸資(不含外資自營商)")
        trust = values.get("投信")
        dealer_self = values.get("自營商(自行買賣)")
        dealer_hedge = values.get("自營商(避險)")
        total = values.get("合計")
        if None in (foreign, trust, dealer_self, dealer_hedge, total):
            logger.warning("日期 %s 的上市大盤法人金額欄位不完整", date_str)
            return None
        return {"foreign": foreign, "trust": trust, "dealer": dealer_self + dealer_hedge, "total": total}
    except Exception as exc:
        logger.error("抓取 TWSE 大盤法人金額失敗 (%s): %s", date_str, exc)
        return None


def get_latest_market_institutional_amounts(target_date: Optional[str] = None) -> Tuple[str, Dict[str, int]]:
    """取得指定或最近交易日的上市大盤三大法人買賣超金額。"""
    if target_date:
        summary = fetch_twse_market_institutional_amounts(target_date)
        if summary is None:
            raise ValueError(f"指定日期 {target_date} 查無上市大盤三大法人金額資料")
        return target_date, summary
    today = datetime.date.today()
    for days_back in range(7):
        candidate = today - datetime.timedelta(days=days_back)
        if candidate.weekday() >= 5:
            continue
        date_str = candidate.strftime("%Y%m%d")
        summary = fetch_twse_market_institutional_amounts(date_str)
        if summary is not None:
            return date_str, summary
        time.sleep(0.5)
    raise RuntimeError("無法獲取最近一週的上市大盤三大法人金額資料")

def get_latest_institutional_data(target_date: Optional[str] = None) -> Tuple[str, List[Dict[str, Any]]]:
    """
    獲取最新交易日的盤後三大法人資料。
    若未指定 target_date，會自動由今天往前推尋找最近有資料的交易日。
    """
    if target_date:
        twse_records = fetch_twse_t86_for_date(target_date)
        tpex_records = fetch_tpex_t86_for_date(target_date)
        if twse_records is None and tpex_records is None:
            raise ValueError(f"指定日期 {target_date} 查無三大法人籌碼資料（可能非交易日或尚未公布）")
        return target_date, (twse_records or []) + (tpex_records or [])

    # 自動向前搜尋最近 7 天
    today = datetime.date.today()
    for days_back in range(7):
        candidate_date = today - datetime.timedelta(days=days_back)
        # 跳過週六日
        if candidate_date.weekday() >= 5:
            continue

        date_str = candidate_date.strftime("%Y%m%d")
        logger.info(f"嘗試獲取交易日資料: {date_str}")
        twse_records = fetch_twse_t86_for_date(date_str)
        tpex_records = fetch_tpex_t86_for_date(date_str)
        records = (twse_records or []) + (tpex_records or [])
        if records:
            return date_str, records
        time.sleep(0.5)

    raise RuntimeError("無法獲取最近一週之三大法人籌碼資料，請稍後再試。")
