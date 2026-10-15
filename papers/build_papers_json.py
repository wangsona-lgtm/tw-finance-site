#!/usr/bin/env python3
"""Convert daily QVAR paper notes (.md) + uploaded papers into papers.json
   with automatic topic categorization."""

import os, json, re, glob, hashlib
from datetime import datetime

PAPERS_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORY_DIR = os.path.expanduser("~/.openclaw/workspace/memory/qvar-papers")
BF_DIR = os.path.expanduser("~/.openclaw/workspace/memory/behavioral-finance-papers")
UPLOADS_JSON = os.path.join(PAPERS_DIR, "uploads.json")
OUTPUT_JSON = os.path.join(PAPERS_DIR, "papers.json")
# 獨立論文站 repo（wangsona-lgtm.github.io/papers/）的 papers.json — 重建時合併保留其豐富條目
STANDALONE_JSON = os.path.expanduser("~/桌面/Claude cowork/papers/papers.json")

# ====== Topic classification rules ======
TOPIC_RULES = [
    ("綠債/ESG", [
        "green bond", "esg", "sustainable", "socially responsible",
        "綠債", "esg 股票", "esg指數",
        "biodiversity",
    ]),
    ("潔淨能源", [
        "clean energy", "renewable", "solar", "renewables", "net-zero",
        "新能源車", "clean energy", "清潔能源", "氫能", "hydrogen",
        "潔淨能源", "綠色能源", "能源效率", "energy efficiency",
        "碳中和", "carbon neutral",
    ]),
    ("碳市場/碳交易", [
        "carbon market", "carbon trading", "carbon price", "carbon emission",
        "carbon", "碳交易", "碳市場", "etf",
        "環境足跡", "ecological footprint", "co2",
    ]),
    ("氣候風險/政策", [
        "climate policy", "climate risk", "cpu", "climate policy uncertainty",
        "氣候政策不確定性", "氣候風險",
        "ecological sustainability", "生態永續",
    ]),
    ("能源市場", [
        "oil market", "crude oil", "natural gas", "energy market",
        "petroleum", "energy indicator", "能源市場", "原油", "石油",
        "oil shock",
    ]),
    ("金融市場", [
        "stock index", "stock market", "financial market", "financial risk",
        "systemic risk", "banking", "股價指數", "金融市場", "金融風險",
        "exchange rate", "匯率",
        "stock return", "stock indices", "islamic stock",
        "portfolio", "shielding",
    ]),
    ("地緣政治/國防", [
        "geopolitical", "defense stock", "rare earth", "military",
        "地緣政治", "國防", "稀土", "中東衝突",
    ]),
    ("加密貨幣/數位金融", [
        "cryptocurrency", "bitcoin", "digital finance", "fintech",
        "加密貨幣", "數位金融",
        "crypto", "blockchain",
    ]),
    ("原物料/商品", [
        "commodity", "gold", "rare earth mineral", "agricultural",
        "商品市場", "原物料",
    ]),
    ("宏觀總體", [
        "gdp", "inflation", "economic growth", "fiscal policy",
        "trade policy", "monetary policy", "inequality",
        "匯率", "通膨", "經濟成長", "政策",
        "economic activity", "不確定性", "uncertainty",
        "income inequality",
    ]),
    ("方法論", [
        "quantile regression", "quantile impulse", "quantile granger",
        "weighted quantile", "methodology", "estimation",
        "inference", "r package", "套件", "漸進理論",
        "quantile vector", "分位數",
    ]),
    ("AI/科技", [
        "artificial intelligence", "machine learning", "deep learning",
        "neural network", "a.i", "人工智能", "機器學習",
        "第四次工業革命", "fourth industrial revolution",
        "ict", "digital",
    ]),
    ("行為金融", [
        "informed trading", "smart money", "institutional herding",
        "positive feedback trading", "retail attention", "disposition effect",
        "behavioral finance", "investor behavior", "herding",
        "feedback trading", "attention", "momentum trading",
        "information asymmetry", "toxic flow", "insider trading",
    ]),
]

def classify_topics(title, abstract):
    """Classify a paper into topics based on title and abstract."""
    text = (title + " " + (abstract or "")).lower()
    topics = []
    for topic_name, keywords in TOPIC_RULES:
        for kw in keywords:
            if kw.lower() in text:
                topics.append(topic_name)
                break
    if not topics:
        topics.append("其他")
    return list(dict.fromkeys(topics))  # deduplicate preserving order

# 垃灑標題過濾：誤抓、占位符、重複註記、撤稿通知、與研究無關的條目
JUNK_TITLE_PAT = re.compile(
    r'^(QVAR|❌|年份)$|Retraction notice|Retraction\b|同上|Película|VOIR|'
    r'Wondershare|Quiz Creator|HOTS Questions|Navier|toxicology|'
    r'Every Time I Die|Quantum Variational Regularization', re.I)

def is_junk_title(title):
    return bool(JUNK_TITLE_PAT.search((title or '').strip()))

def paper_key(p):
    """Stable dedup key: normalized DOI > OpenAlex ID > normalized title."""
    doi = re.sub(r'^https?://(dx\.)?doi\.org/', '', (p.get('doi') or '').strip().lower())
    if doi and doi != 'nan':
        return 'doi:' + doi
    oa_m = re.search(r'(W\d+)', p.get('openalex_url') or '')
    if oa_m:
        return 'oa:' + oa_m.group(1)
    t = re.sub(r'\s+', ' ', (p.get('title') or '').strip().lower())
    return 't:' + t

def paper_richness(p):
    """Score entry richness — merge prefers the richer duplicate."""
    score = 0
    if p.get('abstract'): score += 4
    score += min(len(p.get('notes') or []), 20)
    score += min(len(p.get('viewpoints') or []), 10)
    if p.get('journal'): score += 2
    if p.get('authors'): score += 1
    if p.get('pdf'): score += 2
    if p.get('fulltext_url'): score += 1
    return score

def parse_daily_md_tables(text, search_date):
    """Parse new table-format daily QVAR notes (since 2026-09-22).

    Table rows: | # | 標題 | 年份 | DOI | OpenAlex ID | 命中詞 |
    Rows under 誤抓/False Positives sections are skipped.
    """
    papers = []
    in_false_positive = False

    for line in text.split('\n'):
        line_s = line.strip()

        if line_s.startswith('## '):
            in_false_positive = bool(re.search(r'誤抓|不相關|False Positive', line_s))
            continue
        if line_s.startswith('### '):
            continue

        if in_false_positive:
            continue

        # 6-column data row
        m = re.match(
            r'^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*$',
            line_s)
        if not m:
            continue
        num, title, year, doi, oa_id, term = m.groups()

        # Skip header / separator rows
        if set(num) <= set('-: #') or set(title) <= set('-: '):
            continue
        if title in ('標題', ''):
            continue

        clean_title = re.sub(r'^⚠️\s*', '', title.strip())
        clean_title = re.sub(r'（[^）]*待確認[^）]*）$', '', clean_title).strip()

        doi_norm = re.sub(r'^https?://(dx\.)?doi\.org/', '', doi.strip())
        oa = oa_id.strip()
        oa_url = f"https://openalex.org/{oa}" if re.match(r'^W\d+$', oa) else ""

        tags = []
        methods = ["QVAR", "QARDL", "TVP-VAR", "WQC", "QQGC", "WQR", "QTVAR", "jQIRF", "jQFEVD"]
        hay = (term + " " + clean_title).lower()
        for mm in methods:
            if mm.lower() in hay:
                tags.append(mm)
        if not tags:
            tags.append("QVAR")

        papers.append({
            "id": f"qvar-{search_date}-{oa or hashlib.md5(clean_title.encode('utf-8')).hexdigest()[:8]}",
            "title": clean_title,
            "search_date": search_date,
            "authors": "",
            "year": year.strip(),
            "journal": "",
            "doi": doi_norm,
            "citations": "",
            "openalex_url": oa_url,
            "abstract": "",
            "tags": tags,
            "topics": classify_topics(clean_title, ""),
            "type": "search",
            "notes": []
        })

    return papers

def parse_daily_md(path):
    """Parse a daily QVAR paper note .md file into a list of paper dicts.
    Supports both old (### N.M sections) and new (markdown table) formats."""
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    
    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', text[:200])
    search_date = date_match.group(1) if date_match else "unknown"
    
    # New table format detection
    if '| DOI |' in text and re.search(r'^\|\s*\d+\s*\|', text, re.M):
        table_papers = parse_daily_md_tables(text, search_date)
        if table_papers:
            return table_papers
    
    papers = []
    sections = re.split(r'\n###\s+\d+\.\d+\s+', text)
    
    for idx, sec in enumerate(sections):
        if idx == 0:
            continue
        
        lines = sec.strip().split('\n')
        title = lines[0].strip() if lines else ""
        
        paper = {
            "id": f"{search_date}-{idx}",
            "title": title,
            "search_date": search_date,
            "authors": "",
            "year": "",
            "journal": "",
            "doi": "",
            "citations": "",
            "openalex_url": "",
            "abstract": "",
            "tags": [],
            "topics": [],
            "type": "search",
            "notes": []
        }
        
        for line in lines[1:]:
            line = line.strip()
            if re.match(r'^-?\s*\*\*年份[：:]\*\*', line):
                paper["year"] = re.sub(r'[\*\-]', '', line).split('：')[-1].split(':')[-1].strip()
            elif re.match(r'^-?\s*\*\*期刊[：:]\*\*', line):
                paper["journal"] = re.sub(r'[\*\-]', '', line).split('：')[-1].split(':')[-1].strip()
            elif re.match(r'^-?\s*\*\*作者[：:]\*\*', line):
                paper["authors"] = re.sub(r'[\*\-]', '', line).split('：')[-1].split(':')[-1].strip()
            elif re.match(r'^-?\s*\*\*DOI[：:]\*\*', line):
                paper["doi"] = re.sub(r'[\*\-]', '', line).split('：')[-1].split(':')[-1].strip()
            elif re.match(r'^-?\s*\*\*被引[：:]\*\*', line):
                paper["citations"] = re.sub(r'[\*\-]', '', line).split('：')[-1].split(':')[-1].strip()
            elif re.match(r'^-?\s*\*\*連結[：:]\*\*', line):
                paper["openalex_url"] = re.sub(r'[\*\-]', '', line).split('：')[-1].split(':')[-1].strip()
            elif "**摘要：**" in line:
                paper["abstract"] = line.replace("**摘要：**", "").replace("**摘要:**", "").strip()
        
        # Method tags
        methods = ["QVAR", "QARDL", "TVP-VAR", "WQC", "QQGC", "WQR", "QTVAR", "jQIRF", "jQFEVD"]
        for m in methods:
            if m.lower() in title.lower():
                paper["tags"].append(m)
        if not paper["tags"]:
            paper["tags"].append("QVAR")
        
        # Topic classification
        paper["topics"] = classify_topics(title, paper.get("abstract", ""))
        
        papers.append(paper)
    
    return papers

def parse_behavioral_finance_md(path):
    """Parse a behavioral finance paper note .md file into a list of paper dicts."""
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    
    date_match = re.search(r'搜尋日期：(\\d{4}-\\d{2}-\\d{2})', text)
    search_date = date_match.group(1) if date_match else "2026-07-07"
    
    papers = []
    # Match sections like ### 1.1 Title
    sections = re.split(r'\n###\s+\d+\.\d+\s+', text)
    
    for idx, sec in enumerate(sections):
        if idx == 0:
            continue
        
        lines = sec.strip().split('\n')
        title = lines[0].strip() if lines else ""
        
        paper = {
            "id": f"bf-{search_date}-{idx}",
            "title": title,
            "search_date": search_date,
            "authors": "",
            "year": "",
            "journal": "",
            "doi": "",
            "citations": "",
            "openalex_url": "",
            "abstract": "",
            "tags": [],
            "topics": ["行為金融"],
            "type": "search",
            "notes": []
        }
        
        for line in lines[1:]:
            line = line.strip()
            if line.startswith("- **作者：**"):
                paper["authors"] = line.replace("- **作者：**", "").strip()
            elif line.startswith("- **年份：**"):
                paper["year"] = line.replace("- **年份：**", "").strip()
            elif line.startswith("- **期刊：**"):
                paper["journal"] = line.replace("- **期刊：**", "").strip()
            elif line.startswith("- **DOI：**"):
                paper["doi"] = line.replace("- **DOI：**", "").strip()
            elif line.startswith("- **被引：**"):
                paper["citations"] = line.replace("- **被引：**", "").strip()
            elif line.startswith("- **OpenAlex：**"):
                paper["openalex_url"] = line.replace("- **OpenAlex：**", "").strip()
            elif line.startswith("**【Key Findings】**"):
                break  # Notes will be collected separately
        
        # Collect notes
        in_notes = False
        for line in lines[1:]:
            line = line.strip()
            if line.startswith("**【變數】**"):
                in_notes = True
                paper["notes"].append("=== 變數 ===")
            elif line.startswith("**【資料來源】**"):
                paper["notes"].append("=== 資料來源 ===")
            elif line.startswith("**【方法論】**"):
                paper["notes"].append("=== 方法論 ===")
            elif line.startswith("**【Key Findings】**"):
                paper["notes"].append("=== Key Findings ===")
            elif line.startswith("**【APA】**"):
                paper["notes"].append("=== APA ===")
            elif in_notes and line and not line.startswith("#") and not line.startswith("---"):
                paper["notes"].append(line)
        
        # Behavioral finance specific tags
        bf_topics = ["informed trading", "smart money", "institutional herding", 
                     "positive feedback trading", "retail attention", "disposition effect"]
        for topic in bf_topics:
            if topic.lower() in title.lower():
                paper["tags"].append(topic.title())
        if not paper["tags"]:
            paper["tags"].append("Behavioral Finance")
        
        papers.append(paper)
    
    return papers

def load_uploads():
    """Load user-uploaded papers from uploads.json"""
    if os.path.exists(UPLOADS_JSON):
        with open(UPLOADS_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def build():
    all_papers = []
    counts = {"search": 0, "upload": 0}
    
    # Parse QVAR papers
    md_files = sorted(glob.glob(os.path.join(MEMORY_DIR, "*.md")), reverse=True)
    for mf in md_files:
        try:
            papers = parse_daily_md(mf)
            all_papers.extend(papers)
            counts["search"] += len(papers)
        except Exception as e:
            print(f"⚠️  Skip {os.path.basename(mf)}: {e}")
    
    # Parse behavioral finance papers
    bf_files = sorted(glob.glob(os.path.join(BF_DIR, "*.md")), reverse=True)
    for mf in bf_files:
        try:
            papers = parse_behavioral_finance_md(mf)
            all_papers.extend(papers)
            counts["search"] += len(papers)
            print(f"   📚 Behavioral finance: {len(papers)} papers from {os.path.basename(mf)}")
        except Exception as e:
            print(f"⚠️  Skip BF {os.path.basename(mf)}: {e}")
    
    uploads = load_uploads()
    for up in uploads:
        up["type"] = "upload"
        if "tags" not in up:
            up["tags"] = []
        if "topics" not in up:
            up["topics"] = ["上傳文章"]
        if "id" not in up:
            up["id"] = f"upload-{up.get('date','unknown')}-{hashlib.md5(str(up.get('title','')).encode('utf-8')).hexdigest()[:8]}"
        all_papers.append(up)
        counts["upload"] += 1
    
    # Merge with existing papers.json (both tw-finance-site and standalone repo):
    # preserves rich entries (abstract/notes/viewpoints) written by the 20:00 search job
    # that the .md rebuild cannot regenerate.
    existing = []
    for src in (OUTPUT_JSON, STANDALONE_JSON):
        if os.path.exists(src):
            try:
                with open(src, "r", encoding="utf-8") as f:
                    existing.extend(json.load(f).get("papers", []))
            except Exception as e:
                print(f"⚠️  Skip existing {src}: {e}")
    
    merged = {}
    for p in all_papers:
        if is_junk_title(p.get("title")):
            continue
        k = paper_key(p)
        if k not in merged or paper_richness(p) > paper_richness(merged[k]):
            merged[k] = p
    preserved = 0
    for p in existing:
        if is_junk_title(p.get("title")):
            continue
        k = paper_key(p)
        if k not in merged:
            merged[k] = p
            preserved += 1
        elif paper_richness(p) > paper_richness(merged[k]):
            merged[k] = p
    all_papers = list(merged.values())
    if preserved:
        print(f"   🔒 保留既有條目 {preserved} 篇（來自現有 papers.json，.md 無法重建）")
    
    all_papers.sort(key=lambda p: (p.get("search_date", p.get("date", "2000-01-01")), p.get("id", "")), reverse=True)
    
    # Collect unique topics
    all_topics = set()
    for p in all_papers:
        for t in p.get("topics", []):
            all_topics.add(t)
    
    output = {
        "total": len(all_papers),
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "topics": sorted(all_topics),
        "papers": all_papers
    }
    
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"✅  papers.json 已更新: {len(all_papers)} 篇論文")
    print(f"   - 每日搜尋: {counts['search']} 篇")
    print(f"   - 上傳文章: {counts['upload']} 篇")
    print(f"   - 主題分類: {len(all_topics)} 個 ({', '.join(sorted(all_topics))})")

if __name__ == "__main__":
    build()
