#!/usr/bin/env python3
"""Refetch the OFFICIAL TWSE MI_INDEX for the target date.

Why this exists: TWSE load-sheds the rwd `MI_INDEX?type=ALL` query with a
"每日1:30PM到1:45PM為網站尖峰時間，查詢全部資料功能暫停使用!" stub -- the block
persists well past 13:45 and is *intermittent*, so a short fixed retry loop in
fetch_twse_data.py can lose the race and leave MI_INDEX.json holding the
previous day's rows (build_closing_data.py then silently falls back to Yahoo's
provisional ^TWII, which can be ~100 points off right after the close).

This script keeps polling both the rwd and the legacy exchangeReport endpoints
for up to ~20 minutes and only writes when it captures a real table set for the
requested date. Safe to re-run: it refuses to overwrite a good MI_INDEX.json.
"""
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

BASE = Path(__file__).parent
DATA_DIR = BASE / 'data'

UA = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0 Safari/537.36')
HEADERS = {
    'User-Agent': UA,
    'Referer': 'https://www.twse.com.tw/zh/afterTrading/MI_INDEX',
    'Accept': 'application/json, text/plain, */*',
}

tw_now = datetime.utcnow() + timedelta(hours=8)
target = tw_now
if tw_now.hour < 14:
    target = tw_now
if target.weekday() >= 5:
    d = target - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    target = d

date_str = target.strftime('%Y%m%d')
target_roc = (target.year - 1911) * 10000 + target.month * 100 + target.day
print(f'Target ROC date: {target_roc} ({date_str})')

# Already good?
try:
    with open(DATA_DIR / 'MI_INDEX.json', encoding='utf-8') as f:
        cur = json.load(f)
    if cur and str(cur[0].get('日期', '')) == str(target_roc):
        print('MI_INDEX.json already has the target date -- nothing to do.')
        sys.exit(0)
except Exception:
    pass

URLS = [
    f'https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={date_str}&type=ALL&response=json',
    f'https://www.twse.com.tw/exchangeReport/MI_INDEX?response=json&date={date_str}&type=ALL',
]

deadline = time.time() + 20 * 60
d = {}
attempt = 0
while time.time() < deadline:
    attempt += 1
    url = URLS[attempt % len(URLS)]
    try:
        r = requests.get(url, timeout=90, headers=HEADERS)
        d = r.json()
    except Exception as e:
        print(f'  attempt {attempt}: {e}')
        d = {}
        time.sleep(15)
        continue
    tables = d.get('tables') or []
    # The stub answers arrive as {"stat": "...", "type": "ALL"} with no tables.
    if any(t.get('fields') for t in tables):
        break
    print(f'  attempt {attempt}: {d.get("stat", "no tables")}')
    time.sleep(15)

tables = d.get('tables') or []
mapped, digest = [], {}
for t in tables:
    fields = t.get('fields') or []
    rows = t.get('data') or []
    if fields[:2] == ['指數', '收盤指數']:
        for row in rows:
            _s = str(row[2])
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

if not mapped:
    print('FAILED: never captured a real MI_INDEX table set.')
    sys.exit(1)

with open(DATA_DIR / 'MI_INDEX.json', 'w', encoding='utf-8') as f:
    json.dump(mapped, f, ensure_ascii=False)
print(f'MI_INDEX.json saved: {len(mapped)} index rows (ROC {target_roc})')

digest['date'] = date_str
industries = [m for m in mapped if m['指數'].endswith('類指數')]
digest['industries'] = industries
digest['key_indices'] = [
    m for m in mapped if m['指數'] in (
        '發行量加權股價指數', '未含金融指數', '未含電子指數',
        '未含金融電子指數', '臺灣50指數', '寶島股價指數')]
with open(DATA_DIR / 'mi-index-digest.json', 'w', encoding='utf-8') as f:
    json.dump(digest, f, ensure_ascii=False)
print(f'  digest: {len(industries)} 類股指數, '
      f'{len(digest.get("turnover", []))} 成交統計 rows, '
      f'{len(digest.get("breadth", []))} 漲跌證券數 rows')
taiex = [m for m in mapped if m['指數'] == '發行量加權股價指數']
if taiex:
    print(f'  TAIEX {taiex[0]["收盤指數"]} ({taiex[0]["漲跌"]}{taiex[0]["漲跌點數"]}, '
          f'{taiex[0]["漲跌百分比"]}%)')
