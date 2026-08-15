#!/usr/bin/env python3
"""Fetch sentiment data (three institutional only) and save to JSON.

期貨選擇權資料已停用（2026-08-14）：PC ratio、期貨法人部位、期貨選擇權未平倉
不再爬取，僅保留三大法人（股票現貨）買賣超。
"""
import urllib.request, json, os, datetime, ssl

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

H = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'}
DIR = os.path.dirname(__file__)
OUT = os.path.join(DIR, 'sentiment-data.json')
HIST = os.path.join(DIR, 'sentiment-history.json')

def fetch(url, data=None):
    req = urllib.request.Request(url, headers=H)
    if data:
        req.data = data.encode('utf-8')
    resp = urllib.request.urlopen(req, context=ctx)
    raw = resp.read()
    try:
        return raw.decode('utf-8', errors='replace')
    except:
        return raw.decode('big5', errors='replace')

def get_twse_inst(date_str):
    """Fetch three major institutional data from TWSE (股票現貨)."""
    url = f'https://www.twse.com.tw/rwd/zh/fund/BFI82U?date={date_str}&selectType=ALL'
    html = fetch(url)
    data = json.loads(html)
    if data.get('stat') != 'OK':
        return None
    result = {'date': data.get('date', date_str)}
    for r in data.get('data', []):
        name = r[0]
        buy = int(r[1].replace(',', ''))
        sell = int(r[2].replace(',', ''))
        diff = int(r[3].replace(',', ''))
        if '外資及陸資' in name:
            key = 'foreign'
        elif name == '投信':
            key = 'trust'
        elif '自營商' in name and '避險' not in name and '自行買賣' not in name:
            key = 'dealer'
        elif '自行買賣' in name:
            key = 'dealer_self'
        elif '避險' in name:
            key = 'dealer_hedge'
        else:
            continue
        result[key] = {'buy': buy, 'sell': sell, 'diff': diff}
    dealer_buy = sum(int(r[1].replace(',', '')) for r in data.get('data', []) if '自營商' in r[0] and '外資' not in r[0])
    dealer_sell = sum(int(r[2].replace(',', '')) for r in data.get('data', []) if '自營商' in r[0] and '外資' not in r[0])
    dealer_diff = sum(int(r[3].replace(',', '')) for r in data.get('data', []) if '自營商' in r[0] and '外資' not in r[0])
    result['dealer_total'] = {'buy': dealer_buy, 'sell': dealer_sell, 'diff': dealer_diff}
    return result

def main():
    today = datetime.datetime.today()
    today_str = today.strftime('%Y%m%d')

    output = {
        'updated': today.isoformat(),
        'today': today_str,
        'institution': {},
        'error': None
    }

    # 三大法人（股票現貨）
    inst = None
    try:
        inst = get_twse_inst(today_str)
        if not inst:
            for d in range(1, 7):
                dt = today - datetime.timedelta(days=d)
                inst = get_twse_inst(dt.strftime('%Y%m%d'))
                if inst:
                    break
        if inst:
            output['institution'] = inst
        else:
            output['error'] = 'Cannot get institutional data'
    except Exception as e:
        output['error'] = f'Institution: {str(e)}'

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    try:
        hist = json.load(open(HIST, 'r')) if os.path.exists(HIST) else []
    except:
        hist = []

    if inst:
        actual_date = inst.get('date', today_str)
        entry = {
            'date': actual_date[:4] + '-' + actual_date[4:6] + '-' + actual_date[6:8],
            'inst': {
                'foreign': inst.get('foreign', {}).get('diff', 0),
                'investment_trust': inst.get('trust', {}).get('diff', 0),
                'dealer_total': inst.get('dealer_total', {}).get('diff', 0)
            }
        }
        existing = [h for h in hist if h['date'] == entry['date']]
        if existing:
            existing[0].update(entry)
        else:
            hist.append(entry)
        hist = hist[-30:]

    with open(HIST, 'w', encoding='utf-8') as f:
        json.dump(hist, f, ensure_ascii=False, indent=2)

    print('OK: 外資', f'{inst.get("foreign", {}).get("diff", "N/A"):,}' if inst else 'N/A', '元')
    print('OK: 投信', f'{inst.get("trust", {}).get("diff", "N/A"):,}' if inst else 'N/A', '元')
    print('OK: 自營商', f'{inst.get("dealer_total", {}).get("diff", "N/A"):,}' if inst else 'N/A', '元')
    print(f'History entries: {len(hist)}')

if __name__ == '__main__':
    main()
