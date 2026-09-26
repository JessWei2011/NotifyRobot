"""
NotifyRobot 長短線籌碼共振篩選引擎 (Chip Resonance Screener)

核心策略：
千張大戶比例逐週上升 ＋ 5D 券商分點集中度維持正值 ＝ 長短線主力籌碼共振（做多強勢指標）

範圍限制：
1. 上市櫃電子股（半導體、電腦週邊、電子零組件、光電、通信網路、其他電子等）
2. 優先識別並標記 AI 核心供應鏈（AI晶片/伺服器/散熱/先進封裝/CPO/PCB/高速傳輸等）
"""

import os
import re
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from src.fetcher import fetch_watchlist_broker_chips

logger = logging.getLogger(__name__)

# 核心 AI 供應鏈概念個股與次族群對應表（持續擴充維持最新）
AI_SUPPLY_CHAIN_MAP: Dict[str, str] = {
    # AI 晶片 / ASIC / IP / 矽智財
    "2330": "AI先進製程晶圓",
    "2454": "AI邊緣運算/ASIC",
    "3661": "ASIC/AI晶片設計",
    "3443": "ASIC/先進封裝委託",
    "3035": "ASIC/IP矽智財",
    "3529": "IP嵌入式記憶體",
    "6533": "RISC-V/AI架構",
    "6643": "高速介面IP",
    "6462": "神經網路/AI晶片",
    "8054": "ASIC設計服務",
    "5274": "伺服器BMC管理晶片",
    "4966": "高速傳輸晶片",
    # AI 伺服器代工 (ODM/OEM)
    "2382": "AI伺服器代工龍頭",
    "3231": "AI伺服器/基板代工",
    "6669": "高階AI伺服器純度",
    "2356": "AI伺服器組裝",
    "2376": "AI伺服器/GPU散熱",
    "2317": "AI伺服器整機製造",
    "4938": "伺服器/車用組裝",
    "3706": "AI伺服器儲存",
    "2357": "AI伺服器與邊緣PC",
    "2324": "伺服器與終端代工",
    # AI 散熱 / 液冷 / 水冷散熱
    "3017": "水冷板/散熱模組龍頭",
    "3324": "水冷散熱模組龍頭",
    "2421": "AI伺服器散熱風扇",
    "3483": "伺服器導熱管/散熱",
    "3338": "伺服器液冷散熱",
    "8996": "AI液冷伺服器歧管",
    "6230": "伺服器均熱板",
    "6125": "水冷雙相浸沒技術",
    # 先進封裝 (CoWoS / 封測設備 / 廠務 / 測試介面)
    "3711": "全球封測與先進封裝",
    "2449": "AI晶片成品測試",
    "6257": "先進封測與高階測試",
    "6147": "驅動IC與封裝測試",
    "3583": "CoWoS濕製程設備",
    "3131": "CoWoS濕製程龍頭",
    "6187": "先進封裝點膠設備",
    "6640": "先進封裝挑揀設備",
    "2467": "先進封裝壓膜設備",
    "6515": "AI測試座/垂直探針卡",
    "6223": "高階探針卡測試介面",
    "6683": "高速測試載板設計",
    # AI PCB / 高頻高速 CCL / ABF 載板
    "3037": "ABF載板/高階PCB",
    "8046": "ABF載板高階產能",
    "3189": "高階載板/記憶體載板",
    "2383": "高頻高速CCL銅箔基板",
    "6274": "高階伺服器CCL基板",
    "6213": "高頻CCL銅箔基板",
    "2368": "高階AI伺服器UBB/OAM",
    "3044": "高階HDI與伺服器PCB",
    "8155": "高階伺服器厚板PCB",
    "1815": "高階玻纖布材料",
    # 伺服器機殼 / 滑軌 / 連接線器
    "2059": "AI伺服器高階導軌",
    "8210": "AI伺服器高階機箱",
    "3693": "雲端伺服器機箱",
    "3533": "高階CPU/GPU Socket",
    "3653": "伺服器均熱片/散熱機構",
    "3665": "AI伺服器高速線束",
    "5269": "高速傳輸介面晶片",
    "3526": "高速連接器/線材",
    "3217": "伺服器DDR5連接器",
    # CPO / 矽光子 / 光通訊傳輸
    "3450": "CPO矽光子/光通訊封測",
    "6442": "800G光收發模組",
    "3163": "光纖被動元件/CPO",
    "4979": "光收發晶粒與模組",
    "4977": "CPO光通訊模組",
    "3363": "光纖跳線/矽光封裝",
    "3081": "光通訊雷射磊晶片",
    "6451": "高階光電系統封裝",
    "3234": "光通訊收發模組",
    "3167": "高階PCB/載板鑽孔機",
    # AI 電源 / 電力供應
    "2308": "AI伺服器高瓦數電源",
    "2301": "雲端伺服器電源",
    "6412": "高功率伺服器電源",
    "6282": "伺服器電源供應",
    # AI 儲存 / 高頻記憶體模組
    "8299": "AI邊緣SSD控制晶片",
    "3260": "高頻DDR5記憶體模組",
    "4967": "電競與伺服器超頻記憶體",
    "5289": "工控與邊緣AI儲存",
    "2408": "DRAM高頻記憶體",
    "2344": "記憶體晶圓代工製造",
    "6531": "VHM高頻寬記憶體IP",
    # 網通交換器 / 高速資料中心傳輸
    "2345": "800G白牌交換器龍頭",
}

ELECTRONIC_SECTOR_KEYWORDS = {
    "半導體", "電腦", "電子", "光電", "通信", "通訊", "資訊服務", "電子通路", "電子零組件", "網路"
}


def is_electronic_stock(code: str, name: str, sector: str) -> bool:
    """判斷個股是否為上市櫃電子類股普通股"""
    # 排除 ETF、權證、債券等非普通股（代號非4碼數字）
    if not (code.isdigit() and len(code) == 4):
        return False

    # 若為已知 AI 供應鏈直接通過
    if code in AI_SUPPLY_CHAIN_MAP:
        return True

    # 檢驗產業類別文字
    for kw in ELECTRONIC_SECTOR_KEYWORDS:
        if kw in sector:
            return True

    return False


def screen_chip_resonance_top10(
    market_snapshot: Dict[str, Dict[str, Any]],
    previous_market: Optional[Dict[str, Any]],
    market_names: Dict[str, str],
    market_sectors: Dict[str, str],
    limit: int = 10,
    trade_date: str = "",
) -> List[Dict[str, Any]]:
    """
    執行長短線籌碼共振篩選：
    1. 限制電子股（AI股優先加權）
    2. 千張大戶持股比例較上週上升 (ratio_change_1000 > 0)
    3. 5D 券商分點集中度維持正值 (concentration_5d > 0%)
    4. 依共振強度評分輸出 Top 10
    """
    previous_stocks = (previous_market or {}).get("stocks", {})
    if not previous_stocks:
        logger.warning("無上期集保快照，無法計算長短線籌碼共振排行")
        return []

    # 第一階段：篩出本週千張大戶持股比例上升之電子股
    candidates = []
    for code, curr in market_snapshot.items():
        name = market_names.get(code, curr.get("name", code))
        sector = market_sectors.get(code, "")
        if not is_electronic_stock(code, name, sector):
            continue

        prev = previous_stocks.get(code)
        if not prev:
            continue

        try:
            prev_ratio = float(str(prev.get("ratio_1000", 0)).replace(",", ""))
            curr_ratio = float(str(curr.get("ratio_1000", 0)).replace(",", ""))
            change_1000 = curr_ratio - prev_ratio
        except Exception:
            continue

        if change_1000 <= 0:
            continue

        is_ai = code in AI_SUPPLY_CHAIN_MAP
        ai_tag = AI_SUPPLY_CHAIN_MAP.get(code, "")

        # 候選池初篩權重：AI 概念優先給予額外加權
        initial_score = (change_1000 * 10) + (15.0 if is_ai else 0.0)

        candidates.append({
            "code": code,
            "name": name,
            "sector": sector,
            "ratio_1000": curr_ratio,
            "change_1000": change_1000,
            "is_ai": is_ai,
            "ai_tag": ai_tag,
            "initial_score": initial_score,
        })

    if not candidates:
        logger.info("本週未篩出千張大戶增加之電子股")
        return []

    # 排序初選池，取前 35 檔進行第二階段分點查詢
    candidates.sort(key=lambda x: x["initial_score"], reverse=True)
    top_candidates = candidates[:35]
    query_codes = [c["code"] for c in top_candidates]

    logger.info("已篩出 %d 檔大戶吃貨電子股，正在查詢近 5 日券商分點集中度...", len(query_codes))

    # 第二階段：平行查詢 5D 券商分點集中度
    broker_data = fetch_watchlist_broker_chips(query_codes, target_date=trade_date)

    # 交叉驗證：長短線共振篩選 (5D 集中度必須 > 0)
    resonated_stocks = []
    for item in top_candidates:
        code = item["code"]
        b_info = broker_data.get(code, {})
        c5 = b_info.get("concentration_5d")
        c1 = b_info.get("concentration_1d")

        # 若查無 5D 集中度或 5D 集中度 <= 0，代表短線主力並未進駐甚至在出貨，予以剔除！
        if c5 is None or c5 <= 0:
            continue

        c1_val = c1 if c1 is not None else 0.0

        # 最終綜合共振評分公式：
        # 大戶存量增幅 (權重 x10) + 5D短線集中度 (權重 x2.5) + 1D短線衝刺 (權重 x0.5) + AI加權 (+15)
        ai_bonus = 15.0 if item["is_ai"] else 0.0
        final_score = (item["change_1000"] * 10.0) + (c5 * 2.5) + (c1_val * 0.5) + ai_bonus

        resonated_stocks.append({
            **item,
            "concentration_5d": c5,
            "concentration_1d": c1,
            "matrix_status": b_info.get("matrix_status", "主力買超"),
            "matrix_action": b_info.get("matrix_action", "順勢偏多"),
            "top_buyers_5d": b_info.get("top_buyers_5d", []),
            "final_score": round(final_score, 1),
        })

    # 依綜合共振評分排序
    resonated_stocks.sort(key=lambda x: x["final_score"], reverse=True)
    return resonated_stocks[:limit]


def format_chip_resonance_report(
    stocks: List[Dict[str, Any]],
    report_date: str = "",
    baseline_date: str = "",
) -> str:
    """將籌碼共振 Top 10 格式化為 Markdown 報告（適合 Discord 頻道與週報）"""
    lines = [
        "🚀 *【台股長短線籌碼共振 Top 10（電子／AI 供應鏈）】*",
        f"📅 集保週日：`{report_date}` ｜ 比較基準：`{baseline_date}`",
        "🎯 *選股核心*：千張大戶逐週吸籌 ＋ 近5日券商主力分點同步買超",
        "──────────────────────",
    ]

    if not stocks:
        lines.append("本週電子族群中無同時滿足「千張大戶增加 ＋ 5D分點集中度>0」之個股。")
        return "\n".join(lines)

    for idx, s in enumerate(stocks, 1):
        ai_badge = f" 🤖【{s['ai_tag']}】" if s.get("is_ai") else ""
        c5_str = f"+{s['concentration_5d']:.1f}%" if s['concentration_5d'] > 0 else f"{s['concentration_5d']:.1f}%"
        c1_str = f"{s['concentration_1d']:+.1f}%" if s.get('concentration_1d') is not None else "—"
        
        buyers = ""
        if s.get("top_buyers_5d"):
            buyers = f"｜買方：{s['top_buyers_5d'][0].split('+')[0].strip()}"

        lines.append(
            f"**{idx}.** 🔷 **{s['code']} {s['name']}**{ai_badge}\n"
            f"   • 大戶籌碼：千張大戶 `{s['ratio_1000']:.1f}%`（`{s['change_1000']:+.2f}pt` 🔼）\n"
            f"   • 主力分點：5D集中度 `{c5_str}`（1D `{c1_str}`）{buyers}\n"
            f"   • 籌碼型態：{s['matrix_status']}（{s['matrix_action']}）｜共振分 `{s['final_score']}`\n"
        )

    lines.append("──────────────────────")
    lines.append("💡 **實戰解析**：千張大戶增加代表長線籌碼鎖碼，5D集中度大於零代表短線主力點火，長短線共振具備波段續航力。")
    return "\n".join(lines)


def export_to_stockcenter_ranking(
    stocks: List[Dict[str, Any]],
    report_date: str = "",
    stockcenter_root: str = "/Users/jess/Desktop/Python/StockCenter",
) -> None:
    """將排行榜同步寫入 StockCenter 的 Markdown 排行榜檔案中"""
    sc_path = Path(stockcenter_root)
    if not sc_path.exists():
        logger.debug("StockCenter 路徑不存在，略過 StockCenter 同步: %s", stockcenter_root)
        return

    # 1. 寫入專屬獨立排行榜檔案：stock_chip_resonance_ranking.md
    target_md = sc_path / "stock_chip_resonance_ranking.md"
    table_lines = [
        "# 🚀 台股長短線籌碼共振 Top 10（電子／AI 供應鏈）",
        "",
        f"> 集保統計日：{report_date}。篩選條件：限上市櫃電子股、千張大戶比例逐週上升、近5日券商分點集中度維持正值。",
        "",
        "| 排名 | 代號 | 名稱 | AI族群標籤 | 千張大戶持股 | 本週大戶增幅 | 5D分點集中度 | 1D分點集中度 | 籌碼型態 | 共振評分 |",
        "|:---:|:---:|:---|:---|---:|---:|---:|---:|:---|---:|",
    ]

    for idx, s in enumerate(stocks, 1):
        ai_label = s.get("ai_tag") or s.get("sector") or "電子"
        table_lines.append(
            f"| **{idx}** | `{s['code']}` | **{s['name']}** | {ai_label} | {s['ratio_1000']:.1f}% | +{s['change_1000']:.2f}pt | +{s['concentration_5d']:.1f}% | {s['concentration_1d']:+.1f}% | {s['matrix_status']} | **{s['final_score']}** |"
        )

    table_lines.append("")
    table_lines.append("---")
    table_lines.append("### 💡 判讀心法")
    table_lines.append("1. **長線存量鎖碼**：千張大戶比例上升，代表散戶籌碼沉澱，由公司大股東或外資投信主帳戶穩定吸收。")
    table_lines.append("2. **短線流量發動**：5D 分點集中度大於 0%，證明這不是沉睡中的存量，而是短線主力券商正在進場拉抬或吸籌。")
    table_lines.append("3. **AI 供應鏈加成**：AI 相關個股具備長線產業基本面題材，長短線共振時波段爆發力最強。")
    table_lines.append("")

    full_md_content = "\n".join(table_lines)
    try:
        target_md.write_text(full_md_content, encoding="utf-8")
        logger.info("已成功寫入 StockCenter 專屬籌碼共振榜: %s", target_md)
    except Exception as exc:
        logger.error("寫入 StockCenter 專屬榜失敗: %s", exc)

    # 2. 追加同步更新至 stock_winrate_ranking.md 與 stock_winrate_ranking_evolution.md
    for filename in ["stock_winrate_ranking.md", "stock_winrate_ranking_evolution.md"]:
        main_md = sc_path / filename
        if not main_md.exists():
            continue
        try:
            content = main_md.read_text(encoding="utf-8")
            section_header = "## 🚀 長短線籌碼共振 Top 10（電子／AI 供應鏈）"
            # 建立要嵌入的區塊
            embed_lines = [
                section_header,
                f"> 資料日期：{report_date}。條件：上市櫃電子股、千張大戶逐週增加 ＋ 5D主力分點集中度維持正值。",
                "",
                "| 排名 | 代號 | 股票名稱 | 核心AI題材 | 千張大戶比例 | 大戶增幅 | 5D集中度 | 1D集中度 | 籌碼矩陣型態 | 共振評分 |",
                "|:---:|:---:|:---|:---|---:|---:|---:|---:|:---|---:|",
            ]
            for idx, s in enumerate(stocks, 1):
                ai_label = s.get("ai_tag") or s.get("sector") or "電子"
                embed_lines.append(
                    f"| **{idx}** | `{s['code']}` | **{s['name']}** | {ai_label} | {s['ratio_1000']:.1f}% | +{s['change_1000']:.2f}pt | +{s['concentration_5d']:.1f}% | {s['concentration_1d']:+.1f}% | {s['matrix_status']} | **{s['final_score']}** |"
                )
            embed_lines.append("")
            embed_block = "\n".join(embed_lines)

            # 若已存在舊章節則替換，否則追加於檔案末尾
            if section_header in content:
                pattern = re.compile(rf"{re.escape(section_header)}.*?(?=\n## |\Z)", re.DOTALL)
                new_content = pattern.sub(embed_block, content)
            else:
                new_content = content.rstrip() + "\n\n---\n\n" + embed_block

            main_md.write_text(new_content, encoding="utf-8")
            logger.info("已同步更新 StockCenter 排行榜文件: %s", filename)
        except Exception as exc:
            logger.warning("更新 StockCenter 文件 %s 失敗: %s", filename, exc)

    # 3. 同步寫入 StockCenter 的法人與主力籌碼策略榜 (institutional_chip_strategy_ranking.md)
    inst_md = sc_path / "institutional_chip_strategy_ranking.md"
    if inst_md.exists():
        try:
            content = inst_md.read_text(encoding="utf-8")
            section_header = "## ⑤ 🚀 長短線籌碼共振 TOP 10（電子／AI 供應鏈）"
            embed_lines = [
                section_header,
                "",
                "| 排名 | 股票代號 | 股票名稱 | AI族群標籤 | 千張大戶持股 | 5D集中度 | 共振評分 |",
                "|---:|:---:|:---|:---|---:|---:|---:|",
            ]
            for idx, s in enumerate(stocks, 1):
                ai_label = s.get("ai_tag") or s.get("sector") or "電子"
                embed_lines.append(
                    f"| {idx} | `{s['code']}` | {s['name']} | {ai_label} | {s['ratio_1000']:.1f}%(+{s['change_1000']:.2f}pt) | +{s['concentration_5d']:.1f}% | {s['final_score']} |"
                )
            embed_lines.append("")
            embed_block = "\n".join(embed_lines)

            if section_header in content:
                pattern = re.compile(rf"{re.escape(section_header)}.*?(?=\n## |\n> 僅納入|\Z)", re.DOTALL)
                new_content = pattern.sub(embed_block + "\n", content)
            else:
                if "\n> 僅納入" in content:
                    parts = content.split("\n> 僅納入", 1)
                    new_content = parts[0].rstrip() + "\n\n" + embed_block + "\n> 僅納入" + parts[1]
                else:
                    new_content = content.rstrip() + "\n\n" + embed_block

            inst_md.write_text(new_content, encoding="utf-8")
            logger.info("已成功寫入 StockCenter 法人與主力策略榜: %s", inst_md)
        except Exception as exc:
            logger.warning("寫入 StockCenter 法人策略榜失敗: %s", exc)
