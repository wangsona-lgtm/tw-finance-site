#!/usr/bin/env python3
"""Fetch sentiment data (three institutional + TAIFEX PC ratio) and save to JSON."""
import urllib.request, urllib.parse, json, os, datetime, ssl
import re, html, csv, io

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

H = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36', 'Accept': 'application/json'}
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
        return raw.decode('utf-8-sig', errors='replace')
    except:
        return raw.decode('big5', errors='replace')

def parse_taifex_openapi(raw):
    """Parse the TAIFEX endpoint's JSON or current UTF-8 CSV response."""
    text = raw.decode('utf-8-sig', errors='replace')
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass
    rows = []
    for row in csv.DictReader(io.StringIO(text)):
        def val(label):
            return row.get(label, '0').strip() or '0'
        rows.append({
            'Date': val('日期'),
            'Item': val('身份別'),
            'FuturesOpenInterest(Long)': val('期貨多方未平倉口數'),
            'FuturesOpenInterest(Short)': val('期貨空方未平倉口數'),
            'FuturesOpenInterest(Net)': val('期貨多空未平倉口數淨額'),
            'OptionsOpenInterest(Long)': val('選擇權多方未平倉口數'),
            'OptionsOpenInterest(Short)': val('選擇權空方未平倉口數'),
            'OptionsOpenInterest(Net)': val('選擇權多空未平倉口數淨額'),
        })
    return rows

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
    # Calculate totals for dealer (自行買賣 + 避險)
    dealer_buy = sum(int(r[1].replace(',','')) for r in data.get('data',[]) if '自營商' in r[0] and '外資' not in r[0])
    dealer_sell = sum(int(r[2].replace(',','')) for r in data.get('data',[]) if '自營商' in r[0] and '外資' not in r[0])
    dealer_diff = sum(int(r[3].replace(',','')) for r in data.get('data',[]) if '自營商' in r[0] and '外資' not in r[0])
    result['dealer_total'] = {'buy': dealer_buy, 'sell': dealer_sell, 'diff': dealer_diff}
    
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
    """Fetch ALL futures (not just TX) institutional net OI from TAIFEX OpenAPI."""
    url = 'https://openapi.taifex.com.tw/v1/MarketDataOfMajorInstitutionalTradersDividedByFuturesAndOptionsBytheDate'
    try:
        req = urllib.request.Request(url, headers=H)
        resp = urllib.request.urlopen(req, context=ctx, timeout=15)
        data = parse_taifex_openapi(resp.read())
        if not isinstance(data, list) or len(data) == 0:
            return None
        # TAIFEX API returns data for the latest date available, not filtered by input dt.
        # Use the actual date from the response.
        actual_date = data[0].get('Date', dt.strftime('%Y%m%d'))
        result = {'date': actual_date[:4]+'/'+actual_date[4:6]+'/'+actual_date[6:8]}
        for entry in data:
            item = entry.get('Item')
            fut_net = int(entry.get('FuturesOpenInterest(Net)', '0'))
            result[item] = fut_net
        foreign_net = result.get('外資及陸資', 0)
        trust_net = result.get('投信', 0)
        dealer_net = result.get('自營商', 0)
        result['total'] = foreign_net + trust_net + dealer_net
        result['foreign_net'] = foreign_net
        return result
    except Exception as e:
        print(f'TAIFEX futures API error: {e}')
        return None

def get_institutional_oi():
    """Fetch futures/options open interest split by the three institutions."""
    url = 'https://openapi.taifex.com.tw/v1/MarketDataOfMajorInstitutionalTradersDividedByFuturesAndOptionsBytheDate'
    try:
        req = urllib.request.Request(url, headers=H)
        resp = urllib.request.urlopen(req, context=ctx, timeout=15)
        data = parse_taifex_openapi(resp.read())
        if not isinstance(data, list) or not data:
            return None
        items = []
        name_map = {'自營商': 'dealer', '投信': 'trust', '外資及陸資': 'foreign'}
        for row in data:
            name = name_map.get(row.get('Item', ''))
            if not name:
                continue
            def iv(key):
                return int(row.get(key, 0) or 0)
            items.append({
                'name': name,
                'futures_long': iv('FuturesOpenInterest(Long)'),
                'futures_short': iv('FuturesOpenInterest(Short)'),
                'futures_net': iv('FuturesOpenInterest(Net)'),
                'options_long': iv('OptionsOpenInterest(Long)'),
                'options_short': iv('OptionsOpenInterest(Short)'),
                'options_net': iv('OptionsOpenInterest(Net)'),
            })
        return {'date': data[0].get('Date', ''), 'items': items}
    except Exception as e:
        print(f'TAIFEX institutional OI API error: {e}')
        return None

def main():
    today = datetime.datetime.today()
    today_str = today.strftime('%Y%m%d')
    
    output = {
        'updated': today.isoformat(),
        'today': today_str,
        'institution': {},
        'pc_ratio': {},
        'futures': {},
        'institutional_oi': {},
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
    pc_data = None
    for d in range(0, 10):
        dt = today - datetime.timedelta(days=d)
        if dt.weekday() >= 5: continue  # Skip weekends
        pc = get_pc_ratio(dt)
        if pc:
            output['pc_ratio'] = pc
            pc_data = pc
            break
    
    # 3. Futures data from TAIFEX OpenAPI
    futures_data = None
    for d in range(0, 10):
        dt = today - datetime.timedelta(days=d)
        if dt.weekday() >= 5: continue
        futures_data = get_tx_futures(dt)
        if futures_data:
            break
    if futures_data:
        output['futures'] = {
            'note': '期貨(全部合約) Net OI per TAIFEX',
            'last_seen_date': futures_data.get('date', ''),
            'foreign_tx_net': f"{futures_data.get('foreign_net', 0):,}",
            'total_inst_futures_net': f"{futures_data.get('total', 0):,}",
        }
    else:
        output['futures'] = {
            'note': 'Futures data unavailable',
            'last_seen_date': '',
            'foreign_tx_net': '',
            'total_inst_futures_net': '',
        }

    # 4. Futures/options open interest split by institution
    oi = get_institutional_oi()
    if oi:
        output['institutional_oi'] = oi

    # Do not publish a partial dashboard snapshot.  The scheduled wrapper
    # relies on this non-zero exit status to avoid committing stale data.
    missing = []
    if not inst:
        missing.append('TWSE institutional spot data')
    if not pc_data:
        missing.append('TAIFEX P/C ratio')
    if not futures_data:
        missing.append('TAIFEX futures net OI')
    if not oi or len(oi.get('items', [])) != 3:
        missing.append('TAIFEX futures/options institutional OI')
    if missing:
        raise RuntimeError('Missing required data: ' + ', '.join(missing))
    
    # Save
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    # Build/append history
    try:
        hist = json.load(open(HIST, 'r')) if os.path.exists(HIST) else []
    except:
        hist = []
    
    # Add entry (僅當成功取得資料時，用實際資料日期而非執行日期)
    if inst:
        actual_date = inst.get('date', today_str)
        entry = {
            'date': actual_date[:4]+'-'+actual_date[4:6]+'-'+actual_date[6:8],
            'inst': {
                'foreign': inst.get('foreign', {}).get('diff', 0),
                'investment_trust': inst.get('trust', {}).get('diff', 0),
                'dealer_total': inst.get('dealer_total', {}).get('diff', 0)
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
    
    print('OK: 外資', f'{inst.get("foreign",{}).get("diff","N/A"):,}' if inst else 'N/A', '元')
    print('OK: 投信', f'{inst.get("trust",{}).get("diff","N/A"):,}' if inst else 'N/A', '元')
    print('OK: 自營商', f'{inst.get("dealer_total",{}).get("diff","N/A"):,}' if inst else 'N/A', '元')
    print('PC:', output.get('pc_ratio', {}).get('pc_vol_ratio', 'N/A'))
    print(f'History entries: {len(hist)}')

if __name__ == '__main__':
    main()
