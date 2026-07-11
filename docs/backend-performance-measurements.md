# Backend Performance Measurements

## Route Timing

All values are milliseconds on the WSL Linux filesystem. Warm values are medians of four calls.

| Route | Cold | Warm median | Payload |
| --- | ---: | ---: | ---: |
| `/api/health` | 13.89 | 1.52 | 33 B |
| `/api/ready` | 17.94 | 14.35 | 322 B |
| `/api/system/status` | 103.71 | 94.08 | 801 B |
| `/api/books` | 92.49 | 58.98 | 779 B |
| `/api/library/books` | 56.54 | 56.32 | 1.2 KB |
| 150-chapter list | 25.45 | 25.35 | 87.3 KB |
| normal translation | 37.18 | 36.61 | 20.6 KB |
| long translation | 39.67 | 38.39 | 410.4 KB |
| 500 glossary terms | 29.36 | 29.78 | 23.7 KB |
| 100 job logs | 23.79 | 23.03 | 17.9 KB |
| source catalog | 44.49 | 23.10 | 73 B |
| backup list | 13.88 | 12.29 | 12 B |

## Database Findings

The project `get_connection()` median was 9.346 ms versus 0.038 ms for raw `sqlite3.connect()`. Each project connection runs migration checks, default seeding, owner backfill checks, and commits. This fixed cost dominates many small routes.

`PipelineService.list_books()` and `list_translated_book_summaries()` call `list_chapters()` once per book. With 59 synthetic books, `/api/books` took 645-663 ms and `/api/library/books` took 644-739 ms. This is confirmed N+1 behavior, not an inference from file size.

Query-plan checks showed:

- chapter-by-book and job-log lookups use appropriate indexes;
- glossary-by-book uses an index but a temporary B-tree for ordering;
- QA chapter lookup uses the book/status index and a temporary B-tree;
- the small books table is scanned, which is acceptable at current size.

No index was added because the dominant measured issue is connection lifecycle and N+1 access. Adding indexes first would not address the observed cost.

## Import, Export, Backup

- Normal 24 KB import commit: 119 ms.
- One-chapter 1 MB commit: 256 ms.
- One-chapter 4.9 MB commit: 797 ms.
- 120 small unique chapters: 5.62 seconds.
- TXT/DOCX/EPUB export medians: 95/94/106 ms.
- Plain backup: 17.46 seconds.
- Encrypted fixture backup: 11.40 seconds.

The 120-chapter result is consistent with per-chapter file/database operations and transaction boundaries. Backup creation is synchronous in the API request and is the clearest request-time operational risk.

## Recommendations

1. P1: make schema initialization process-scoped, while retaining explicit startup migration and tests.
2. P1: replace library N+1 calls with one aggregate query or repository method.
3. P1: commit reviewed multi-chapter imports in one bounded transaction with rollback and progress semantics.
4. P1: move backup creation to a tracked job or background operation with visible status.
5. P2: re-run plans on a larger copied database before adding glossary or QA indexes.

## P2A Database Lifecycle And Library Follow-Up

P2A was measured on an isolated Linux-filesystem synthetic database. Normal project connection setup fell from a fresh 11.921 ms median to 0.035 ms after migration, seeding, backfill, WAL negotiation, and version recording moved behind explicit `init_db()` startup.

Both measured list paths now use one connection and one query instead of one book query plus one chapter query per book:

| Fixture | General list median | Translated library median |
| ---: | ---: | ---: |
| 1 book | 0.710 ms | 1.002 ms |
| 10 books | 0.641 ms | 1.172 ms |
| 59 books | 0.740 ms | 2.668 ms |
| 100 books | 0.864 ms | 3.872 ms |

Authenticated-ASGI-equivalent local route measurements with auth bypass limited to the isolated audit app were 3.195 ms median for `/api/books` and 5.188 ms for `/api/library/books` at 59 books. Payloads were 12.1 KB and 22.7 KB respectively.

`EXPLAIN QUERY PLAN` confirms use of `idx_chapters_active_number`. The translated aggregate uses temporary B-trees for window/group/order operations, but the measured 100-book result does not justify another index. No index was added.

Reproduction command:

```bash
python scripts/benchmark_database_library.py \
  --work-dir /home/<user>/novel-tnn-p2a-fixtures \
  --samples 7 \
  --book-counts 1 10 59 100 \
  --output /tmp/novel-tnn-p2a.json
```

The benchmark creates only synthetic databases under the supplied work directory and must not be pointed at the operator data directory.
