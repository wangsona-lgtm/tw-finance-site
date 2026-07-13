#!/usr/bin/env python3
"""
台股資料補救助手 - 補回盤前分析 & 完整籌碼
"""
import json
import os
import glob
import sys

REPORTS_DIR = "/home/nutc/.openclaw/workspace/tw-finance-site/reports"
POSTMARKET_DIR = "/home/nutc/.openclaw/workspace/tw-finance-site/postmarket"
PREMARKET_SOURCE = "/home/nutc/.hermes/cron/output/2edfc497e5ad"
CHIP_SOURCE = "/home/nutc/.hermes/cron/output/a3b9c8d7e6f5"

# Day of week in Chinese
DOW_CN = {0: "一", 1: "二", 2: "三", 3: "四", 4: "五", 5: "六", 6: "日"}

def get_dow(date_str):
    """Get day of week from date string YYYY-MM-DD"""
    from datetime import datetime
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return dt.weekday()

# ============================================================
# PART A: 補盤前分析
# ============================================================
PREMARKET_DATES = ["2026-07-06", "2026-07-07", "2026-07-08", "2026-07-09",
                   "2026-07-10", "2026-07-13", "2026-07-14"]

def backfill_premarket():
    for date_str in PREMARKET_DATES:
        # Find upstream file
        pattern = os.path.join(PREMARKET_SOURCE, f"{date_str}_*.md")
        matches = sorted(glob.glob(pattern))
        if not matches:
            print(f"[盤前] {date_str}: ⚠️ 上游檔案不存在，跳過")
            continue
        
        upstream_file = matches[-1]  # latest if multiple
        print(f"[盤前] {date_str}: 讀取上游 {upstream_file}")

        # Read upstream content (everything after "## Response" if it exists, else full file)
        with open(upstream_file) as f:
            full_content = f.read()
        
        # Extract content after ## Response
        response_marker = "## Response"
        if response_marker in full_content:
            # Option 1: Use everything including prompt for completeness
            content = full_content.strip()
        else:
            content = full_content.strip()
        
        # Read existing report JSON
        report_file = os.path.join(REPORTS_DIR, f"{date_str}.json")
        if not os.path.exists(report_file):
            print(f"[盤前] {date_str}: ⚠️ 報告 JSON 不存在，跳過")
            continue
        
        with open(report_file) as f:
            report = json.load(f)
        
        # Check if premarket-analysis already exists
        if "sections" in report:
            for s in report["sections"]:
                if isinstance(s, dict) and s.get("type") == "premarket-analysis":
                    print(f"[盤前] {date_str}: ✅ 已有盤前分析，跳過")
                    break
            else:
                dow = get_dow(date_str)
                new_section = {
                    "type": "premarket-analysis",
                    "title": f"📊 台股盤前分析 | {date_str}（{DOW_CN[dow]}）",
                    "content": content,
                    "icon": "🌅"
                }
                report["sections"].append(new_section)
                with open(report_file, "w") as f:
                    json.dump(report, f, ensure_ascii=False, indent=2)
                print(f"[盤前] {date_str}: ✅ 已補回盤前分析（{len(content)}字元）")
        else:
            print(f"[盤前] {date_str}: ⚠️ 報告 JSON 無 sections 欄位，跳過")

# ============================================================
# PART B: 補完整籌碼
# ============================================================
CHIP_DATES = ["2026-06-30", "2026-07-01", "2026-07-02", "2026-07-03",
              "2026-07-06", "2026-07-07", "2026-07-08", "2026-07-09",
              "2026-07-10", "2026-07-13"]

def backfill_chip_data():
    for date_str in CHIP_DATES:
        # Find upstream file
        pattern = os.path.join(CHIP_SOURCE, f"{date_str}_*.md")
        matches = sorted(glob.glob(pattern))
        if not matches:
            print(f"[籌碼] {date_str}: ⚠️ 上游檔案不存在，跳過")
            continue
        
        upstream_file = matches[-1]
        print(f"[籌碼] {date_str}: 讀取上游 {upstream_file}")

        with open(upstream_file) as f:
            full_content = f.read()
        
        content = full_content.strip()
        
        # Read existing postmarket JSON
        pm_file = os.path.join(POSTMARKET_DIR, f"{date_str}.json")
        if not os.path.exists(pm_file):
            print(f"[籌碼] {date_str}: ⚠️ postmarket JSON 不存在，跳過")
            continue
        
        with open(pm_file) as f:
            raw = f.read()
            pm = json.loads(raw)
        
        # Check if already has complete_holdings or full_chip_data
        if "complete_holdings" in pm and pm["complete_holdings"]:
            print(f"[籌碼] {date_str}: ✅ complete_holdings 已存在，跳過")
            continue
        if "full_chip_data" in pm and pm["full_chip_data"]:
            print(f"[籌碼] {date_str}: ✅ full_chip_data 已存在，跳過")
            continue
        
        # Add complete_holdings
        pm["complete_holdings"] = content
        
        with open(pm_file, "w") as f:
            json.dump(pm, f, ensure_ascii=False, indent=2)
        print(f"[籌碼] {date_str}: ✅ 已補回完整籌碼（{len(content)}字元）")

# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("步驟 A：補盤前分析")
    print("=" * 60)
    backfill_premarket()
    
    print()
    print("=" * 60)
    print("步驟 B：補完整籌碼")
    print("=" * 60)
    backfill_chip_data()
    
    print()
    print("✅ 全部完成")
