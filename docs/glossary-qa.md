# Glossary and Translation QA

Phase 4 adds per-book glossary metadata and deterministic chapter QA on top of the existing translation pipeline. It is still a single-operator workflow; this does not add tenant isolation, SaaS roles, or new crawler behavior.

## Existing Reality

Novel-TNN already had a SQLite `glossary_terms` table, glossary APIs, style profiles, translation memory, and LLM QA reports. Translation prompts already used approved glossary data, and the workbench already had a glossary/QA panel.

The Phase 4 changes keep that architecture and add missing durability fields, review statuses, deterministic QA checks, and post-import/post-translation hooks. Rejected glossary rows are now retained for history instead of being silently deleted.

## Glossary Model

Glossary remains per-book first. Global/default glossary data may exist, but per-book terms are the operator-facing source of truth for a novel.

Important fields now include:

- `book_id`
- `source_term`
- `target_term`
- `alternatives`
- `term_type`
- `gender`
- `first_seen_chapter_id`
- `first_seen_chapter_number`
- `review_status`
- `source_context`
- `occurrence_count`
- `priority`
- `locked`
- `approved`
- `notes_vi`
- `created_at`
- `updated_at`

Supported review statuses:

- `NEEDS_REVIEW`: extracted or imported candidate waiting for operator approval.
- `APPROVED`: safe to use in translation prompts.
- `REJECTED`: kept for history and not injected into prompts.
- `CONFLICT`: needs operator review because a term or translation conflicts.
- `LOCKED`: highest priority approved term; translators should follow it.

Supported term types include character, sect, realm, skill, artifact, location/place, title, idiom, cultivation, organization, and other. Internally the app still accepts older lowercase values for compatibility.

## Extraction Behavior

When raw Chinese text is imported or translated, the app scans for likely Chinese novel terms using deterministic heuristics. It looks for repeated names, sect/organization suffixes, realm/cultivation suffixes, skills, artifacts, and place terms.

Extracted candidates default to `NEEDS_REVIEW`. They are not auto-approved. Existing `APPROVED`, `LOCKED`, and `REJECTED` terms are not overwritten by extraction candidates. Source context and first-seen chapter metadata are preserved where available.

This extraction is intentionally conservative. It is not a replacement for human glossary review.

## Conflict Rules

The app reports conflicts when it sees:

- the same Chinese source term with conflicting metadata;
- the same Vietnamese target reused for multiple important source terms;
- a locked term expected in the raw chapter but missing from the translated output;
- rejected terms suggested again by extraction.

Conflicts do not overwrite existing approved or locked terms. They are shown as review work for the operator.

## Prompt Integration

Future translation prompts include only bounded, relevant glossary terms:

1. locked terms;
2. approved terms present in the current source chapter;
3. high-priority approved terms;
4. recently seen terms when space remains.

Rejected terms are excluded. The prompt glossary section is bounded by term count and character limits so a large glossary cannot flood the model context. Ordering is deterministic.

Job logs may record that glossary terms were used, but must not log provider keys, Authorization headers, raw stack traces, or private book text.

## Chapter QA Reports

Chapter QA reports are stored in `qa_reports` and linked to `book_id`, `chapter_id`, and optionally `job_id`.

The deterministic report fields include:

- `overall_status`
- `chinese_leakage_count`
- `length_ratio`
- `missing_paragraph_warning`
- `repetition_warning`
- `name_consistency_status`
- `term_consistency_status`
- `style_warnings`
- `glossary_violations`
- `suggested_fixes`

Statuses are `PASS`, `WARNING`, `FAIL`, or `NOT_RUN`.

## QA Checks

Deterministic QA currently checks:

- CJK/Chinese characters leaking into Vietnamese output;
- suspicious raw-to-translation length ratio;
- translated paragraph count much lower than raw paragraph count;
- repeated translated paragraphs;
- locked glossary terms not followed;
- basic Chinese punctuation leakage.

If provider-based QA is also available, deterministic warnings are merged into the saved report instead of replacing the provider review.

## Job Integration

At the end of translation jobs, Novel-TNN now runs glossary extraction and deterministic QA as follow-up work. This follow-up must not turn a successfully saved translation into a failed translation job just because QA produced warnings.

Job logs record:

- QA started/completed;
- warning/failure count;
- glossary candidate count;
- sanitized failure reason if the follow-up itself errors.

QA warnings are operator feedback, not automatic translation failure.

## Import Integration

The unified import wizard can create translated chapters or raw+translated chapters. After commit, the app runs follow-up glossary extraction and deterministic QA where practical:

- raw Chinese available: extract candidates and run full deterministic QA if translation exists;
- translated Vietnamese only: run limited QA when the book glossary is available;
- warnings do not block import commit.

Imported content is rendered as text in the UI; glossary context and QA messages are not rendered as raw HTML.

## Operator Workflow

1. Import or translate a chapter.
2. Open the workbench QA panel and review warnings.
3. Open the glossary page and approve, reject, edit, or lock candidate terms.
4. Re-run QA after edits when needed.
5. Retry translation or manually edit the chapter if a locked glossary violation is important.
6. Use locked glossary terms to stabilize future chapters.

## Limitations

- Extraction is deterministic and intentionally shallow; some names or idioms will need manual review.
- QA is heuristic and can produce false positives on stylized prose, poetry, or mixed-language chapter titles.
- Locked glossary checks only catch terms present in raw text and absent from translated text; they do not fully prove semantic correctness.
- Very large glossaries are bounded before prompt injection, so not every approved term appears in every prompt.
- This phase does not implement SaaS-grade audit review, per-tenant glossaries, or multi-user ownership enforcement.
