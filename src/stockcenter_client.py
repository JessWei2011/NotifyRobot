"""
StockCenter Interface Client for NotifyRobot
負責與 StockCenter HTTP API 介面通訊，觸發報表更新並解析專業指標標籤
"""

import os
import logging
import datetime
import requests
import discord
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

STOCKCENTER_API_URL = os.getenv("STOCKCENTER_API_URL", "http://127.0.0.1:8935")


def fetch_stockcenter_tags(ticker: str, force: bool = True, timeout: int = 70) -> Dict[str, Any]:
    """
    透過 HTTP API 呼叫 StockCenter 的 interface 端點：
    更新該個股報表並取得完整的價量、K線、KD、MACD、RSI、法人籌碼標籤。
    """
    url = f"{STOCKCENTER_API_URL.rstrip('/')}/api/interface/stock-tags"
    payload = {"code": ticker.strip(), "force": force}

    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        try:
            data = resp.json()
        except Exception:
            data = {"ok": False, "error": f"StockCenter 回傳非 JSON 格式 (HTTP {resp.status_code}): {resp.text[:200]}"}

        return data
    except requests.exceptions.ConnectionError:
        return {
            "ok": False,
            "error": f"無法連線至 StockCenter 服務 ({STOCKCENTER_API_URL})。\n請確認 StockCenter 控制台或伺服器 (reports_manager_server) 是否已啟動。",
        }
    except requests.exceptions.Timeout:
        return {
            "ok": False,
            "error": f"呼叫 StockCenter 更新超時 ({timeout} 秒)，伺服器正在抓取資料，請稍候重試。",
        }
    except Exception as e:
        return {
            "ok": False,
            "error": f"請求 StockCenter 發生未預期錯誤: {e}",
        }


def _format_tag_list(tags: list) -> str:
    """格式化標籤列表為好看的 Markdown bullet 項目"""
    if not tags:
        return "• ⚪ 暫無特殊型態標籤"
    return "\n".join(f"• {t}" for t in tags)


def build_stockcenter_tags_embed(ticker: str) -> discord.Embed:
    """
    呼叫 StockCenter 並將回傳的標籤與行情資料排版為 Discord Embed 卡片
    """
    data = fetch_stockcenter_tags(ticker, force=True)

    if not data.get("ok"):
        err_msg = data.get("error", "未知錯誤")
        detail = data.get("detail", "")
        desc = f"❌ **查詢或更新失敗**\n\n{err_msg}"
        if detail:
            clean_detail = detail.strip().splitlines()
            last_lines = "\n".join(clean_detail[-5:])
            desc += f"\n\n```text\n{last_lines}\n```"

        embed = discord.Embed(
            title=f"【{ticker}】StockCenter 串接回報",
            description=desc,
            color=0xEF4444,  # 紅色警示
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        embed.set_footer(text="StockCenter Interface • 連線異常或代碼錯誤")
        return embed

    code = data.get("code", ticker)
    name = data.get("name", "")
    market = data.get("market", "TW")
    category = data.get("category", "未分類")
    date = data.get("date", "")
    price = data.get("price", 0.0)
    change = data.get("change", 0.0)
    change_pct = data.get("change_pct", 0.0)
    volume_lots = data.get("volume_lots", 0)
    tags = data.get("tags", {})

    # 決定顏色 (台股紅漲綠跌)
    if change > 0:
        color = 0xDC2626  # 紅色 (漲)
        sign = "+"
        dir_icon = "🔺"
    elif change < 0:
        color = 0x16A34A  # 綠色 (跌)
        sign = ""
        dir_icon = "🔻"
    else:
        color = 0x64748B  # 灰色 (平)
        sign = " "
        dir_icon = "➖"

    title = f"【{code} {name} ({market})】StockCenter 指標標籤庫"

    header_lines = [
        f"📅 **報表更新日期**：`{date}` ｜ **產業族群**：`{category}`",
        f"💰 **收盤股價**：`{price:,.2f}` 元  {dir_icon} **{sign}{change:+.2f} ({sign}{change_pct:+.2f}%)**",
        f"📊 **當日成交量**：`{volume_lots:,}` 張",
        "────────────────────────────",
    ]

    embed = discord.Embed(
        title=title,
        description="\n".join(header_lines),
        color=color,
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )

    # 1. K 線與均線型態
    kline_content = _format_tag_list(tags.get("kline", []))
    embed.add_field(name="📐 K 線與均線型態", value=kline_content, inline=False)

    # 2. 成交量價結構
    vol_content = _format_tag_list(tags.get("volume", []))
    embed.add_field(name="📊 成交量價結構", value=vol_content, inline=False)

    # 3. KD 擺盪指標
    kd_content = _format_tag_list(tags.get("kd", []))
    embed.add_field(name="⚡ KD 擺盪指標", value=kd_content, inline=False)

    # 4. MACD 動能指標
    macd_content = _format_tag_list(tags.get("macd", []))
    embed.add_field(name="🌊 MACD 動能趨勢", value=macd_content, inline=False)

    # 5. RSI 強弱指標
    rsi_content = _format_tag_list(tags.get("rsi", []))
    embed.add_field(name="🎯 RSI 相對強弱", value=rsi_content, inline=False)

    # 6. 法人與分點籌碼
    chips_content = _format_tag_list(tags.get("chips", []))
    embed.add_field(name="🏦 三大法人與主力籌碼", value=chips_content, inline=False)

    embed.set_footer(text="StockCenter 智慧量化分析核心 • 即時更新與標籤萃取")
    return embed


def build_integrated_stock_embed(code_or_name: str) -> Optional[discord.Embed]:
    """
    整合 NotifyRobot 個股籌碼全方位報告與 StockCenter 最新量化技術指標標籤
    """
    clean_input = code_or_name.strip()

    # 1. 呼叫 StockCenter 進行更新並取得指標標籤
    sc_data = fetch_stockcenter_tags(clean_input, force=True)
    resolved_code = sc_data.get("code") if sc_data.get("ok") else clean_input

    # 2. 產出 NotifyRobot 自選股規格個股全方位籌碼與行情報告
    from src.stock_query import build_full_stock_watchlist_report
    report = build_full_stock_watchlist_report(resolved_code)

    if not report and not sc_data.get("ok"):
        return None

    if report:
        embed = discord.Embed(
            description=report["text"],
            color=report["color"],
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
    else:
        name = sc_data.get("name", "")
        code = sc_data.get("code", resolved_code)
        market = sc_data.get("market", "TW")
        embed = discord.Embed(
            title=f"【{code} {name} ({market})】個股分析報告",
            color=0x2563EB,
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )

    # 3. 附加 StockCenter 量化指標標籤至 Embed fields
    if sc_data.get("ok"):
        tags = sc_data.get("tags", {})
        embed.add_field(name="📐 K 線與均線型態", value=_format_tag_list(tags.get("kline", [])), inline=False)
        embed.add_field(name="📊 成交量價結構", value=_format_tag_list(tags.get("volume", [])), inline=False)
        embed.add_field(name="⚡ KD 擺盪指標", value=_format_tag_list(tags.get("kd", [])), inline=False)
        embed.add_field(name="🌊 MACD 動能趨勢", value=_format_tag_list(tags.get("macd", [])), inline=False)
        embed.add_field(name="🎯 RSI 相對強弱", value=_format_tag_list(tags.get("rsi", [])), inline=False)
        embed.add_field(name="🏦 StockCenter 量化籌碼標籤", value=_format_tag_list(tags.get("chips", [])), inline=False)
        embed.set_footer(text="NotifyRobot × StockCenter 聯合全方位量化分析報告 • 即時更新與標籤萃取")
    else:
        err_msg = sc_data.get("error", "未能連接 StockCenter 服務")
        embed.add_field(
            name="⚠️ StockCenter 量化標籤",
            value=f"暫時無法取得最新標籤（{err_msg}）",
            inline=False,
        )
        embed.set_footer(text="NotifyRobot 個股籌碼全方位報告 • 與自選股報告規格同步")

    return embed

