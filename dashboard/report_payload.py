#!/usr/bin/env python3
"""Assemble the Taiwan close report payload from official local data.

Sources (all already local after fetch_twse_data.py + refetch_mi_index.py):
  data/MI_INDEX.json          TWSE official index table (TAIEX + 類股指數)
  data/mi-index-digest.json   turnover / breadth / key indices
  data/STOCK_DAY_ALL.json     TWSE official per-stock close (10/16)
  data/MI_INDEX20.json        recent TAIEX closes (for the trend line)
  ../closing/<date>.json      full listed+OTC board (OTC may be Yahoo-labelled)
  MIS realtime (twse)         OTC index (o00) -- TWSE MIS has no TAIEX/OTC
                              index in STOCK_DAY_ALL
"""
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import requests

BASE = Path(__file__).parent
DATA = BASE / 'data'
CLOSING = BASE.parent / 'closing'

tw_now = datetime.utcnow() + timedelta(hours=8)
date_str = tw_now.strftime('%Y-%m-%d')
roc = f'{tw_now.year - 1911}{tw_now.month:02d}{tw_now.day:02d}'

mi = json.load(open(DATA / 'MI_INDEX.json', encoding='utf-8'))
dg = json.load(open(DATA / 'mi-index-digest.json', encoding='utf-8'))
sda = json.load(open(DATA / 'STOCK_DAY_ALL.json', encoding='utf-8'))
closing = json.load(open(CLOSING / f'{date_str}.json', encoding='utf-8'))

by_name = {m['指數']: m for m in mi}


def f(x):
    try:
        return float(str(x).replace(',', ''))
    except Exception:
        return None


def pct(m):
    return f(m['漲跌百分比'])


def show(m):
    return (f"{m['指數']} {m['收盤指數']} "
            f"{m['漲跌']}{m['漲跌點數']} ({m['漲跌百分比']}%)")


out = {}

taiex = by_name['發行量加權股價指數']
out['taiex'] = {
    'name': taiex['指數'],
    'close': f(taiex['收盤指數']),
    'change': f(taiex['漲跌點數']),
    'sign': taiex['漲跌'],
    'pct': f(taiex['漲跌百分比']),
}

# ── MI_INDEX20: intraday-ish TAIEX series for open/high/low ───────────────
try:
    m20 = json.load(open(DATA / 'MI_INDEX20.json', encoding='utf-8'))
    rows = [r for r in m20 if str(r.get('日期', '')) == roc]
    out['mi_index20_today'] = rows
except Exception as e:
    out['mi_index20_today'] = f'err {e}'

# ── OTC (櫃買) index from TWSE MIS realtime ──────────────────────────────
MIS = ('https://mis.twse.com.tw/stock/api/getStockInfo.jsp'
       '?ex_ch={sym}&json=1&delay=0')
head = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64)',
        'Referer': 'https://mis.twse.com.tw/stock/index.jsp'}
for sym, key in (('otc_o00.tw', 'otc'), ('tse_t00.tw', 'tse_mis')):
    try:
        r = requests.get(MIS.format(sym=sym), timeout=20, headers=head)
        arr = r.json().get('msgArray') or []
        if arr and arr[0].get('z') not in (None, '-', ''):
            a = arr[0]
            out[key] = {
                'code': a.get('c'), 'name': a.get('n'),
                'close': f(a.get('z')), 'prev': f(a.get('y')),
                'open': f(a.get('o')), 'high': f(a.get('h')),
                'low': f(a.get('l')), 'date': a.get('d'), 'time': a.get('%'),
            }
    except Exception as e:
        out[key] = f'err {e}'

# ── 類股指數 ranking ────────────────────────────────────────────────────
inds = [m for m in dg['industries'] if pct(m) is not None]
inds_sorted = sorted(inds, key=pct, reverse=True)
out['top_sectors'] = [{'name': m['指數'], 'close': f(m['收盤指數']),
                       'chg': m['漲跌'] + m['漲跌點數'], 'pct': pct(m)}
                      for m in inds_sorted[:6]]
out['bottom_sectors'] = [{'name': m['指數'], 'close': f(m['收盤指數']),
                          'chg': m['漲跌'] + m['漲跌點數'], 'pct': pct(m)}
                         for m in inds_sorted[-6:][::-1]]

# ── Heavyweights (official STOCK_DAY_ALL) ───────────────────────────────
hidx = {s['Code']: s for s in sda}
WANT = ['2330', '2454', '2317', '2308', '2382', '2303', '3711', '2881',
        '2882', '2412', '2891', '1301', '3008', '2408', '2357', '3231',
        '6669', '2603', '2454']
hw = []
for c in dict.fromkeys(WANT):
    s = hidx.get(c)
    if not s:
        continue
    cl, ch = f(s['ClosingPrice']), f(s['Change'])
    prev = cl - ch if (cl is not None and ch is not None) else None
    hw.append({
        'code': c, 'name': s['Name'], 'close': cl, 'change': ch,
        'pct': round(ch / prev * 100, 2) if prev else None,
        'turnover_yi': round(f(s['TradeValue']) / 1e8, 1) if f(s['TradeValue']) else None,
    })
out['heavyweights'] = hw

# ── Breadth from official STOCK_DAY_ALL (listed only) ───────────────────
up = down = flat = 0
for s in sda:
    ch = f(s['Change'])
    if ch is None:
        continue
    if ch > 0:
        up += 1
    elif ch < 0:
        down += 1
    else:
        flat += 1
out['breadth_listed'] = {'up': up, 'down': down, 'flat': flat,
                         'source': 'TWSE STOCK_DAY_ALL (上市)',
                         'raw_digest': dg.get('breadth')}
# OTC breadth from the closing file (may be Yahoo-sourced)
ou = od = of = 0
for s in closing['stocks']:
    if s.get('market') != '上櫃':
        continue
    c = s.get('change')
    if c is None:
        continue
    if c > 0:
        ou += 1
    elif c < 0:
        od += 1
    else:
        of += 1
out['breadth_otc'] = {'up': ou, 'down': od, 'flat': of,
                      'source': closing['summary'].get('otcSource', '?')}

# ── Top movers, listed, with a turnover floor to kill illiquid noise ────
def movers(rows, floor_yi=3.0, n=6, gain=True):
    cand = []
    for s in rows:
        cl, ch = f(s['ClosingPrice']), f(s['Change'])
        tv = f(s['TradeValue']) or 0
        if cl is None or ch is None or tv < floor_yi * 1e8:
            continue
        prev = cl - ch
        if not prev:
            continue
        p = ch / prev * 100
        cand.append({'code': s['Code'], 'name': s['Name'], 'close': cl,
                     'change': ch, 'pct': round(p, 2),
                     'turnover_yi': round(tv / 1e8, 1)})
    cand.sort(key=lambda x: x['pct'], reverse=gain)
    return cand[:n]


out['top_gainers'] = movers(sda, gain=True)
out['top_losers'] = movers(sda, gain=False)

# ── Turnover ────────────────────────────────────────────────────────────
tv = closing['index'].get('tradeValue')
out['turnover'] = {
    'today_ntd': tv,
    'today_yi': round(tv / 1e8, 1) if tv else None,
    'digest_rows': dg.get('turnover'),
}
# previous session from FMTQIK (month file) if reachable, else known value
try:
    r = requests.get('https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK'
                     '?date=' + tw_now.strftime('%Y%m01') + '&response=json',
                     timeout=60, headers=head)
    rows = r.json().get('data') or []
    prev = None
    for i, row in enumerate(rows):
        if str(row[0]).replace('115/', '').replace('/', '') == roc[3:]:
            if i > 0:
                prev = rows[i - 1]
            break
    out['fmtqik'] = {'prev_row': prev, 'last_row': rows[-1] if rows else None}
except Exception as e:
    out['fmtqik'] = f'err {e}'

# ── FX ──────────────────────────────────────────────────────────────────
try:
    import yfinance as yf
    d1 = yf.download(['TWD=X'], period='7d', interval='1d',
                     progress=False, auto_adjust=False)
    d5 = yf.download(['TWD=X'], period='1d', interval='5m',
                     progress=False, auto_adjust=False)
    cl = d1['Close']['TWD=X'].dropna()
    last = d5['Close']['TWD=X'].dropna()
    out['fx'] = {
        'latest': float(last.iloc[-1]) if len(last) else float(cl.iloc[-1]),
        'latest_ts': str(last.index[-1]) if len(last) else str(cl.index[-1]),
        'prev_close': float(cl.iloc[-1]) if len(last) else float(cl.iloc[-2]),
        'daily_rows': {str(k.date()): (None if v != v else round(float(v), 3))
                       for k, v in cl.items()},
    }
except Exception as e:
    out['fx'] = f'err {e}'

print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
