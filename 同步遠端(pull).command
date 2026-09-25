#!/bin/zsh

set -u

cd "$(dirname "$0")" || exit 1

echo "=========================================="
echo "  NotifyRobot - 同步遠端至本機 (Git Pull)  "
echo "=========================================="
echo "⚠️  注意：此操作將以遠端 (origin/main) 完全覆蓋本機追蹤檔案！"
echo "ℹ️  本機未提交的修改將被放棄；.env 等私有設定檔會保留。"
echo ""
read "confirm?是否開始同步覆蓋本機？ [y/N] "

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

echo ""
echo "📥 正在自遠端抓取最新主分支 (fetch)..."
if ! git fetch origin --prune || ! git rev-parse --verify origin/main >/dev/null; then
  echo "❌ 無法讀取 origin/main，請檢查網路連線或遠端權限。"
  read "?按 Enter 鍵關閉視窗..."
  exit 1
fi

current_branch="$(git branch --show-current)"
if [[ "$current_branch" != "main" ]]; then
  echo "🔀 切換至 main 分支..."
  if ! git switch --discard-changes main; then
    echo "❌ 無法切換至 main 分支。"
    read "?按 Enter 鍵關閉視窗..."
    exit 1
  fi
fi

echo "🔄 正在以 origin/main 強制覆蓋本機追蹤檔案..."
if ! git reset --hard origin/main; then
  echo "❌ 重置同步失敗。"
  read "?按 Enter 鍵關閉視窗..."
  exit 1
fi

echo ""
echo "✅ 同步完成！本機檔案目前已與遠端 origin/main 完全一致。"
read "?按 Enter 鍵關閉視窗..."
