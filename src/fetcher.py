import concurrent.futures
import datetime
import logging
import re
import requests
import time
import certifi
from bs4 import BeautifulSoup
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

def fetch_twse_t86_for_date(date_str: str, max_retries: int = 3) -> Optional[List[Dict[str, Any]]]:
    """
    抓取指定日期的證交所 T86 三大法人買賣超日報
    :param date_str: YYYYMMDD 格式字串
    :param max_retries: 最大重試次數
    :return: 股票籌碼資料清單，若無資料或尚未產生則回傳 None
    """
    url = f"https://www.twse.com.tw/rwd/zh/fund/T86?date={date_str}&selectType=ALL&response=json"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    last_error = None
    for attempt in range(max_retries):
        try:
            res = requests.get(url, headers=headers, timeout=20)
            res.raise_for_status()

            if not res.text or not res.text.strip():
                raise ValueError("TWSE 回傳內容為空")

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
            last_error = e
            if attempt < max_retries - 1:
                logger.warning(f"抓取 TWSE T86 失敗 ({date_str})，第 {attempt + 1}/{max_retries} 次重試...: {e}")
                time.sleep(2 * (attempt + 1))

    logger.error(f"抓取 TWSE T86 最終失敗 ({date_str}): {last_error}")
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
        return {
            "foreign": foreign,
            "trust": trust,
            "dealer": dealer_self,  # 排除避險，僅計自行買賣
            "dealer_self": dealer_self,
            "dealer_hedge": dealer_hedge,
            "total": foreign + trust + dealer_self,  # 排除避險合計
            "twse_total": total,  # 證交所官方含避險合計
        }
    except Exception as exc:
        logger.error("抓取 TWSE 大盤法人金額失敗 (%s): %s", date_str, exc)
        return None


def get_latest_market_institutional_amounts(target_date: Optional[str] = None) -> Tuple[str, Dict[str, int]]:
    """取得指定日或今天的上市大盤三大法人買賣超金額。

    未指定日期時絕不回退至前一交易日，避免即時通知誤發舊資料。
    """
    if target_date:
        summary = fetch_twse_market_institutional_amounts(target_date)
        if summary is None:
            raise ValueError(f"指定日期 {target_date} 查無上市大盤三大法人金額資料")
        return target_date, summary
    today = datetime.date.today()
    if today.weekday() >= 5:
        raise RuntimeError("今天不是交易日，不發送上市大盤法人金額")
    date_str = today.strftime("%Y%m%d")
    summary = fetch_twse_market_institutional_amounts(date_str)
    if summary is None:
        raise RuntimeError(f"當日上市大盤法人金額尚未公布（{date_str}），本次不發送")
    return date_str, summary

def get_latest_institutional_data(target_date: Optional[str] = None) -> Tuple[str, List[Dict[str, Any]]]:
    """
    獲取最新交易日的盤後三大法人資料。
    若未指定 target_date，會自動由今天往前推尋找最近有資料的交易日。
    """
    if target_date:
        twse_records = fetch_twse_t86_for_date(target_date)
        tpex_records = fetch_tpex_t86_for_date(target_date)
        # 上櫃有公布但上市失敗時，主動延遲再嘗試補抓一次
        if twse_records is None and tpex_records is not None:
            logger.warning(f"指定日期 {target_date} 僅取得上櫃資料而無上市資料，嘗試再次補抓 TWSE...")
            time.sleep(3)
            twse_records = fetch_twse_t86_for_date(target_date, max_retries=3)

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

        # 若上櫃成功但上市失敗，一般交易日通常兩者皆有，進行二次補抓
        if twse_records is None and tpex_records is not None:
            logger.warning(f"日期 {date_str} 僅取得上櫃資料而無上市資料，嘗試再次補抓 TWSE...")
            time.sleep(3)
            twse_records = fetch_twse_t86_for_date(date_str, max_retries=3)

        # 若至少取得一個市場且重試完成
        records = (twse_records or []) + (tpex_records or [])
        if records:
            return date_str, records
        time.sleep(0.5)

    raise RuntimeError("無法獲取最近一週之三大法人籌碼資料，請稍後再試。")


def ensure_chip_history(state: Any, latest_date: str, days_needed: int = 15) -> List[str]:
    """確保 SQLite 快取中包含至少 days_needed 個歷史交易日資料。"""
    try:
        latest = datetime.datetime.strptime(latest_date, "%Y%m%d").date()
    except ValueError:
        latest = datetime.date.today()

    recorded = set(state.get_recorded_trade_dates())
    found_dates = sorted([d for d in recorded if d <= latest_date], reverse=True)

    if len(found_dates) >= days_needed:
        return sorted(found_dates[:days_needed])

    logger.info("歷史籌碼快取不足（現有 %s 天，需求 %s 天），開始回補近期交易日...", len(found_dates), days_needed)

    candidate = latest
    for _ in range(45):
        if len(found_dates) >= days_needed:
            break
        candidate -= datetime.timedelta(days=1)
        if candidate.weekday() >= 5:
            continue
        date_str = candidate.strftime("%Y%m%d")
        if date_str in recorded:
            if date_str not in found_dates:
                found_dates.append(date_str)
            continue

        twse_records = fetch_twse_t86_for_date(date_str)
        tpex_records = fetch_tpex_t86_for_date(date_str)
        records = (twse_records or []) + (tpex_records or [])
        if records:
            state.save_daily_chip_records(date_str, records)
            recorded.add(date_str)
            found_dates.append(date_str)
            logger.info("已成功回補歷史交易日 [%s] 籌碼資料（共 %s 檔）", date_str, len(records))
        time.sleep(0.3)

    return sorted(found_dates[:days_needed])


def fetch_company_name_map() -> Dict[str, str]:
    """以交易所公開基本資料取得上市、上櫃股票的中文簡稱。"""
    sources = (
        ("https://openapi.twse.com.tw/v1/opendata/t187ap03_L", "公司代號", "公司簡稱"),
        ("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O", "SecuritiesCompanyCode", "CompanyAbbreviation"),
    )
    names: Dict[str, str] = {}
    for url, code_field, name_field in sources:
        try:
            rows = requests.get(url, timeout=30, verify=certifi.where()).json()
            for row in rows:
                code = str(row.get(code_field, "")).strip()
                name = str(row.get(name_field, "")).strip()
                if code and name:
                    names[code] = name
        except Exception as exc:
            logger.warning("取得公司基本資料名稱失敗 (%s)：%s", url, exc)
    if not names:
        raise RuntimeError("交易所公司基本資料未回傳任何名稱")
    return names


def get_margin_balances(date_str: str) -> Dict[str, Dict[str, Any]]:
    """取得上市、上櫃個股融資前／今餘額與當日增減率。"""
    balances: Dict[str, Dict[str, Any]] = {}
    try:
        url = f"https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date={date_str}&selectType=ALL&response=json"
        tables = requests.get(url, timeout=20).json().get("tables", [])
        table = next((table for table in tables if len(table.get("fields", [])) >= 7 and table["fields"][0] == "代號"), {})
        for row in table.get("data", []):
            if len(row) < 7:
                continue
            previous, current = _clean_int(row[5]), _clean_int(row[6])
            balances[str(row[0]).strip()] = {"margin_previous": previous, "margin_current": current}
    except Exception as exc:
        logger.warning("抓取上市融資資料失敗 (%s): %s", date_str, exc)
    try:
        date = datetime.datetime.strptime(date_str, "%Y%m%d").date()
        roc = f"{date.year - 1911:03d}/{date.month:02d}/{date.day:02d}"
        url = "https://www.tpex.org.tw/web/stock/margin_trading/margin_balance/margin_bal_result.php"
        payload = requests.get(url, params={"l": "zh-tw", "o": "json", "s": "0", "d": roc}, timeout=20, verify=certifi.where()).json()
        tables = payload.get("tables", [])
        for row in (tables[0].get("data", []) if tables else []):
            if len(row) >= 7:
                balances[str(row[0]).strip()] = {"margin_previous": _clean_int(row[2]), "margin_current": _clean_int(row[6])}
    except Exception as exc:
        logger.warning("抓取上櫃融資資料失敗 (%s): %s", date_str, exc)
    for values in balances.values():
        previous, current = values["margin_previous"], values["margin_current"]
        values["margin_change"] = current - previous
        values["margin_change_rate"] = (current - previous) / previous * 100 if previous else None
    return balances


def _clean_broker_name(name: str) -> str:
    """清理券商名稱前贅詞與後綴"""
    cleaned = re.sub(r"^(美商|港商|新加坡商|法商|香港上海|瑞士信貸|台灣|大和)", "", name)
    cleaned = re.sub(r"證券$", "", cleaned)
    return cleaned.strip() or name


def _parse_single_period_html(html_text: str) -> Optional[Dict[str, Any]]:
    soup = BeautifulSoup(html_text, "html.parser")
    date_match = re.search(r"最後更新日：(\d{4}/\d{2}/\d{2})", soup.get_text())
    report_date = date_match.group(1) if date_match else ""

    top_buyers, top_sellers = [], []
    total_buy, total_sell = 0, 0
    buy_pct_sum, sell_pct_sum = 0.0, 0.0

    for t in soup.find_all("table"):
        text = t.get_text()
        if "合計買超張數" in text and "合計賣超張數" in text:
            for r in t.find_all("tr"):
                cols = [td.get_text(strip=True).replace(",", "") for td in r.find_all(["td", "th"])]
                if len(cols) >= 10:
                    b_name, b_net = cols[0], cols[3]
                    s_name, s_net = cols[5], cols[8]
                    if (
                        len(top_buyers) < 2
                        and b_name
                        and b_name not in ("買超券商", "合計買超張數")
                        and b_net.lstrip("-").isdigit()
                        and int(b_net) > 0
                    ):
                        clean_b = _clean_broker_name(b_name)
                        top_buyers.append(f"{clean_b}+{int(b_net):,}")
                    if (
                        len(top_sellers) < 2
                        and s_name
                        and s_name not in ("賣超券商", "合計賣超張數")
                        and s_net.lstrip("-").isdigit()
                        and int(s_net) > 0
                    ):
                        clean_s = _clean_broker_name(s_name)
                        top_sellers.append(f"{clean_s}-{int(s_net):,}")

                    if cols[4].endswith("%"):
                        try:
                            buy_pct_sum += float(cols[4].rstrip("%"))
                        except ValueError:
                            pass
                    if cols[9].endswith("%"):
                        try:
                            sell_pct_sum += float(cols[9].rstrip("%"))
                        except ValueError:
                            pass

                for i, c in enumerate(cols):
                    if "合計買超張數" in c and i + 1 < len(cols) and cols[i + 1].isdigit():
                        total_buy = int(cols[i + 1])
                    if "合計賣超張數" in c and i + 1 < len(cols) and cols[i + 1].isdigit():
                        total_sell = int(cols[i + 1])
            break

    if total_buy > 0 or total_sell > 0:
        conc = round(buy_pct_sum - sell_pct_sum, 1) if (buy_pct_sum or sell_pct_sum) else 0.0
        return {
            "report_date": report_date,
            "total_buy": total_buy,
            "total_sell": total_sell,
            "net_lots": total_buy - total_sell,
            "top_buyers": top_buyers,
            "top_sellers": top_sellers,
            "concentration": conc,
        }
    return None


def determine_matrix_status(conc_1d: Optional[float], conc_5d: Optional[float]) -> Dict[str, str]:
    if conc_1d is None and conc_5d is None:
        return {"status": "⚪ 無資料", "action": "觀望", "type": "none"}
    c1 = conc_1d if conc_1d is not None else 0.0
    c5 = conc_5d if conc_5d is not None else c1

    if c5 >= 5.0 and c1 >= 10.0:
        return {"status": "🔥 真突破·強勢吸籌", "action": "波段順勢做多", "type": "breakout"}
    elif c5 >= 5.0 and c1 <= -5.0:
        return {"status": "💎 波段吸籌·短線洗盤", "action": "拉回守均線低接", "type": "wash"}
    elif c5 <= -5.0 and c1 >= 10.0:
        return {"status": "⚠️ 空方反彈·隔日沖搶短", "action": "逢高獲利減碼，切忌追高", "type": "rebound"}
    elif c5 <= -5.0 and c1 <= -5.0:
        return {"status": "🚨 主力波段倒貨", "action": "空手觀望或果斷停損", "type": "dump"}
    elif c5 >= 5.0:
        return {"status": "🟢 波段主力吸籌", "action": "持股續抱", "type": "accumulate"}
    elif c5 <= -5.0:
        return {"status": "🔴 波段籌碼發散", "action": "謹慎避開", "type": "distribute"}
    elif c1 >= 10.0:
        return {"status": "⚡ 單日大單急拉", "action": "觀察次日續航力", "type": "single_buy"}
    elif c1 <= -10.0:
        return {"status": "⚠️ 單日急殺調節", "action": "提防短線回檔", "type": "single_sell"}
    else:
        return {"status": "⚪ 主力多空拉鋸", "action": "區間震盪整理", "type": "neutral"}


def fetch_broker_branch_chips(code: str, target_date: str = "") -> Optional[Dict[str, Any]]:
    """抓取單一個股券商分點主力買賣超（同時抓取單日 1D 與波段 5D 數據並做矩陣診斷）"""
    target_formatted = ""
    is_mmdd = False
    if target_date:
        clean_d = str(target_date).replace("-", "").replace("/", "").strip()
        if len(clean_d) == 8 and clean_d.isdigit():
            target_formatted = f"{clean_d[:4]}/{clean_d[4:6]}/{clean_d[6:8]}"
        elif len(clean_d) == 4 and clean_d.isdigit():
            target_formatted = f"{clean_d[:2]}/{clean_d[2:4]}"
            is_mmdd = True
        else:
            target_formatted = target_date

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    mirrors = [
        "https://concords.moneydj.com/z/zc/zco/zco_{code}_{period}.djhtm",
        "https://fubon-ebrokerdj.fbs.com.tw/z/zc/zco/zco_{code}_{period}.djhtm",
        "https://kgieworld.moneydj.com/z/zc/zco/zco_{code}_{period}.djhtm",
    ]

    def _fetch_p(p: int) -> Optional[Dict[str, Any]]:
        for tmpl in mirrors:
            url = tmpl.format(code=code, period=p)
            try:
                resp = requests.get(url, headers=headers, timeout=8)
                if resp.status_code != 200:
                    continue
                resp.encoding = "big5"
                data = _parse_single_period_html(resp.text)
                if data:
                    rep_date = data.get("report_date", "")
                    if target_formatted and rep_date:
                        if is_mmdd and not rep_date.endswith(target_formatted):
                            continue
                        elif not is_mmdd and rep_date != target_formatted:
                            continue
                    return data
            except Exception:
                continue
        return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(_fetch_p, 1)
        f5 = executor.submit(_fetch_p, 2)
        d1 = f1.result()
        d5 = f5.result()

    if not d1 and not d5:
        return None

    base_d = d1 or d5
    rep_date = base_d.get("report_date", "")
    conc_1d = d1.get("concentration") if d1 else None
    conc_5d = d5.get("concentration") if d5 else None

    matrix_info = determine_matrix_status(conc_1d, conc_5d)

    return {
        "broker_buy_lots": d1.get("total_buy", 0) if d1 else (d5.get("total_buy", 0) if d5 else 0),
        "broker_sell_lots": d1.get("total_sell", 0) if d1 else (d5.get("total_sell", 0) if d5 else 0),
        "broker_net_lots": (d1.get("net_lots", 0) if d1 else (d5.get("net_lots", 0) if d5 else 0)),
        "top_buyers": d1.get("top_buyers", []) if d1 else [],
        "top_sellers": d1.get("top_sellers", []) if d1 else [],
        "top_buyers_5d": d5.get("top_buyers", []) if d5 else [],
        "top_sellers_5d": d5.get("top_sellers", []) if d5 else [],
        "broker_concentration": conc_1d,
        "concentration_1d": conc_1d,
        "concentration_5d": conc_5d,
        "matrix_status": matrix_info["status"],
        "matrix_action": matrix_info["action"],
        "matrix_type": matrix_info["type"],
        "broker_report_date": rep_date,
    }


def fetch_watchlist_broker_chips(codes: List[str], target_date: str = "") -> Dict[str, Dict[str, Any]]:
    """平行抓取自選股清單之券商分點主力買賣超資料"""
    results: Dict[str, Dict[str, Any]] = {}
    if not codes:
        return results

    def _worker(c: str) -> Tuple[str, Optional[Dict[str, Any]]]:
        return c, fetch_broker_branch_chips(c, target_date)

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(codes))) as executor:
        future_map = {executor.submit(_worker, code): code for code in codes}
        for future in concurrent.futures.as_completed(future_map):
            try:
                code, data = future.result()
                if data:
                    results[code] = data
            except Exception as e:
                logger.warning(f"解析 {future_map[future]} 券商分點失敗: {e}")

    return results

