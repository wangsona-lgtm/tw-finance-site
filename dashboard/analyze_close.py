#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Summarise today's official TWSE close from data/STOCK_DAY_ALL.json + industry map.

Industry code -> name from TWSE ISIN 證券編碼_分類查詢 (isin.twse.com.tw/isin/class_i.jsp).
"""
import json, os, sys, collections, requests

BASE = '/home/nutc/.openclaw/workspace/tw-finance-site/dashboard'
DATA = os.path.join(BASE, 'data')

IND_NAME = {
    '01': '水泥工業', '02': '食品工業', '03': '塑膠工業', '04': '紡織纖維',
    '05': '電機機械', '06': '電器電纜', '08': '玻璃陶瓷', '09': '造紙工業',
    '10': '鋼鐵工業', '11': '橡膠工業', '12': '汽車工業', '13': '電子工業',
    '14': '建材營造', '15': '航運業', '16': '觀光餐旅', '17': '金融保險',
    '18': '貿易百貨', '19': '綜合', '20': '其他業', '21': '化學工業',
    '22': '生技醫療', '23': '油電燃氣', '24': '半導體業', '25': '電腦及週邊',
    '26': '光電業', '27': '通信網路', '28': '電子零組件', '29': '電子通路',
    '30': '資訊服務', '31': '其他電子', '32': '文化創意', '33': '農業科技',
    '35': '綠能環保', '36': '數位雲端', '37': '運動休閒', '38': '居家生活',
    '91': '存託憑證',
}


def num(s):
    s = str(s).replace(',', '').strip()
    try:
        return float(s)
    except Exception:
        return None


rows = json.load(open(os.path.join(DATA, 'STOCK_DAY_ALL.json'), encoding='utf-8'))

ind = {}
try:
    r = requests.get('https://openapi.twse.com.tw/v1/opendata/t187ap03_L',
                     timeout=60, headers={'User-Agent': 'Mozilla/5.0'})
    for it in r.json():
        ind[it.get('公司代號', '').strip()] = (it.get('產業別') or '').strip()
except Exception as e:
    print('industry map failed:', e, file=sys.stderr)

recs, stocks = [], []
for r0 in rows:
    c, ch = num(r0.get('ClosingPrice')), num(r0.get('Change'))
    if c is None or ch is None:
        continue
    x = {'code': r0['Code'], 'name': r0['Name'], 'close': c, 'chg': ch,
         'vol': num(r0.get('TradeVolume')) or 0, 'val': num(r0.get('TradeValue')) or 0,
         'chg_pct': (ch / (c - ch) * 100) if (c - ch) else 0.0}
    x['ind'] = IND_NAME.get(ind.get(x['code'], ''), '')
    recs.append(x)
    if len(x['code']) == 4 and not x['code'].startswith('00'):
        stocks.append(x)

out = []
out.append('官方 STOCK_DAY_ALL: %d 檔有收盤價/漲跌' % len(recs))
up = [x for x in stocks if x['chg'] > 0]
dn = [x for x in stocks if x['chg'] < 0]
fl = [x for x in stocks if x['chg'] == 0]
out.append('4碼個股 %d 檔：上漲 %d、下跌 %d、平盤 %d' % (len(stocks), len(up), len(dn), len(fl)))
out.append('漲停(+9.5%%以上) %d 家；跌停(-9.5%%以下) %d 家'
           % (len([x for x in stocks if x['chg_pct'] > 9.5]),
              len([x for x in stocks if x['chg_pct'] < -9.5])))

out.append('\n-- 成交金額 top 20 --')
for x in sorted(stocks, key=lambda z: -z['val'])[:20]:
    out.append('  %-6s %-9s %9.2f %+8.2f %+7.2f%%  %6.1f億'
               % (x['code'], x['name'], x['close'], x['chg'], x['chg_pct'], x['val'] / 1e8))

big = [x for x in stocks if x['val'] > 3e8]
out.append('\n-- 漲幅 top 20 (成交金額>3億) --')
for x in sorted(big, key=lambda z: -z['chg_pct'])[:20]:
    out.append('  %-6s %-9s %9.2f %+8.2f %+7.2f%%  %6.1f億  [%s]'
               % (x['code'], x['name'], x['close'], x['chg'], x['chg_pct'], x['val'] / 1e8, x['ind']))
out.append('\n-- 跌幅 top 20 (成交金額>3億) --')
for x in sorted(big, key=lambda z: z['chg_pct'])[:20]:
    out.append('  %-6s %-9s %9.2f %+8.2f %+7.2f%%  %6.1f億  [%s]'
               % (x['code'], x['name'], x['close'], x['chg'], x['chg_pct'], x['val'] / 1e8, x['ind']))

WATCH = ['2330', '2454', '2317', '2308', '2382', '2881', '2882', '2891', '2412',
         '3711', '3008', '2379', '3231', '2884', '2886', '1301', '1303', '6505',
         '2880', '1216', '2207', '2603', '2609', '2615', '2303', '2383', '3037',
         '2327', '2408', '6669', '3443', '2890', '2892']
out.append('\n-- 權值/焦點股 (官方) --')
m = {x['code']: x for x in recs}
for w in WATCH:
    x = m.get(w)
    if x:
        out.append('  %-6s %-9s %9.2f %+8.2f %+7.2f%%  %s'
                   % (w, x['name'], x['close'], x['chg'], x['chg_pct'],
                      '🟢' if x['chg'] > 0 else ('🔴' if x['chg'] < 0 else '⚪')))


def med(v):
    v = sorted(v)
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


buckets = collections.defaultdict(list)
for x in stocks:
    if x['ind']:
        buckets[x['ind']].append(x['chg_pct'])
agg = [(k, med(v), len(v)) for k, v in buckets.items() if len(v) >= 3]
out.append('\n-- 產業別族群表現（個股漲跌幅中位數）--')
for k, mm, n in agg:
    out.append('  %-12s %+7.2f%%  (%d檔)' % (k, mm, n))
srt = sorted(agg, key=lambda z: -z[1])
out.append('\n  最強 5: ' + ', '.join('%s %+.2f%%' % (k, mm) for k, mm, n in srt[:5]))
out.append('  最弱 5: ' + ', '.join('%s %+.2f%%' % (k, mm) for k, mm, n in srt[-5:]))

out.append('\n上市個股成交金額合計: %.1f 億元' % (sum(x['val'] for x in recs) / 1e8))

txt = '\n'.join(out)
print(txt)
open('/tmp/close_analysis.txt', 'w', encoding='utf-8').write(txt)
json.dump({'breadth': {'up': len(up), 'down': len(dn), 'flat': len(fl),
                       'limit_up': len([x for x in stocks if x['chg_pct'] > 9.5]),
                       'limit_down': len([x for x in stocks if x['chg_pct'] < -9.5])},
           'turnover_100m': round(sum(x['val'] for x in recs) / 1e8, 1)},
          open('/tmp/breadth.json', 'w'), ensure_ascii=False)
