#!/usr/bin/env python3
"""Fetch sentiment data (three institutional + TAIFEX PC ratio) and save to JSON."""
import urllib.request, urllib.parse, json, os, datetime, ssl
import re, html

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
    # Try UTF-8 first, then Big5
    try:
        return raw.decode('utf-8', errors='replace')
    except:
        return raw.decode('big5', errors='replace')

def get_twse_inst(date_str):
    """Fetch three major institutional data from TWSE."""
    url = f'https://www.twse.com.tw/rwd/zh/fund/BFI82U?date={date_str}&selectType=ALL'
    html = fetch(url)
    data = json.loads(html)
    if data.get('stat') != 'OK':
        return None
    result = {'date': data.get('date', date_str)}
    for r in data.get('data', []):
        name = r[0]
        buy = int(r[1].replace(',',''))
        sell = int(r[2].replace(',',''))
        diff = int(r[3].replace(',',''))
        key = name.replace('(不含外資自營商)','').replace('(自行買賣)','').replace('(避險)','')
        result[key] = {'buy': buy, 'sell': sell, 'diff': diff}
    # Calculate totals for dealer (自行買賣 + 避險)
    dealer_buy = sum(int(r[1].replace(',','')) for r in data.get('data',[]) if '自營商' in r[0] and '外資' not in r[0])
    dealer_sell = sum(int(r[2].replace(',','')) for r in data.get('data',[]) if '自營商' in r[0] and '外資' not in r[0])
    dealer_diff = sum(int(r[3].replace(',','')) for r in data.get('data',[]) if '自營商' in r[0] and '外資' not in r[0])
    result['自營商合計'] = {'buy': dealer_buy, 'sell': dealer_sell, 'diff': dealer_diff}
    
    # 備註：原「自營商」key 會被後者覆蓋（因為 (自行買賣) 和 (避險) 都對應到同一 key）
    return result

def get_pc_ratio(dt):
    """Fetch PC ratio from TAIFEX for a given date."""
    ds = f'{dt.year}/{dt.month:02d}/{dt.day:02d}'
    html = fetch('https://www.taifex.com.tw/cht/3/pcRatio', 
                 f'queryStartDate={ds}&queryEndDate={ds}&down_type=')
    tables = re.findall(r'<table[^>]*>(.*?)</table>', html, re.DOTALL)
    for table in tables:
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', table, re.DOTALL)
        for r in rows:
            cells = re.findall(r'<td[^>]*>(.*?)</td>', r, re.DOTALL)
            cells = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
            if len(cells) >= 7:
                try:
                    return {
                        'date': cells[0],
                        'call_vol': int(cells[1].replace(',','')),
                        'put_vol': int(cells[2].replace(',','')),
                        'pc_vol_ratio': float(cells[3].replace(',','')),
                        'call_oi': int(cells[4].replace(',','')),
                        'put_oi': int(cells[5].replace(',','')),
                        'pc_oi_ratio': float(cells[6].replace(',',''))
                    }
                except: pass
    return None

def get_tx_futures(dt):
    """Fetch TX futures from TWSE or fallback to mock."""
    # Try to use the old report data format
    return None  # Will use pre-seeded data

def main():
    today = datetime.datetime.today()
    today_str = today.strftime('%Y%m%d')
    
    output = {
        'updated': today.isoformat(),
        'today': today_str,
        'institution': {},
        'pc_ratio': {},
        'futures': {},
        'error': None
    }
    
    # 1. Three major institutional data
    try:
        inst = get_twse_inst(today_str)
        if not inst:
            for d in range(1, 7):
                dt = today - datetime.timedelta(days=d)
                inst = get_twse_inst(dt.strftime('%Y%m%d'))
                if inst: break
        if inst:
            output['institution'] = inst
        else:
            output['error'] = 'Cannot get institutional data'
    except Exception as e:
        output['error'] = f'Institution: {str(e)}'
        inst = None
    
    # 2. PC Ratio from TAIFEX
    for d in range(0, 10):
        dt = today - datetime.timedelta(days=d)
        if dt.weekday() >= 5: continue  # Skip weekends
        pc = get_pc_ratio(dt)
        if pc:
            output['pc_ratio'] = pc
            break
    
    # 3. Futures data - use pre-seeded from reports
    output['futures'] = {
        'note': 'Futures/options data from latest available report',
        'last_seen_date': '2026/06/11',
        'foreign_tx_net': '-61,949',
        'total_inst_futures_net': '-74,321',
    }
    
    # Save
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    # Build/append history
    try:
        hist = json.load(open(HIST, 'r')) if os.path.exists(HIST) else []
    except:
        hist = []
    
    # Add today's entry (僅當成功取得資料時)
    if inst:
        entry = {
            'date': today_str[:4]+'-'+today_str[4:6]+'-'+today_str[6:8],
            'inst': {
                'foreign': inst.get('外資及陸資', {}).get('diff', 0),
                'investment_trust': inst.get('投信', {}).get('diff', 0),
                'dealer_total': inst.get('自營商合計', {}).get('diff', 0)
            },
            'pc_ratio': output.get('pc_ratio', {}).get('pc_vol_ratio', 0),
            'pc_oi_ratio': output.get('pc_ratio', {}).get('pc_oi_ratio', 0),
            'futures_foreign_net': output.get('futures', {}).get('foreign_tx_net', ''),
            'futures_total_net': output.get('futures', {}).get('total_inst_futures_net', '')
        }
        
        # Update or add (僅限當天)
        existing = [h for h in hist if h['date'] == entry['date']]
        if existing:
            existing[0].update(entry)
        else:
            hist.append(entry)
        # 保留最近 30 天
        hist = hist[-30:]
    
    with open(HIST, 'w', encoding='utf-8') as f:
        json.dump(hist, f, ensure_ascii=False, indent=2)
    
    print('OK: 外資', f'{inst.get("外資及陸資",{}).get("diff","N/A"):,}' if inst else 'N/A', '元')
    print('OK: 投信', f'{inst.get("投信",{}).get("diff","N/A"):,}' if inst else 'N/A', '元')
    print('OK: 自營商', f'{inst.get("自營商合計",{}).get("diff","N/A"):,}' if inst else 'N/A', '元')
    print('PC:', output.get('pc_ratio', {}).get('pc_vol_ratio', 'N/A'))
    print(f'History entries: {len(hist)}')

if __name__ == '__main__':
    main()
