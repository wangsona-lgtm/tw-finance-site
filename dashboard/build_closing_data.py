#!/usr/bin/env python3
"""
Build comprehensive closing/YYYY-MM-DD.json with ALL 上市櫃 stocks.

Sources:
  - TWSE OpenAPI (上市):  dashboard/data/STOCK_DAY_ALL.json (from fetch_twse_data.py)
  - TPEx API (上櫃):      https://www.tpex.org.tw (queried live)

Output:
  - closing/YYYY-MM-DD.json: daily closing data with index + all stocks
  - closing/list.json:       updated date index

Run after fetch_twse_data.py (step 1 of refresh_data.sh).
"""
import json, os, sys, time, urllib.request
from datetime import datetime, timedelta, timezone

# ── paths ──────────────────────────────────────────────────────────
BASE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(BASE)
DATA_DIR = os.path.join(BASE, 'data')
CLOSING_DIR = os.path.join(REPO, 'closing')
os.makedirs(CLOSING_DIR, exist_ok=True)

# ── date helpers ───────────────────────────────────────────────────
def prev_trading_day(dt):
    dt = dt - timedelta(days=1)
    while dt.weekday() >= 5:
        dt -= timedelta(days=1)
    return dt

def get_target_date():
    tw = datetime.now(timezone.utc) + timedelta(hours=8)
    # Before 14:00 → use previous trading day
    if tw.hour < 14:
        return prev_trading_day(tw)
    # Weekend → use Friday
    if tw.weekday() >= 5:
        return prev_trading_day(tw)
    return tw

target = get_target_date()
date_iso = target.strftime('%Y-%m-%d')
date_roc = target.strftime('%Y%m%d')   # 1150612 for ROC
date_tpex = target.strftime('%Y%m%d')  # same for TPEx
dow_map = '一二三四五六日'
day_of_week = dow_map[target.weekday()]

print(f'Target date: {date_iso} (ROC {date_roc}, {day_of_week})')

# ── 1. TAIEX index from Yahoo Finance ─────────────────────────────
index_data = {}
try:
    url = 'https://query1.finance.yahoo.com/v8/finance/chart/%5ETWII?range=2d&interval=1d'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    resp = urllib.request.urlopen(req, timeout=15)
    chart = json.loads(resp.read())
    r = chart['chart']['result'][0]
    ts = r['timestamp']
    q = r['indicators']['quote'][0]
    t = time.gmtime(ts[-1] + 28800)
    idx_date = time.strftime('%Y-%m-%d', t)

    if idx_date == date_iso or True:  # accept whatever Yahoo gives
        prev = q['close'][-2] if len(ts) > 1 else q['close'][-1]
        c = q['close'][-1] or 0
        o = q['open'][-1] or 0
        h = q['high'][-1] or 0
        l = q['low'][-1] or 0
        v = q['volume'][-1] or 0
        chg = c - prev
        chg_pct = round(chg / prev * 100, 2) if prev else 0

        index_data = {
            'name': 'TAIEX 加權指數',
            'close': round(c, 2),
            'change': round(chg, 2),
            'changePercent': chg_pct,
            'open': round(o, 2),
            'high': round(h, 2),
            'low': round(l, 2),
            'prevClose': round(prev, 2),
            'volume': int(v),
            'feature': f'{"🟢" if chg>=0 else "🔴"} {"漲" if chg>=0 else "跌"} {abs(chg):.0f} 點（{chg_pct:+.2f}%）'
        }
        print(f'  ✅ TAIEX: {c:.0f} ({chg:+.0f}, {chg_pct:+.2f}%)')
except Exception as e:
    print(f'  ⚠️ TAIEX fetch failed: {e}')

# ── 2. TWSE listed stocks (上市) ───────────────────────────────────
twse_stocks = []
sda_path = os.path.join(DATA_DIR, 'STOCK_DAY_ALL.json')
if os.path.exists(sda_path):
    try:
        with open(sda_path) as f:
            raw = json.load(f)
        for s in raw:
            code = s.get('Code', '')
            name = s.get('Name', '')
            close_str = s.get('ClosingPrice', '--')
            change_str = s.get('Change', '0')

            if close_str == '--' or not close_str:
                continue

            try:
                close = float(close_str)
            except (ValueError, TypeError):
                continue

            # Change might be like "0.0000", "-0.1100", "+1.50"
            try:
                change = float(change_str)
            except (ValueError, TypeError):
                change = 0.0

            # Calculate changePercent from change and previous close
            prev_close = close - change
            change_pct = round(change / prev_close * 100, 2) if prev_close != 0 else 0.0

            twse_stocks.append({
                'code': code,
                'name': name,
                'close': close,
                'change': round(change, 2),
                'changePercent': change_pct,
                'market': '上市'
            })
        print(f'  ✅ TWSE stocks: {len(twse_stocks)}')
    except Exception as e:
        print(f'  ⚠️ TWSE parse error: {e}')
else:
    print(f'  ⚠️ STOCK_DAY_ALL.json not found (run fetch_twse_data.py first)')

# ── 3. TPEx OTC stocks (上櫃) ──────────────────────────────────────
otc_stocks = []
try:
    tpex_url = f'https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/stk_quote_result.php?l=zh-tw&d={date_tpex}&stk=ALL'
    req = urllib.request.Request(tpex_url, headers={'User-Agent': 'Mozilla/5.0'})
    resp = urllib.request.urlopen(req, timeout=15)
    tpex_data = json.loads(resp.read())

    for table in tpex_data.get('tables', []):
        title = table.get('title', '')
        if '上櫃' not in title and '管理' not in title:
            continue
        fields = table.get('fields', [])
        # Find column indices
        try:
            ix_code = fields.index('代號')
            ix_name = fields.index('名稱')
            ix_close = fields.index('收盤')
            ix_change = fields.index('漲跌')
        except ValueError:
            continue

        for row in table.get('data', []):
            if len(row) <= max(ix_code, ix_name, ix_close, ix_change):
                continue
            code = row[ix_code]
            name = row[ix_name]
            close_str = row[ix_close]
            change_str = row[ix_change]

            # Filter: only actual OTC stocks (not warrants 7xxxx, not ETFs 6xxxx)
            # OTC stock codes are 4-digit or 0xxx
            if not code.isdigit():
                continue
            if len(code) > 4 or code.startswith('6'):
                continue  # skip ETFs and warrants

            if close_str in ('--', '', None):
                continue
            try:
                close = float(close_str)
            except (ValueError, TypeError):
                continue

            # Change: "+1.79", "-0.50", or "---"
            try:
                change = float(change_str)
            except (ValueError, TypeError):
                change = 0.0

            prev_close = close - change
            change_pct = round(change / prev_close * 100, 2) if prev_close != 0 else 0.0

            otc_stocks.append({
                'code': code,
                'name': name,
                'close': close,
                'change': round(change, 2),
                'changePercent': change_pct,
                'market': '上櫃'
            })
    print(f'  ✅ TPEx OTC stocks: {len(otc_stocks)}')
except Exception as e:
    print(f'  ⚠️ TPEx fetch error: {e}')

# ── 4. Combine & save ─────────────────────────────────────────────
all_stocks = twse_stocks + otc_stocks
# Remove duplicates (some ETFs might appear in both)
seen = set()
unique_stocks = []
for s in all_stocks:
    key = s['code']
    if key in seen:
        continue
    seen.add(key)
    unique_stocks.append(s)

# Sort by market (上市 first), then by code
unique_stocks.sort(key=lambda s: (0 if s['market'] == '上市' else 1, s['code']))

closing_data = {
    'date': date_iso,
    'dayOfWeek': day_of_week,
    'marketStatus': 'closed',
    'index': index_data,
    'stocks': unique_stocks,
    'summary': {
        'totalStocks': len(unique_stocks),
        'listed': len(twse_stocks),
        'otc': len(otc_stocks)
    }
}

closing_path = os.path.join(CLOSING_DIR, f'{date_iso}.json')
with open(closing_path, 'w', encoding='utf-8') as f:
    json.dump(closing_data, f, ensure_ascii=False, indent=2)
print(f'\n✅ closing/{date_iso}.json saved: {len(unique_stocks)} stocks ({len(twse_stocks)} 上市 + {len(otc_stocks)} 上櫃)')

# ── 5. Update list.json ──────────────────────────────────────────
list_path = os.path.join(CLOSING_DIR, 'list.json')
if os.path.exists(list_path):
    with open(list_path) as f:
        lst = json.load(f)
else:
    lst = []

# Insert at front, remove duplicate
lst = [e for e in lst if e.get('date') != date_iso]
feature = index_data.get('feature', '—')
lst.insert(0, {'date': date_iso, 'dayOfWeek': day_of_week, 'feature': feature})

with open(list_path, 'w', encoding='utf-8') as f:
    json.dump(lst, f, ensure_ascii=False, indent=2)
print(f'  ✅ list.json updated ({len(lst)} entries)')

# ── 6. Update today-index.json for dashboard ──────────────────────
if index_data:
    today_idx_path = os.path.join(DATA_DIR, 'today-index.json')
    with open(today_idx_path, 'w') as f:
        json.dump({
            'date': date_iso.replace('-', ''),
            'open': index_data['open'],
            'high': index_data['high'],
            'low': index_data['low'],
            'close': index_data['close'],
            'volume': index_data.get('volume', 0),
        }, f)
    print(f'  ✅ today-index.json updated')

print(f'\n🎉 Done! {len(unique_stocks)} stocks total')
