#!/usr/bin/env python3
"""Update backtest/tw-stock-data.json with recent daily OHLCV data from Yahoo Finance.

Appends new trading days to each stock's data list if not already present.
"""
import json, time, urllib.request, os, sys

STOCK_PATH = os.path.join(os.path.dirname(__file__), '..', 'backtest', 'tw-stock-data.json')
STOCK_PATH = os.path.abspath(STOCK_PATH)

with open(STOCK_PATH) as f:
    data = json.load(f)

stocks = data.get('stocks', {})

updated_count = 0
for code, sdata in stocks.items():
    if not isinstance(sdata, dict) or 'data' not in sdata:
        continue
    records = sdata['data']
    if not records:
        continue
    last_date = records[-1]['d']

    # Yahoo Finance symbol (remove .TW suffix for query or use as-is)
    yf_symbol = code

    # Fetch from Yahoo Finance (last 5 days to cover weekends/holidays)
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{yf_symbol}?range=5d&interval=1d'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        resp = urllib.request.urlopen(req, timeout=15)
        chart = json.loads(resp.read())
    except Exception as e:
        print(f'  ⚠️ {code}: fetch failed ({e})')
        continue

    result = chart['chart']['result']
    if not result:
        print(f'  ⚠️ {code}: empty result')
        continue

    timestamps = result[0]['timestamp']
    quotes = result[0]['indicators']['quote'][0]
    adjclose = result[0]['indicators'].get('adjclose', [{}])[0].get('adjclose', [])

    added = 0
    for i in range(len(timestamps)):
        ts = timestamps[i]
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

        # Use adjusted close if available (for ETFs/dividends)
        if adjclose and i < len(adjclose) and adjclose[i] is not None:
            c = adjclose[i]

        records.append({
            'd': date_str,
            'o': round(o, 2), 'h': round(h, 2),
            'l': round(l, 2), 'c': round(c, 2),
            'v': int(v)
        })
        added += 1
        last_date = date_str

    if added > 0:
        updated_count += 1
        print(f'  ✅ {code} ({sdata.get("name","")}): +{added} day(s) → {len(records)} rec')
    else:
        print(f'  ℹ️  {code} ({sdata.get("name","")}): up to date ({last_date})')

if updated_count > 0:
    data['updated'] = time.strftime('%Y-%m-%d %H:%M')
    with open(STOCK_PATH, 'w') as f:
        json.dump(data, f, ensure_ascii=False)
    print(f'\n✅ Updated {updated_count}/{len(stocks)} stocks')
else:
    print(f'\nℹ️  No updates needed ({len(stocks)} stocks checked)')
