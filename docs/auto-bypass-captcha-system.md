# Auto-Bypass Captcha System — Technical Reference

> **Project:** Novel-TNN
> **Created:** 2026-07-14
> **Status:** Working — 33 tests pass, E2E verified

---

## 1. Kiến trúc tổng quan

```
┌─────────────────────────────────────────────────────────────┐
│  Mobile Web UI (ImportPanel.tsx)                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ URL input → Preview → Chapter checkboxes → Tải N chương │  │
│  │ Badge: 🔒 Auto-bypass / ✅ Kết nối trực tiếp           │  │
│  └────────────────────────┬──────────────────────────────┘  │
└───────────────────────────┼──────────────────────────────────┘
                            │ HTTPS
┌───────────────────────────┼──────────────────────────────────┐
│  FastAPI Backend (port 7860)                                  │
│  ┌──────────────────────────▼──────────────────────────────┐ │
│  │ POST /api/import/url/preview  → Source preview + bypass  │ │
│  │ POST /api/import/url/fetch    → Fetch chapters + import  │ │
│  └──────────────────────────┬──────────────────────────────┘ │
│  ┌──────────────────────────▼──────────────────────────────┐ │
│  │ source_adapters.py                                        │ │
│  │   fetch_public_html()                                     │ │
│  │     1. requests.get() — direct HTTP                       │ │
│  │     2. Cloudflare 403? → _try_stealth_fallback()          │ │
│  │     3. Stealth browser → return HTML                      │ │
│  └──────────────────────────┬──────────────────────────────┘ │
│  ┌──────────────────────────▼──────────────────────────────┐ │
│  │ stealth_browser.py                                        │ │
│  │   Playwright persistent context + WSLg headed mode       │ │
│  │   → Cloudflare challenge auto-resolve                     │ │
│  │   → Captcha detection (Turnstile/reCAPTCHA)               │ │
│  │   → 2Captcha API solver (if configured)                   │ │
│  │   → Cookie persistence                                     │ │
│  └─────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

---

## 2. Cấu trúc thư mục & files

```
Novel-TNN/
├── app/
│   ├── ingestion/
│   │   └── source_adapters.py          # Core: fetch, bypass, extract
│   ├── utils/
│   │   ├── stealth_browser.py          # Playwright stealth + Cloudflare bypass
│   │   ├── captcha_solver.py           # 2Captcha API integration
│   │   ├── proxy_pool.py              # Proxy rotation
│   │   ├── cookie_store.py            # Cookie save/load/apply
│   │   └── asyncio_bridge.py          # Async→sync bridge for uvicorn
│   └── mobile_api/
│       ├── routers/import_routes.py   # API endpoints
│       ├── schemas/__init__.py        # Pydantic models
│       └── services/pipeline_service.py
├── web/src/
│   ├── api/
│   │   ├── types.ts                   # TypeScript types
│   │   └── client.ts                  # API client methods
│   ├── components/ImportPanel.tsx     # Main UI component
│   ├── App.tsx                        # Prop wiring
│   └── styles/features.css            # CSS styles
├── tests/
│   ├── test_browser_fallback.py       # Bypass + cookie tests
│   └── test_source_adapters.py        # Adapter + extraction tests
└── .env                               # CAPTCHA_API_KEY (masked), CAPTCHA_PROVIDER
```

---

## 3. Chi tiết từng file

### 3.1 `app/ingestion/source_adapters.py` (Core engine)

**Data structures:**

```python
@dataclass(frozen=True)
class SourcePreview:
    adapter_id: str
    adapter_label: str
    source: str
    source_url: str
    title: str
    author: str = ""
    description: str = ""
    cover_url: str = ""
    chapters: tuple[SourceChapter, ...] = ()
    policy: dict | None = None
    bypass_used: bool = False        # ← NEW
    bypass_method: str = ""          # ← NEW
```

**Key functions:**

| Function | Mục đích |
|----------|----------|
| `fetch_public_html(url, timeout=20, allow_browser_fallback=True)` | Entry point. Thử HTTP → nếu blocked → stealth fallback |
| `_raise_if_blocked_http_response(url, response)` | Detect Cloudflare 403, captcha pages, cooldown |
| `_try_stealth_fallback(url, reason, timeout)` | Gọi `stealth_browser.fetch_with_stealth_sync()` |
| `_reset_bypass_info()` / `_set_bypass_info(used, method)` | Thread-local tracking bypass status |
| `_get_bypass_info()` | Đọc bypass status sau fetch |

**Fetch flow:**

```
fetch_public_html(url)
├── requests.Session().get(url)
│   ├── apply_cookies_to_session()     ← Load saved cf_clearance
│   ├── 200 OK → decode → return HTML
│   ├── 403 + cf-mitigated → raise SourceBlockedError
│   └── 302 redirect → validate same source
│
├── except SourceBlockedError:
│   ├── if allow_browser_fallback:
│   │   └── _try_stealth_fallback(url, reason, timeout)
│   │       ├── fetch_with_stealth_sync(url, timeout)
│   │       ├── raise_if_cooldown_page(url, html)
│   │       ├── _set_bypass_info(True, "stealth_browser")
│   │       └── return html
│   │   └── raise SourceBlockedError
│   └── else: raise
```

**Adapter configs (69shuba example):**

```python
SelectorSourceAdapter(
    adapter_id="69shuba",
    domains=("69shuba.com", "69shuba.cx", "69shux.com"),
    title_patterns=(r"<h1[^>]*>(.*?)</h1>", ...),
    author_patterns=(r"(?:作者|作\s*者)\s*[:：]\s*([^<\n\r]{1,40})",),
    chapter_link_patterns=(chapter_link_pattern,),
    content_patterns=(
        r'<div[^>]+class="container"[^>]*>(.*?)</div>\s*<div[^>]+class="(?:bottom|foot|pagefoot)',
        r'<div[^>]+class="[^"]*txtnav[^"]*"[^>]*>(.*?)</div>\s*<div',
        r'<div[^>]+id="content"[^>]*>(.*?)</div>',
        r'<div[^>]+class="[^"]*content[^"]*"[^>]*>(.*?)</div>',
    ),
)
```

**Supported sources (17 domains):**

`69shuba.com, 69shuba.cx, 69shux.com, 69shumi.com, 69shumi.net, fanqienovel.com, qidian.com, book.qq.com, jjwxc.net, hetushu.com, ixdzs.com, ixdzs8.com, 17k.com, 22biqu.com, 52shuku.net, novel543.com, xbanxia.com`

---

### 3.2 `app/utils/stealth_browser.py` (Browser bypass)

**Class: `StealthBrowser`**

| Method | Mục đích |
|--------|----------|
| `fetch_with_stealth(url, timeout)` | Main async fetch — persistent context + Cloudflare wait + captcha solve |
| `_detect_and_solve_captcha(page, url)` | Detect Turnstile/reCAPTCHA → solve via 2Captcha |
| `init()` | Launch browser (legacy, dùng cho non-persistent) |

**fetch_with_stealth flow:**

```
1. Auto-detect display (:0 WSLg, fallback :99 Xvfb)
2. launch_persistent_context("/tmp/pw_stealth_profile")
   ├── headless=False (khi có DISPLAY)
   ├── Anti-detection args (--disable-blink-features=AutomationControlled)
   └── add_init_script(stealth JS)
3. page.goto(url, wait_until="domcontentloaded")
4. Cloudflare challenge detection:
   ├── sleep(5) → check title
   ├── "Just a moment"? → wait_for_function(45s)
   └── Still blocked? → page.reload() → sleep(5) → recheck
5. Captcha detection:
   ├── Query: [data-sitekey], .cf-turnstile
   ├── Found? → solver.solve_turnstile(url, sitekey) → inject token
   └── reCAPTCHA? → solver.solve_recaptcha(url, sitekey)
6. Save cookies → save_cookies(url, cookies)
7. Return page.content()
8. Cleanup: context.close() + playwright.stop()
```

**Stealth JS injected:**

```javascript
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
window.chrome = { runtime: {} };
```

**Sync wrapper:**

```python
def fetch_with_stealth_sync(url: str, timeout_ms: int = 60000) -> str:
    """Bridge for calling async fetch from sync context (ThreadPoolExecutor)."""
    # Uses run_coro_sync() from asyncio_bridge.py
```

---

### 3.3 `app/utils/captcha_solver.py` (2Captcha)

```python
class CaptchaSolver:
    def solve_turnstile(url, sitekey) -> str | None    # ~15-30s
    def solve_recaptcha(url, sitekey) -> str | None     # ~15-30s

def get_captcha_solver() -> CaptchaSolver | None:
    # Reads CAPTCHA_API_KEY + CAPTCHA_PROVIDER from .env
```

**Config (.env):**

```
CAPTCHA_API_KEY=*** (masked)
CAPTCHA_PROVIDER=2captcha
```

**Cost:** ~$0.003/solve. Budget $3 ≈ 1000 solves.

---

### 3.4 `app/utils/cookie_store.py`

| Function | Mục đích |
|----------|----------|
| `save_cookies(url, cookies)` | Save Playwright cookies → JSON file |
| `load_cookies(url)` | Load saved cookies → list[dict] |
| `apply_cookies_to_session(url, session)` | Inject cookies vào requests.Session |
| `clear_cookies(url)` | Xóa cookie file |

**Storage:** `~/.novel_pipeline/cookies/<domain>.json`

---

### 3.5 `app/mobile_api/routers/import_routes.py`

**Endpoints:**

| Route | Method | Mục đích |
|-------|--------|----------|
| `/api/import/url/preview` | POST | Preview URL → chapter list + bypass status |
| `/api/import/url/fetch` | POST | Fetch selected chapters → import vào book |
| `/api/import/url` | POST | Start background import job (cần Source Hub verified) |

**`/url/fetch` endpoint chi tiết:**

```python
@router.post("/url/fetch", response_model=URLFetchResponse)
async def fetch_source_chapters(data: URLFetchRequest, ...):
    for ch in data.chapters:
        result = await asyncio.to_thread(
            pipeline.import_from_source_url,
            book_title=data.title,
            chapter_url=ch.url,
            chapter_number=ch.chapter_number,
            ...
        )
        # → fetch_public_html() → auto-bypass → extract text → import
```

---

### 3.6 `app/mobile_api/schemas/__init__.py`

```python
class URLFetchRequest(BaseModel):
    source_url: str = ""
    title: str = ""
    author: str = ""
    source: str = ""
    chapters: list[URLFetchChapterRequest]

class URLFetchChapterRequest(BaseModel):
    url: str
    chapter_number: int = 1
    title: str = ""

class URLFetchResponse(BaseModel):
    title: str
    book_id: int
    total: int
    succeeded: int
    failed: int
    chapters: list[URLFetchChapterResult]

class URLFetchChapterResult(BaseModel):
    chapter_number: int
    title: str
    url: str
    success: bool
    error: str = ""
    text_length: int = 0
    book_id: int = 0
    chapter_id: int = 0

class SourcePreviewResponse(BaseModel):
    # ... existing fields ...
    bypass_used: bool = False      # ← NEW
    bypass_method: str = ""        # ← NEW
```

---

### 3.7 Frontend files

**`web/src/api/types.ts`:**

```typescript
export type URLFetchRequest = {
  source_url: string;
  title: string;
  author: string;
  source: string;
  chapters: URLFetchChapterRequest[];
};

export type URLFetchResponse = {
  title: string;
  book_id: number;
  total: number;
  succeeded: number;
  failed: number;
  chapters: URLFetchChapterResult[];
};
```

**`web/src/api/client.ts`:**

```typescript
async fetchSourceChapters(request: URLFetchRequest): Promise<URLFetchResponse> {
  // POST /api/import/url/fetch
}

async previewImportUrl(url: string): Promise<SourcePreview> {
  // POST /api/import/url/preview
}
```

**`web/src/components/ImportPanel.tsx`:**

| State | Mục đích |
|-------|----------|
| `selectedChapterUrls: Set<string>` | Track checked chapters |
| `fetchState: 'idle' \| 'loading' \| 'ready' \| 'error'` | Download progress |
| `fetchResult: URLFetchResponse \| null` | Download results |
| `fetchError: string` | Error message |

| Handler | Mục đích |
|---------|----------|
| `handlePreviewSourceUrl()` | Preview URL + reset states |
| `toggleChapterSelection(url)` | Checkbox toggle |
| `toggleSelectAllChapters()` | Select/deselect all |
| `handleFetchChapters()` | Call API → fetch + import |

**UI elements:**

```
┌──────────────────────────────────────┐
│ ☑ Chọn tất cả (3/5)   [⬇ Tải 3 chương] │
├──────────────────────────────────────┤
│ ☑ #927 第927章 手段！心术！             │
│   https://www.69shuba.com/txt/...     │
│   ✅ 4.482 chars                       │
│                                       │
│ ☑ #928 第928章 新朝第一次朝会！          │
│   https://www.69shuba.com/txt/...     │
│   (pending)                           │
│                                       │
│ ☐ #929 第929章 大雪山的神              │
│   https://www.69shuba.com/txt/...     │
├──────────────────────────────────────┤
│ ✅ Đã tải 2/3 chương vào "长生武尊"     │
└──────────────────────────────────────┘
```

---

## 4. Workflow end-to-end

```
USER                          FRONTEND                    BACKEND                     EXTERNAL
  │                              │                           │                           │
  │ 1. Paste 69shuba URL         │                           │                           │
  │─────────────────────────────>│                           │                           │
  │                              │ 2. POST /url/preview      │                           │
  │                              │──────────────────────────>│                           │
  │                              │                           │ 3. fetch_public_html()    │
  │                              │                           │──────────────────────────>│ HTTP GET
  │                              │                           │                           │
  │                              │                           │ 4. 403 Cloudflare?        │
  │                              │                           │    YES → stealth_browser  │
  │                              │                           │──────────────────────────>│ Playwright
  │                              │                           │    Persistent context     │ headed
  │                              │                           │    Cloudflare auto-resolve│
  │                              │                           │<──────────────────────────│ HTML
  │                              │                           │                           │
  │                              │                           │ 5. Extract title, author, │
  │                              │                           │    chapters, bypass_used  │
  │                              │ 6. Return SourcePreview   │                           │
  │                              │<──────────────────────────│                           │
  │                              │                           │                           │
  │ 7. See chapters +            │                           │                           │
  │    🔒 Auto-bypass badge      │                           │                           │
  │<─────────────────────────────│                           │                           │
  │                              │                           │                           │
  │ 8. Check chapters            │                           │                           │
  │    Click "Tải 3 chương"      │                           │                           │
  │─────────────────────────────>│                           │                           │
  │                              │ 9. POST /url/fetch        │                           │
  │                              │──────────────────────────>│                           │
  │                              │                           │ 10. For each chapter:     │
  │                              │                           │   fetch_public_html()     │
  │                              │                           │──────────────────────────>│ Playwright
  │                              │                           │   Extract text            │
  │                              │                           │   import_from_text()      │
  │                              │                           │   → DB insert             │
  │                              │                           │                           │
  │                              │ 11. Return results        │                           │
  │                              │<──────────────────────────│                           │
  │                              │                           │                           │
  │ 12. See per-chapter badges   │                           │                           │
  │     ✅ 4.482 chars            │                           │                           │
  │     ✅ Đã tải 2/3 chương      │                           │                           │
  │<─────────────────────────────│                           │                           │
```

---

## 5. Bypass levels (4 tầng)

```
Level 0: Direct HTTP (requests.get)
  ├── Cost: $0
  ├── Speed: ~2s
  └── Pass rate: ~30% (non-protected sites)

Level 1: Stealth Browser Headless (Playwright)
  ├── Cost: $0
  ├── Speed: ~10-15s
  └── Pass rate: ~60% (light Cloudflare, book pages)

Level 2: Persistent Context Headed (WSLg/Xvfb)
  ├── Cost: $0
  ├── Speed: ~15-20s
  └── Pass rate: ~90% (Cloudflare Turnstile, chapter pages) ← HIỆN TẠI

Level 3: 2Captcha API Solver
  ├── Cost: $0.003/solve
  ├── Speed: +15-30s/solve
  └── Pass rate: ~95% (hard captcha) ← CÓ SẴN, CHƯA TRIGGER TỰ ĐỘNG
```

---

## 6. Test suite

| File | Tests | Status |
|------|-------|--------|
| `test_browser_fallback.py` | 10 tests | ✅ Pass |
| `test_source_adapters.py` | 23 tests | ✅ Pass |
| `test_asyncio_bridge.py` | (included) | ✅ Pass |

**Total: 33 passed**

---

## 7. Điểm cần lưu ý khi nâng cấp

### Known limitations

1. **Sequential fetch** — chapters tải 1 lúc 1, không có concurrency
2. **No retry** — nếu 1 chapter fail, skip sang chương tiếp theo
3. **text_length luôn = 0** trong API response (cosmetic bug, text vẫn import OK)
4. **2Captcha chưa auto-trigger** cho Cloudflare interstitial — chỉ trigger khi tìm thấy `data-sitekey` element
5. **Cookie expiry** — cf_clearance cookie hết hạn sau ~30ph, cần re-fetch

### Nâng cấp đề xuất

| Priority | Item | Effort |
|----------|------|--------|
| High | Concurrent fetch (asyncio.gather cho N chapters) | 2h |
| High | Retry logic (3 retries per chapter, backoff 8s) | 1h |
| Medium | Auto-trigger 2Captcha cho Cloudflare "Just a moment" | 3h |
| Medium | Proxy rotation (proxy_pool.py đã có, chưa wire vào stealth) | 2h |
| Low | Progress streaming (SSE/WebSocket thay vì blocking) | 4h |
| Low | Text cleanup (remove nav/breadcrumb/ads từ extracted text) | 2h |
