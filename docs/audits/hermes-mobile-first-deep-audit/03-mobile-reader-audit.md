# Mobile Reader Audit

## Viewports

Authenticated Reader checks ran at 360x740, 390x844, and 412x915 against an isolated API and copied database. Production artifacts were mounted read-only. [Source: browser evidence JSON]

## Passing behavior

- Reader opened from Library at all three viewports.
- No horizontal overflow was observed.
- Translation rendered as one article with about 11,417 characters and 131 paragraphs in the sampled chapter.
- QA mode could be selected.
- TOC, font settings, and More options opened.
- Mobile bottom navigation was absent inside Reader.

[Source: browser actions, screenshots, and focused Reader mode probe]

## READ-001: source state mismatch

The source API response for the selected chapter contained 3,701 characters and 2,783 CJK characters. Translation responses contained Vietnamese text. Reader still disabled `Song song`, `Raw gọn`, and `Raw tiếng Trung` and displayed that raw content was unavailable. [Source: focused Playwright response-length probe and settings-state probe]

Classification: P1, REPRODUCED.

Risk: valid source artifacts cannot be accessed through advertised Reader modes. Response ordering or state ownership may associate the wrong source status with the selected chapter.

## READ-002: offline reload failure

After opening Reader, forcing offline mode, and reloading, all three mobile viewports reported:

```text
articleVisible: 0
loginVisible: 0
bodyHasOfflineText: false
domNodes: 17
```

A service worker registration and manifest were present. [Source: browser evidence JSON `offline` and `pwa` fields]

Classification: P1, REPRODUCED.

## Navigation and request behavior

The latest chapter correctly disabled the next control. A separate previous-chapter probe worked in about 1.38 seconds. Four rapid previous-chapter transitions produced 23 API calls, including seven translation requests. No failed API response was observed in that focused probe. [Source: rapid-navigation Playwright probe]

## Reader density

| State | DOM nodes | Interactive elements |
|---|---:|---:|
| Reader | about 455 | 6 |
| Reader TOC | 5,342 | 707 |
| Reader font settings | about 576 | 35 |
| Reader More options | about 580 | 31 |

[Source: browser evidence JSON `scans`]

## Limits

Audio was unavailable for the sampled chapter. No GPU synthesis was attempted. Scroll restoration under a forced slow network and stale-response injection were not fully exercised.
