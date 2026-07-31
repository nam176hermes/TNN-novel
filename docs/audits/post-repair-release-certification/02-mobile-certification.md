# Mobile and desktop certification

## Verdict

Mobile: **GO**

Desktop: **GO**

Offline/PWA: **GO_WITH_LIMITATIONS** because the contract was verified with
the production service worker and isolated fixtures rather than by disconnecting
the live production domain.

## Test environments

- Chromium Playwright against the repository production build and controlled
  API fixtures.
- Isolated API built from the certified commit, using a consistent copy of the
  production SQLite database and only the two Reader chapters/artifacts needed
  for read-only behavior validation.
- No production content was written. No title or chapter text is included here.

## Required viewport matrix

| Viewport | Surfaces scanned | Maximum DOM nodes | Maximum visible controls | Undersized visible controls | Horizontal overflow |
|---|---:|---:|---:|---:|---|
| 360×740 | 9 | 662 | 59 | 0 | no |
| 390×844 | 9 | 662 | 59 | 0 | no |
| 412×915 | 9 | 662 | 59 | 0 | no |

Surfaces included Dashboard, Library, Jobs, Import, Sources, Glossary/style,
Providers, Status/Backup, and Export. Book detail, Reader, QA, Settings,
offline, and TTS-unavailable behavior were covered by Reader and Playwright
scenarios.

## Reader certification

| Contract | Result |
|---|---|
| Vietnamese rendering | pass |
| Raw availability when source exists | pass |
| Raw compact availability | pass |
| Split availability with source + translation | pass |
| Truthful disable when source is absent | pass |
| QA present/absent handling | pass |
| Rapid chapter navigation | pass |
| Stale response rejection | pass in contract/integration tests |
| Refresh | pass |
| Offline reload | pass with cached content or explicit offline state |
| No broad protected-route caching | pass |
| Logout private-cache clearing | pass |
| Dialog focus entry/containment/Escape/restore | pass |
| TOC current-context behavior | pass |
| Horizontal overflow | none |

The production-scale staging sample initially lacked copied artifacts and
correctly returned optional 404 responses. After copying only the required
source and translation artifacts into the isolated staging root, Raw, Raw
compact, and Split all enabled. This distinguishes a truthful missing-resource
state from the former `READ-001` mismatch.

## Request ownership

After allowing initial loading to settle, four rapid chapter transitions
produced:

| Resource | Requests |
|---|---:|
| source | 4 |
| translation | 4 |
| QA | 4 |
| dictionary pack | 4 |

No duplicate core resource owner was observed. Reader sync POSTs are debounced
progress/event writes and varied with interaction timing; they did not duplicate
source/translation/QA reads or overwrite current content.

## Offline and error behavior

The E2E suite demonstrated an offline reload with cached Reader content while
excluding arbitrary protected API responses from Cache Storage. Optional
chapter-audio 404 responses remained safe and did not block reading. The
initial refresh request can return 401 when no refresh cookie exists; login then
proceeds normally. Neither condition produced a page error or blank shell.

## Desktop parity

| Viewport | Surfaces scanned | Maximum DOM nodes | Horizontal overflow |
|---|---:|---:|---|
| 1366×768 | 11 | 1,500 | no |
| 1440×1000 | 11 | 1,500 | no |

Desktop and mobile use the same API/client and Reader capability contracts.
Desktop-only hover was not required for the certified workflows.

## Automated evidence

`npm --prefix web run test:e2e -- --project=chromium` completed 11/11 tests,
including login, import, translation-job start, Reader raw/split, offline
reload, mobile shell at all required widths, dialog focus, touch targets,
status/backup, export, and desktop provider layout.

## Limitations

- No low-end physical Android device was used for a long-duration memory soak.
- Offline behavior was not tested against the live domain to avoid production
  session/cache mutation.
- This report does not claim broad visual perfection outside the required
  workflows and viewports.
