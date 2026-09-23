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


def send_discord_message(
    webhook_url: str = "",
    text: str = "",
    max_retries: int = 3,
    bot_token: Optional[str] = None,
    channel_id: Optional[str] = None,
) -> SendResult:
    """透過 Discord Bot API 或 Incoming Webhook 發送卡片式通知。"""
    use_bot = bool(bot_token and channel_id)
    if not use_bot and not webhook_url:
        return SendResult(False, error="missing Discord bot credentials or webhook URL")

    title = re.sub(r"[*`_]", "", text.splitlines()[0]).strip()[:256] or "NotifyRobot"
    description = _highlight_discord_stock_headers(text[len(text.splitlines()[0]):].strip())[:4096] or "通知內容"

    if use_bot:
        endpoint = f"https://discord.com/api/v10/channels/{channel_id}/messages"
        headers = {
            "Authorization": f"Bot {bot_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "embeds": [{"title": title, "description": description, "color": 0x3B82F6}],
            "allowed_mentions": {"parse": []},
        }
    else:
        endpoint = f"{webhook_url}?wait=true"
        headers = {"Content-Type": "application/json"}
        payload = {
            "username": "NotifyRobot",
            "embeds": [{"title": title, "description": description, "color": 0x3B82F6}],
            "allowed_mentions": {"parse": []},
        }

    for attempt in range(max_retries + 1):
        try:
            response = requests.post(endpoint, json=payload, headers=headers, timeout=15)
            if response.ok:
                body = response.json() if response.content else {}
                target_label = f"channel {channel_id}" if use_bot else "webhook"
                logger.info("Discord 訊息推播成功 (%s, message_id: %s)", target_label, body.get("id"))
                return SendResult(True, message_id=int(body["id"]) if str(body.get("id", "")).isdigit() else None)
            error, retryable = f"HTTP {response.status_code}: {response.text[:200]}", response.status_code in {429, 500, 502, 503, 504}
            wait_time = 2 ** attempt
            if response.status_code == 429:
                try:
                    wait_time = float(response.json().get("retry_after", wait_time))
                except Exception:
                    pass
        except requests.RequestException as exc:
            error, retryable, wait_time = str(exc), True, 2 ** attempt
        if retryable and attempt < max_retries:
            time.sleep(wait_time)
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


def format_market_institutional_amount_message(
    date_str: str,
    summary: Dict[str, Any],
    status: str = "final",
) -> str:
    """產出上市大盤三大法人的淨買賣超金額摘要（自營商不含避險）。"""
    title = (
        "📈 *【上市大盤三大法人買賣超（盤後初估）】*"
        if status == "preliminary"
        else "📈 *【上市大盤三大法人買賣超（盤後定案）】*"
    )

    lines = [
        title,
        f"📅 日期：`{date_str}`",
        "💰 單位：新台幣億元（淨買／賣超）",
        "──────────────────────",
    ]

    # 外資
    f_amt = summary.get("foreign", 0)
    f_dir = "買超" if f_amt > 0 else "賣超" if f_amt < 0 else "持平"
    lines.append(f"📌 *外資*：{f_dir} `{f_amt / 100_000_000:+,.1f} 億`")

    # 投信
    t_amt = summary.get("trust", 0)
    t_dir = "買超" if t_amt > 0 else "賣超" if t_amt < 0 else "持平"
    lines.append(f"📌 *投信*：{t_dir} `{t_amt / 100_000_000:+,.1f} 億`")

    # 自營商（自行買賣）
    d_amt = summary.get("dealer", 0)
    d_dir = "買超" if d_amt > 0 else "賣超" if d_amt < 0 else "持平"
    lines.append(f"📌 *自營商（自行買賣）*：{d_dir} `{d_amt / 100_000_000:+,.1f} 億`")

    # 三大法人合計（外資 + 投信 + 自營自行買賣）
    tot_amt = summary.get("total", 0)
    tot_dir = "買超" if tot_amt > 0 else "賣超" if tot_amt < 0 else "持平"
    lines.append(f"📌 *三大法人合計*：{tot_dir} `{tot_amt / 100_000_000:+,.1f} 億`")

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
        lines.append(f"   • 法人合計：{total_str}")
        if "broker_net_lots" in item:
            b_net = item["broker_net_lots"]
            b_net_str = _format_num(b_net)
            b_buy = item.get("broker_buy_lots", 0)
            b_sell = item.get("broker_sell_lots", 0)
            lines.append(f"   • 主力分點：{b_net_str}（前15大買 `{b_buy:,}`／賣 `{b_sell:,}`）")

            top_buyers = item.get("top_buyers", [])
            top_sellers = item.get("top_sellers", [])
            if top_buyers or top_sellers:
                b_str = "、".join(top_buyers) if top_buyers else "無"
                s_str = "、".join(top_sellers) if top_sellers else "無"
                lines.append(f"   • 分點買賣：買【{b_str}】｜賣【{s_str}】")

            conc = item.get("broker_concentration")
            if conc is not None:
                if conc >= 15.0:
                    flow_desc = f"集中度 `{conc:+.1f}%` 🔥 主力強力吸籌，籌碼高度集中"
                elif conc >= 5.0:
                    flow_desc = f"集中度 `{conc:+.1f}%` 🟢 主力偏多吸籌，籌碼趨向集中"
                elif conc > -5.0:
                    flow_desc = f"集中度 `{conc:+.1f}%` ⚖️ 主力多空拉鋸，籌碼中性平衡"
                elif conc > -15.0:
                    flow_desc = f"集中度 `{conc:+.1f}%` ⚠️ 籌碼偏向發散，流向散戶接盤"
                else:
                    flow_desc = f"集中度 `{conc:+.1f}%` ⚠️ 主力大幅倒貨，由全台散戶接盤"
                lines.append(f"   • 籌碼流向：{flow_desc}")
        if "big_order_net_lots" in item:
            net_lots = item["big_order_net_lots"]
            net_str = _format_num(net_lots)
            buy_lots = item.get("big_order_buy_lots", 0)
            sell_lots = item.get("big_order_sell_lots", 0)
            pct = item.get("big_order_volume_ratio")
            pct_text = f"｜佔比 `{pct:.1f}%`" if pct is not None else ""
            t_wan = item.get("big_order_threshold_wan")
            t_text = f"單筆≥{t_wan}萬｜" if t_wan else ""
            lines.append(f"   • 大戶力道：{net_str}（{t_text}買 `{buy_lots:,}`／賣 `{sell_lots:,}`{pct_text}）")
        if "margin_current" in item:
            change = item["margin_change"]
            rate = item.get("margin_change_rate")
            rate_text = "—" if rate is None else f"{rate:+.2f}%"
            lines.append(f"   • 融資：`{item['margin_current']:,} 張`（{change:+,} 張｜{rate_text}）")
        if period := item.get("disposition_period"):
            lines.append(f"   ❗ 處置日期：`{period[0]}` ～ `{period[1]}`")
        lines.append("")

    return "\n".join(lines)


def format_big_holder_message(
    report_date: str,
    previous_date: str | None,
    rows: List[Dict[str, Any]],
    rankings: Dict[str, List[Dict[str, Any]]] | None = None,
) -> str:
    lines = ["🧩 *【自選股大戶籌碼週報】*", f"📅 集保資料日：`{report_date}`"]
    if previous_date:
        lines.append(f"比較基準：`{previous_date}`")
    lines.append("──────────────────────")
    for index, item in enumerate(rows, 1):
        lines.append(f"{index}. 🔷 **{item['code']} {item['name']}**")
        change_400 = item["ratio_change_400"]
        change_1000 = item["ratio_change_1000"]
        if change_400 is None or change_1000 is None:
            lines.append(f"   400 張以上大戶 `{item['ratio_400']:.1f}%`｜千張大戶 `{item['ratio_1000']:.1f}%`  ")
            lines.append("💡 結論：本週首次建立基準，下週開始比較變化。")
            lines.append("")
            continue
        lines.append(f"   400 張以上大戶 `{item['ratio_400']:.1f}%`（{change_400:+.2f}pt）｜千張大戶 `{item['ratio_1000']:.1f}%`（{change_1000:+.2f}pt）  ")
        if change_400 > 0.1 and change_1000 > 0.1:
            conclusion = "400 張以上與千張大戶同步集中。"
        elif change_400 < -0.1 and change_1000 < -0.1:
            conclusion = "兩層大戶同步鬆動。"
        elif change_1000 > 0.1 and change_400 <= 0.1:
            conclusion = "籌碼偏向千張大戶集中。"
        elif change_400 > 0.1 and change_1000 <= 0.1:
            conclusion = "400 張以上大戶增加，但千張大戶未同步。"
        else:
            conclusion = "大戶結構大致持平。"
        lines.append(f"💡 結論：{conclusion}")
        lines.append("")
    if rankings is None:
        lines.extend([
            "──────────────────────",
            "📊 全市場 Top 10：本週已建立比較基準，下週起依持股比例增加幅度排行。",
        ])
    else:
        for group, label in (("400", "400 張以上大戶"), ("1000", "千張大戶")):
            lines.extend(["──────────────────────", f"📈 *【本週{label}持股比例增加 Top 10】*"])
            entries = rankings.get(group, [])
            if not entries:
                lines.append("   本週無持股比例增加的標的")
                continue
            for index, entry in enumerate(entries, 1):
                lines.append(
                    f"{index}. 🔷 **{entry['code']} {entry['name']}**｜"
                    f"`{entry['ratio']:.1f}%`（{entry['change']:+.2f}pt）"
                )
    lines.extend(["──────────────────────", "💡 400 張以上含 400–999 張與千張大戶；資料每週更新一次。"])
    return "\n".join(lines)

def format_screener_message(
    date_str: str,
    dual_buyers: List[Dict[str, Any]],
    it_buyers: List[Dict[str, Any]],
    show_dual_buyers: bool = True,
    show_it_buyers: bool = True,
) -> str:
    """產出市場策略篩選推播訊息文字（相容舊版單則格式）"""
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


def format_daily_buyers_message(
    date_str: str,
    dual_buyers: List[Dict[str, Any]],
    foreign_buyers: List[Dict[str, Any]],
    it_buyers: List[Dict[str, Any]],
) -> str:
    lines = [
        "📊 *【盤後籌碼榜｜單日買超強勢】*",
        f"📅 日期：`{date_str}`",
        "──────────────────────",
        "🔥 *外資 & 投信同步買超 Top 10（土洋合作）*",
    ]
    if not dual_buyers:
        lines.append("   無符合條件之標的")
    else:
        for idx, item in enumerate(dual_buyers, 1):
            f_lots = item.get("foreign_lots", 0)
            t_lots = item.get("trust_lots", 0)
            lines.append(
                f"{idx}. *{item['code']} {item['name']}*：`+{item['dual_total']:,}` 張 "
                f"(外 `+{f_lots:,}`｜投 `+{t_lots:,}`)"
            )

    lines.extend([
        "──────────────────────",
        "🦅 *外資買超 Top 10*",
    ])
    if not foreign_buyers:
        lines.append("   無資料")
    else:
        for idx, item in enumerate(foreign_buyers, 1):
            lines.append(f"{idx}. *{item['code']} {item['name']}*：`+{item['foreign_lots']:,}` 張")

    lines.extend([
        "──────────────────────",
        "💎 *投信買超 Top 10*",
    ])
    if not it_buyers:
        lines.append("   無資料")
    else:
        for idx, item in enumerate(it_buyers, 1):
            lines.append(f"{idx}. *{item['code']} {item['name']}*：`+{item['trust_lots']:,}` 張")

    lines.append("──────────────────────")
    return "\n".join(lines)


def format_daily_sellers_message(
    date_str: str,
    dual_sellers: List[Dict[str, Any]],
    foreign_sellers: List[Dict[str, Any]],
    it_sellers: List[Dict[str, Any]],
) -> str:
    lines = [
        "⚠️ *【盤後籌碼榜｜單日賣超警示】*",
        f"📅 日期：`{date_str}`",
        "──────────────────────",
        "💥 *外資 & 投信同步賣超 Top 10（土洋同步賣超）*",
    ]
    if not dual_sellers:
        lines.append("   無符合條件之標的")
    else:
        for idx, item in enumerate(dual_sellers, 1):
            f_lots = item.get("foreign_lots", 0)
            t_lots = item.get("trust_lots", 0)
            lines.append(
                f"{idx}. *{item['code']} {item['name']}*：`{item['dual_total']:,}` 張 "
                f"(外 `{f_lots:,}`｜投 `{t_lots:,}`)"
            )

    lines.extend([
        "──────────────────────",
        "🔴 *外資賣超 Top 10*",
    ])
    if not foreign_sellers:
        lines.append("   無資料")
    else:
        for idx, item in enumerate(foreign_sellers, 1):
            lines.append(f"{idx}. *{item['code']} {item['name']}*：`{item['foreign_lots']:,}` 張")

    lines.extend([
        "──────────────────────",
        "🔻 *投信賣超 Top 10*",
    ])
    if not it_sellers:
        lines.append("   無資料")
    else:
        for idx, item in enumerate(it_sellers, 1):
            lines.append(f"{idx}. *{item['code']} {item['name']}*：`{item['trust_lots']:,}` 張")

    lines.append("──────────────────────")
    return "\n".join(lines)


def format_consecutive_buyers_message(
    date_str: str,
    dual_consecutive: List[Dict[str, Any]],
    foreign_consecutive: List[Dict[str, Any]],
    it_consecutive: List[Dict[str, Any]],
) -> str:
    lines = [
        "🌊 *【盤後籌碼榜｜波段連續買超】*",
        f"📅 日期：`{date_str}`（篩選門檻：連續買超 ≥ 5 天）",
        "──────────────────────",
        "⚡ *外資 & 投信雙連買 Top 10*",
    ]
    if not dual_consecutive:
        lines.append("   無符合條件之標的")
    else:
        for idx, item in enumerate(dual_consecutive, 1):
            lines.append(
                f"{idx}. 🔷 **{item['code']} {item['name']}**\n"
                f"   • 外資連 `{item['foreign_days']}` 天（累計 `+{item['foreign_accum']:,}` 張）\n"
                f"   • 投信連 `{item['trust_days']}` 天（累計 `+{item['trust_accum']:,}` 張）\n"
                f"   • 雙法人合計累計 `+{item['total_accum']:,}` 張"
            )

    lines.extend([
        "──────────────────────",
        "🦅 *外資連續買超 Top 10*",
    ])
    if not foreign_consecutive:
        lines.append("   無符合條件之標的")
    else:
        for idx, item in enumerate(foreign_consecutive, 1):
            lines.append(
                f"{idx}. 🔷 **{item['code']} {item['name']}**｜"
                f"連 `{item['days']}` 天｜累計 `+{item['accum_lots']:,}` 張（今日 `+{item['today_lots']:,}`）"
            )

    lines.extend([
        "──────────────────────",
        "💎 *投信連續買超 Top 10*",
    ])
    if not it_consecutive:
        lines.append("   無符合條件之標的")
    else:
        for idx, item in enumerate(it_consecutive, 1):
            lines.append(
                f"{idx}. 🔷 **{item['code']} {item['name']}**｜"
                f"連 `{item['days']}` 天｜累計 `+{item['accum_lots']:,}` 張（今日 `+{item['today_lots']:,}`）"
            )

    lines.extend([
        "──────────────────────",
        "💡 排序規則：天數越多名次越高；天數相同時依期間累計買超張數排序。",
    ])
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
