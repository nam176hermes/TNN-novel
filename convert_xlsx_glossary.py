#!/usr/bin/env python3
"""Convert Xianxia_Wuxia_Glossary_VN.xlsx to pipeline CSV schema and merge useful terms."""

import csv
import sqlite3
from pathlib import Path

import openpyxl

XLSX = Path.home() / ".hermes/cache/documents/doc_ce5712dc7c3b_Xianxia_Wuxia_Glossary_VN.xlsx"
OUT_CSV = Path("/home/thenam176/novel_pipeline/data/glossary/xianxia_wuxia_glossary_vn_converted.csv")
REPORT = Path("/home/thenam176/novel_pipeline/data/glossary/xianxia_wuxia_glossary_vn_analysis.md")
DB = Path("/home/thenam176/novel_pipeline/data/pipeline.db")

CATEGORY_MAP = {
    "Basic": "co_ban_the_loai",
    "Cultivation Stage": "canh_gioi_base",
    "Treasures & Pills": "phap_bao_dan_duoc",
    "Races": "chung_toc",
    "Cosmology": "vu_tru_quan",
}

def mode_for(category: str, zh: str) -> str:
    if category in {"Basic", "Treasures & Pills", "Races", "Cosmology"}:
        return "translate"
    if category == "Cultivation Stage":
        return "translate"
    return "translate"

def normalize_vi(vi: str, category: str) -> str:
    """Keep current pipeline convention: common nouns lowercase in prose; realm names Title Case."""
    vi = (vi or "").strip()
    if category == "Cultivation Stage":
        return vi  # realm bases are OK title-cased
    # For genre labels and named concepts, keep provided capitalization.
    if category in {"Basic", "Cosmology", "Races"}:
        return vi
    return vi

wb = openpyxl.load_workbook(XLSX)
ws = wb.active
rows = []
for row in ws.iter_rows(min_row=2, values_only=True):
    category, zh, pinyin, vi, en_ref, notes, variants = row
    if not zh or not vi:
        continue
    rows.append({
        "category": CATEGORY_MAP.get(category, str(category).lower().replace(" ", "_")),
        "source_zh": str(zh).strip(),
        "pinyin": str(pinyin or "").strip(),
        "vi_preferred": normalize_vi(str(vi).strip(), category),
        "mode": mode_for(category, str(zh).strip()),
        "variants": str(variants or en_ref or "").strip(),
        "notes_vi": str(notes or "").strip(),
        "orig_category": category,
    })

OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=["category", "source_zh", "pinyin", "vi_preferred", "mode", "variants", "notes_vi"])
    writer.writeheader()
    for r in rows:
        writer.writerow({k: r[k] for k in ["category", "source_zh", "pinyin", "vi_preferred", "mode", "variants", "notes_vi"]})

conn = sqlite3.connect(DB)
existing = {r[0]: r[1] for r in conn.execute("SELECT source_term, target_term FROM glossary_terms")}
new_terms = []
conflicts = []
same_case_insensitive = []
for r in rows:
    zh, vi = r["source_zh"], r["vi_preferred"]
    if zh not in existing:
        new_terms.append(r)
    elif existing[zh] == vi:
        pass
    elif existing[zh].lower() == vi.lower():
        same_case_insensitive.append((zh, existing[zh], vi, r))
    else:
        conflicts.append((zh, existing[zh], vi, r))

# Merge policy: insert new terms only; do not override existing conflicts.
for r in new_terms:
    conn.execute(
        """
        INSERT OR REPLACE INTO glossary_terms (book_id, source_term, target_term, category, approved, mode, pinyin, notes_vi, variants)
               VALUES (0, ?, ?, ?, 1, ?, ?, ?, ?)
        """,
        (r["source_zh"], r["vi_preferred"], r["category"], r.get("mode", ""), r.get("pinyin", ""), r.get("notes_vi", ""), r.get("variants", "")),
    )
conn.commit()
post_count = conn.execute("SELECT COUNT(*) FROM glossary_terms WHERE approved=1").fetchone()[0]
conn.close()

report = []
report.append("# Xianxia_Wuxia_Glossary_VN.xlsx Analysis\n")
report.append(f"- Source: `{XLSX}`")
report.append(f"- Converted CSV: `{OUT_CSV}`")
report.append(f"- Terms in XLSX: {len(rows)}")
report.append(f"- New terms merged into SQLite: {len(new_terms)}")
report.append(f"- Case-only conflicts kept as existing: {len(same_case_insensitive)}")
report.append(f"- Real conflicts not overwritten: {len(conflicts)}")
report.append(f"- Approved glossary terms after merge: {post_count}\n")
report.append("## Merge Policy\n")
report.append("- Insert new terms from XLSX.")
report.append("- Do not overwrite current DB when difference is only capitalization, because current pipeline uses lowercase for common terms in prose and Title Case for proper realms/sect names.")
report.append("- Do not overwrite real conflicts automatically; keep them for manual review.\n")
report.append("## New Terms Merged\n")
for r in new_terms:
    report.append(f"- `{r['source_zh']}` → **{r['vi_preferred']}** ({r['category']}) — {r['notes_vi']}")
report.append("\n## Case-only Conflicts Kept\n")
for zh, db_vi, xlsx_vi, r in same_case_insensitive:
    report.append(f"- `{zh}`: DB=`{db_vi}` | XLSX=`{xlsx_vi}`")
report.append("\n## Real Conflicts Requiring Manual Review\n")
if conflicts:
    for zh, db_vi, xlsx_vi, r in conflicts:
        report.append(f"- `{zh}`: DB=`{db_vi}` | XLSX=`{xlsx_vi}` — {r['notes_vi']}")
else:
    report.append("- None")
REPORT.write_text("\n".join(report), encoding="utf-8")

print(f"converted_csv={OUT_CSV}")
print(f"analysis_report={REPORT}")
print(f"xlsx_terms={len(rows)} new_merged={len(new_terms)} case_conflicts={len(same_case_insensitive)} real_conflicts={len(conflicts)} approved_total={post_count}")
