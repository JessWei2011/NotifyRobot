import os
import re
import datetime
import logging
import requests
import certifi
import sqlite3
from typing import Optional, Dict, Any, List
from bs4 import BeautifulSoup
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "notification_state.sqlite3"


class StockResolver:
    """快取並精準比對上市、上櫃股票代號與名稱、類股。"""
    def __init__(self):
        self.twse_map: Dict[str, str] = {}
        self.tpex_map: Dict[str, str] = {}
        self.last_fetch: Optional[datetime.datetime] = None

    def refresh_if_needed(self):
        now = datetime.datetime.now()
        if self.last_fetch and (now - self.last_fetch).total_seconds() < 86400:
            return

        try:
            r1 = requests.get("https://openapi.twse.com.tw/v1/opendata/t187ap03_L", timeout=8).json()
            self.twse_map = {str(r.get("公司代號", "")).strip(): str(r.get("公司簡稱", "")).strip() for r in r1}
        except Exception as exc:
            logger.warning("載入 TWSE 上市清單失敗: %s", exc)

        try:
            r2 = requests.get(
                "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O",
                timeout=8,
                verify=certifi.where(),
            ).json()
            self.tpex_map = {str(r.get("SecuritiesCompanyCode", "")).strip(): str(r.get("CompanyAbbreviation", "")).strip() for r in r2}
        except Exception as exc:
            logger.warning("載入 TPEx 上櫃清單失敗: %s", exc)

        self.last_fetch = now

    def resolve(self, code: str) -> Dict[str, Any]:
        self.refresh_if_needed()
        c = str(code).strip().upper()
        name = ""
        market = ""

        if c in self.twse_map:
            name = self.twse_map[c]
            market = "上市"
        elif c in self.tpex_map:
            name = self.tpex_map[c]
            market = "上櫃"

        # 透過 Yahoo 查詢即時報價與驗證（支援 ETF、各類有價證券）
        for sym in [f"{c}.TWO", f"{c}.TW"] if market == "上櫃" else [f"{c}.TW", f"{c}.TWO"]:
            try:
                url = (
                    f"https://tw.stock.yahoo.com/_td-stock/api/resource/StockServices.stockList;"
                    f"fields=avgPrice%2CorderPct%2Csymbol%2Cprice%2Cchange%2CchangePercent%2Cvolume%2C"
                    f"high%2Clow%2Copen%2CpreviousClose%2Cturnover%2Cname%2CsectorName%2Cexchange%2C"
                    f"inMarketPercentage%2CoutMarketPercentage%2CmarketStatus;"
                    f"symbols={sym}"
                )
                res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5).json()
                if res and len(res) > 0 and res[0].get("symbolName"):
                    item = res[0]
                    name = name or item.get("symbolName") or item.get("name")
                    ex = item.get("exchange", "")
                    if not market:
                        market = "上櫃" if ex == "TWO" else ("上市" if ex == "TAI" else "上市")
                    sec = item.get("sectorName", "")
                    if sec.startswith("櫃"):
                        sec = sec[1:]

                    return {
                        "code": c,
                        "name": name,
                        "symbol": sym,
                        "market": market,
                        "sector": sec,
                        "exists": True,
                        "raw_item": item,
                    }
            except Exception as exc:
                logger.debug("Yahoo 查詢 %s 略過: %s", sym, exc)

        if name and market:
            return {
                "code": c,
                "name": name,
                "symbol": f"{c}.TW" if market == "上市" else f"{c}.TWO",
                "market": market,
                "sector": "",
                "exists": True,
                "raw_item": None,
            }

        return {
            "code": c,
            "name": "",
            "symbol": "",
            "market": "",
            "sector": "",
            "exists": False,
            "raw_item": None,
        }


resolver = StockResolver()


def roc_to_iso(val: str) -> str:
    """將民國年月日轉為 ISO 日期 YYYY-MM-DD"""
    val = val.replace("/", "").replace(".", "").replace("-", "").strip()
    digits = re.sub(r"\D", "", val)
    if len(digits) == 7:
        return f"{int(digits[:3]) + 1911:04d}-{digits[3:5]}-{digits[5:7]}"
    return val


def parse_period(val: str) -> tuple[str, str]:
    """解析處置期間起訖日期"""
    parts = re.split(r"[~～]", val)
    if len(parts) == 2:
        return (roc_to_iso(parts[0]), roc_to_iso(parts[1]))
    return (val, val)


def get_stock_quote(code: str) -> Optional[Dict[str, Any]]:
    """
    抓取個股報價與基本資訊。若查無此股則回傳 None。
    """
    info = resolver.resolve(code)
    if not info["exists"]:
        return None

    item = info.get("raw_item")
    if not item:
        # 如果 resolver 沒拿到 raw_item，再次補抓
        for sym in [f"{info['code']}.TW", f"{info['code']}.TWO"]:
            try:
                url = (
                    f"https://tw.stock.yahoo.com/_td-stock/api/resource/StockServices.stockList;"
                    f"fields=avgPrice%2CorderPct%2Csymbol%2Cprice%2Cchange%2CchangePercent%2Cvolume%2C"
                    f"high%2Clow%2Copen%2CpreviousClose%2Cturnover%2Cname%2CsectorName%2Cexchange%2C"
                    f"inMarketPercentage%2CoutMarketPercentage%2CmarketStatus;"
                    f"symbols={sym}"
                )
                res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5).json()
                if res and len(res) > 0 and res[0].get("symbolName"):
                    item = res[0]
                    break
            except Exception:
                pass

    if not item:
        return None

    change_raw = item.get("change", {}).get("fmt", "0")
    change_status = "平盤"
    if str(change_raw).startswith("-"):
        change_status = f"跌 {change_raw.lstrip('-')}"
    elif change_raw != "0" and change_raw != "0.00" and not str(change_raw).startswith("0"):
        change_status = f"漲 {change_raw.lstrip('+')}"

    return {
        "code": info["code"],
        "name": info["name"],
        "symbol": info["symbol"],
        "market": info["market"],
        "sector": info["sector"],
        "price": item.get("price", {}).get("fmt", "0"),
        "change": change_raw,
        "change_status": change_status,
        "change_percent": item.get("changePercent", "0%"),
        "open": item.get("regularMarketOpen", {}).get("fmt", "-"),
        "high": item.get("regularMarketDayHigh", {}).get("fmt", "-"),
        "low": item.get("regularMarketDayLow", {}).get("fmt", "-"),
        "previous_close": item.get("regularMarketPreviousClose", {}).get("fmt", "-"),
        "volume_lots": item.get("volumeK", 0),
        "turnover_m": item.get("turnoverM", "0"),
        "in_pct": item.get("inMarketPercentage", ""),
        "out_pct": item.get("outMarketPercentage", ""),
    }


def get_stock_chips(code: str) -> Optional[Dict[str, Any]]:
    """
    從本機資料庫取得最近交易日之三大法人籌碼歷史。
    """
    clean_code = str(code).strip().upper()
    if not DB_PATH.exists():
        return None

    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT trade_date, foreign_lots, trust_lots, dealer_lots, total_lots
            FROM daily_chip_history
            WHERE code = ?
            ORDER BY trade_date DESC
            LIMIT 5
            """,
            (clean_code,),
        )
        rows = cur.fetchall()
        conn.close()

        if rows:
            latest = rows[0]
            history = []
            for r in rows:
                history.append({
                    "date": r[0],
                    "foreign": r[1],
                    "trust": r[2],
                    "dealer": r[3],
                    "total": r[4],
                })
            return {
                "latest_date": latest[0],
                "foreign_lots": latest[1],
                "trust_lots": latest[2],
                "dealer_lots": latest[3],
                "total_lots": latest[4],
                "history": history,
            }
    except Exception as exc:
        logger.warning("讀取三大法人資料庫失敗 (%s): %s", clean_code, exc)

    return None


def get_stock_alerts(code: str) -> Dict[str, Any]:
    """
    檢查個股是否進入：注意股票、處置股票。
    若查無此股代號，直接回傳 exists=False。
    若已確認處置日期（不管是即將處置或已進入處置），皆完整回傳處置日期與起訖資訊。
    """
    clean_code = str(code).strip().upper()
    info = resolver.resolve(clean_code)

    if not info["exists"]:
        return {
            "code": clean_code,
            "name": "",
            "market": "",
            "exists": False,
            "disposal": None,
            "attention": None,
        }

    today = datetime.date.today().isoformat()
    result = {
        "code": clean_code,
        "name": info["name"],
        "market": info["market"],
        "exists": True,
        "disposal": None,
        "attention": None,
    }

    # 1. 查詢上櫃處置資訊
    try:
        tpex_punish = requests.get(
            "https://www.tpex.org.tw/openapi/v1/tpex_disposal_information",
            verify=certifi.where(),
            timeout=8,
        ).json()
        for it in tpex_punish:
            if str(it.get("SecuritiesCompanyCode", "")).strip() == clean_code:
                s, e = parse_period(it.get("DispositionPeriod", ""))
                name = it.get("CompanyName", "") or result["name"]
                result["name"] = name
                result["market"] = "上櫃"
                result["disposal"] = {
                    "market": "上櫃",
                    "name": name,
                    "start_date": s,
                    "end_date": e,
                    "reasons": it.get("DispositionReasons", ""),
                    "measures": it.get("DisposalCondition", ""),
                    "is_future": s > today,
                    "is_active": s <= today <= e,
                    "is_ended": today > e,
                }
                break
    except Exception as exc:
        logger.warning("查詢上櫃處置失敗: %s", exc)

    # 2. 查詢上市處置資訊
    if not result["disposal"]:
        try:
            twse_punish = requests.get(
                "https://openapi.twse.com.tw/v1/announcement/punish",
                timeout=8,
            ).json()
            for it in twse_punish:
                if str(it.get("Code", "")).strip() == clean_code:
                    s, e = parse_period(it.get("DispositionPeriod", ""))
                    name = it.get("Name", "") or result["name"]
                    result["name"] = name
                    result["market"] = "上市"
                    result["disposal"] = {
                        "market": "上市",
                        "name": name,
                        "start_date": s,
                        "end_date": e,
                        "reasons": it.get("ReasonsOfDisposition", ""),
                        "measures": it.get("DispositionMeasures", "") or it.get("Detail", ""),
                        "is_future": s > today,
                        "is_active": s <= today <= e,
                        "is_ended": today > e,
                    }
                    break
        except Exception as exc:
            logger.warning("查詢上市處置失敗: %s", exc)

    # 3. 查詢上櫃注意股票
    try:
        tpex_notice = requests.get(
            "https://www.tpex.org.tw/openapi/v1/tpex_trading_warning_information",
            verify=certifi.where(),
            timeout=8,
        ).json()
        for it in tpex_notice:
            if str(it.get("SecuritiesCompanyCode", "")).strip() == clean_code:
                name = it.get("CompanyName", "") or result["name"]
                result["name"] = name
                result["market"] = "上櫃"
                result["attention"] = {
                    "market": "上櫃",
                    "name": name,
                    "date": roc_to_iso(it.get("Date", "")),
                    "info": it.get("TradingInformation", ""),
                }
                break
    except Exception as exc:
        logger.warning("查詢上櫃注意股票失敗: %s", exc)

    # 4. 查詢上市注意股票（回溯最近 7 天）
    if not result["attention"]:
        try:
            start_d = (datetime.date.today() - datetime.timedelta(days=7)).strftime("%Y%m%d")
            end_d = datetime.date.today().strftime("%Y%m%d")
            url = f"https://www.twse.com.tw/rwd/zh/announcement/notice?startDate={start_d}&endDate={end_d}&response=json"
            twse_notice = requests.get(url, timeout=8).json()
            for row in twse_notice.get("data", []):
                if len(row) > 4 and str(row[1]).strip() == clean_code:
                    name = str(row[2]).strip() or result["name"]
                    result["name"] = name
                    result["market"] = "上市"
                    result["attention"] = {
                        "market": "上市",
                        "name": name,
                        "date": roc_to_iso(str(row[5]).strip()),
                        "info": str(row[4]).strip(),
                    }
                    break
        except Exception as exc:
            logger.warning("查詢上市注意股票失敗: %s", exc)

    return result


def fetch_stock_news(code: str, name: str = "", limit: int = 5) -> List[Dict[str, str]]:
    """
    抓取個股最新新聞列表（結合 Google 新聞 RSS 與 Yahoo 股市新聞）。
    """
    news_items: List[Dict[str, str]] = []
    seen_titles = set()

    # 1. 抓取 Yahoo 股市新聞
    try:
        url = f"https://tw.stock.yahoo.com/quote/{code}/news"
        res = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=6,
        )
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            anchors = soup.find_all("a", href=lambda h: h and "/news/" in h)
            for a in anchors:
                title = a.get_text(strip=True)
                href = a.get("href", "")
                if href.startswith("/"):
                    href = "https://tw.stock.yahoo.com" + href
                if title and len(title) > 8 and title not in seen_titles:
                    seen_titles.add(title)
                    news_items.append({
                        "title": title,
                        "source": "Yahoo 股市",
                        "link": href,
                        "pub_date": "最新",
                    })
                if len(news_items) >= limit:
                    break
    except Exception as exc:
        logger.warning("抓取 Yahoo 股市新聞失敗 (%s): %s", code, exc)

    # 2. 若新聞不足，由 Google News RSS 補充
    if len(news_items) < limit:
        try:
            query = f"{code} {name}".strip()
            url = f"https://news.google.com/rss/search?q={query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
            res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=6)
            if res.status_code == 200:
                soup = BeautifulSoup(res.content, "xml")
                for it in soup.find_all("item")[:limit]:
                    raw_title = it.title.text if it.title else ""
                    parts = raw_title.rsplit(" - ", 1)
                    title = parts[0].strip()
                    source = parts[1].strip() if len(parts) > 1 else "Google News"
                    link = it.link.text if it.link else ""
                    pub = it.pubDate.text if it.pubDate else ""

                    if title and title not in seen_titles:
                        seen_titles.add(title)
                        news_items.append({
                            "title": title,
                            "source": source,
                            "link": link,
                            "pub_date": pub[:16] if pub else "",
                        })
                    if len(news_items) >= limit:
                        break
        except Exception as exc:
            logger.warning("抓取 Google News RSS 失敗 (%s): %s", code, exc)

    return news_items[:limit]


def summarize_news_with_ai(code: str, name: str, news_list: List[Dict[str, str]]) -> str:
    """
    透過 AI 總結個股新聞重點動態與多空因素。
    採用極簡條列格式 [問題]: 回答，不使用過量 emoji。
    """
    if not news_list:
        return "[動態總結]: 查無近期相關即時新聞。"

    news_text = ""
    for idx, item in enumerate(news_list, 1):
        news_text += f"{idx}. 【{item['source']}】{item['title']}\n"

    prompt = f"""請根據以下台股【{code} {name}】的最新新聞，進行精簡條列分析。
要求：
- 繁體中文，禁止使用任何多餘裝飾性 emoji。
- 採用標準條列格式：
[核心題材]:
• （1~2點近期核心營運或題材）
[正面利多]:
• （1~2點正面消息）
[風險觀察]:
• （1~2點風險或觀察變數）

新聞列表：
{news_text}
"""

    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key:
        try:
            from google import genai
            client = genai.Client(api_key=gemini_key)
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
            )
            if response and response.text:
                return response.text.strip()
        except Exception as exc:
            logger.warning("Gemini API 調用失敗: %s", exc)

    try:
        import ollama
        resp = ollama.chat(
            model="qwen3:8b",
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.2},
        )
        if resp and "message" in resp and resp["message"].get("content"):
            return resp["message"]["content"].strip()
    except Exception as exc:
        logger.debug("Ollama 調用略過: %s", exc)

    # 備用條列
    summary = "[最新新聞清單]:\n"
    for idx, item in enumerate(news_list, 1):
        summary += f"{idx}. [{item['title']}]({item['link']}) ({item['source']})\n"
    summary += "\n(提示: 於 .env 設定 GEMINI_API_KEY 可啟用 AI 重點分析)"
    return summary


def _format_chip_num(lots: int) -> str:
    """格式化買賣超張數（正▲、負▼、平▶）"""
    if lots > 0:
        return f"+{lots:,} 張 ▲"
    elif lots < 0:
        return f"{lots:,} 張 ▼"
    else:
        return "0 張 ▶"


def build_full_stock_watchlist_report(code: str) -> Optional[Dict[str, Any]]:
    """
    為指定個股產出與自選股 (Watchlist) 完全同等規格的完整報告：
    包含：即時價量行情、三大法人買賣超與5日走勢、券商主力分點、籌碼型態診斷、
    隔日衝大戶警戒、大戶大單力道、信用交易融資、注意與處置警示狀態。
    """
    clean_code = str(code).strip().upper()
    info = resolver.resolve(clean_code)
    if not info["exists"]:
        return None

    name = info["name"]
    market = info["market"]
    sector = info.get("sector")
    market_sector = f"{market}・{sector}" if sector else market

    quote = get_stock_quote(clean_code)
    chips = get_stock_chips(clean_code)
    trade_date = chips["latest_date"] if chips else datetime.date.today().strftime("%Y%m%d")
    date_fmt = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}" if len(trade_date) == 8 else trade_date

    # 1. 抓取主力分點
    broker = {}
    try:
        from src.fetcher import fetch_watchlist_broker_chips
        b_res = fetch_watchlist_broker_chips([clean_code], trade_date)
        if b_res and clean_code in b_res:
            broker = b_res[clean_code]
    except Exception as exc:
        logger.warning("抓取主力分點失敗 (%s): %s", clean_code, exc)

    # 2. 抓取融資資料
    margin = {}
    try:
        from src.fetcher import get_margin_balances
        m_res = get_margin_balances(trade_date)
        if m_res and clean_code in m_res:
            margin = m_res[clean_code]
    except Exception as exc:
        logger.warning("抓取融資資料失敗 (%s): %s", clean_code, exc)

    # 3. 抓取大單力道
    big_order = {}
    try:
        from src.holdings import fetch_big_order_flow
        import json
        config_path = BASE_DIR / "config.json"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            big_cfg = cfg.get("big_order_settings", {})
            bo_res = fetch_big_order_flow([clean_code], trade_date, price_tiers=big_cfg.get("price_tiers"))
            if bo_res and clean_code in bo_res:
                big_order = bo_res[clean_code]
    except Exception as exc:
        logger.debug("抓取大戶力道略過: %s", exc)

    # 4. 抓取注意與處置狀態
    alerts = get_stock_alerts(clean_code)

    # 組裝完整報告文字
    lines = [
        f"📊 *【自選股盤後籌碼報告｜{clean_code} {name}】*",
        f"📅 日期：`{date_fmt}` ｜ 市場：`{market_sector}`",
        "──────────────────────",
    ]

    # 成交行情
    if quote:
        change_indicator = "🔺" if quote["change_status"].startswith("漲") else ("🔻" if quote["change_status"].startswith("跌") else "➖")
        lines.append(f"💰 *成交行情*：`{quote['price']}` ({change_indicator} `{quote['change_status']}`, `{quote['change_percent']}`)")
        lines.append(f"   • 開高低：開 `{quote['open']}` ｜ 高 `{quote['high']}` ｜ 低 `{quote['low']}`（昨收 `{quote['previous_close']}`）")
        lines.append(f"   • 成交量：`{quote['volume_lots']:,} 張` ｜ 成交額：`{quote['turnover_m']} 億`")
        if quote.get("in_pct") and quote.get("out_pct"):
            lines.append(f"   • 盤中力道：內盤 `{quote['in_pct']}` ｜ 外盤 `{quote['out_pct']}`")
        lines.append("")

    # 三大法人
    if chips:
        f_str = _format_chip_num(chips["foreign_lots"])
        t_str = _format_chip_num(chips["trust_lots"])
        d_str = _format_chip_num(chips["dealer_lots"])
        tot_str = _format_chip_num(chips["total_lots"])
        lines.append("🏛️ *三大法人買賣超*：")
        lines.append(f"   • 外資：{f_str}")
        lines.append(f"   • 投信：{t_str}")
        lines.append(f"   • 自營商：{d_str}")
        lines.append(f"   👉 **法人合計**：{tot_str}")
        if len(chips.get("history", [])) > 1:
            h_strs = []
            for h in chips["history"][:5]:
                d = h["date"]
                df = f"{d[4:6]}/{d[6:]}" if len(d) == 8 else d
                h_strs.append(f"{df}: `{h['total']:+,}`")
            lines.append(f"   • 5日法人走勢：{' ｜ '.join(h_strs)}")
        lines.append("")
    else:
        lines.append("🏛️ *三大法人買賣超*：*尚無本檔歷史庫存紀錄*\n")

    # 主力分點
    if broker:
        b_net = broker.get("broker_net_lots", 0)
        b_net_str = _format_chip_num(b_net)
        b_buy = broker.get("broker_buy_lots", 0)
        b_sell = broker.get("broker_sell_lots", 0)
        lines.append(f"🏢 *主力分點*：{b_net_str}（前15大買 `{b_buy:,}`／賣 `{b_sell:,}`）")

        tb = broker.get("top_buyers", [])
        ts = broker.get("top_sellers", [])
        if tb or ts:
            b_str = "、".join(tb) if tb else "無"
            s_str = "、".join(ts) if ts else "無"
            lines.append(f"   • 分點買賣：買【{b_str}】｜賣【{s_str}】")

        c1 = broker.get("concentration_1d", broker.get("broker_concentration"))
        c5 = broker.get("concentration_5d")
        matrix_status = broker.get("matrix_status", "")
        matrix_action = broker.get("matrix_action", "")
        if c5 is not None and c1 is not None:
            conc_text = f"5D `{c5:+.1f}%` ｜ 1D `{c1:+.1f}%`"
            diag_text = f"【{matrix_status}】" if matrix_status else ""
            lines.append(f"   • 籌碼型態：{diag_text} 集中度 {conc_text}（{matrix_action}）")

        tb5 = broker.get("top_buyers_5d", [])
        ts5 = broker.get("top_sellers_5d", [])
        if tb5 or ts5:
            b5_str = "、".join(tb5[:2]) if tb5 else "無"
            s5_str = "、".join(ts5[:2]) if ts5 else "無"
            lines.append(f"   • 5日波段：買【{b5_str}】｜賣【{s5_str}】")

        # 隔日衝大戶警戒名單比對
        day_trading = [
            "凱基-台北", "凱基台北", "富邦-建國", "富邦建國", "元大-土城永寧", "土城永寧",
            "富邦-忠孝", "國泰-敦南", "群益金鼎-大安", "兆豐-大同", "元大-北府", "華南永昌-世貿", "凱基-松山"
        ]
        hit = []
        for b in tb:
            for dt in day_trading:
                if dt in b:
                    hit.append(b.split("+")[0].strip())
                    break
        if hit:
            lines.append(f"   • 隔日衝警戒：⚡ 買方見【{'、'.join(hit)}】隔日衝大戶，次日開盤切勿追高！")
        lines.append("")

    # 大戶力道
    if big_order and "big_order_net_lots" in big_order:
        bo_net = big_order["big_order_net_lots"]
        bo_net_str = _format_chip_num(bo_net)
        bo_buy = big_order.get("big_order_buy_lots", 0)
        bo_sell = big_order.get("big_order_sell_lots", 0)
        pct = big_order.get("big_order_volume_ratio")
        pct_text = f"｜佔比 `{pct:.1f}%`" if pct is not None else ""
        t_wan = big_order.get("big_order_threshold_wan")
        t_text = f"單筆≥{t_wan}萬｜" if t_wan else ""
        lines.append(f"💪 *大戶大單力道*：{bo_net_str}（{t_text}買 `{bo_buy:,}`／賣 `{bo_sell:,}`{pct_text}）\n")

    # 信用交易
    if margin and "margin_current" in margin:
        m_curr = margin["margin_current"]
        change = margin.get("margin_change", 0)
        rate = margin.get("margin_change_rate")
        rate_text = "—" if rate is None else f"{rate:+.2f}%"
        lines.append(f"💳 *信用交易*：融資 `{m_curr:,} 張`（{change:+,} 張｜{rate_text}）\n")

    # 警示與處置狀態
    lines.append("🚨 *交易警示狀態*：")
    has_alert = False
    if alerts.get("disposal"):
        d = alerts["disposal"]
        tag = "【即將處置】" if d.get("is_future") else ("【處置管制中】" if d.get("is_active") else "【處置已結束】")
        lines.append(f"   • 處置股票：{tag} 期間 `{d['start_date']}` ～ `{d['end_date']}`")
        lines.append(f"     原因：{d.get('reasons', '')}")
        has_alert = True
    if alerts.get("attention"):
        a = alerts["attention"]
        lines.append(f"   • 注意股票：公告日期 `{a.get('date', '')}`")
        lines.append(f"     條款：{a.get('info', '')[:100]}...")
        has_alert = True
    if not has_alert:
        lines.append("   • 正常交易：未列入注意股票或處置管制名單。")

    # 決定卡片主色調
    if quote:
        if quote["change_status"].startswith("跌"):
            embed_color = 0x10B981  # 台股綠跌
        elif quote["change_status"].startswith("漲"):
            embed_color = 0xEF4444  # 台股紅漲
        else:
            embed_color = 0x2563EB
    else:
        embed_color = 0x2563EB

    return {
        "text": "\n".join(lines),
        "color": embed_color,
        "name": name,
        "market_sector": market_sector,
    }
