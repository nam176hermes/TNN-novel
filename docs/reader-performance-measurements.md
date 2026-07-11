# Reader Performance Measurements

## Measured Results

- First Reader open: 479-527 ms in the completed desktop/mobile audit; three-run warm values ranged from 154 to 835 ms depending on cache/state.
- Long chapter API payload: about 410 KB translated text plus about 276 KB source text.
- Long chapter selection: 207-497 ms in the instrumented runs, with rendering still asynchronous on one mobile sample.
- Chapter switch: 191-493 ms.
- QA mode: 102-599 ms; long fixture reached about 5,182 DOM nodes.
- Reader route chunk: 181.73 KB raw, 49.54 KB gzip.

## Network Findings

Observed Reader opens made duplicate chapter-list calls and repeated reader-state and QA calls. Text became visible without waiting for audio playlist or dictionary data, which is correct. Adjacent chapter translation prefetch occurs after 250 ms and avoids source prefetch; it is bounded but can add bandwidth for large chapters.

## Correctness and UX Findings

Raw, split, and Raw gon were disabled in the live App workflow even though the chapter had source text. ReaderView derives raw content from `contentHtml`, while the top-level App passes translation and HTML but not the source text already loaded by `useChapterText`. This is a functional limitation, not a performance-only issue.

The mobile chapter-navigation row and mode row overlapped and blocked QA interaction. The audit applied a narrow CSS fix and verified interaction at 390x844 and 360x740.

## Recommendations

- P1: pass sanitized source text into ReaderView, or define a dedicated raw-content response contract; add App integration coverage for all modes.
- P1: deduplicate chapter, reader-state, and QA loads.
- P1: isolate QA badge mapping and progressive rendering from the base text-visible path.
- P2: split Reader by optional feature panels. Preserve a thin orchestrator, text surface, and existing state modules.
- Do not add virtualization yet. The evidence supports progressive QA rendering and request cleanup first; ordinary chapter navigation is already below one second locally.
