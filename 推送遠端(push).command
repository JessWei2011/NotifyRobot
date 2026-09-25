#!/bin/zsh

set -u

cd "$(dirname "$0")" || exit 1

echo "=========================================="
echo "  NotifyRobot - 強制推送覆蓋遠端 (Git Push) "
echo "=========================================="
echo "⚠️  注意：此操作將以本機版本為主，強制覆蓋遠端 (origin/main)！"
echo ""
read "confirm?是否開始推送覆蓋遠端？ [y/N] "

if [[ "$confirm" != [yY] ]]; then
  echo "已取消操作，沒有變更任何檔案。"
  read "?按 Enter 鍵關閉視窗..."
  exit 0
fi

if ! command -v git >/dev/null 2>&1; then
  echo "❌ 找不到 Git，請確認系統已安裝 Git。"
  read "?按 Enter 鍵關閉視窗..."
  exit 1
fi

current_branch="$(git branch --show-current)"
if [[ "$current_branch" != "main" ]]; then
  echo "❌ 目前不在 main 分支（目前為：${current_branch:-無}），為保護專案暫停推送。"
  read "?按 Enter 鍵關閉視窗..."
  exit 1
fi

echo ""
read "commit_message?請輸入提交訊息 (直接按 Enter 使用預設更新時間)："
if [[ -z "${commit_message// }" ]]; then
  commit_message="Update: $(date '+%Y-%m-%d %H:%M:%S')"
fi

echo "📦 暫存本機所有變更 (git add)..."
git add -A || {
  echo "❌ 暫存檔案失敗。"
  read "?按 Enter 鍵關閉視窗..."
  exit 1
}

# 檢查是否有已暫存的修改
if ! git diff --cached --quiet; then
  echo "📝 建立 Commit [${commit_message}]..."
  git commit -m "$commit_message" || {
    echo "❌ 建立 Commit 失敗。"
    read "?按 Enter 鍵關閉視窗..."
    exit 1
  }
else
  echo "ℹ️  本機沒有新的未提交變更，直接進行推送。"
fi

echo "🚀 正在強制推送至遠端 (git push --force origin main)..."
if ! git push --force origin main; then
  echo "❌ 推送至遠端失敗，請檢查網路連線或遠端權限。"
  read "?按 Enter 鍵關閉視窗..."
  exit 1
fi

echo ""
echo "✅ 推送完成！遠端 origin/main 已成功被本機版本覆蓋。"
read "?按 Enter 鍵關閉視窗..."
