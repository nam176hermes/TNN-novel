# PR6 Mobile Raw Navigation Design

## Goal

Restore access to the existing `Raw chưa dịch` view on mobile without expanding the five-item bottom navigation.

## User experience

- Keep the mobile bottom navigation unchanged: Bàn dịch, Thư viện, Đọc, Tác vụ, and Thêm.
- Add a semantic `Raw chưa dịch` button to the `Quản lý` section of the mobile More sheet.
- Activating the button closes the sheet, switches the active workflow view to `raw`, and exposes the existing Raw backlog page.
- When Raw is active, the More item remains selected through the existing `moreViews` behavior.

## Accessibility and responsive contract

- The new entry is a real keyboard-focusable button with an accessible name of `Raw chưa dịch`.
- Its visible hit area is at least 44 by 44 CSS pixels.
- The More sheet and Raw page must not cause horizontal document overflow at widths 360, 390, and 412 CSS pixels.
- Existing dialog focus lifecycle and Escape/return-focus behavior remain unchanged.

## Implementation boundary

- Reuse the existing `raw` route, `RawBacklogView`, and `openMobileView` callback.
- Add only the missing More-sheet entry and focused tests.
- Do not redesign bottom navigation or modify Raw backlog behavior.

## Verification

- Component test proves the More sheet exposes `Raw chưa dịch`, routes to `raw`, and closes.
- Playwright test enters Raw through More at 360, 390, and 412 pixels, checks the heading, 44px target policy, and absence of horizontal overflow.
