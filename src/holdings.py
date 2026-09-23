import datetime
import logging
import os
from pathlib import Path
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


def _load_env_file(path_text: str, *, override: bool = False) -> None:
    """載入指定 env；明確指定的憑證檔可覆寫專案內舊設定。"""
    path = Path(path_text).expanduser()
    if not path.is_file():
        raise RuntimeError(f"找不到 Shioaji 設定檔：{path}")
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip("\"'")
        if override or key not in os.environ:
            os.environ[key] = value


def get_stock_holdings() -> List[Dict[str, str]]:
    """登入正式 Shioaji 帳戶，唯讀取得持股並排除 ETF。

    本函式不啟用 CA、交易回報或任何下單 API。
    """
    # 主程式已載入 .env；保留此步驟讓本模組也能安全獨立執行／測試。
    _load_env_file(str(Path(__file__).resolve().parents[1] / ".env"))
    env_file = os.getenv("SJ_ENV_FILE", "").strip()
    if env_file:
        # SJ_ENV_FILE 是使用者明確指定且已驗證的憑證來源，因此優先使用它。
        _load_env_file(env_file, override=True)
    api_key = os.getenv("SJ_API_KEY", "").strip()
    secret_key = os.getenv("SJ_SECRET_KEY", "").strip() or os.getenv("SJ_SEC_KEY", "").strip()
    if not api_key or not secret_key:
        raise RuntimeError("缺少 SJ_API_KEY 或 SJ_SECRET_KEY，無法同步持股")

    try:
        import shioaji as sj
    except ImportError as exc:
        raise RuntimeError("未安裝 shioaji，請執行 pip install -r requirements.txt") from exc

    api = sj.Shioaji(simulation=False)
    logged_in = False
    try:
        accounts = api.login(api_key=api_key, secret_key=secret_key, subscribe_trade=False)
        logged_in = True
        stock_accounts = [
            account for account in accounts
            if getattr(getattr(account, "account_type", ""), "value", getattr(account, "account_type", "")) == "S"
        ]
        stock_account = next((account for account in stock_accounts if getattr(account, "signed", False)), None)
        stock_account = stock_account or (stock_accounts[0] if stock_accounts else None)
        if stock_account is None:
            raise RuntimeError("此 Shioaji API 沒有可用的證券帳戶，無法同步台股持股")
        # API test 專案以 Unit.Share 讀取，包含整股與零股，數量最精確。
        positions = api.list_positions(account=stock_account, unit=sj.Unit.Share)
        holdings: List[Dict[str, str]] = []
        for position in positions:
            code = str(getattr(position, "code", "")).strip()
            quantity = int(getattr(position, "quantity", 0) or 0)
            if not code or quantity <= 0:
                continue
            contract = api.contracts.get(code) or api.Contracts.Stocks[code]
            exchange = str(getattr(contract, "exchange", "")).upper()
            name = str(getattr(contract, "name", "")).strip()
            category = str(getattr(contract, "category", "")).upper()
            # 僅納入台灣上市／上櫃普通股；海外市場與其他商品一律排除。
            if exchange not in {"TSE", "OTC"}:
                continue
            # 台灣上市櫃 ETF 代號以 00 開頭；同時保留名稱／分類的保護判斷。
            if code.startswith("00") or "ETF" in name.upper() or "ETF" in category:
                continue
            holdings.append({"code": code, "name": name or code})
        return sorted(holdings, key=lambda item: item["code"])
    finally:
        if logged_in:
            api.logout()


DEFAULT_PRICE_TIERS = [
    {"min_price": 1000.0, "threshold_amount_wan": 1000.0},
    {"min_price": 500.0,  "threshold_amount_wan": 500.0},
    {"min_price": 100.0,  "threshold_amount_wan": 300.0},
    {"min_price": 0.0,    "threshold_amount_wan": 100.0},
]


def get_big_order_threshold_wan(price: float, price_tiers: Optional[List[Dict[str, float]]] = None) -> float:
    """依據昨日收盤價（開盤參考價）決定單筆大單成交金額門檻（單位：萬元）"""
    tiers = price_tiers or DEFAULT_PRICE_TIERS
    for tier in tiers:
        if price >= tier.get("min_price", 0):
            return float(tier.get("threshold_amount_wan", 100.0))
    return 100.0


def fetch_big_order_flow(
    codes: List[str],
    date_str: str,
    price_tiers: Optional[List[Dict[str, float]]] = None,
) -> Dict[str, Dict[str, Any]]:
    """透過永豐 Shioaji 逐筆成交 (Ticks) 計算當日盤中自選股大戶大單買賣超力道。

    門檻：依據昨日收盤價（開盤參考價）動態對應成交金額門檻（純金額判定，不卡張數）。
    排除開盤集合競價（第 0 筆）與 13:25:00 後之收盤集合競價。

    :param codes: 股票代號清單，例如 ["2330", "2454"]
    :param date_str: 交易日字串，格式為 YYYYMMDD 或 YYYY-MM-DD
    :param price_tiers: 自訂股價級距金額門檻清單
    :return: { "2330": { "big_order_buy_lots": 2750, "big_order_sell_lots": 6829, ... } }
    """
    _load_env_file(str(Path(__file__).resolve().parents[1] / ".env"))
    env_file = os.getenv("SJ_ENV_FILE", "").strip()
    if env_file:
        _load_env_file(env_file, override=True)
    api_key = os.getenv("SJ_API_KEY", "").strip()
    secret_key = os.getenv("SJ_SECRET_KEY", "").strip() or os.getenv("SJ_SEC_KEY", "").strip()
    if not api_key or not secret_key:
        return {}

    try:
        import shioaji as sj
    except ImportError:
        return {}

    raw_date = date_str.replace("-", "").strip()
    if len(raw_date) == 8:
        formatted_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
        year, month, day = int(raw_date[:4]), int(raw_date[4:6]), int(raw_date[6:])
    else:
        return {}

    cutoff_dt = datetime.datetime(year, month, day, 13, 25, 0, tzinfo=datetime.timezone.utc)
    cutoff_ns = int(cutoff_dt.timestamp() * 1e9)

    api = sj.Shioaji(simulation=False)
    logged_in = False
    results: Dict[str, Dict[str, Any]] = {}
    try:
        api.login(api_key=api_key, secret_key=secret_key, subscribe_trade=False)
        logged_in = True

        import warnings
        for code in codes:
            clean_code = str(code).strip()
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", category=DeprecationWarning)
                contract = api.Contracts.Stocks.get(clean_code)
            if not contract:
                continue
            ticks = api.ticks(contract=contract, date=formatted_date)
            if not ticks:
                continue
            try:
                ts = ticks["ts"]
                close = ticks["close"]
                volume = ticks["volume"]
                tick_type = ticks["tick_type"]
            except (KeyError, TypeError, IndexError):
                continue

            if not ts or len(ts) <= 1:
                continue

            # 取得昨日收盤價（開盤參考價）；若無則以當日開盤首筆成交價推估
            ref_price = float(getattr(contract, "reference", 0) or 0)
            if ref_price <= 0 and close:
                ref_price = float(close[0])

            # 依昨日收盤價動態判定大單金額門檻（萬元）
            threshold_amount_wan = get_big_order_threshold_wan(ref_price, price_tiers)

            total_lots = sum(volume)
            big_buy_lots = 0
            big_sell_lots = 0

            # 排除第 0 筆（09:00:00 開盤集合競價），取盤中連續撮合（< 13:25:00）
            for i in range(1, len(ts)):
                t = ts[i]
                if t >= cutoff_ns:
                    break
                v = volume[i]
                c = close[i]
                amount_wan = c * v / 10.0
                if amount_wan >= threshold_amount_wan:
                    tt = tick_type[i]
                    if tt == 2:
                        big_buy_lots += v
                    elif tt == 1:
                        big_sell_lots += v

            net_lots = big_buy_lots - big_sell_lots
            ratio = ((big_buy_lots + big_sell_lots) / total_lots * 100.0) if total_lots > 0 else 0.0

            results[clean_code] = {
                "big_order_buy_lots": big_buy_lots,
                "big_order_sell_lots": big_sell_lots,
                "big_order_net_lots": net_lots,
                "big_order_volume_ratio": round(ratio, 1),
                "big_order_threshold_wan": int(threshold_amount_wan),
                "reference_price": ref_price,
            }
    except Exception as exc:
        logger.warning("計算 Shioaji 當日大戶大單力道時發生錯誤: %s", exc)
    finally:
        if logged_in:
            api.logout()

    return results

