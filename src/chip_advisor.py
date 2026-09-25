"""
NotifyRobot 籌碼趨勢評估外掛模組 (Chip Advisor Plugin)

本模組設計為獨立外掛函式庫，作為系統的接入點：
1. 整理個股籌碼與盤後資訊（排除「中實戶」）
2. 將數據結構化包裝並送至本機 Mac mini M4 的 Ollama Qwen 模型
3. Prompt: 「以專業經理人的角度，依據主力的實戰經驗，你給未來短期趨勢作評價。(不要樂觀、不要悲觀、就以專業角度回答)」
4. 清理並過濾思考標籤後，回傳純文字專業評價
"""

import os
import re
import logging
import requests
from pathlib import Path
from typing import Optional, Dict, Any

from src.stock_query import (
    resolver,
    build_full_stock_watchlist_report,
)

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
PROMPT_FILE = BASE_DIR / "chip_prompt.txt"

DEFAULT_PROMPT_TEMPLATE = """【股票標的】：{stock_info}
【籌碼與即時行情數據】：
{chip_data}

【分析任務】：
以專業經理人的角度，依據主力的實戰經驗，你給未來短期趨勢作評價。(不要樂觀、不要悲觀、就以專業角度回答)"""

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "120"))


def load_prompt_template() -> str:
    """熱載入外部 chip_prompt.txt 文件檔，修改後即時生效"""
    if not PROMPT_FILE.exists():
        try:
            PROMPT_FILE.write_text(DEFAULT_PROMPT_TEMPLATE, encoding="utf-8")
        except Exception as exc:
            logger.warning("建立 chip_prompt.txt 失敗: %s", exc)
        return DEFAULT_PROMPT_TEMPLATE

    try:
        content = PROMPT_FILE.read_text(encoding="utf-8").strip()
        if not content:
            return DEFAULT_PROMPT_TEMPLATE
        return content
    except Exception as exc:
        logger.warning("讀取 chip_prompt.txt 失敗: %s，改用預設模板", exc)
        return DEFAULT_PROMPT_TEMPLATE


def build_qwen_prompt(stock_info: str, chip_data: str) -> str:
    """根據外部文件檔內容組裝最終發送給 Qwen 的 Prompt"""
    template = load_prompt_template()
    # 若模板包含佔位符 {chip_data}，直接替換
    if "{chip_data}" in template:
        return template.replace("{stock_info}", stock_info).replace("{chip_data}", chip_data)
    else:
        # 若使用者在文件中直接輸入自訂的 Prompt 指令（未含佔位符）
        return f"【股票標的】：{stock_info}\n【籌碼與即時行情數據】：\n{chip_data}\n\n【分析任務】：\n{template}"


def clean_qwen_output(text: str) -> str:
    """過濾 <think>...</think> 標籤，保留純淨專業評價內文"""
    if not text:
        return ""
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    return cleaned.strip()


def query_qwen_model(prompt: str, model: str = OLLAMA_MODEL, timeout: int = OLLAMA_TIMEOUT) -> str:
    """呼叫本機 Mac mini M4 上的 Ollama API 進行推論"""
    endpoint = f"{OLLAMA_BASE_URL.rstrip('/')}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
    }
    try:
        response = requests.post(endpoint, json=payload, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        raw_output = data.get("response", "")
        return clean_qwen_output(raw_output)
    except requests.exceptions.ConnectionError:
        error_msg = f"無法連線至本地 Ollama 服務 ({endpoint})，請確認 Mac 上 Ollama 是否已啟動。"
        logger.error(error_msg)
        return f"❌ 【系統錯誤】：{error_msg}"
    except requests.exceptions.Timeout:
        error_msg = f"Ollama Qwen 模型生成逾時（超過 {timeout} 秒），請稍後再試。"
        logger.error(error_msg)
        return f"⏱️ 【系統逾時】：{error_msg}"
    except Exception as exc:
        error_msg = f"呼叫 Qwen 模型時發生例外錯誤: {exc}"
        logger.error(error_msg)
        return f"❌ 【系統錯誤】：{error_msg}"


def evaluate_stock_chip(code: str) -> str:
    """
    【主要外掛接入點函式】
    接收股票代號，整理除「中實戶」外的所有籌碼資訊，
    餵給本機 Qwen 評估短期趨勢並回傳評價字串。
    """
    clean_code = str(code).strip().upper()
    info = resolver.resolve(clean_code)
    if not info.get("exists"):
        return f"查無此股票代號「{clean_code}」，請確認台股代號是否正確。"

    name = info.get("name", clean_code)
    market_sector = f"{info.get('market', '')}・{info.get('sector', '')}".strip("・")

    # 1. 整理除中實戶外的所有資訊（現有完整報告包含行情、三大法人、主力分點、隔日衝、大戶大單、融資、警示）
    report = build_full_stock_watchlist_report(clean_code)
    if not report or not report.get("text"):
        return f"暫時無法取得 {clean_code} {name} 的完整籌碼數據，請稍後再試。"

    chip_summary = report["text"]
    stock_info = f"{clean_code} {name} ({market_sector})"

    # 2. 構建 Prompt（由外部 chip_prompt.txt 動態熱載入）
    prompt = build_qwen_prompt(stock_info, chip_summary)

    # 3. 送交 Qwen 推論
    evaluation = query_qwen_model(prompt)
    if not evaluation:
        return f"Qwen 未能針對 {clean_code} {name} 產出有效評價內容，請稍後再試。"

    return evaluation
