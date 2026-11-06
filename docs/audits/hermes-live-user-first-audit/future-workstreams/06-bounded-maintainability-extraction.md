# Workstream 6: Bounded Maintainability Extraction

Goal: Reduce one high-risk hotspot after P1 and operational fixes are complete.

Default target: extract one cohesive public contract from `PipelineService` or `ReaderView`, not both.

Scope:
- Run caller-impact analysis first.
- Record behavior and API compatibility constraints.
- Move one responsibility with no product cleanup or UI redesign.
- Keep imports, schemas, and public signatures compatible.
- Add characterization tests before extraction.

Required verification: targeted tests, full backend and frontend suites as applicable, typecheck, build, E2E, diff review, and rollback command.
