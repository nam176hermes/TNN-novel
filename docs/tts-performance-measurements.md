# TTS Performance Measurements

No paid or real provider was called. These numbers do not predict provider synthesis speed.

## Fixture Smoke

Three complete fixture runs, each generating two MP3 chapters and one M4B, took 6.89, 6.91, and 7.09 seconds. All 9 checks passed. Each chapter fixture MP3 was 2,160 bytes; M4B was 7,768 bytes.

## Stage Timing

| Text | Characters | Chunks | Normalize | Chunk |
| --- | ---: | ---: | ---: | ---: |
| Short | 1,000 | 9 | 0.69 ms | 0.22 ms |
| Medium | 20,000 | 173 | 12.31 ms | 4.30 ms |
| Long | 100,000 | 863 | 60.85 ms | 21.73 ms |

| WAV chunks | MP3 merge | Audio QA | ffprobe |
| ---: | ---: | ---: | ---: |
| 1 | 138 ms | 52 ms | 53 ms |
| 10 | 303 ms | 51 ms | 52 ms |
| 50 | 1.06 s | 53 ms | 56 ms |
| 100 | 1.82 s | 54 ms | 53 ms |

Four fixture chapter MP3s merged to M4B in 467 ms and probed in 54 ms. The generated M4B had no chapter markers; operational validation returned `No chapter markers detected`.

## Findings

- Normalization and chunking are small compared with synthesis and ffmpeg merge.
- MP3 merge scales approximately with chunk count and becomes the dominant measured non-provider stage.
- Audio QA and ffprobe have a roughly 50 ms process-start floor each.
- Retry and cache-reuse behavior is covered by backend tests, but cache speedup was not separately timed in this audit.
- Fixture synthesis speed must not be extrapolated to F5, Edge TTS, or any paid provider.

## Recommendations

- P1: preserve chunk reuse and failed-chunk retry semantics while optimizing only measured merge/process overhead.
- P1: decide whether M4B chapter markers are a required artifact contract; if yes, treat the current result as incomplete.
- P2: batch or reuse metadata probes where safe, but retain final artifact validation.
