#!/bin/bash
# ==============================================================================
# Mac 本機 Crontab 排程設定小幫手
# 用途：設定台股通知、事件警示，以及每日 Discord 主機心跳
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_EXEC="$(which python3)"
LOG_FILE="$SCRIPT_DIR/bot.log"
MARKET_CRON_JOB="*/10 15-18 * * 1-5 cd $SCRIPT_DIR && $PYTHON_EXEC $SCRIPT_DIR/main.py --market-summary >> $LOG_FILE 2>&1"
STOCK_CRON_JOB="30 20 * * 1-5 cd $SCRIPT_DIR && $PYTHON_EXEC $SCRIPT_DIR/main.py >> $LOG_FILE 2>&1"
EVENT_CRON_JOB="*/10 8-23 * * 1-5 cd $SCRIPT_DIR && $PYTHON_EXEC $SCRIPT_DIR/main.py --check-events >> $LOG_FILE 2>&1"
CALENDAR_CRON_JOB="30 8 * * 1-5 cd $SCRIPT_DIR && $PYTHON_EXEC $SCRIPT_DIR/main.py --morning-calendar >> $LOG_FILE 2>&1"
BIG_HOLDER_CRON_JOB="30 9 * * 6 cd $SCRIPT_DIR && $PYTHON_EXEC $SCRIPT_DIR/main.py --big-holder-report >> $LOG_FILE 2>&1"
HEARTBEAT_CRON_JOB="0 * * * * cd $SCRIPT_DIR && $PYTHON_EXEC $SCRIPT_DIR/main.py --heartbeat-discord >> $LOG_FILE 2>&1"
PROJECT_MARKER="$SCRIPT_DIR/main.py"

echo "=================================================="
echo "🍎 Mac 本機定時排程設定助手"
echo "=================================================="
echo "專案路徑: $SCRIPT_DIR"
echo "Python 路徑: $PYTHON_EXEC"
echo "排程時間: 平日 15:00–18:50 確認當日法人資料、20:30 個股報告"
echo "自選股事件警示: 平日 08:00~23:59 每 10 分鐘"
echo "開盤前行事曆: 平日 08:30"
echo "大戶籌碼週報: 每週六 09:30"
echo "Discord 主機心跳: 每小時整點"
echo "日誌輸出: $LOG_FILE"
echo "=================================================="

# 檢查是否已存在相同的 cron 排程
crontab -l 2>/dev/null | grep -F "$PROJECT_MARKER" > /dev/null
if [ $? -eq 0 ]; then
    echo "⚠️ 偵測到已存在本專案的排程！"
    echo "目前的 Crontab 內容如下："
    crontab -l | grep -F "$PROJECT_MARKER"
    echo ""
    read -p "是否要移除舊排程並重新建立？(y/N): " choice
    if [[ "$choice" =~ ^[Yy]$ ]]; then
        crontab -l 2>/dev/null | grep -v -F "$PROJECT_MARKER" | crontab -
        echo "已移除舊排程。"
    else
        echo "操作已取消。"
        exit 0
    fi
fi

# 新增排程
(crontab -l 2>/dev/null; echo "$MARKET_CRON_JOB"; echo "$STOCK_CRON_JOB"; echo "$EVENT_CRON_JOB"; echo "$CALENDAR_CRON_JOB"; echo "$BIG_HOLDER_CRON_JOB"; echo "$HEARTBEAT_CRON_JOB") | crontab -

echo "🎉 排程設定完成！已新增以下定時任務至你的 Mac："
crontab -l | grep -F "$PROJECT_MARKER"
echo ""
echo "💡 提示："
echo "1. 每日執行紀錄可於 $LOG_FILE 查看。"
echo "2. 若未來想移除排程，可執行: crontab -e 並刪除對應行，或清空排程。"
