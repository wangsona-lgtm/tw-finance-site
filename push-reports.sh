#!/bin/bash
# ============================================================
# push-reports.sh - 每日晨報/行情自動上傳 GitHub Pages
# 用法: bash push-reports.sh
# ============================================================
TZ='Asia/Taipei'; export TZ
DATE=$(date +%Y-%m-%d)
REPO_DIR="/home/nutc/.openclaw/workspace/tw-finance-site"

cd "$REPO_DIR" || { echo "❌ 找不到 $REPO_DIR"; exit 1; }

# 檢查是否有變更
if [[ -z $(git status --short) ]]; then
  echo "ℹ️ 沒有新的變更 ($DATE)"
  exit 0
fi

echo "📦 準備上傳 $DATE 的資料..."

# 顯示即將提交的檔案
echo ""
echo "📋 變更檔案："
git status --short
echo ""

# Add, Commit, Push
git add -A
git commit -m "data: 更新 $DATE 晨報與行情"
git push origin main 2>&1

if [[ $? -eq 0 ]]; then
  echo ""
  echo "✅ 上傳完成：$DATE → https://wangsona-lgtm.github.io/tw-finance-site/daily-reports.html"
else
  echo "❌ 上傳失敗，請檢查 git 狀態"
  exit 1
fi
