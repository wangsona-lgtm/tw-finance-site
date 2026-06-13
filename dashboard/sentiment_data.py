#!/usr/bin/env python3
"""Fetch TAIFEX sentiment data (futures, options, PC ratio) and save to JSON."""
import urllib.request, urllib.parse, json, re, os, datetime, ssl
from html.parser import HTMLParser

# Disable SSL verification for TAIFEX
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

HEADERS = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'}
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), 'sentiment-data.json')

def fetch_url(url):
    req = urllib.request.Request(url, headers=HEADERS)
    return urllib.request.urlopen(req, context=ctx).read().decode('utf-8', errors='replace')

def fetch_pc_ratio(date_str):
    """Fetch P/C ratio from TAIFEX."""
    url = f'https://www.taifex.com.tw/cht/3/pcRatio'
    html = fetch_url(url)
    # Parse the table
    rows = re.findall(r'<tr[^>]*>.*?</tr>', html, re.DOTALL)
    result = {}
    for row in rows:
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
        cells = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
        if len(cells) >= 4 and date_str in cells[0]:
            result = {
                'date': cells[0],
                'pc_volume': cells[1],       # P/C成交量
                'pc_open_interest': cells[2], # P/C未平倉
                'tx_volume': cells[3]         # 台指期成交量
            }
            break
    return result

def fetch_futures_tx():
    """Fetch TX futures data."""
    url = 'https://www.taifex.com.tw/cht/3/futContractsDate?queryType=1&commodityId=TX'
    html = fetch_url(url)
    # Parse table to find foreign institutional net position
    result = {}
    rows = re.findall(r'<tr[^>]*>.*?</tr>', html, re.DOTALL)
    for row in rows:
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
        cells = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
        if len(cells) >= 6:
            result['raw_data'] = cells[:8]
    return result

def fetch_futures_summary():
    """Fetch 三大法人期貨 table."""
    url = 'https://www.taifex.com.tw/cht/3/futAndOptDate'
    html = fetch_url(url)
    result = {}
    # Look for futures table
    tables = re.findall(r'<table[^>]*>.*?</table>', html, re.DOTALL)
    for ti, table in enumerate(tables):
        rows = re.findall(r'<tr[^>]*>.*?</tr>', table, re.DOTALL)
        for row in rows:
            cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
            cells = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
            if '外資' in row and '台指' in row and len(cells) >= 4:
                result['futures_foreign_tx'] = cells
    return result

def main():
    today = datetime.datetime.today()
    date_str = f'{today.year}/{today.month:02d}/{today.day:02d}'
    
    output = {
        'updated': today.isoformat(),
        'date': date_str,
        'pc_ratio': {},
        'futures': {},
        'error': None
    }
    
    try:
        pc = fetch_pc_ratio(date_str)
        if pc:
            output['pc_ratio'] = pc
    except Exception as e:
        output['error'] = f'PC ratio: {str(e)}'
    
    try:
        fut = fetch_futures_summary()
        if fut:
            output['futures'] = fut
    except Exception as e:
        output['error'] = (output['error'] or '') + f' Futures: {str(e)}'
    
    # Also try latest available data if today not found
    if not output['pc_ratio']:
        try:
            # Try past dates
            for d in range(1, 10):
                dt = today - datetime.timedelta(days=d)
                ds = f'{dt.year}/{dt.month:02d}/{dt.day:02d}'
                pc = fetch_pc_ratio(ds)
                if pc:
                    output['pc_ratio'] = pc
                    output['date'] = ds
                    break
        except:
            pass
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"Saved to {OUTPUT_FILE}")
    print(f"PC ratio: {output.get('pc_ratio', {})}")
    print(f"Error: {output.get('error')}")

if __name__ == '__main__':
    main()
