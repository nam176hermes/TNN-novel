#!/usr/bin/env python3
"""Import enhanced glossary CSV into pipeline, replacing all global terms."""

import csv
import sqlite3
from pathlib import Path

csv_path = Path.home() / ".hermes/cache/documents/doc_662fe56b327b_xianxia_wuxia_xuanhuan_glossary_vi_enhanced.csv"
db_path = Path("/home/thenam176/novel_pipeline/data/pipeline.db")

if not csv_path.exists():
    print(f"CSV not found: {csv_path}")
    exit(1)

conn = sqlite3.connect(str(db_path))
cur = conn.cursor()

# Clear all global (book_id=0) glossary terms
cur.execute("DELETE FROM glossary_terms WHERE book_id = 0")

with open(csv_path, "r", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    count = 0
    for row in reader:
        mode = row.get("mode", "").strip()
        source = row["source_zh"].strip()
        target = row["vi_preferred"].strip()
        note = row.get("notes_vi", "").strip()
        if source and target:
            cur.execute(
                """
                INSERT OR REPLACE INTO glossary_terms (book_id, source_term, target_term, category, approved, mode, pinyin, notes_vi, variants)
                       VALUES (0, ?, ?, ?, 1, ?, ?, ?, ?)
                """,
                (source, target, row.get("category", ""), row.get("mode", ""), row.get("pinyin", ""), row.get("notes_vi", ""), row.get("variants", "")),
            )
            count += 1

conn.commit()
print(f"✓ Enhanced glossary imported: {count} terms (global)")
conn.close()
