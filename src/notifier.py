import logging
import re
import requests
import time
from dataclasses import dataclass
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)
DISCORD_STOCK_HEADER_PATTERN = re.compile(
    r"(?m)^(?P<prefix>(?:(?:📌|\d+\.)\s*)?)\*(?P<stock>[0-9A-Za-z]{4,6}\s+[^*\n]+)\*"
)


@dataclass
class SendResult:
    success: bool
    message_id: Optional[int] = None
    error: Optional[str] = None


def _highlight_discord_stock_headers(description: str) -> str:
    """用 Discord 穩定支援的彩色符號與粗體分隔個股標頭。"""
    def replace(match: re.Match[str]) -> str:
        stock = match.group("stock")
        return f"{match.group('prefix')}🔷 **{stock}**"

    return DISCORD_STOCK_HEADER_PATTERN.sub(replace, description)


def send_discord_message(webhook_url: str, text: str, max_retries: int = 3) -> SendResult:
    """透過 Discord Incoming Webhook 發送卡片式通知。"""
    if not webhook_url:
        return SendResult(False, error="missing Discord webhook URL")
    title = re.sub(r"[*`_]", "", text.splitlines()[0]).strip()[:256] or "NotifyRobot"
    description = _highlight_discord_stock_headers(text[len(text.splitlines()[0]):].strip())[:4096] or "通知內容"
    payload = {
        "username": "NotifyRobot",
        "embeds": [{"title": title, "description": description, "color": 0x3B82F6}],
        "allowed_mentions": {"parse": []},
    }
    for attempt in range(max_retries + 1):
        try:
            response = requests.post(f"{webhook_url}?wait=true", json=payload, timeout=15)
            if response.ok:
                body = response.json() if response.content else {}
                logger.info("Discord 訊息推播成功 (message_id: %s)", body.get("id"))
                return SendResult(True, message_id=int(body["id"]) if str(body.get("id", "")).isdigit() else None)
            error, retryable = f"HTTP {response.status_code}: {response.text[:200]}", response.status_code in {429, 500, 502, 503, 504}
        except requests.RequestException as exc:
            error, retryable = str(exc), True
        if retryable and attempt < max_retries:
            time.sleep(2 ** attempt)
            continue
        logger.error("Discord 推播失敗：%s", error)
        return SendResult(False, error=error)
    return SendResult(False, error="retry loop exited unexpectedly")

def _format_num(lots: int) -> str:
    """格式化買賣超張數，附帶正負號與顏色指示符號"""
    if lots > 0:
        return f"+{lots:,} 張 🟢"
    elif lots < 0:
        return f"{lots:,} 張 🔴"
    else:
        return "0 張 ⚪"


def format_market_institutional_message(date_str: str, summary: Dict[str, int]) -> str:
    """產出上市大盤三大法人的淨買賣超張數摘要。"""
    lines = [
        "📈 *【台股大盤三大法人買賣超】*",
        f"📅 日期：`{date_str}`",
        "💰 單位：張（淨買／賣超）",
        "──────────────────────",
    ]
    for label, key in (("外資", "foreign"), ("投信", "trust"), ("自營商", "dealer"), ("三大法人合計", "total")):
        lots = summary[key]
        direction = "買超" if lots > 0 else "賣超" if lots < 0 else "持平"
        lines.append(f"📌 *{label}*：{direction} `{lots:+,} 張`")
    lines.extend([
        "──────────────────────",
        "💡 資料範圍：上市與上櫃股票；自營商含自行買賣與避險。",
    ])
    return "\n".join(lines)


def format_market_institutional_amount_message(date_str: str, summary: Dict[str, int]) -> str:
    """產出上市大盤三大法人的淨買賣超金額摘要。"""
    lines = [
        "📈 *【上市大盤三大法人買賣超】*",
        f"📅 日期：`{date_str}`",
        "💰 單位：新台幣億元（淨買／賣超）",
        "──────────────────────",
    ]
    for label, key in (("外資", "foreign"), ("投信", "trust"), ("自營商", "dealer"), ("三大法人合計", "total")):
        amount = summary[key]
        direction = "買超" if amount > 0 else "賣超" if amount < 0 else "持平"
        lines.append(f"📌 *{label}*：{direction} `{amount / 100_000_000:+,.1f} 億`")
    lines.extend([
        "──────────────────────",
        "💡 資料範圍：證交所上市市場；自營商含自行買賣與避險。",
    ])
    return "\n".join(lines)

def format_watchlist_message(date_str: str, watchlist_data: List[Dict[str, Any]]) -> str:
    """產出自選股推播訊息文字"""
    lines = [
        f"📊 *【自選股盤後籌碼動態】*",
        f"📅 日期：`{date_str}`",
        "──────────────────────"
    ]

    for item in watchlist_data:
        code = item["code"]
        name = item["name"]
        if item.get("not_found"):
            lines.append(f"*{code} {name}*")
            lines.append("   ⚠️ 當日查無籌碼數據（可能未上市或暫停交易）")
            if period := item.get("disposition_period"):
                lines.append(f"   ❗ 處置日期：`{period[0]}` ～ `{period[1]}`")
            lines.append("")
            continue

        f_str = _format_num(item["foreign_lots"])
        t_str = _format_num(item["trust_lots"])
        d_str = _format_num(item["dealer_lots"])
        total_str = _format_num(item["total_lots"])

        lines.append(f"*{code} {name}*")
        lines.append(f"   • 外資：{f_str}")
        lines.append(f"   • 投信：{t_str}")
        lines.append(f"   • 自營商：{d_str}")
        lines.append(f"   • 法人合計：*{total_str}*")
        if "margin_current" in item:
            change = item["margin_change"]
            rate = item.get("margin_change_rate")
            rate_text = "—" if rate is None else f"{rate:+.2f}%"
            lines.append(f"   • 融資：`{item['margin_current']:,} 張`（{change:+,} 張｜{rate_text}）")
        if period := item.get("disposition_period"):
            lines.append(f"   ❗ 處置日期：`{period[0]}` ～ `{period[1]}`")
        lines.append("")

    return "\n".join(lines)


def format_big_holder_message(report_date: str, previous_date: str | None, rows: List[Dict[str, Any]]) -> str:
    lines = ["🧩 *【自選股大戶籌碼週報】*", f"📅 集保資料日：`{report_date}`"]
    if previous_date:
        lines.append(f"比較基準：`{previous_date}`")
    lines.append("──────────────────────")
    for index, item in enumerate(rows, 1):
        lines.append(f"{index}. 🔷 **{item['code']} {item['name']}**")
        change_400 = item["ratio_change_400"]
        change_1000 = item["ratio_change_1000"]
        if change_400 is None or change_1000 is None:
            lines.append(f"   中大戶 `{item['ratio_400']:.1f}%`｜千張大戶 `{item['ratio_1000']:.1f}%`")
            lines.append("   💡 結論：本週首次建立基準，下週開始比較變化。")
            continue
        lines.append(f"   中大戶 `{item['ratio_400']:.1f}%`（{change_400:+.2f}pt）｜千張大戶 `{item['ratio_1000']:.1f}%`（{change_1000:+.2f}pt）")
        if change_400 > 0.1 and change_1000 > 0.1:
            conclusion = "中大戶與千張大戶同步集中。"
        elif change_400 < -0.1 and change_1000 < -0.1:
            conclusion = "兩層大戶同步鬆動。"
        elif change_1000 > 0.1 and change_400 <= 0.1:
            conclusion = "籌碼偏向千張大戶集中。"
        elif change_400 > 0.1 and change_1000 <= 0.1:
            conclusion = "中大戶增加，但千張大戶未同步。"
        else:
            conclusion = "大戶結構大致持平。"
        lines.append(f"   💡 結論：{conclusion}")
    lines.extend(["──────────────────────", "💡 400–999 張與 1,000 張以上依集保持股級距統計；資料每週更新一次。"])
    return "\n".join(lines)

def format_screener_message(
    date_str: str,
    dual_buyers: List[Dict[str, Any]],
    it_buyers: List[Dict[str, Any]],
    show_dual_buyers: bool = True,
    show_it_buyers: bool = True,
) -> str:
    """產出市場策略篩選推播訊息文字"""
    lines = [
        f"🎯 *【盤後籌碼策略篩選榜】*",
        f"📅 日期：`{date_str}`",
        "──────────────────────"
    ]

    if show_dual_buyers:
        lines.append("🔥 *策略一：外資 & 投信同步買超*")
        if not dual_buyers:
            lines.append("   無符合條件之標的")
        else:
            for idx, item in enumerate(dual_buyers, 1):
                code = item["code"]
                name = item["name"]
                f_lots = item["foreign_lots"]
                t_lots = item["trust_lots"]
                lines.append(f"{idx}. *{code} {name}*")
                lines.append(f"   外資: `+{f_lots:,}` | 投信: `+{t_lots:,}` | 合計: `+{item['dual_total']:,}` 張")

    if show_dual_buyers and show_it_buyers:
        lines.append("")
        lines.append("──────────────────────")

    if show_it_buyers:
        lines.append("💎 *策略二：投信買超前 10 強*")
        if not it_buyers:
            lines.append("   無資料")
        else:
            for idx, item in enumerate(it_buyers, 1):
                code = item["code"]
                name = item["name"]
                t_lots = item["trust_lots"]
                lines.append(f"{idx}. *{code} {name}*：`+{t_lots:,}` 張")

    lines.append("──────────────────────")
    return "\n".join(lines)

def send_telegram_message(
    token: str,
    chat_id: str,
    text: str,
    parse_mode: str = "Markdown",
    reply_markup: Optional[Dict[str, Any]] = None,
    max_retries: int = 3,
) -> SendResult:
    """發送訊息並回傳 Telegram 接受後的 message_id。"""
    if not token or not chat_id:
        logger.error("未設定 TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID")
        return SendResult(False, error="missing Telegram credentials")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    for attempt in range(max_retries + 1):
        try:
            response = requests.post(url, json=payload, timeout=15)
            try:
                res_data = response.json()
            except ValueError:
                res_data = {}

            if res_data.get("ok"):
                message_id = res_data["result"].get("message_id")
                logger.info("Telegram 訊息推播成功 (message_id: %s)", message_id)
                return SendResult(True, message_id=message_id)

            description = res_data.get("description", f"HTTP {response.status_code}")
            retry_after = res_data.get("parameters", {}).get("retry_after")
            retryable = response.status_code == 429 or response.status_code >= 500
        except requests.RequestException as exc:
            description = str(exc)
            retry_after = None
            retryable = True

        if retryable and attempt < max_retries:
            delay = retry_after if retry_after is not None else 2 ** attempt
            logger.warning("Telegram 發送失敗，%.0f 秒後重試：%s", delay, description)
            time.sleep(delay)
            continue

        logger.error("Telegram 推播失敗：%s", description)
        return SendResult(False, error=description)

    return SendResult(False, error="retry loop exited unexpectedly")

def get_latest_chat_id(token: str) -> Optional[str]:
    """
    新手輔助工具：透過 getUpdates 自動抓取最新與機器人互動的 chat_id
    """
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    try:
        res = requests.get(url, timeout=10).json()
        if not res.get("ok"):
            return None
        results = res.get("result", [])
        if not results:
            return None
        # 取得最後一條訊息的 chat id
        last_update = results[-1]
        if "message" in last_update:
            return str(last_update["message"]["chat"]["id"])
    except Exception as e:
        logger.error(f"無法取得 chat_id: {e}")
    return None


def get_updates(token: str, offset: Optional[int] = None) -> List[Dict[str, Any]]:
    """取得尚未處理的 Telegram 更新，用於同步「已收到」按鈕。"""
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    params: Dict[str, Any] = {"timeout": 0, "allowed_updates": ["callback_query"]}
    if offset is not None:
        params["offset"] = offset
    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        if data.get("ok"):
            return data.get("result", [])
        logger.error("讀取 Telegram updates 失敗：%s", data.get("description"))
    except requests.RequestException as exc:
        logger.error("讀取 Telegram updates 發生例外：%s", exc)
    return []


def answer_callback_query(token: str, callback_query_id: str, text: str) -> bool:
    url = f"https://api.telegram.org/bot{token}/answerCallbackQuery"
    try:
        response = requests.post(url, json={"callback_query_id": callback_query_id, "text": text}, timeout=15)
        return bool(response.json().get("ok"))
    except (requests.RequestException, ValueError) as exc:
        logger.error("回覆確認按鈕失敗：%s", exc)
        return False
