#!/bin/bash
# Refresh dashboard data and push to GitHub
set -e
cd "$(dirname "$0")"

# 1. 儀表板 TWSE 資料
python3 fetch_twse_data.py

# 2. 三大法人
python3 fetch_sentiment_data.py

# 3. 台股指數 K線歷史（Yahoo Finance）
python3 update_taiex_historical.py

# 4. 個股日K線（19 檔預載股，Yahoo Finance）
python3 update_stock_data.py

# 5. 每日收盤行情（上市櫃全量，closing-viewer）
python3 build_closing_data.py

# 6. Commit + Push
git add data/ ../closing/ ../charts/data/taiex-historical.json ../backtest/tw-stock-data.json sentiment-data.json sentiment-history.json
git commit -m "chore: refresh $(date +%Y-%m-%d)" --allow-empty
git push
