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

# 4. 本日收盤快照（Yahoo Finance）
python3 -c "
import json, urllib.request, time
url = 'https://query1.finance.yahoo.com/v8/finance/chart/%5ETWII?range=2d&interval=1d'
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
resp = urllib.request.urlopen(req, timeout=15)
chart = json.loads(resp.read())
r = chart['chart']['result'][0]
ts = r['timestamp'][-1]; q = r['indicators']['quote'][0]
t = time.gmtime(ts + 28800)
date_str = time.strftime('%Y%m%d', t)
with open('data/today-index.json', 'w') as f:
    json.dump({
        'date': date_str,
        'open': q['open'][-1], 'high': q['high'][-1],
        'low': q['low'][-1], 'close': q['close'][-1],
        'volume': q['volume'][-1] or 0,
    }, f)
print(f'✅ today-index.json: {date_str} close={q["close"][-1]:.0f}')
"

# 5. Commit + Push
git add data/ ../charts/data/taiex-historical.json sentiment-data.json sentiment-history.json
git commit -m "chore: refresh $(date +%Y-%m-%d)" --allow-empty
git push
