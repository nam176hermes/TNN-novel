# Database Lifecycle

## Policy

Novel-TNN uses short-lived SQLite connections. It does not share one global connection across request threads and does not use a connection pool.

`init_db(db_path)` is the explicit initialization boundary. Application entry points, standalone CLIs, jobs, and tests must call it before normal database operations.

Startup-scoped work:

- persistent WAL journal configuration;
- schema creation;
- additive legacy migrations and compatibility checks;
- required index creation;
- default provider and style-profile seeding;
- operator-user creation and ownership backfill;
- duplicate-key consolidation;
- schema-version recording.

Normal `get_connection(db_path)` work:

- open a short-lived SQLite connection;
- install `sqlite3.Row` as the row factory;
- enable foreign keys for that connection;
- set a 5-second SQLite busy timeout.

Normal connections do not run schema checks, migrations, backfills, default seeding, index creation, WAL negotiation, or commits merely because a connection was opened.

## Startup Ordering

Initialization configures WAL, creates the migration registry, runs the additive legacy migration once, applies the canonical schema, seeds required defaults, backfills ownership, records the current schema version, and commits.

Legacy migration runs before the canonical schema script because existing databases may not yet contain columns referenced by canonical indexes. Reversing that order makes schema initialization fail on older databases.

`init_db()` remains idempotent. Repeated explicit calls are safe, but they are intentional startup/CLI operations rather than a request-path fallback.

## Transactions And Threads

Each repository function owns and closes its connection. Write functions retain their existing explicit commit boundaries. SQLite serializes writes; the busy timeout allows short lock contention without unsafe cross-thread connection sharing. A connection is not passed between request threads.

## Scheduled Metadata Retention

FastAPI starts one process-local retention task from its lifespan after `init_db()` completes. The task runs immediately and every 21,600 seconds by default. Shutdown signals, cancels, and awaits that task so no maintenance task is left behind.

Retention is not a request-path fallback. It drains repository-owned batches of 500 rows by default and yields between batches. Each auth batch shares one short transaction across inactive sessions and login failures; each operational-event batch has its own short transaction. Active, unexpired sessions are excluded by repository predicates from both age and count pruning.

The default bounds are 30 days/5,000 rows for revoked or expired auth sessions, 30 days/5,000 rows for login failures, and 90 days/50,000 rows for operational events. All eight retention settings are positive validated environment integers; zero and negative values are rejected.

Concurrent processes may attempt the same idempotent cleanup. A SQLite busy or locked result skips the run safely and retries on the next interval without blocking API startup. Deletion produces one count-only operational event after event pruning; a zero-delete run produces no event. Authenticated status performs count queries only and exposes no paths, SQL, row values, exception text, or secrets.

## Entry Points

Initialization is called by the FastAPI startup path, batch jobs, source-catalog CLI, standalone TTS commands, and TTS smoke tooling. The root Typer callback initializes the database once before normal CLI commands; the explicit `init` command is excluded so its existing database-exists behavior remains intact. Tests creating legacy schemas must call `init_db()` explicitly before testing post-migration behavior.

## Library Queries

`PipelineService.list_books()` uses one indexed `EXISTS` query to preserve the existing active-chapter filter. `PipelineService.list_translated_book_summaries()` uses one CTE/window aggregate query for counts and first/latest translated chapter metadata.

The translated-library query preserves:

- translated detection by translated path, HTML content path, or translated/QA/audio status;
- exclusion of soft-deleted chapters;
- chapter, translation, audio, failure, and QA-low counts;
- first/latest translated chapter ordering by chapter number and ID;
- last-activity and book-ID ordering;
- cover URL generation in the service layer;
- existing API path sanitization.

The base `list_books()` repository function still returns zero-chapter books. The API service lists retain their previous filters: the general API list requires an active chapter, and the translated library requires at least one translated chapter. Reader progress and last-read metadata are separate API concerns and were not added to the library response contract.

## Independent Scripts

New scripts must not rely on a read operation to migrate a database. The safe pattern is:

```python
init_db(db_path)
with get_connection(db_path) as conn:
    ...
```

This keeps startup failures visible and prevents unpredictable first-request migration latency.
