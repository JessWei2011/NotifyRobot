import os
import re
import logging
from typing import Tuple, Dict, Any, List
import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi
from google import genai
import discord

logger = logging.getLogger(__name__)

def is_apple_podcast_url(url: str) -> bool:
    """判斷是否為 Apple Podcast 網址"""
    return "podcasts.apple.com" in url.lower()

def extract_apple_podcast_info(podcast_url: str) -> Dict[str, Any]:
    """從 Apple Podcast 單集頁面中解析單集名稱、節目名稱、時長、縮圖與音訊下載網址"""
    import urllib.request
    import urllib.parse
    import json

    parts = urllib.parse.urlsplit(podcast_url)
    encoded_url = urllib.parse.urlunsplit((
        parts.scheme,
        parts.netloc,
        urllib.parse.quote(parts.path),
        parts.query,
        parts.fragment
    ))
    
    req = urllib.request.Request(
        encoded_url,
        headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}
    )
    with urllib.request.urlopen(req) as resp:
        html = resp.read().decode('utf-8', errors='ignore')

    og_title_m = re.search(r'<meta property="og:title" content="([^"]+)"', html)
    og_img_m = re.search(r'<meta property="og:image" content="([^"]+)"', html)
    og_desc_m = re.search(r'<meta property="og:description" content="([^"]+)"', html)

    title = og_title_m.group(1) if og_title_m else '未知 Podcast 單集'
    thumbnail = og_img_m.group(1) if og_img_m else ''
    uploader = 'Apple Podcast'
    audio_url = ''
    duration = 0

    if og_desc_m:
        desc_text = og_desc_m.group(1)
        dur_m = re.search(r'(\d+)\s*(?:分鐘|mins?|minutes)', desc_text)
        if dur_m:
            duration = int(dur_m.group(1)) * 60

    server_data_m = re.search(r'<script[^>]*id="serialized-server-data"[^>]*>(.*?)</script>', html, re.DOTALL)
    if server_data_m:
        try:
            data = json.loads(server_data_m.group(1))
            def search_data(obj):
                nonlocal uploader, audio_url, duration
                if isinstance(obj, dict):
                    if 'currentMediaEnclosure' in obj and isinstance(obj['currentMediaEnclosure'], dict):
                        stream = obj['currentMediaEnclosure'].get('streamUrl')
                        if stream:
                            audio_url = stream
                    elif 'streamUrl' in obj and obj['streamUrl'] and not audio_url:
                        audio_url = obj['streamUrl']
                    if 'episodeOffer' in obj and isinstance(obj['episodeOffer'], dict):
                        show = obj['episodeOffer'].get('showOffer', {})
                        if show.get('title'):
                            uploader = show['title']
                    if 'durationMs' in obj and not duration:
                        duration = int(obj['durationMs']) // 1000
                    for v in obj.values():
                        search_data(v)
                elif isinstance(obj, list):
                    for item in obj:
                        search_data(item)
            search_data(data)
        except Exception:
            pass

    if not audio_url:
        mp3s = re.findall(r'https?://[^"\'\s]+\.(?:mp3|m4a)[^"\'\s]*', html)
        if mp3s:
            audio_url = mp3s[0]

    return {
        'title': title,
        'uploader': uploader,
        'duration': duration,
        'thumbnail': thumbnail,
        'webpage_url': podcast_url,
        'audio_url': audio_url,
        'media_type': 'podcast'
    }

def extract_video_id(url: str) -> str:
    """從常見 YouTube 網址格式中解析出 11 碼的 Video ID (包含 watch?v=, youtu.be, shorts, live)"""
    patterns = [
        r'(?:v=|\/v\/|youtu\.be\/|\/embed\/|\/shorts\/|\/live\/)([a-zA-Z0-9_-]{11})',
        r'^[a-zA-Z0-9_-]{11}$'
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return ""

def _get_common_ydl_opts() -> Dict[str, Any]:
    """取得相容且防 403 封鎖的 yt-dlp 通用選項"""
    opts: Dict[str, Any] = {
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'ios', 'web']
            }
        },
        'quiet': True,
        'no_warnings': True,
    }
    if os.path.exists('/opt/homebrew/bin/node'):
        opts['js_runtimes'] = {'node': {'path': '/opt/homebrew/bin/node'}}
    elif os.path.exists('/usr/local/bin/node'):
        opts['js_runtimes'] = {'node': {'path': '/usr/local/bin/node'}}
    return opts

def get_video_info(youtube_url: str) -> Dict[str, Any]:
    """獲取影片基本資訊（標題、作者、長度、縮圖）"""
    ydl_opts = _get_common_ydl_opts()
    ydl_opts['skip_download'] = True
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(youtube_url, download=False)
        return {
            'title': info.get('title', '未知標題'),
            'uploader': info.get('uploader', '未知作者'),
            'duration': info.get('duration', 0),
            'thumbnail': info.get('thumbnail', ''),
            'webpage_url': info.get('webpage_url', youtube_url)
        }

def get_transcript_from_youtube(video_id: str) -> Tuple[str, str]:
    """
    雙軌第一軌：嘗試提取官方或自動產生的字幕。
    相容新版與舊版 youtube-transcript-api 介面。
    優先順序：zh-TW, zh-Hant, zh, zh-Hans, en，若無則抓任一語言並自動轉為繁中。
    """
    try:
        # 相容物件實例或靜態類別方法
        if hasattr(YouTubeTranscriptApi, 'list_transcripts'):
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        else:
            api_instance = YouTubeTranscriptApi()
            transcript_list = api_instance.list(video_id)

        try:
            transcript = transcript_list.find_transcript(['zh-TW', 'zh-Hant', 'zh', 'zh-Hans', 'en'])
            lang_desc = f"原文字幕 ({transcript.language})"
        except Exception:
            transcript = next(iter(transcript_list))
            if transcript.is_translatable:
                transcript = transcript.translate('zh-Hant')
                lang_desc = f"自動翻譯字幕 (原語言: {transcript.language} -> 繁中)"
            else:
                lang_desc = f"可用字幕 ({transcript.language})"

        raw_data = transcript.fetch()
        full_text = " ".join([
            item.text if hasattr(item, 'text') else item.get('text', '')
            for item in raw_data
        ])
        return full_text.strip(), lang_desc
    except Exception as e:
        logger.warning(f"擷取 YouTube 字幕失敗或無字幕: {e}")
        return "", ""

def download_audio_and_transcribe_whisper(url_or_audio: str, is_direct_audio: bool = False, model_size: str = "base") -> Tuple[str, str]:
    """
    雙軌第二軌 / Podcast：啟用 Whisper 語音辨識（支援 YouTube 與直接音訊連結）
    """
    from faster_whisper import WhisperModel

    output_audio = "/tmp/yt_temp_audio.mp3"
    if os.path.exists(output_audio):
        os.remove(output_audio)

    if is_direct_audio:
        import urllib.request
        req = urllib.request.Request(
            url_or_audio,
            headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}
        )
        with urllib.request.urlopen(req) as resp, open(output_audio, 'wb') as f:
            while chunk := resp.read(1024 * 512):
                f.write(chunk)
    else:
        ydl_opts = _get_common_ydl_opts()
        ydl_opts.update({
            'format': 'bestaudio/best',
            'outtmpl': output_audio.rsplit('.', 1)[0],
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        })
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url_or_audio])

    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, info = model.transcribe(output_audio, language="zh", beam_size=3)

    text_list = [segment.text for segment in segments]
    full_text = " ".join(text_list).strip()

    if os.path.exists(output_audio):
        os.remove(output_audio)

    return full_text, f"Whisper 語音辨識 ({model_size})"

def generate_summary_with_ollama(prompt: str, transcript: str) -> str:
    """
    調用本機 Ollama (qwen3:8b) 進行摘要：
    完整傳送 100% 逐字稿，不刪減任何內容，並透過禁用思考推演加快本機運算速度。
    """
    import requests
    base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    model_name = os.getenv("OLLAMA_MODEL", "qwen3:8b")
    # 將本地超時拉長至 360 秒，確保長文本能完整運算完畢
    timeout = 360

    ollama_prompt = f"/no_think\n請直接輸出結構化繁體中文成果，不要輸出 <think> 思考標籤。\n\n{prompt}"

    resp = requests.post(
        f"{base_url.rstrip('/')}/api/generate",
        json={
            "model": model_name,
            "prompt": ollama_prompt,
            "stream": False,
            "options": {
                "temperature": 0.2,
                "num_ctx": 32768,
                "top_p": 0.8
            }
        },
        timeout=timeout
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Ollama 回應異常 (HTTP {resp.status_code}): {resp.text}")
    raw_result = resp.json().get("response", "")
    return re.sub(r"<think>.*?</think>", "", raw_result, flags=re.DOTALL).strip()


def generate_youtube_summary_smart(
    transcript: str,
    video_title: str,
    force_qwen: bool = False,
    content_type: str = "影音"
) -> Tuple[str, str]:
    """
    智慧摘要入口：
    - 若 force_qwen 為 True：直接使用本機 Ollama Qwen
    - 若 force_qwen 為 False：
        1. 優先嘗試 Gemini-2.5-flash
        2. 若遇 503/忙碌，自動重試 gemini-flash-latest 或 gemini-3.8-flash
        3. 若 Gemini 全數無法使用，自動無縫切換到本機 Ollama Qwen
    回傳 (摘要內容, 實際使用的模型名稱說明)
    """
    prompt = f"""你是一位資深的證券投資研究員與內容萃取專家。
請針對 {content_type}《{video_title}》的逐字稿，進行「去蕪存菁」的深入繁體中文專業筆記整理。

【過濾原則】：
1. 嚴格徹底濾除所有主持贅詞、口頭禪、哈囉打招呼、廢話、社群按讚訂閱、會員方案宣傳與工商廣告。
2. 拒絕浮泛表面的簡化摘要！請保留講者提到的「具體數據、位階點位、理由邏輯、產業趨勢、利多/利空」。

【請嚴格依據以下結構整理輸出】：

### 🔑 【特別提醒：週報通關密語】（若無提及則此區塊直接寫「無」）
- 若講者在內容中提及領取「週報」、「資料」、「研究報告」、「黑馬股名單」的**通關密語 / 通關密碼 / 暗號 / 代碼**（通常為一串數字如 888、168、年份，或英文如 WIN、VIP，或特定短詞）：
  👉 **請在此處醒目標註：「📢 本集週報通關密語：【密語內容】（用途說明/領取方式）」**

### 🌐 一、總經與大盤盤勢觀點
- **大盤/國際情勢**：（講者對目前台股大盤、美股、聯準會、匯率或總經局勢的判斷，包含關鍵支撐壓力、點位、多空方向或轉折訊號）
- **關鍵市場邏輯**：（講者提出支撐其大盤論點的核心原因）

### 📈 二、節目提及個股與族群深度剖析（務必完整列出）
（請逐一列出內容中講者提及的「每一檔個股／產業族群」，若無特定個股則寫該產業。每檔個股請包含：代號名稱、多空方向、講者的核心論點、營運/題材利多或風險、技術/籌碼看法）
• **【股票名稱/代號】**：
  - **核心題材/基本面**：...
  - **技術/籌碼/點位觀點**：...
  - **講者策略建議**：（例如：拉回找買點、高檔獲利了結、波段續抱等）

### 🎯 三、核心結論與操作策略指引
- **講者最終結論**：（濃縮整部內容最核心的投資結論）
- **操作重點建議**：（資金水位建議、持股節奏、後續觀察指標）

---
逐字稿內容：
{transcript}
"""

    gemini_key = os.getenv("GEMINI_API_KEY", "")
    default_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    ollama_model = os.getenv("OLLAMA_MODEL", "qwen3:8b")

    # 1. 使用者手動指定 -q：直接走本地 Qwen
    if force_qwen:
        logger.info(f"使用者指定 -q 參數，使用本機 Ollama ({ollama_model})...")
        summary = generate_summary_with_ollama(prompt, transcript)
        return summary, f"本機 Ollama ({ollama_model})"

    # 2. 預設走 Gemini 梯隊輪巡
    if not gemini_key:
        logger.warning("未偵測到 GEMINI_API_KEY，自動轉用本機 Ollama Qwen")
        summary = generate_summary_with_ollama(prompt, transcript)
        return summary, f"本機 Ollama ({ollama_model})"

    # 備用 Gemini 模型梯隊，防止單一型號 503
    candidate_gemini_models = [default_model, "gemini-flash-latest", "gemini-3.8-flash"]
    # 去除重複
    candidate_gemini_models = list(dict.fromkeys(candidate_gemini_models))

    last_gemini_err = None
    from google.genai import types
    client = genai.Client(
        api_key=gemini_key,
        http_options=types.HttpOptions(timeout=90.0)
    )

    for g_model in candidate_gemini_models:
        try:
            logger.info(f"嘗試呼叫 Gemini ({g_model}) 產出筆記...")
            response = client.models.generate_content(
                model=g_model,
                contents=prompt
            )
            return response.text.strip(), f"Google {g_model}"
        except Exception as exc:
            last_gemini_err = exc
            logger.warning(f"⚠️ Gemini ({g_model}) 呼叫失敗 ({exc})，嘗試下一順位...")

    # 若所有 Gemini 模型皆因高流量 503 或異常，自動啟用容錯機制切換至本機 Ollama Qwen
    logger.warning("所有 Gemini 模型均暫時無法使用，自動無縫切換至本機 Ollama Qwen...")
    try:
        summary = generate_summary_with_ollama(prompt, transcript)
        notice = f"> ⚠️ **系統提示**：Gemini 全線伺服器暫時壅塞 (503 高峰期)，已自動切換至本機 Ollama Qwen 完成分析。\n\n"
        return notice + summary, f"本機 Ollama ({ollama_model}) [自動容錯備援]"
    except Exception as qwen_err:
        raise RuntimeError(f"Gemini 呼叫失敗: {last_gemini_err}；且本機 Qwen 備援亦失敗: {qwen_err}")


def build_youtube_summary_embeds(
    video_info: Dict[str, Any],
    raw_summary: str,
    source_desc: str,
    model_desc: str = ""
) -> List[discord.Embed]:
    """
    將摘要文字轉換為 Discord 卡片式 (Embed) 排版
    """
    title = video_info.get("title", "YouTube 影片")
    url = video_info.get("webpage_url", "")
    uploader = video_info.get("uploader", "未知作者")
    duration = video_info.get("duration", 0)
    thumbnail = video_info.get("thumbnail", "")

    duration_str = f"{duration // 60} 分 {duration % 60} 秒" if duration else "未知長度"

    # Discord 單一 Embed description 上限 4096 字元，且所有 Embeds 總字數上限 6000 字元
    # 為確保絕對不會爆字數引發 DiscordServerError 500，單卡保守設為 3500 字元
    max_len = 3500
    chunks = [raw_summary[i:i + max_len] for i in range(0, len(raw_summary), max_len)]
    embeds = []

    is_podcast = video_info.get("media_type") == "podcast"
    icon = "🎙️" if is_podcast else "🎬"
    color = discord.Color.from_rgb(142, 68, 173) if is_podcast else discord.Color.from_rgb(255, 0, 0)
    source_label = "節目" if is_podcast else "頻道"

    for idx, chunk in enumerate(chunks):
        card_title = f"{icon} {title[:200]}" if idx == 0 else f"{icon} {title[:190]} (續 {idx + 1})"
        embed = discord.Embed(
            title=card_title,
            url=url,
            color=color,
            description=chunk
        )
        if idx == 0 and thumbnail:
            embed.set_thumbnail(url=thumbnail)
        if idx == len(chunks) - 1:
            footer_parts = [f"{source_label}: {uploader}", f"時長: {duration_str}", f"來源: {source_desc}"]
            if model_desc:
                footer_parts.append(f"AI: {model_desc}")
            embed.set_footer(text=" ｜ ".join(footer_parts))
        embeds.append(embed)

    return embeds
