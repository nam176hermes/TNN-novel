# CAPTCHA Bypass Upgrade Plan

## Current State: 7/10

## Bugs (must fix)

### BUG-1: navigator.plugins array contains integers
**File:** `app/utils/stealth_browser.py` line 48
**Severity:** High — Cloudflare detects this instantly
**Current:**
```js
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
```
**Problem:** Real plugins are PluginArray objects, not integers. Any anti-bot script checking `navigator.plugins[0].name` will crash or return undefined, flagging the browser.

### BUG-2: Turnstile token injection does not trigger callback
**File:** `app/utils/stealth_browser.py` line 430-440
**Severity:** High — CAPTCHA solve succeeds but page doesn't advance
**Current:**
```js
const el = document.querySelector('[data-sitekey]');
if (el) el.setAttribute('data-response', token);
if (window.turnstile) { window.turnstile.reset(); }
```
**Problem:** `setAttribute('data-response')` doesn't trigger Turnstile's internal callback. `reset()` clears the widget instead of submitting the token. The page never advances.

### BUG-3: Duplicate taskId lookup
**File:** `app/utils/captcha_solver.py` line 65, 137
**Severity:** Low — works by accident (same key twice)
**Current:**
```python
task_id = data.get("taskId") or data.get("taskId")
```
**Problem:** Redundant. 2Captcha API returns `requestId`, Capsolver returns `taskId`.

### BUG-4: CAPTCHA detection misses iframe-embedded widgets
**File:** `app/utils/stealth_browser.py` line 417
**Severity:** Medium — Turnstile increasingly uses cross-origin iframes
**Current:**
```python
turnstile_el = await page.query_selector('[data-sitekey], .cf-turnstile, ...')
```
**Problem:** Only searches main frame. Turnstile widget inside `<iframe>` is invisible to `page.query_selector`.

### BUG-5: 2Captcha getTaskResult payload format outdated
**File:** `app/utils/captcha_solver.py` line 75-78
**Severity:** Medium — 2Captcha solver may silently fail
**Current:**
```python
json={"key": self.api_key, "taskId": task_id}
```
**Problem:** 2Captcha uses `requestId` from createTask response, not `taskId`. The poll payload should use `{"key": api_key, "requestId": request_id, "json": 1}`.

---

## Upgrade Milestones

### C01: Fingerprint Stealth Hardening

**Scope:** `app/utils/stealth_browser.py`

**Changes:**

1. Replace `_STEALTH_INIT_SCRIPT` with comprehensive stealth script:
   - Mock `navigator.plugins` as proper PluginArray (named objects with `.name`, `.filename`, `.description`)
   - Mock `navigator.mimeTypes` to match plugins
   - Add `navigator.permissions.query` override (Notification permission)
   - Add WebGL renderer/vendor override (`UNMASKED_VENDOR_WEBGL`, `UNMASKED_RENDERER_WEBGL`)
   - Add `window.chrome` full mock (app, csi, loadTimes, runtime)
   - Add `navigator.hardwareConcurrency = 8` and `navigator.deviceMemory = 8`
   - Add `navigator.platform` consistent with User-Agent
   - Add `navigator.connection` mock (effectiveType, rtt, downlink)
   - Add AudioContext fingerprint randomization (sampleRate, channelCount)
   - Add canvas fingerprint noise (toDataURL / getImageData subtle pixel offset)
   - Randomize `navigator.languages` order within zh-CN/zh/en set
   - Patch `Notification.permission` to return 'default'

2. Dynamic User-Agent rotation:
   - Pool of 5+ recent Chrome UA strings (Windows/Mac/Linux variants)
   - Rotate per session restart, not per request (maintains session consistency)
   - Keep UA consistent within one persistent context lifecycle

3. WebRTC leak prevention:
   - Add `--force-webrtc-ip-handling-policy=disable_non_proxied_udp` to launch args
   - Add init script to override `RTCPeerConnection` and strip local IP candidates

4. Viewport randomization:
   - Small variations per session (1920x1080, 1680x1050, 1440x900)
   - Keep `window.innerWidth/innerHeight` consistent with viewport

**Tests:**
- Unit: init script produces valid PluginArray (not integers)
- Unit: WebGL vendor/renderer returns override values
- Unit: AudioContext properties are randomized per call
- Integration (mock): launch args include WebRTC flag
- Regression: existing browser session manager tests still pass

---

### C02: Turnstile Token Injection Fix

**Scope:** `app/utils/stealth_browser.py`

**Changes:**

1. Replace Turnstile injection with callback-based approach:
   ```js
   // Approach 1: Call turnstile.execute() then inject token
   if (window.turnstile) {
       const callback = document.querySelector('[data-sitekey]')?.getAttribute('data-callback');
       if (callback && typeof window[callback] === 'function') {
           window[callback](token);
       }
       // Set the hidden response textarea
       const textarea = document.querySelector('input[name="cf-turnstile-response"], textarea[name="cf-turnstile-response"]');
       if (textarea) textarea.value = token;
   }
   ```

2. Fallback: submit form if Turnstile is inside a form:
   ```js
   const form = document.querySelector('[data-sitekey]')?.closest('form');
   if (form) form.submit();
   ```

3. Add post-injection verification:
   - Wait 3s after injection
   - Check if Turnstile widget shows success state (checkmark)
   - Log success/failure with redacted URL

4. Add Turnstile in iframe detection:
   ```python
   for frame in page.frames:
       if frame == page.main_frame:
           continue
       turnstile_el = await frame.query_selector('[data-sitekey], .cf-turnstile')
       if turnstile_el:
           # Solve using frame.url() as page_url
   ```

**Tests:**
- Unit: mock Turnstile callback is invoked with token
- Unit: hidden textarea receives token value
- Unit: iframe frame scanning finds widget in child frame
- Integration (mock): full detect → solve → inject → verify flow

---

### C03: CAPTCHA Solver API Fix

**Scope:** `app/utils/captcha_solver.py`

**Changes:**

1. Fix 2Captcha createTask response parsing:
   ```python
   if self.provider == "2captcha":
       task_id = data.get("requestId") or data.get("taskId")
   else:
       task_id = data.get("taskId")
   ```

2. Fix 2Captcha getTaskResult payload:
   ```python
   if self.provider == "2captcha":
       poll_payload = {"key": self.api_key, "requestId": task_id, "json": 1}
   else:
       poll_payload = {"clientKey": self.api_key, "taskId": task_id}
   ```

3. Fix Capsolver response field for reCAPTCHA:
   ```python
   # Capsolver returns solution.gRecaptchaResponse
   # 2Captcha returns request.token or solution.token
   if self.provider == "2captcha":
       return result_data.get("solution", {}).get("token")
   else:
       return result_data.get("solution", {}).get("gRecaptchaResponse")
   ```

4. Add retry on solve failure (1 retry with 5s delay)

5. Add Capsolver TurnstileTaskProxyless type (more reliable than TurnstileTask)

6. Add response status logging (without payload):
   ```python
   logger.info("Captcha provider status: %s", status)
   ```

**Tests:**
- Unit: 2Captcha createTask returns requestId correctly
- Unit: Capsolver createTask returns taskId correctly
- Unit: getTaskResult payload uses correct field per provider
- Unit: retry logic triggers on first failure
- Unit: no raw API response in logs

---

### C04: Cloudflare Challenge Handler Enhancement

**Scope:** `app/utils/stealth_browser.py`

**Changes:**

1. Detect challenge type from page content:
   - Managed challenge: `cf-mitigated: challenge` header or "Checking your browser" title
   - Interactive challenge: presence of Turnstile widget after managed phase
   - JS challenge: `__cf_chl_js_tk` in page source

2. Multi-strategy managed challenge handling:
   - Strategy 1: Wait 45s for auto-resolve (current)
   - Strategy 2: Reload page (current)
   - Strategy 3: Navigate to same URL fresh (new tab, copy cookies, close old)
   - Strategy 4: Clear cookies for domain, reload (forces fresh challenge)

3. Challenge attempt tracking:
   - Max 3 challenge cycles per URL
   - Log attempt count and strategy used (redacted)
   - Return typed error `USER_VERIFICATION_REQUIRED` after all strategies fail

4. Post-challenge content validation:
   - After challenge resolves, verify page has real content (not challenge HTML)
   - Use DOM content validator from P12 to check content length/boilerplate ratio

**Tests:**
- Unit: managed challenge detected by title pattern
- Unit: interactive challenge detected by Turnstile presence
- Unit: 3 retry strategies execute in sequence
- Unit: typed error returned after all strategies fail
- Unit: post-challenge content validation rejects stub HTML

---

### C05: Proxy Pool Enhancement

**Scope:** `app/utils/proxy_pool.py`, `app/ingestion/source_adapters.py`

**Changes:**

1. Add automatic retry with different proxy on failure:
   - When `fetch_with_proxy` fails with connection/timeout error
   - Mark current proxy unhealthy
   - Retry with next healthy proxy
   - Max 3 proxy retries before falling back to direct

2. Add SOCKS5 support:
   - Parse `socks5://` prefix in PROXY_LIST
   - Pass `proxies={"http": "...", "https": "..."}` format

3. Add proxy health check thread (optional, env-gated):
   - Periodically test each proxy against a known endpoint
   - Update health status proactively
   - `PROXY_HEALTH_CHECK_INTERVAL` env var (default: disabled)

4. Add proxy authentication via Connect headers for HTTP proxies requiring auth

**Tests:**
- Unit: round-robin skips unhealthy proxies
- Unit: retry with next proxy on connection failure
- Unit: SOCKS5 URL parsed correctly
- Unit: health check marks dead proxies
- Regression: empty PROXY_LIST skips all proxy logic

---

## Implementation Order

```
C03 (CAPTCHA API fix)     — smallest, fixes silent failures
    ↓
C01 (Fingerprint stealth) — highest impact, fixes detection
    ↓
C02 (Turnstile injection) — depends on C01 for reliable testing
    ↓
C04 (Cloudflare handler)  — depends on C02 for interactive challenge
    ↓
C05 (Proxy pool)          — independent, lowest priority
```

## Boundaries

- No new production dependencies (use vanilla JS injection, not playwright-stealth)
- No CAPTCHA farming / browser-based solving (API solver only)
- No residential proxy services (manual PROXY_LIST only)
- All changes must have tests (mock Playwright, no real browser/API calls)
- No cookie/token/HTML/chapter text in logs
- No changes to router/API/SSE/scheduler outside stealth scope
- Backward compatible: `fetch_with_stealth_sync` API unchanged
- `STEALTH_BROWSER_ENABLED=0` still disables everything

## Expected Score After All Milestones: 8.5/10

| Area | Current | Target |
|------|---------|--------|
| Fingerprint | 4/10 | 8/10 |
| Cloudflare | 7/10 | 8.5/10 |
| CAPTCHA solve | 4/10 | 7.5/10 |
| Proxy | 7/10 | 8/10 |
| Cookie/Session | 9/10 | 9/10 |
| Reliability | 8/10 | 9/10 |
