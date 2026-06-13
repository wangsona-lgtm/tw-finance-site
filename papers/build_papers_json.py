#!/usr/bin/env python3
"""Convert daily QVAR paper notes (.md) + uploaded papers into papers.json
   with automatic topic categorization."""

import os, json, re, glob
from datetime import datetime

PAPERS_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORY_DIR = os.path.expanduser("~/.openclaw/workspace/memory/qvar-papers")
UPLOADS_JSON = os.path.join(PAPERS_DIR, "uploads.json")
OUTPUT_JSON = os.path.join(PAPERS_DIR, "papers.json")

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

def parse_daily_md(path):
    """Parse a daily QVAR paper note .md file into a list of paper dicts."""
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    
    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', text[:200])
    search_date = date_match.group(1) if date_match else "unknown"
    
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

def load_uploads():
    """Load user-uploaded papers from uploads.json"""
    if os.path.exists(UPLOADS_JSON):
        with open(UPLOADS_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def build():
    all_papers = []
    counts = {"search": 0, "upload": 0}
    
    md_files = sorted(glob.glob(os.path.join(MEMORY_DIR, "*.md")), reverse=True)
    for mf in md_files:
        try:
            papers = parse_daily_md(mf)
            all_papers.extend(papers)
            counts["search"] += len(papers)
        except Exception as e:
            print(f"⚠️  Skip {os.path.basename(mf)}: {e}")
    
    uploads = load_uploads()
    for up in uploads:
        up["type"] = "upload"
        if "tags" not in up:
            up["tags"] = []
        if "topics" not in up:
            up["topics"] = ["上傳文章"]
        if "id" not in up:
            up["id"] = f"upload-{up.get('date','unknown')}-{abs(hash(str(up.get('title',''))))%10000}"
        all_papers.append(up)
        counts["upload"] += 1
    
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
