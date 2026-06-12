#!/usr/bin/env python3
"""Update charts/data/taiex-historical.json with yesterday's closing data from Yahoo Finance.

Runs daily after market close. Appends new daily OHLCV record if not already present.
"""
import json, time, urllib.request, os, sys

HISTORICAL_PATH = os.path.join(os.path.dirname(__file__), '..', 'charts', 'data', 'taiex-historical.json')
HISTORICAL_PATH = os.path.abspath(HISTORICAL_PATH)

# Load existing data
with open(HISTORICAL_PATH) as f:
    data = json.load(f)

last_date = data[-1]['date'] if data else ''

# Fetch latest data from Yahoo Finance (last 2 days)
url = 'https://query1.finance.yahoo.com/v8/finance/chart/%5ETWII?range=5d&interval=1d'
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
resp = urllib.request.urlopen(req, timeout=15)
chart = json.loads(resp.read())

result = chart['chart']['result'][0]
timestamps = result['timestamp']
quotes = result['indicators']['quote'][0]

added = 0
for i in range(len(timestamps)):
    ts = timestamps[i]
    # Convert to Asia/Taipei date string
    t = time.gmtime(ts + 28800)  # UTC+8
    date_str = time.strftime('%Y-%m-%d', t)
    o = quotes['open'][i]
    h = quotes['high'][i]
    l = quotes['low'][i]
    c = quotes['close'][i]
    v = quotes['volume'][i] or 0

    if o is None or c is None:
        continue
    if date_str <= last_date:
        continue  # already in file

    data.append({
        'date': date_str,
        'o': round(o, 2), 'h': round(h, 2),
        'l': round(l, 2), 'c': round(c, 2),
        'v': int(v)
    })
    added += 1
    last_date = date_str

if added > 0:
    with open(HISTORICAL_PATH, 'w') as f:
        json.dump(data, f)
    print(f'✅ taiex-historical.json: added {added} day(s), now {len(data)} records (last: {last_date})')
else:
    print(f'ℹ️  taiex-historical.json: no new data (last: {last_date})')
