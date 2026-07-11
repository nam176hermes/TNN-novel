# Import Performance Measurements

## Fixtures

All fixtures were synthetic: 24 KB normal chapter, 1 MB text, 4.9 MB near-limit text, 4.5 MB single chapter, and 120 chapters in 163 KB.

## Browser Preview

| Fixture | Desktop | Mobile |
| --- | ---: | ---: |
| 24 KB | 335 ms | 107 ms |
| 1 MB | 130 ms | 168 ms |
| 4.9 MB | 393 ms | 442 ms |
| 120 chapters | 152 ms | 122 ms |
| 4.5 MB single chapter | 337 ms | 367 ms |

The browser reads the complete file, makes several full-text normalization/detection passes, and retains the text for commit. The measured 5 MB limit remained usable on this desktop-class machine, but long tasks above 100 ms occurred during the broader workflow. This does not prove smooth behavior on a low-end Android device.

## Server Commit

| Fixture | Request size | Result |
| --- | ---: | ---: |
| 24 KB, one chapter | 24.6 KB | 119 ms |
| 1 MB, one chapter | 1.02 MB | 256 ms |
| 4.9 MB, one chapter | 4.98 MB | 797 ms |
| 4.5 MB, one chapter | 4.54 MB | 786 ms |
| 120 unique chapters | 96 KB | 5.62 s |

An initial 120-chapter fixture correctly failed duplicate-source detection because every chapter body was identical; the corrected unique fixture passed. This is valid duplicate protection, not a product failure.

## Answers

- Is 5 MB client-side handling acceptable? Yes for the measured desktop-class environment, with limitations. It is near the practical ceiling and should not be raised without mobile hardware testing.
- When does UX become uncomfortable? Structure matters more than bytes. A 4.9 MB single chapter preview stayed under 0.45 seconds, while committing 120 small chapters took 5.62 seconds.
- Does 100+ chapter preview remain usable? Yes. Commit does not.
- Is server-side preview/session architecture justified now? Not solely by the 5 MB preview result. First fix multi-chapter commit transactions. A preview session becomes justified if the limit rises, uploads resume, or low-end mobile evidence degrades.
- Web Worker or backend? Move pure client detection/cleanup to a Worker if low-end device profiling shows input freezes. Use backend preview sessions for resumable uploads, larger files, and avoiding preview/commit payload duplication.
- Chunked upload? Future option, not currently justified under the enforced 5 MB text limit.

## P2B Reviewed-Import Commit

P2B measurements used isolated synthetic databases and content directories on WSL ext4. Three runs were collected per fixture. Glossary/QA were stubbed for the transaction-focused numbers and measured separately with actual deterministic follow-up.

| Fixture | P2B service median | Connections | Commits | Duplicate queries |
| --- | ---: | ---: | ---: | ---: |
| 1 chapter | 5.938 ms | 1 | 1 | 1 |
| 10 chapters | 7.207 ms | 1 | 1 | 1 |
| 120 chapters | 24.724 ms | 1 | 1 | 1 |
| 500 chapters | 94.859 ms | 1 | 1 | 1 |
| 4.9 MB single chapter | 20.917 ms | 1 | 1 | 1 |

For 120 chapters, the fresh post-P2A baseline was 366.449 ms with 243 connections, 122 commits, and 240 duplicate queries. The P2B path reduced those counts to 1/1/1 and 139 total traced SQL statements.

The authenticated ASGI endpoint with real glossary follow-up measured 144.083 ms median over three runs. The service with real follow-up measured 149.771 ms median. Follow-up work runs after commit and still uses per-chapter glossary repository calls; it does not extend the SQLite write transaction.

Always pass `--work-root` to the benchmark. On this machine, Python's default temporary directory can resolve to `/mnt/c` even when the checkout is under `/home`, invalidating an ext4 label.
