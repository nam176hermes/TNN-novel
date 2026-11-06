# Mobile Workflows Audit

## Navigation coverage

The following screens opened at 360x740, 390x844, and 412x915:

- Dashboard
- Library
- Jobs
- Import
- Sources
- Glossary and style
- Providers
- Status and backup
- Export
- Settings
- Reader

No audited screen showed horizontal overflow. [Source: browser evidence JSON `actions` and `scans`]

## Touch and density findings

At 360x740, undersized interactive counts included:

| Screen | Count below audit threshold |
|---|---:|
| Dashboard | 5 |
| Jobs | 5 |
| Sources | 58 |
| Status | 6 |
| Settings | 6 |
| Reader font settings | 9 |
| Reader More options | 25 |

Inputs intentionally rendered at one pixel for file selection and range-track geometry require manual filtering, but Sources and More options still contain many genuine controls below 44 CSS pixels. [Source: browser evidence JSON]

## Workflow interpretation

Screen-open success does not prove mutating workflows. Import, translation, QA, export, and backup behavior is instead supported by 271 focused isolated tests. Live provider actions were intentionally excluded. [Source: `07-core-workflow-evidence.md`]

## Mobile-specific blockers

- Reader offline and raw-mode failures.
- More dialog keyboard behavior.
- Dense Sources actions.
- Large Glossary DOM.
- No explicit offline explanation after reload.

[Source: `03-mobile-reader-audit.md`; `11-accessibility.md`; `09-performance-and-request-ownership.md`]
