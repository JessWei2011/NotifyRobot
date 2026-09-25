# 📈 台股盤後籌碼 Telegram 自動推播機器人

專為新手設計的自動化台股盤後籌碼推播工具。每日盤後自動推播兩個時段的三大法人資料：15:00–18:50 每 10 分鐘確認、當日資料就緒後才發送的**上市大盤法人買賣超金額**，以及 20:30 的上市、上櫃**自選股動態**與**三大策略榜單**（單日法人買超 Top 10、單日法人賣超 Top 10、波段連續買超 $\ge$ 5 天 Top 10）。

每日 08:00 至 23:59，程式每 10 分鐘檢查一次自選股的重大訊息、注意股票與處置資訊；新公告、處置開始與結束都會個別推送。

每週六 09:30 另推送一次集保大戶籌碼週報：400–999 張與 1,000 張以上的持股比例、戶數與週變化。每日 20:30 的自選股報告則會附上當日盤中大戶大單力道（買賣超張數與佔比）及融資餘額、增減張數與增減率。

若在 `.env` 設定 `DISCORD_BOT_TOKEN`、`DISCORD_CHANNEL_ID`（#台股通知）與 `DISCORD_CHIP_CHANNEL_ID`（#籌碼資料），通知將自動分流：自選股、重大訊息、行事曆、大戶週報與大盤金額推送到台股通知頻道，三大法人買賣超榜單與連買策略則推送到籌碼資料頻道。亦可使用舊版 `DISCORD_WEBHOOK_URL` 進行單一 Webhook 推播。可用 `python3 main.py --test-discord` 進行 Discord 連線測試。

若要自動同步永豐 Shioaji 的非 ETF 持股，請在 NotifyRobot 的 `.env` 設定 `SJ_ENV_FILE` 指向已驗證可用的 Shioaji `.env`。程式只讀取持股，不會啟用憑證或下單；指定的憑證檔優先於 NotifyRobot 內舊的 Shioaji 變數。

若要確認遠端電腦與排程正常運作，可另外建立 Discord 頻道並設定 `DISCORD_HEARTBEAT_WEBHOOK_URL`。執行 `python3 main.py --heartbeat-discord` 可手動在該頻道發送主機名稱與目前時間。可在 `config.json` 的 `discord_heartbeat.message` 自訂內容，並以 `{hostname}`、`{time}` 與 `{quote}` 插入主機名稱、發送時間與隨機金句；金句清單由 `discord_heartbeat.quotes` 管理。將 `discord_heartbeat.enabled` 改為 `false` 即可停用手動心跳。

---

## 🚀 新手 3 步驟快速上手

### 一鍵執行（Mac / Windows）

完成 `.env` 設定後：
- **Mac**：在 Finder 雙擊 `run.command`。
- **Windows**：直接雙擊 `run.bat`。

即可執行一次正式推播。視窗會保留執行結果；同一交易日已成功推播的報告會自動略過。

首次取得 Telegram Chat ID 時，請先對新 Bot 傳送 `hi`，Mac 雙擊 `setup_telegram.command`，Windows 可執行 `python test_telegram.py`。

### 步驟 1：建立 Telegram Bot（約 2 分鐘）

1. 打開 Telegram，在搜尋欄搜尋官方機器人管理員：`@BotFather`。
2. 傳送指令 `/newbot` 給它。
3. 依提示依序輸入：
   - 機器人顯示名稱（如：`MyStockBot`）
   - 機器人帳號 ID（必須以 `bot` 結尾，如：`jess_stock_alert_bot`）
4. 建立成功後，`@BotFather` 會給你一串 **HTTP API Token**（格式如：`123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ`）。

### 步驟 2：設定 Token 與 Chat ID

1. 複製設定檔：
   ```bash
   cp .env.example .env
   ```
2. 編輯 `.env` 檔案，填入你的 Token：
   ```env
   TELEGRAM_BOT_TOKEN=你的Token
   ```
3. 執行連線測試小工具（它會自動幫你抓取你的個人 Chat ID 並發送測試 Hello 訊息）：
   ```bash
   python3 test_telegram.py
   ```

### 步驟 3：測試執行與排程

1. **終端機預覽測試（免發送訊息）**：
   ```bash
   python3 main.py --dry-run
   ```
2. **正式推播測試**：
   ```bash
   python3 main.py
   ```
3. **設定 Mac 本機平日自動排程**：
   ```bash
   ./setup_cron.sh
   ```
   *排程將於平日週一至週五 15:00–18:50 每 10 分鐘確認一次當日法人資料，資料就緒後推送一次；20:30 推送上市與上櫃個股報告；08:30 推送開盤前行事曆（沒有事件時也會通知），並寫入 `bot.log`。*

## ✅ 推播成功與「已收到」確認

- Telegram API 回傳成功與 `message_id` 後，程式才會將報告標記為已推播；暫時性網路錯誤、429 或伺服器錯誤會自動重試。
- 大盤法人買賣超採兩階段獨立推播：15:00（約 15:10 資料就緒）推播「盤後初估版本」，17:00 推播「盤後定案版本」。自營商僅計算自行買賣，避險部位不納入三大法人現貨合計計算（附帶備註參考）。
- 同一交易日的同一份報告預設只發送一次。若需手動重送，使用 `python3 main.py --force`。
- 每則正式推播預設附有「✅ 已收到」按鈕。點擊後會記錄於 `data/notification_state.sqlite3`。
- `setup_cron.sh` 同時會加上一個每五分鐘執行的確認同步工作。若不使用 cron，可手動執行 `python3 main.py --check-acks`。

---

## ⚙️ 如何新增或修改自選股？

最簡單的方式是開啟本機設定頁：
- **Mac**：在 Finder 雙擊 `config_ui.command`。
- **Windows**：雙擊 `config_ui.bat`。

瀏覽器會開啟本機設定頁，可新增、刪除與修改通知個股；按「儲存通知清單」後，下次推播便會套用。此清單會與未來自動同步的永豐非 ETF 持股合併。

開啟 `config.json`，直接修改 `watchlist` 陣列即可：

```json
{
  "watchlist": [
    {"code": "2330", "name": "台積電"},
    {"code": "2317", "name": "鴻海"},
    {"code": "2454", "name": "聯發科"},
    {"code": "3008", "name": "大立光"}
  ],
  "screener": {
    "enable_dual_buyers": true,
    "enable_it_top": true,
    "top_n": 10,
    "min_lots": 300
  }
}
```

---

## 🤖 Discord 互動查詢機器人 (斜線指令)

NotifyRobot 現已支援 Discord 即時雙向互動！只要機器人常駐執行，即可在 Discord 任何頻道直接下指令查詢個股：

- **`/stock <代號>`**：查詢個股即時價量行情、開高低收、成交量、內外盤大單力道，以及最近交易日三大法人（外資、投信、自營商）買賣超籌碼。
- **`/news <代號>`**：上網即時爬取個股最新新聞，並由 AI 自動總結核心動態、題材、正面動能（利多）與風險觀察（利空）。
- **`/alert <代號>`（或 `/alart`）**：查詢個股是否進入注意股票、警告或處置股票。**若主管機關已公告確認處置日期（不論是否已經開始處置），皆會完整印出處置起訖日期、原因與措施。**

### 啟動方式
- **Mac 雙擊**：`run_discord_bot.command`
- **Windows 雙擊**：`run_discord_bot.bat`
- **終端機執行**：
  ```bash
  python3 run_bot.py
  # 或
  python3 main.py --discord-bot
  ```

> 💡 **AI 新聞分析設定**：在 `.env` 中設定 `GEMINI_API_KEY=你的金鑰`（可免費於 Google AI Studio 申請），即可啟用 Gemini 智能新聞重點分析！若未設定，機器人將條列最新新聞標題與連結。

---

## 📂 專案檔案說明

- `main.py`：主程式入口，支援 `--dry-run`、`--date YYYYMMDD` 與 `--discord-bot`。
- `run_bot.py`：Discord 互動機器人啟動腳本。
- `run_discord_bot.command` / `.bat`：一鍵啟動 Discord 互動機器人。
- `src/bot_service.py`：Discord Slash Commands 與事件監聽處理器。
- `src/stock_query.py`：即時價量、籌碼查詢、處置注意警示與 AI 新聞分析模組。
- `test_telegram.py`：Telegram Bot 連線驗證小幫手。
- `setup_cron.sh`：Mac 定時排程設定腳本。
- `config.json`：自選股清單與策略開關設定。
- `.env`：敏感金鑰 (Token / Chat ID / API Keys) 儲存檔。
- `src/fetcher.py`：證交所官方開放資料 API 爬蟲。
- `src/analyzer.py`：籌碼統計、自選比對、土洋同步買超篩選。
- `src/notifier.py`：Telegram / Discord Markdown 訊息美化與發送。
