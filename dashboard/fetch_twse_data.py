#!/usr/bin/env python3
"""Fetch TWSE market data server-side and save as local JSON files.
OpenAPI has no CORS; this prefetches from server (no CORS issues)."""
import json, os, sys
from pathlib import Path
from datetime import datetime, timedelta

try:
    import requests
except ImportError:
    os.system(f"{sys.executable} -m pip install requests -q")
    import requests

BASE = Path(__file__).parent
DATA_DIR = BASE / 'data'
DATA_DIR.mkdir(exist_ok=True)

utc_now = datetime.utcnow()
tw_now = utc_now + timedelta(hours=8)

def prev_trading_day(dt):
    dt = dt - timedelta(days=1)
    while dt.weekday() >= 5:
        dt -= timedelta(days=1)
    return dt

if tw_now.hour < 13 or (tw_now.hour == 13 and tw_now.minute < 30):
    target = prev_trading_day(tw_now)
else:
    target = tw_now
    if target.weekday() >= 5:
        target = prev_trading_day(target)

date_str = target.strftime('%Y%m%d')
print(f'Target date: {date_str}')

API = 'https://openapi.twse.com.tw/v1'
endpoints = {
    'MI_INDEX':     f'{API}/exchangeReport/MI_INDEX',
    'STOCK_DAY_ALL': f'{API}/exchangeReport/STOCK_DAY_ALL',
    'BWIBBU_ALL':   f'{API}/exchangeReport/BWIBBU_ALL',
    'MI_MARGN':     f'{API}/exchangeReport/MI_MARGN',
    'MI_INDEX20':   f'{API}/exchangeReport/MI_INDEX20',
}
for name, url in endpoints.items():
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            data = r.json()
            fp = DATA_DIR / f'{name}.json'
            with open(fp, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
            n = len(data) if isinstance(data, list) else '?'
            print(f'  {name}: {n} items saved')
        else:
            print(f'  {name}: HTTP {r.status_code}')
    except Exception as e:
        print(f'  {name}: {e}')

# Margin RWD - try multiple dates with fallback
def prev_td(dt):
    dt = dt - timedelta(days=1)
    while dt.weekday() >= 5:
        dt -= timedelta(days=1)
    return dt
margin_data = None
for d in range(10):
    if d == 0:
        test_date = target  # use the script's already-calculated target date
    else:
        test_date = prev_td(target) if d == 1 else prev_td(test_date)
    ds = test_date.strftime('%Y%m%d')
    try:
        r = requests.get(
            f'https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date={ds}&selectType=ALL',
            timeout=15
        )
        if r.status_code == 200:
            data = r.json()
            if data.get('stat') == 'OK' and data.get('tables'):
                margin_data = data
                date_str = ds
                print(f'  MARGIN_RWD: date={ds}, {len(data["tables"])} tables saved')
                break
            else:
                print(f'  MARGIN_RWD: {ds} -> {data.get("stat","no data")}')
        else:
            print(f'  MARGIN_RWD: {ds} -> HTTP {r.status_code}')
    except Exception as e:
        print(f'  MARGIN_RWD: {ds} -> {e}')
if margin_data:
    fp = DATA_DIR / 'MARGIN_RWD.json'
    with open(fp, 'w', encoding='utf-8') as f:
        json.dump(margin_data, f, ensure_ascii=False)
else:
    print(f'  MARGIN_RWD: no valid data found in last 10 days')

# Meta
with open(DATA_DIR / 'meta.json', 'w') as f:
    json.dump({'date': date_str, 'updated': tw_now.strftime('%Y-%m-%dT%H:%M:%S+08:00')}, f)

print('Done.')
