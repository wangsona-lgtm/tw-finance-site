#!/usr/bin/env python3
"""Convert daily QVAR paper notes (.md) + uploaded papers into papers.json"""

import os, json, re, glob
from datetime import datetime

PAPERS_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORY_DIR = os.path.expanduser("~/.openclaw/workspace/memory/qvar-papers")
UPLOADS_JSON = os.path.join(PAPERS_DIR, "uploads.json")
OUTPUT_JSON = os.path.join(PAPERS_DIR, "papers.json")

def parse_daily_md(path):
    """Parse a daily QVAR paper note .md file into a list of paper dicts."""
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    
    # Extract date from first line "每日 QVAR 文獻搜尋報告 — YYYY-MM-DD"
    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', text[:200])
    search_date = date_match.group(1) if date_match else "unknown"
    
    papers = []
    # Each paper section starts with "### N.M Title"
    sections = re.split(r'\n###\s+\d+\.\d+\s+', text)
    
    for idx, sec in enumerate(sections):
        if idx == 0:
            continue  # skip header
        
        # Title is the first line before any other content
        lines = sec.strip().split('\n')
        title = lines[0].strip() if lines else ""
        
        # Extract metadata
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
            "type": "search",  # search=from daily search, upload=user uploaded
            "notes": []
        }
        
        for line in lines[1:]:
            line = line.strip()
            if line.startswith("**年份：") or line.startswith("**Year：") or line.startswith("- **年份：") or re.match(r'^-?\s*\*\*年份[：:]\*\*', line):
                paper["year"] = re.sub(r'[\*\-]', '', line).split('：')[-1].split(':')[-1].strip()
            elif line.startswith("**期刊：") or line.startswith("- **期刊：") or re.match(r'^-?\s*\*\*期刊[：:]\*\*', line):
                paper["journal"] = re.sub(r'[\*\-]', '', line).split('：')[-1].split(':')[-1].strip()
            elif line.startswith("**作者：") or line.startswith("- **作者：") or re.match(r'^-?\s*\*\*作者[：:]\*\*', line):
                paper["authors"] = re.sub(r'[\*\-]', '', line).split('：')[-1].split(':')[-1].strip()
            elif line.startswith("**DOI：") or line.startswith("- **DOI：") or re.match(r'^-?\s*\*\*DOI[：:]\*\*', line):
                paper["doi"] = re.sub(r'[\*\-]', '', line).split('：')[-1].split(':')[-1].strip()
            elif line.startswith("**被引：") or line.startswith("- **被引：") or re.match(r'^-?\s*\*\*被引[：:]\*\*', line):
                paper["citations"] = re.sub(r'[\*\-]', '', line).split('：')[-1].split(':')[-1].strip()
            elif line.startswith("**連結：") or line.startswith("- **連結：") or re.match(r'^-?\s*\*\*連結[：:]\*\*', line):
                paper["openalex_url"] = re.sub(r'[\*\-]', '', line).split('：')[-1].split(':')[-1].strip()
            elif "**摘要：**" in line or re.match(r'^-?\s*\*\*摘要[：:]\*\*', line):
                paper["abstract"] = line.replace("**摘要：**", "").replace("**摘要:**", "").strip()
        
        # Determine method tags from title + context
        methods = ["QVAR", "QARDL", "TVP-VAR", "WQC", "QQGC", "WQR", "QTVAR", "jQIRF", "jQFEVD"]
        for m in methods:
            if m.lower() in title.lower():
                paper["tags"].append(m)
        # If no specific method tag, put general QVAR
        if not paper["tags"]:
            paper["tags"].append("QVAR")
        
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
    
    # 1. Parse daily QVAR search results
    md_files = sorted(glob.glob(os.path.join(MEMORY_DIR, "*.md")), reverse=True)
    for mf in md_files:
        try:
            papers = parse_daily_md(mf)
            all_papers.extend(papers)
        except Exception as e:
            print(f"⚠️  Skip {mf}: {e}")
    
    # 2. Load uploaded papers
    uploads = load_uploads()
    for up in uploads:
        up["type"] = "upload"
        if "id" not in up:
            up["id"] = f"upload-{up.get('date','unknown')}-{hash(up.get('title',''))%10000}"
        all_papers.append(up)
    
    # 3. Sort by date (newest first), then by id
    all_papers.sort(key=lambda p: (p.get("search_date", p.get("date", "2000-01-01")), p.get("id", "")), reverse=True)
    
    # 4. Write output
    output = {
        "total": len(all_papers),
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "papers": all_papers
    }
    
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"✅  papers.json 已更新: {len(all_papers)} 篇論文")
    print(f"   - 每日搜尋: {len(all_papers) - len(uploads)} 篇")
    print(f"   - 上傳文章: {len(uploads)} 篇")

if __name__ == "__main__":
    build()
