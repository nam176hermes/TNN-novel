# Glossary Phase 0 baseline audit

Before applying a glossary migration, run the audit against a copied database or
an operator-approved database path in dry-run mode:

```bash
.venv/bin/python scripts/audit_glossary_baseline.py --db "$DATA_DIR/pipeline.db"
```

The audit opens SQLite in read-only/query-only mode. It performs no repair,
merge, deletion, migration, or other row modification. Findings are aggregate
counts only; a nonzero exit code means the command itself could not inspect the
database, not that the report found data to review.

For a deterministic compatibility characterization that never reads operator
data, use the synthetic 10,000-row fixture:

```bash
.venv/bin/python scripts/benchmark_glossary_baseline.py --rows 10000 --work-dir /tmp/novel-tnn-glossary-phase0
```

The JSON result records current list, SQL offset-query, prompt-selection, and
glossary-QA behavior without timing thresholds or glossary text.
