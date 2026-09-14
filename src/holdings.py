"""唯讀同步永豐 Shioaji 股票庫存。"""

import os
from pathlib import Path
from typing import Dict, List


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
