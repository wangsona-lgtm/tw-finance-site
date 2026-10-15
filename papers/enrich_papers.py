#!/usr/bin/env python3
"""Enrich thin papers.json entries via OpenAlex (authors/abstract/journal/citations).
Idempotent: only fetches entries missing authors+abstract. Run after build_papers_json.py."""
import json, re, time, urllib.request, urllib.parse

API_KEY = "EWVALn8SCfgqGDuCRz2bpJ"
PAPERS_JSON = "/home/nutc/桌面/Claude cowork/papers/papers.json"

def normalize_doi(doi):
    if not doi:
        return ""
    m = re.search(r'\[?(10\.\d{4,9}/[^\]\s]+)\]?', doi)
    return m.group(1).rstrip(').,') if m else ""

def fetch_openalex(work_id):
    if re.match(r'^W\d+$', work_id):
        url = f"https://api.openalex.org/works/{work_id}?api_key={API_KEY}"
    else:
        url = f"https://api.openalex.org/works/doi:{urllib.parse.quote(work_id)}?api_key={API_KEY}"
    req = urllib.request.Request(url, headers={"User-Agent": "paper-enrich/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

def reconstruct_abstract(inv_idx):
    if not inv_idx:
        return ""
    positions = {}
    for word, idxs in inv_idx.items():
        for i in idxs:
            positions[i] = word
    return " ".join(positions[i] for i in sorted(positions))

def main():
    with open(PAPERS_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)

    thin = [p for p in data["papers"] if not p.get("abstract") and not p.get("authors")]
    if not thin:
        print("✅ 所有條目皆已豐富，無需處理")
        return
    print(f"待豐富: {len(thin)} 篇")

    enriched, failed = 0, 0
    for i, p in enumerate(thin):
        m = re.search(r'(W\d+)', p.get("openalex_url") or "")
        work_id = m.group(1) if m else normalize_doi(p.get("doi") or "")
        if not work_id:
            failed += 1
            continue
        try:
            w = fetch_openalex(work_id)
        except Exception as e:
            print(f"  ⚠️ {p['title'][:45]}: {e}")
            failed += 1
            time.sleep(0.5)
            continue
        p["authors"] = "; ".join(a["author"]["display_name"] for a in w.get("authorships", []) if a.get("author"))
        p["abstract"] = reconstruct_abstract(w.get("abstract_inverted_index"))
        host = (w.get("primary_location") or {}).get("source") or {}
        journal = host.get("display_name") or ""
        bib = w.get("biblio") or {}
        if journal and bib.get("volume"):
            journal += f", {bib['volume']}"
            if bib.get("issue"):
                journal += f"({bib['issue']})"
            if bib.get("first_page"):
                journal += f", {bib['first_page']}"
        if journal:
            p["journal"] = journal
        c = w.get("cited_by_count", 0)
        if c:
            p["citations"] = f"{c} 次"
        if w.get("publication_year"):
            p["year"] = str(w["publication_year"])
        nd = normalize_doi(w.get("doi") or "")
        if nd:
            p["doi"] = nd
        enriched += 1
        print(f"  ✅ [{i+1}/{len(thin)}] {p['title'][:50]}")
        time.sleep(0.35)

    with open(PAPERS_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n完成: 豐富化 {enriched} 篇, 失敗/無連結 {failed} 篇")

if __name__ == "__main__":
    main()
