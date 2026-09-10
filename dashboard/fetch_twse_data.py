#!/usr/bin/env python3
"""Fetch TWSE market data server-side and save as local JSON files.
OpenAPI has no CORS; this prefetches from server (no CORS issues)."""
import json, os, sys, time
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

# ── Fallback: OpenAPI often updates 1-2 hrs after close (still yesterday's data).
# If STOCK_DAY_ALL from OpenAPI is stale, fetch the same-day CSV from
# www.twse.com.tw rwd (updates ~14:00) and convert to OpenAPI schema.
target_roc = (target.year - 1911) * 10000 + target.month * 100 + target.day
try:
    with open(DATA_DIR / 'STOCK_DAY_ALL.json', encoding='utf-8') as f:
        _sda = json.load(f)
    _sda_date = str(_sda[0].get('Date', '')) if _sda else ''
except Exception:
    _sda_date = ''
if _sda_date != str(target_roc):
    print(f'  OpenAPI STOCK_DAY_ALL stale (date={_sda_date}), trying rwd CSV for {date_str}...')
    try:
        r = requests.get(
            f'https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY_ALL?date={date_str}',
            timeout=60)
        if r.status_code == 200 and r.text.strip().startswith('日期'):
            import csv, io
            rows = list(csv.DictReader(io.StringIO(r.text)))
            mapped = []
            for row in rows:
                if str(row.get('日期', '')).strip() != str(target_roc):
                    continue
                def _num(v):
                    return v.replace(',', '') if v else v
                mapped.append({
                    'Date': str(row['日期']).strip(),
                    'Code': row['證券代號'].strip(),
                    'Name': row['證券名稱'].strip(),
                    'TradeVolume': _num(row['成交股數']),
                    'TradeValue': _num(row['成交金額']),
                    'OpeningPrice': row['開盤價'].strip(),
                    'HighestPrice': row['最高價'].strip(),
                    'LowestPrice': row['最低價'].strip(),
                    'ClosingPrice': row['收盤價'].strip(),
                    'Change': row['漲跌價差'].strip(),
                    'Transaction': _num(row['成交筆數']),
                })
            if mapped:
                with open(DATA_DIR / 'STOCK_DAY_ALL.json', 'w', encoding='utf-8') as f:
                    json.dump(mapped, f, ensure_ascii=False)
                print(f'  STOCK_DAY_ALL: rwd fallback OK, {len(mapped)} items (ROC {target_roc})')
            else:
                print('  STOCK_DAY_ALL: rwd CSV has no rows for target date')
        else:
            print(f'  STOCK_DAY_ALL: rwd fallback HTTP {r.status_code} (not CSV)')
    except Exception as e:
        print(f'  STOCK_DAY_ALL: rwd fallback failed: {e}')

# ── Fallback: OpenAPI MI_INDEX also lags 1-2h after close, and the rwd
# `type=ALL` query is blocked between 13:30-13:45 ("網站尖峰時間"). Fetch the
# rwd MI_INDEX (available ~13:45) and convert to the OpenAPI schema so
# build_closing_data.py can use the OFFICIAL TAIEX instead of Yahoo's
# provisional ^TWII value (which can differ by ~100 points right after close).
try:
    with open(DATA_DIR / 'MI_INDEX.json', encoding='utf-8') as f:
        _mi = json.load(f)
    _mi_date = str(_mi[0].get('日期', '')) if _mi else ''
except Exception:
    _mi_date = ''
if _mi_date != str(target_roc):
    print(f'  OpenAPI MI_INDEX stale (date={_mi_date}), trying rwd MI_INDEX for {date_str}...')
    try:
        # TWSE load-sheds `type=ALL` intermittently ("每日1:30PM到1:45PM為網站
        # 尖峰時間..."), even at 13:50 — retry until a real table set arrives.
        d = {}
        for _try in range(6):
            r = requests.get(
                f'https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={date_str}&type=ALL&response=json',
                timeout=120, headers={'User-Agent': 'Mozilla/5.0'})
            d = r.json()
            if d.get('tables'):
                break
            print(f'  MI_INDEX rwd attempt {_try+1}: {d.get("stat", "no tables")}')
            time.sleep(15)
        tables = d.get('tables') or []
        mapped, digest = [], {}
        for t in tables:
            fields = t.get('fields') or []
            rows = t.get('data') or []
            if fields[:2] == ['指數', '收盤指數']:
                for row in rows:
                    _s = str(row[2])
                    # rwd wraps the sign in HTML, e.g. "<p style ='color:green'>-</p>";
                    # take the text node after the first tag so the trailing "</p>"
                    # (whose own '>' has no sign after it) can't hide the sign.
                    _s = _s.split('>')[1] if '>' in _s else _s
                    sign = '-' if '-' in _s else '+'
                    mapped.append({
                        '日期': str(target_roc),
                        '指數': str(row[0]).strip(),
                        '收盤指數': str(row[1]).replace(',', '').strip(),
                        '漲跌': sign,
                        '漲跌點數': str(row[3]).replace(',', '').strip(),
                        '漲跌百分比': str(row[4]).replace(',', '').strip(),
                        '特殊處理註記': str(row[5]).strip() if len(row) > 5 else '',
                    })
            elif '大盤統計' in str(t.get('title') or ''):
                digest['turnover'] = [{'item': r0[0], 'value': r0[1]}
                                      for r0 in rows if len(r0) > 1]
            elif '漲跌證券數' in str(t.get('title') or ''):
                digest['breadth'] = [{'type': r0[0], 'all': r0[1], 'stock': r0[2]}
                                     for r0 in rows if len(r0) > 2]
        if mapped:
            with open(DATA_DIR / 'MI_INDEX.json', 'w', encoding='utf-8') as f:
                json.dump(mapped, f, ensure_ascii=False)
            print(f'  MI_INDEX: rwd fallback OK, {len(mapped)} index rows (ROC {target_roc})')
            digest['date'] = date_str
            industries = [m for m in mapped if m['指數'].endswith('類指數')]
            digest['industries'] = industries
            digest['key_indices'] = [
                m for m in mapped if m['指數'] in (
                    '發行量加權股價指數', '未含金融指數', '未含電子指數',
                    '未含金融電子指數', '臺灣50指數', '寶島股價指數')]
            with open(DATA_DIR / 'mi-index-digest.json', 'w', encoding='utf-8') as f:
                json.dump(digest, f, ensure_ascii=False)
            print(f'  MI_INDEX digest saved: {len(industries)} 類股指數, '
                  f'{len(digest.get("turnover", []))} 成交統計 rows')
        else:
            print('  MI_INDEX: rwd returned no index tables (or 13:30-13:45 block)')
    except Exception as e:
        print(f'  MI_INDEX: rwd fallback failed: {e}')

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
