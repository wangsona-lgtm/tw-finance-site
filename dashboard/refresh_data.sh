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

# 5. 每日收盤行情（closing-viewer）
python3 -c "
import json, urllib.request, time, os

# TAIEX data
url = 'https://query1.finance.yahoo.com/v8/finance/chart/%5ETWII?range=2d&interval=1d'
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
resp = urllib.request.urlopen(req, timeout=15)
chart = json.loads(resp.read())
r = chart['chart']['result'][0]
ts = r['timestamp']; q = r['indicators']['quote'][0]
t = time.gmtime(ts[-1] + 28800)
date_str = time.strftime('%Y-%m-%d', t)
dayOfWeek = '一二三四五六'[t.tm_wday]

# Only update on weekdays
if t.tm_wday < 5:
    close_path = os.path.join(os.path.dirname(__file__), '..', 'closing', f'{date_str}.json')
    if os.path.exists(close_path):
        print(f'ℹ️  closing/{date_str}.json already exists')
    else:
        prev = q['close'][-2] if len(ts) > 1 else q['close'][-1] - 1
        data = {
            'date': date_str, 'dayOfWeek': dayOfWeek, 'marketStatus': 'closed',
            'index': {
                'name': 'TAIEX 加權指數',
                'close': round(q['close'][-1], 2) if q['close'][-1] else 0,
                'change': round(q['close'][-1] - prev, 2) if q['close'][-1] and prev else 0,
                'changePercent': round((q['close'][-1] - prev) / prev * 100, 2) if q['close'][-1] and prev else 0,
                'open': round(q['open'][-1], 2) if q['open'][-1] else 0,
                'high': round(q['high'][-1], 2) if q['high'][-1] else 0,
                'low': round(q['low'][-1], 2) if q['low'][-1] else 0,
                'prevClose': round(prev, 2),
                'feature': f'收 {round(q["close"][-1],0):.0f} 點'
            },
            'stocks': []
        }
        # Daily feature
        chg = data['index']['change']
        data['index']['feature'] = f'{"🟢" if chg>=0 else "🔴"} {"漲" if chg>=0 else "跌"} {abs(chg):.0f} 點（{data["index"]["changePercent"]:+.2f}%）'
        
        with open(close_path, 'w') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f'✅ closing/{date_str}.json created: {data["index"]["feature"]}')
        
        # Update list.json
        list_path = os.path.join(os.path.dirname(__file__), '..', 'closing', 'list.json')
        with open(list_path) as f:
            lst = json.load(f)
        lst.insert(0, {'date': date_str, 'dayOfWeek': dayOfWeek, 'feature': data['index']['feature']})
        with open(list_path, 'w') as f:
            json.dump(lst, f, ensure_ascii=False, indent=2)
"

# 6. 本日收盤快照（Yahoo Finance）
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

# 6. Commit + Push
git add data/ ../charts/data/taiex-historical.json ../backtest/tw-stock-data.json sentiment-data.json sentiment-history.json
git commit -m "chore: refresh $(date +%Y-%m-%d)" --allow-empty
git push
