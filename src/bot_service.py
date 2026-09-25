import os
import re
import logging
import asyncio
import datetime
import discord
from discord import app_commands
from typing import Optional

from src.stock_query import (
    resolver,
    get_stock_quote,
    get_stock_chips,
    get_stock_alerts,
    fetch_stock_news,
    summarize_news_with_ai,
    build_full_stock_watchlist_report,
)
from src.chip_advisor import evaluate_stock_chip

logger = logging.getLogger(__name__)

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


def _format_lots(num: int) -> str:
    """格式化帶符號張數（正🔼、負🔽、平▶️）"""
    if num > 0:
        return f"+{num:,} 張 🔼"
    elif num < 0:
        return f"{num:,} 張 🔽"
    return "0 張 ▶️"


# ==========================================
# 1. /stock 指令：回傳與自選股 (Watchlist) 完全同等規格之完整報告
# ==========================================
@tree.command(name="stock", description="查詢個股完整籌碼報告（規格與自選股推播報告完全一致）")
@app_commands.describe(code="台股代號，例如 2330 或 3529")
async def slash_stock(interaction: discord.Interaction, code: str):
    await interaction.response.defer()
    clean_code = code.strip().upper()

    report = build_full_stock_watchlist_report(clean_code)
    if not report:
        await interaction.followup.send(
            f"查無此股票代號「{clean_code}」，請確認台股代號是否正確。",
            ephemeral=True,
        )
        return

    embed = discord.Embed(
        description=report["text"],
        color=report["color"],
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    embed.set_footer(text="NotifyRobot 個股籌碼全方位報告 • 與自選股報告規格同步")
    await interaction.followup.send(embed=embed)


# ==========================================
# 2. /news 指令：爬取新聞並由 AI 總結動態
# ==========================================
@tree.command(name="news", description="上網爬取個股最新新聞並由 AI 總結重點動態")
@app_commands.describe(code="台股代號，例如 2330 或 3529")
async def slash_news(interaction: discord.Interaction, code: str):
    await interaction.response.defer()
    clean_code = code.strip().upper()

    info = resolver.resolve(clean_code)
    if not info["exists"]:
        await interaction.followup.send(
            f"查無此股票代號「{clean_code}」，請確認台股代號是否正確。",
            ephemeral=True,
        )
        return

    name = info["name"]
    market = info["market"]

    news_items = fetch_stock_news(clean_code, name, limit=5)
    if not news_items:
        await interaction.followup.send(
            f"查無 {clean_code} {name} 近期相關即時新聞。",
            ephemeral=True,
        )
        return

    ai_summary = summarize_news_with_ai(clean_code, name, news_items)

    lines = [
        f"**【{clean_code} {name} ({market}) 最新新聞動態】**",
        "",
        f"[股票]: {clean_code} {name} ({market})",
        ai_summary,
        "",
        "[相關新聞來源]:",
    ]
    for idx, item in enumerate(news_items, 1):
        pub = f" - {item['pub_date']}" if item.get("pub_date") and item["pub_date"] != "最新" else ""
        lines.append(f"{idx}. [{item['title']}]({item['link']}) ({item['source']}{pub})")

    embed = discord.Embed(
        description="\n".join(lines),
        color=0x2563EB,
    )
    await interaction.followup.send(embed=embed)


# ==========================================
# 3. /alert 指令（支援 /alart）：查注意、警告、處置
# ==========================================
async def handle_alert_query(interaction: discord.Interaction, code: str):
    await interaction.response.defer()
    clean_code = code.strip().upper()

    data = get_stock_alerts(clean_code)
    if not data.get("exists"):
        await interaction.followup.send(
            f"查無此股票代號「{clean_code}」，請確認台股代號是否正確。",
            ephemeral=True,
        )
        return

    name = data["name"]
    market = data["market"]
    disposal = data.get("disposal")
    attention = data.get("attention")

    lines = [
        f"**【{clean_code} {name} ({market}) 警示與處置狀態】**",
        "",
        f"[股票]: {clean_code} {name} ({market})",
    ]

    # 1. 處置狀態（若已確認處置日期，不管是否已進入處置，都完整印出處置日期）
    if disposal:
        start_d = disposal["start_date"]
        end_d = disposal["end_date"]
        reasons = disposal.get("reasons") or "無特殊註記"
        measures = disposal.get("measures") or "無詳細措施"
        clean_measures = re.sub(r"\s+", " ", measures).strip()[:200]

        if disposal.get("is_future"):
            status_text = f"即將處置 (處置期間: {start_d} ～ {end_d})"
        elif disposal.get("is_active"):
            status_text = f"處置管制中 (處置期間: {start_d} ～ {end_d})"
        else:
            status_text = f"處置已結束 (處置期間: {start_d} ～ {end_d})"

        lines.extend([
            f"[處置狀態]: {status_text}",
            f"[處置原因]: {reasons}",
            f"[處置措施]: {clean_measures}",
        ])
    else:
        lines.extend([
            "[處置狀態]: 無處置 (未列入處置名單)",
            "[處置原因]: 無",
            "[處置措施]: 無",
        ])

    # 2. 注意狀態
    if attention:
        att_info = re.sub(r"\s+", " ", attention.get("info", "")).strip()
        lines.extend([
            f"[注意狀態]: 列為注意股票 (公告日期: {attention.get('date', '近期')})",
            f"[注意原因]: {att_info}",
        ])
    else:
        lines.extend([
            "[注意狀態]: 正常 (未列入注意股票)",
            "[注意原因]: 無",
        ])

    # 3. 結論
    if disposal:
        if disposal.get("is_future"):
            conclusion = f"主管機關已公告排定處置，預計自 {disposal['start_date']} 起執行，請留意交易限制與風險。"
        else:
            conclusion = f"目前正處於處置管制期間 (預計至 {disposal['end_date']} 結束)，撮合與款券受限，請留意流動性風險。"
    elif attention:
        conclusion = "該個股目前列為注意股票，近期價量波動較大，請留意交易風險。"
    else:
        conclusion = "該個股目前無注意或處置紀錄，交易正常。"

    lines.append(f"[結論]: {conclusion}")

    embed = discord.Embed(
        description="\n".join(lines),
        color=0xDC2626 if disposal else (0xD97706 if attention else 0x16A34A),
    )
    await interaction.followup.send(embed=embed)


@tree.command(name="alert", description="查詢個股注意與處置狀態（處置日期一律印出）")
@app_commands.describe(code="台股代號，例如 2305, 3374, 3529")
async def slash_alert(interaction: discord.Interaction, code: str):
    await handle_alert_query(interaction, code)


@tree.command(name="alart", description="查詢個股注意與處置狀態（同 /alert 指令）")
@app_commands.describe(code="台股代號，例如 2305, 3374, 3529")
async def slash_alart(interaction: discord.Interaction, code: str):
    await handle_alert_query(interaction, code)


# ==========================================
# 4. /chip 指令：外掛接入點（籌碼分析 + Qwen 專業評價）
# ==========================================
@tree.command(name="chip", description="整理個股籌碼（排除中實戶）並由本地 Qwen 評估短期趨勢")
@app_commands.describe(code="台股代號，例如 2330 或 1815")
async def slash_chip(interaction: discord.Interaction, code: str):
    await interaction.response.defer()
    clean_code = code.strip().upper()

    # 於背景線程呼叫外掛函式，避免阻塞 Discord 事件迴圈
    evaluation = await asyncio.to_thread(evaluate_stock_chip, clean_code)

    # Discord 單則訊息長度限制為 2000 字元，若超過進行分段安全傳送
    if len(evaluation) <= 1900:
        await interaction.followup.send(evaluation)
    else:
        chunks = [evaluation[i:i + 1900] for i in range(0, len(evaluation), 1900)]
        for chunk in chunks:
            await interaction.followup.send(chunk)


@client.event
async def on_ready():
    logger.info("Discord Bot 已成功連線，使用者：%s (ID: %s)", client.user, client.user.id)
    try:
        # 1. 即時同步至目前已加入之所有伺服器 (Guild Sync 秒級即時生效，免等待 Discord 全域 1 小時快取)
        for guild in client.guilds:
            tree.copy_global_to(guild=guild)
            await tree.sync(guild=guild)
            logger.info("已即時同步斜線指令至伺服器: %s (ID: %s)", guild.name, guild.id)

        # 2. 同步全域指令 (Global Sync)
        synced = await tree.sync()
        logger.info("已同步 %d 個全域斜線指令 (Slash Commands)", len(synced))
    except Exception as exc:
        logger.error("同步斜線指令失敗: %s", exc)

    await client.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="台股行情 | /stock /news /alert /chip",
        )
    )
    print(f"NotifyRobot Discord 機器人已上線！(使用者: {client.user})")
    print("指令清單: /stock, /news, /alert, /alart, /chip")


def start_discord_bot(token: Optional[str] = None):
    bot_token = token or os.getenv("DISCORD_BOT_TOKEN")
    if not bot_token:
        raise ValueError("未設定 DISCORD_BOT_TOKEN，請於 .env 填入 Bot Token")

    client.run(bot_token)
