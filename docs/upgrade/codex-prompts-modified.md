# Bộ prompt Codex (đã sửa) — Nâng cấp Novel-TNN giữ nguyên bypass

## Thay đổi so với bản gốc

| Phần | Bản gốc | Bản sửa |
|------|---------|---------|
| Ranh giới #2 | Cấm CAPTCHA evasion, fingerprint, proxy, solver | Gỡ bỏ. Thay bằng: giữ ổn định browser session hiện có |
| P01 FetchMethod | Chỉ direct_http, browser_session, user_verification_required | Thêm stealth_browser_headed |
| P08 | Thay persistent context bằng SessionManager, khóa solver | Giữ persistent context, cải thiện lifecycle quanh nó |
| P11 | Xóa "Auto-bypass" khỏi UI | Giữ badge, đổi copy chuyên nghiệp hơn |
| P16 | Verify bypass đã bị gỡ | Verify bypass vẫn ổn định |

---

## Ranh giới bắt buộc (đã sửa)

1. Mục tiêu là tăng độ tin cậy, an toàn, khả năng phục hồi, quan sát vận hành và UX của pipeline nhập nội dung.
2. Giữ nguyên và ổn định browser session management hiện có (launch_persistent_context). Cải thiện lifecycle, isolation và recovery quanh nó, không thay thế cơ chế hoạt động.
3. Chỉ tự động hóa các nguồn/trang mà chủ hệ thống có quyền truy cập và được phép tự động hóa.
4. Không ghi cookie, token, HTML đầy đủ, nội dung chương, API key hoặc PII vào log.
5. Không làm migration phá hủy dữ liệu. Mọi migration phải có đường rollback hoặc hướng dẫn rollback rõ ràng.
6. Không thêm dependency production nếu chưa kiểm tra dependency hiện có và chưa ghi rõ lý do.
7. Không thay đổi ngoài phạm vi prompt; không refactor mỹ thuật không liên quan.
8. Mọi thay đổi phải có test. Không được báo "hoàn thành" nếu chưa chạy các lệnh kiểm thử phù hợp.

---

## P00 — Không đổi

```text
Bạn đang làm việc trong repository Novel-TNN. Đây là bước P00 của chương trình nâng cấp. Chỉ khảo sát, khóa baseline và tạo tài liệu hướng dẫn; không triển khai chức năng production mới.

Mục tiêu:
1. Đọc toàn bộ cấu trúc repository, đặc biệt:
   - app/ingestion/source_adapters.py
   - app/utils/stealth_browser.py
   - app/utils/captcha_solver.py
   - app/utils/proxy_pool.py
   - app/utils/cookie_store.py
   - app/utils/asyncio_bridge.py
   - app/mobile_api/routers/import_routes.py
   - app/mobile_api/schemas/
   - app/mobile_api/services/pipeline_service.py
   - web/src/api/
   - web/src/components/ImportPanel.tsx
   - tests/
   - cấu hình DB, migration, Docker/Compose, pyproject/requirements, package.json và CI.
2. Xác định chính xác framework DB/ORM, cách migration, cách chạy backend/frontend, lệnh test/lint/typecheck/build và entrypoint production.
3. Chạy baseline hiện tại. Tài liệu tham chiếu nói có 33 backend tests pass; hãy xác minh con số thực tế thay vì tin mặc định.
4. Tạo hoặc cập nhật AGENTS.md ở root, ngắn gọn và chính xác, gồm:
   - sơ đồ repo và các thư mục quan trọng;
   - lệnh setup, test, lint, typecheck, build;
   - quy ước code/migration/API;
   - quy tắc một prompt = một PR;
   - yêu cầu test và báo cáo kết quả;
   - quy tắc không ghi secret/cookie/nội dung vào log;
   - yêu cầu giữ backward compatibility trừ khi prompt nói rõ khác đi.
5. Tạo docs/upgrade/PLAN.md là tài liệu sống, có:
   - mục tiêu, non-goals và ranh giới an toàn;
   - kiến trúc hiện tại được xác minh từ code;
   - kiến trúc đích;
   - các milestone P00–P16;
   - bảng phụ thuộc giữa milestone;
   - decision log;
   - test matrix;
   - mục "current status" để mỗi PR sau cập nhật.
6. Tạo docs/upgrade/BASELINE.md ghi:
   - commit hiện tại;
   - lệnh đã chạy;
   - số test pass/fail/skip;
   - lỗi lint/typecheck/build hiện hữu;
   - các điểm khác biệt giữa tài liệu và code thực tế;
   - rủi ro kỹ thuật phát hiện được.

Ranh giới:
- Không sửa logic fetch, browser, import, API hoặc frontend trong P00.
- Chỉ sửa tài liệu/cấu hình hướng dẫn nếu cần.
- Không cài dependency mới.

Tiêu chí nghiệm thu:
- AGENTS.md dùng đúng lệnh thực tế của repo, không chứa placeholder.
- PLAN.md đủ để một Codex task mới hiểu chương trình mà không cần lịch sử chat.
- Baseline tests đã thực sự được chạy và kết quả được ghi nguyên văn/tóm tắt chính xác.

Kết thúc bằng báo cáo:
- files changed;
- commands run và kết quả;
- baseline pass/fail;
- các quyết định kiến trúc cần giữ cho P01;
- dừng lại, không thực hiện P01.
```

---

## P01 — Đã sửa: FetchMethod bao gồm stealth_browser_headed

```text
Thực hiện P01 trong docs/upgrade/PLAN.md. Đọc AGENTS.md và trạng thái P00 trước khi sửa code. Chỉ làm fetch contract và error taxonomy; không làm retry, queue, concurrency, SSE hoặc parser DOM trong PR này.

Mục tiêu:
1. Loại bỏ side channel thread-local dùng bởi _reset_bypass_info/_set_bypass_info/_get_bypass_info.
2. Tạo hợp đồng kết quả fetch có kiểu:
   - FetchMethod: direct_http, stealth_browser_headed, browser_session, user_verification_required.
   - FetchResult bất biến, chứa tối thiểu:
     html, requested_url, final_url, method, status_code, attempts,
     elapsed_ms, bytes_received, cookies_refreshed, cache_hit.
   - FetchErrorCode có các mã tối thiểu:
     invalid_url, source_not_allowed, private_network_blocked,
     connect_timeout, read_timeout, rate_limited, source_unavailable,
     user_verification_required, content_not_found, content_invalid,
     parse_failed, duplicate, import_failed, cancelled, internal_error.
   - Exception/lỗi có code, retryable, message an toàn, http_status tùy chọn và details đã lọc secret.
3. Chuyển các call site nội bộ sang dùng FetchResult trực tiếp.
4. Nếu repository có caller bên ngoài cần chuỗi HTML, giữ một compatibility wrapper trả result.html và đánh dấu deprecated; wrapper không được dùng thread-local.
5. SourcePreview/preview API lấy bypass/fetch metadata trực tiếp từ FetchResult, không đọc trạng thái toàn cục.
6. Giữ nguyên hành vi browser session hiện có; chỉ thay hợp đồng dữ liệu trả về.

Test bắt buộc:
- direct HTTP result chứa metadata đúng;
- stealth_browser_headed result chứa method đúng;
- error mapping giữ code/retryable;
- hai fetch chạy đồng thời không rò metadata sang nhau;
- compatibility wrapper vẫn hoạt động nếu được giữ;
- toàn bộ baseline tests vẫn pass.

Tiêu chí nghiệm thu:
- Không còn thread-local bypass state trong production code.
- Không có code frontend/backend phải parse chuỗi lỗi để biết loại lỗi ở các đường đã chuyển đổi.
- API cũ không bị phá vỡ ngoài các field mới có default/backward-compatible.
- Không thêm retry hoặc concurrency ở P01.

Cập nhật docs/upgrade/PLAN.md với quyết định và trạng thái P01. Kết thúc bằng files changed, tests đã chạy, kết quả, backward-compatibility notes và dừng lại.
```

---

## P02 — Không đổi (URL/SSRF security)

```text
Thực hiện P02 sau khi P01 đã merge. Chỉ tập trung vào URL security và resource limits cho fetch. Không triển khai job queue, retry hoặc frontend.

Mục tiêu:
1. Tạo module policy URL dùng chung, ví dụ app/security/url_policy.py hoặc vị trí phù hợp với repo.
2. Áp dụng cho URL preview, URL chương, redirect và browser navigation:
   - chỉ cho http/https;
   - cấm userinfo trong URL;
   - chỉ cho port 80/443 trừ cấu hình allowlist rõ ràng;
   - canonicalize hostname, IDNA và URL;
   - URL chương phải thuộc domain mà adapter đã khai báo;
   - giới hạn số redirect;
   - validate lại từng redirect target;
   - resolve DNS bằng resolver có thể inject trong test;
   - chặn loopback, private, link-local, multicast, unspecified và reserved IP;
   - chặn hostname/IP metadata phổ biến bằng policy tổng quát;
   - kiểm tra lại IP sau redirect; ghi rõ giới hạn còn lại đối với DNS rebinding.
3. Direct HTTP phải tắt redirect tự động và xử lý redirect thủ công qua policy.
4. Dùng streaming/giới hạn byte để không tải response vô hạn; thêm cấu hình max response bytes, connect timeout, read timeout và total timeout.
5. Chỉ chấp nhận content type phù hợp cho HTML/text.
6. Lỗi phải map vào FetchErrorCode từ P01 và không làm lộ URL chứa credential/query nhạy cảm trong message/log.
7. Browser entrypoint phải validate top-level URL trước khi page.goto.

Test bắt buộc, không gọi Internet thật:
- localhost, 127.0.0.1, ::1, RFC1918, link-local, reserved bị chặn;
- public IP giả lập được cho phép;
- redirect public -> private bị chặn;
- redirect sang domain ngoài adapter bị chặn;
- credential URL và port lạ bị chặn;
- response vượt byte limit bị dừng;
- quá nhiều redirect bị lỗi có kiểu;
- resolver/session được fake hoặc mock để test deterministic;
- baseline tests vẫn pass.

Tiêu chí nghiệm thu:
- Mọi đường nhập URL từ client đều đi qua cùng policy server-side.
- Không dựa vào validation frontend.
- Có config mặc định an toàn và tài liệu biến môi trường.

Cập nhật PLAN.md, báo cáo tests và dừng lại.
```

---

## P03 — Không đổi (text_length fix)

```text
Thực hiện P03. Phạm vi là kết quả import theo chương, bug text_length và metadata; không làm idempotency DB, job queue hoặc parser DOM đầy đủ.

Mục tiêu:
1. Theo dõi luồng text từ extraction -> normalize hiện có -> import_from_text -> DB.
2. Sửa URLFetchChapterResult.text_length để phản ánh chính xác độ dài text đã normalize và thực sự được lưu.
3. Chuẩn hóa importer trả một result có kiểu, chứa tối thiểu:
   book_id, chapter_id, stored_text_length, content_hash,
   created_or_updated/operation, warnings.
4. Mở rộng per-chapter API result theo cách backward-compatible với:
   error_code, retryable, attempts, fetch_method, elapsed_ms,
   started_at, finished_at, content_hash, operation.
5. Giữ field success/error cũ trong giai đoạn chuyển tiếp.
6. Chuẩn hóa Unicode/whitespace tối thiểu tại một hàm duy nhất trước khi tính length/hash.
7. Đảm bảo không log hoặc trả nội dung chương trong API metadata.

Test bắt buộc:
- text_length bằng đúng độ dài stored text;
- normalization làm length/hash deterministic;
- chapter trống hoặc chỉ whitespace trả content_invalid;
- importer failure trả import_failed và metadata hợp lệ;
- schema cũ vẫn deserialize/serialize tương thích;
- baseline tests pass.

Cập nhật PLAN.md và dừng sau báo cáo.
```

---

## P04 — Không đổi (Idempotency)

```text
Thực hiện P04. Trước tiên xác định ORM/database/migration framework thực tế.

Mục tiêu:
1. Thiết kế canonical identity cho chương theo dữ liệu nguồn thực tế:
   source/adapter_id + canonical book identity + canonical chapter URL hoặc source chapter ID.
2. Thêm trường cần thiết và migration không phá dữ liệu:
   canonical_source_url/canonical_chapter_url,
   content_hash, source_updated_at, operation/revision.
3. Thêm unique constraint/index phù hợp để cùng một chương không được tạo hai lần.
4. Implement import/upsert semantics rõ ràng:
   - identity mới -> created;
   - identity cũ + hash không đổi -> skipped_duplicate;
   - identity cũ + hash đổi -> updated;
   - lỗi unique race phải được xử lý như idempotent result, không thành 500.
5. Việc tìm/tạo book và lưu chapter phải nằm trong transaction hợp lý.
6. Canonicalization dùng module URL policy từ P02.
7. Tạo data backfill an toàn cho record cũ.
8. Viết hướng dẫn migration và rollback.

Test bắt buộc:
- import cùng chapter hai lần không tạo duplicate;
- hai import concurrent cùng identity chỉ tạo một row;
- same identity/same hash -> skipped;
- same identity/new hash -> update đúng;
- transaction rollback khi import lỗi;
- migration chạy trên DB test có dữ liệu cũ;
- baseline tests pass.

Cập nhật PLAN.md và dừng lại.
```

---

## P05 — Không đổi (Job persistence models)

```text
Thực hiện P05. Chỉ xây model/repository/state machine bền vững; chưa chạy worker và chưa thêm API SSE.

Mục tiêu:
1. Thêm persistent models/tables theo framework DB hiện tại:
   ImportJob:
   id, tenant/user owner, source, source_url, book_id nullable,
   status, total, created_at, started_at, finished_at,
   cancel_requested_at, config_snapshot, error_summary.

   ChapterTask:
   id, job_id, canonical URL/identity, chapter_number, title,
   status, stage, attempts, next_attempt_at, error_code, error_message,
   fetch_method, text_length, content_hash, elapsed_ms,
   started_at, finished_at, book_id, chapter_id.

   ImportJobEvent:
   monotonic id/sequence, job_id, task_id nullable, event_type,
   payload JSON đã lọc, created_at.
2. Định nghĩa enums/state transitions:
   Job: queued, running, succeeded, partially_succeeded, failed, cancelled.
   Task/stage: queued, fetching, waiting_retry, parsing, validating,
   importing, succeeded, failed, cancelled, user_verification_required.
3. Tạo repository/service thuần dữ liệu với compare-and-set/transaction.
4. Counters của job phải được tính/đồng bộ từ task một cách nhất quán.
5. Event append phải xảy ra cùng transaction với transition quan trọng.
6. Tạo migration và rollback note.
7. Không lưu HTML/content/cookie/token trong config_snapshot hoặc event payload.

Test bắt buộc:
- allowed và forbidden transitions;
- task terminal không quay lại running trừ operation retry;
- cancel request idempotent;
- counters chính xác;
- event sequence tăng ổn định;
- owner/tenant isolation;
- migration tests và baseline tests.

Cập nhật PLAN.md và dừng lại.
```

---

## P06 — Không đổi (Worker core)

```text
Thực hiện P06 trên các model của P05. Mục tiêu là job service và worker core chạy tuần tự trước; chưa tối ưu concurrency/retry ở PR này.

Mục tiêu:
1. Tạo ImportJobService có các operation:
   create_job, enqueue_job, get_job, request_cancel,
   retry_failed_tasks, recover_interrupted_jobs.
2. Tạo worker/scheduler dùng DB làm source of truth.
3. Worker phải claim task atomically để hai worker không xử lý cùng một task.
4. P06 chạy task tuần tự hoặc concurrency=1.
5. Pipeline từng task phải emit/persist stage events:
   fetching -> parsing -> validating -> importing -> terminal.
6. Cooperative cancellation:
   - job nhận cancel_requested;
   - task chưa chạy chuyển cancelled;
   - task đang chạy kiểm tra cancel giữa các stage;
   - operation cancel idempotent.
7. Recovery khi process restart:
   - task đang running nhưng mất lease được requeue hoặc fail;
   - không duplicate import nhờ P04;
   - ghi event recovery.
8. retry_failed_tasks chỉ reset task được phép retry.
9. Dùng fake pipeline trong unit tests, không gọi nguồn thật.

Test bắt buộc:
- create/enqueue/run job đến success;
- partial failure;
- cancel trước khi chạy và cancel giữa stage;
- process crash/expired lease rồi recover;
- hai worker cạnh tranh chỉ một worker claim;
- retry failed không chạy lại success;
- restart không duplicate dữ liệu;
- baseline tests pass.

Cập nhật PLAN.md và dừng lại.
```

---

## P07 — Không đổi (Retry + concurrency)

```text
Thực hiện P07. Nâng worker P06 thành pipeline có bounded concurrency, retry có phân loại và import có trật tự.

Mục tiêu:
1. Tạo RetryPolicy dựa trên FetchErrorCode:
   Retryable mặc định: connect_timeout, read_timeout, rate_limited,
   một số source_unavailable/5xx và browser crash một lần.
   Non-retryable mặc định: invalid_url, source_not_allowed,
   private_network_blocked, user_verification_required,
   parse_failed với cùng content, duplicate, cancelled.
2. Exponential backoff + jitter, tôn trọng Retry-After, có total time budget/task.
3. Inject clock/sleep/random để test deterministic.
4. Bounded concurrency có semaphore/queue:
   - direct HTTP global mặc định 4;
   - direct HTTP per-host mặc định 1 hoặc 2;
   - browser global mặc định 1;
   - DB import serialized.
5. Fetch/parse có thể hoàn thành ngoài thứ tự, nhưng importer phải lưu theo chapter_number.
6. Một task fail không được hủy các task độc lập khác.
7. Backpressure: queue có max size.
8. Cancellation phải ngắt việc chờ retry.
9. Ghi attempts, next_attempt_at, elapsed_ms và event retry.

Test bắt buộc:
- max concurrency quan sát được;
- per-host limit hoạt động;
- retry đúng mã lỗi;
- backoff/jitter deterministic;
- total time budget kết thúc task;
- chapter hoàn thành ngoài thứ tự nhưng DB import đúng thứ tự;
- cancel trong backoff;
- failure isolation;
- không gọi Internet thật;
- full backend tests pass.

Cập nhật PLAN.md và dừng lại.
```

---

## P08 — ĐÃ SỬA: Giữ persistent context, cải thiện lifecycle

```text
Thực hiện P08. Cải thiện lifecycle và isolation của browser session hiện có. Giữ nguyên launch_persistent_context làm cơ chế hoạt động chính.

Mục tiêu:
1. Tạo BrowserSessionManager wrapper quanh launch_persistent_context hiện có:
   - quản lý lifecycle (init lazy, idle TTL, cleanup shutdown);
   - health check và restart khi browser crash;
   - max pages/requests trước restart;
   - không start/stop Playwright process cho từng chapter.
2. Giữ persistent context profile hiện có làm cơ chế hoạt động.
3. Thêm per-session lock để không nhiều task cùng điều khiển một page không an toàn; dùng browser concurrency limit từ P07.
4. Cookie/storage state:
   - đọc expiry thật của cookie;
   - clear/rotate state khi invalid/corrupt;
   - ghi atomic bằng temp + rename;
   - permission chặt (0600);
   - không commit, không log.
5. Lifecycle:
   - init lazy;
   - idle TTL;
   - health check định kỳ;
   - restart khi browser process crash;
   - cleanup khi shutdown.
6. Giữ nguyên cơ chế Cloudflare challenge handling hiện có (wait + reload).
7. Tắt download, đóng popup không mong muốn và giới hạn top-level navigation theo URL policy P02.
8. Giữ compatibility wrapper fetch_with_stealth_sync cho caller cũ, nhưng wrapper phải dùng manager mới.

Test bắt buộc:
- cùng session được serialize đúng qua per-session lock;
- atomic save/corrupt state recovery;
- expiry handling;
- browser crash restart;
- cleanup shutdown;
- mock Playwright cho unit tests;
- baseline tests pass.

Tiêu chí nghiệm thu:
- Không launch một browser process mới cho mỗi chapter.
- Browser concurrency mặc định vẫn là 1.
- Cơ chế persistent context hiện có vẫn hoạt động.
- Lifecycle được quản lý thay vì fire-and-forget.

Cập nhật PLAN.md và dừng lại.
```

---

## P09 — Không đổi (Job API + SSE)

```text
Thực hiện P09. Expose job service qua FastAPI và thêm SSE. Không sửa UI trong PR này.

Endpoint mục tiêu:
- POST /api/import/jobs -> tạo/enqueue job, trả 202 + job_id.
- GET /api/import/jobs/{job_id} -> snapshot job + task summaries.
- GET /api/import/jobs/{job_id}/events -> SSE.
- POST /api/import/jobs/{job_id}/cancel.
- POST /api/import/jobs/{job_id}/retry-failed.

Yêu cầu:
1. Validate ownership/tenant trên mọi endpoint.
2. Request create job dùng chapter selection hiện có, canonicalize URL và enforce quota cơ bản max chapters/job.
3. SSE:
   - event id là sequence persisted từ ImportJobEvent;
   - event/type/data có schema ổn định;
   - hỗ trợ Last-Event-ID hoặc tham số cursor để reconnect;
   - gửi keepalive;
   - kết thúc stream khi job terminal;
   - disconnect client không hủy job;
   - payload không chứa HTML/text/cookie/secret.
4. Transport: dùng fetch streaming với AbortController (hỗ trợ auth headers, cancel được).
5. GET snapshot là source of truth để client reconcile.
6. Cancel/retry idempotent.
7. Route cũ /api/import/url/fetch phải tiếp tục hoạt động và sử dụng cùng job engine.
8. Cập nhật Pydantic/OpenAPI schemas.
9. Map errors có kiểu sang HTTP status phù hợp.

Test bắt buộc:
- create/get/cancel/retry;
- ownership isolation;
- SSE nhận đúng thứ tự event;
- reconnect từ Last-Event-ID/cursor;
- client disconnect không hủy job;
- terminal stream behavior;
- compatibility route cho request cũ;
- API validation/quota;
- full backend tests pass.

Cập nhật PLAN.md và dừng lại.
```

---

## P10 — Không đổi (Frontend client + hook)

```text
Thực hiện P10 ở frontend. Chỉ xây types, API client và state hook/service; chưa redesign ImportPanel lớn.

Mục tiêu:
1. Bổ sung TypeScript types cho ImportJob, ChapterTask, enums/status, JobEvent và request/response mới.
2. Bổ sung API client methods:
   createImportJob, getImportJob, cancelImportJob, retryFailedTasks,
   subscribeJobEvents (dùng fetch streaming + AbortController).
3. Tạo useImportJob hook/state machine:
   idle, creating, queued, running, terminal, reconnecting, error.
4. Reconcile event bằng snapshot; event phải idempotent.
5. Auto reconnect có backoff và cursor/Last-Event-ID.
6. Polling fallback khi SSE không khả dụng.
7. Persist job_id vừa đủ để refresh trang có thể resume.
8. Mapping error_code -> domain state.
9. Giữ API client cũ cho compatibility.

Test bắt buộc:
- typecheck;
- reducer/hook transitions;
- duplicate/out-of-order event handling;
- reconnect và snapshot reconcile;
- polling fallback;
- cancel/retry client calls;
- refresh/resume state;
- lint và build.

Cập nhật PLAN.md và dừng lại.
```

---

## P11 — ĐÃ SỬA: Giữ bypass badge, cải thiện UX

```text
Thực hiện P11. Chuyển ImportPanel từ request blocking sang job UX dùng useImportJob P10.

Mục tiêu UI:
1. Sau khi chọn chương, nút tải tạo job và chuyển sang section tiến độ mà không block request.
2. Job summary hiển thị total, queued, running, succeeded, failed, cancelled và elapsed time.
3. Từng chương hiển thị stage/status, attempts, fetch_method, text_length, operation và error.
4. Actions:
   - cancel job;
   - retry failed;
   - resume sau refresh bằng job_id;
   - quay lại danh sách sách sau terminal.
5. Danh sách chapter lớn:
   - pagination hoặc virtualization;
   - chọn khoảng chapter;
   - select all đúng tập hiển thị;
   - không render hàng nghìn checkbox cùng lúc.
6. Fetch method badge hiển thị:
   - direct_http -> "Kết nối trực tiếp";
   - stealth_browser_headed -> "Trình duyệt ẩn danh";
   - browser_session -> "Phiên trình duyệt";
   - user_verification_required -> "Cần xác minh thủ công".
7. Accessibility/mobile:
   - button disabled/loading rõ;
   - aria-live cho progress;
   - focus management khi error/terminal;
   - touch targets và responsive layout.
8. Nếu SSE rớt, hiển thị reconnecting nhưng không đánh job là failed.
9. Giữ preview/chapter selection hiện có.

Test bắt buộc:
- create job flow;
- progress event updates;
- partial success;
- cancel;
- retry failed;
- reconnect/resume after reload;
- pagination/virtualization selection correctness;
- accessibility checks;
- lint, typecheck, tests, production build.

Cập nhật PLAN.md và dừng lại.
```

---

## P12 — Không đổi (DOM parser framework)

```text
Thực hiện P12. Tạo framework parser DOM và migrate một adapter đại diện là 69shuba.

Mục tiêu:
1. Kiểm tra dependency parser HTML hiện có. Tái sử dụng nếu phù hợp.
2. Tạo adapter contract rõ ràng:
   domain policy, canonicalize_url, parse_preview, parse_chapter,
   normalize/cleanup, validate_content, adapter_version.
3. Tạo selector config có danh sách fallback cho title, author, description,
   chapter links, chapter content và remove selectors.
4. DOM pipeline:
   parse HTML -> remove script/style/nav/ads/breadcrumb -> select content
   -> chuyển block thành paragraph -> Unicode normalization
   -> whitespace cleanup -> validation -> content hash.
5. Content validator phát hiện:
   - challenge/error page trả 200;
   - content rỗng/quá ngắn;
   - nhầm chapter list thành chapter content;
   - boilerplate ratio bất thường.
6. Migrate 69shuba family domains sang parser DOM mới.
7. Giữ regex parser làm fallback có telemetry.
8. Dùng fixture cục bộ đã sanitize; default tests không fetch live.

Test fixture tối thiểu cho 69shuba:
- preview bình thường;
- chapter bình thường;
- relative/absolute chapter links;
- Unicode/entity;
- nav/ads/breadcrumb được loại bỏ;
- 404;
- challenge page status 200;
- thiếu selector chính nhưng fallback hoạt động;
- content quá ngắn/invalid.

Cập nhật PLAN.md và dừng lại.
```

---

## P13 — Không đổi (Migrate adapters)

```text
Thực hiện P13. Migrate toàn bộ adapter còn lại sang contract/parser framework P12.

Phạm vi nguồn theo code thực tế; tài liệu dự kiến có 17 domain:
69shuba.com, 69shuba.cx, 69shux.com, 69shumi.com, 69shumi.net,
fanqienovel.com, qidian.com, book.qq.com, jjwxc.net, hetushu.com,
ixdzs.com, ixdzs8.com, 17k.com, 22biqu.com, 52shuku.net,
novel543.com, xbanxia.com.
Hãy xác minh registry thật và báo khác biệt.

Mục tiêu:
1. Mỗi adapter có version, domain policy, selectors, canonicalization, cleanup và validation riêng.
2. Mỗi adapter có fixture cục bộ tối thiểu.
3. Tạo contract test parametrized chạy cho toàn bộ adapter.
4. Không gọi site live trong default CI.
5. Regex fallback chỉ giữ nơi có fixture chứng minh DOM parser chưa đủ.
6. Cập nhật docs về cách thêm adapter mới.

Test/quality gates:
- toàn bộ adapter contract tests pass;
- baseline tests pass;
- no network trong unit tests;
- lint/typecheck backend.

Cập nhật PLAN.md và dừng lại.
```

---

## P14 — Không đổi (Observability)

```text
Thực hiện P14. Bổ sung quan sát vận hành và bảo vệ tải.

Mục tiêu:
1. Structured logging với correlation fields:
   job_id, task_id, adapter_id, adapter_version, fetch_method,
   error_code, attempts, elapsed_ms, response_bytes,
   parsed_text_length, operation, worker_id.
2. Redaction bắt buộc:
   không cookie, token, API key, query nhạy cảm, HTML hoặc chapter text;
   sanitize exception và URL trước log.
3. Metrics tối thiểu:
   request/job/task counts;
   success/failure/retry/cancel;
   P50/P95 latency;
   response bytes/text length;
   browser launches/restarts;
   parse failure theo adapter_version;
   duplicate/update counts;
   active jobs/queue depth.
4. Circuit breaker theo adapter + fetch method:
   closed/open/half-open;
   threshold, window, cooldown qua config;
   chỉ đếm lỗi phù hợp;
   có event/log/metric khi chuyển trạng thái.
5. Quotas server-side:
   max chapters/job;
   max active jobs/user;
   max retries/task;
   max bytes/chapter;
   max total job duration.
6. Thêm source health endpoint/admin view có auth.
7. Viết runbook alert thresholds ban đầu.

Test bắt buộc:
- redaction tests;
- metric labels không có cardinality không kiểm soát;
- circuit breaker open/half-open/recover;
- quotas reject đúng;
- health endpoint ownership/auth;
- full backend/frontend checks.

Cập nhật PLAN.md và dừng lại.
```

---

## P15 — Không đổi (Deployment hardening)

```text
Thực hiện P15. Tách worker/browser khỏi API trong production và thêm deployment hardening.

Mục tiêu:
1. Tạo worker entrypoint riêng dùng job store P05/P06.
2. Cập nhật Dockerfile/Compose:
   - API service riêng;
   - import/browser worker riêng;
   - non-root user;
   - resource limits CPU/memory/pids;
   - healthchecks;
   - graceful shutdown;
   - tmpfs cho browser;
   - không mount secrets không cần thiết vào browser worker.
3. Network/egress:
   - browser worker chỉ outbound HTTP/HTTPS/DNS cần thiết;
   - API/DB/internal services không được browser page truy cập trực tiếp;
   - nếu Compose không enforce đầy đủ, cung cấp cấu hình firewall mẫu.
4. Playwright request interception block subresource request tới private IP.
5. Secrets:
   - không bake .env vào image;
   - document secret injection/rotation.
6. Startup recovery và multi-worker lease phải được kiểm thử.
7. Viết production runbook:
   setup/migrate/rollback, start/stop, health, backup,
   recover stuck job, tune concurrency/quotas, incident response.

Test/verification:
- build images;
- run Compose/test environment;
- API và worker health;
- job survives API restart;
- worker crash rồi recovery không duplicate;
- browser request tới mock private endpoint bị block;
- full test suite.

Cập nhật PLAN.md và dừng lại.
```

---

## P16 — ĐÃ SỬA: Review giữ bypass

```text
Đây là P16, bước review độc lập cuối cùng. Không thêm feature mới. Hãy đọc toàn bộ AGENTS.md, docs/upgrade/PLAN.md, migrations và diff từ P00-P15. Thực hiện review như một maintainer/security reviewer chưa tham gia triển khai.

Mục tiêu:
1. Kiểm tra kiến trúc đích đã đạt:
   typed FetchResult/errors;
   SSRF/redirect/byte limits;
   text_length đúng;
   idempotency/transactions;
   persistent jobs/tasks/events;
   durable worker/recovery;
   bounded concurrency/retry/order;
   BrowserSessionManager lifecycle;
   job API/SSE/cancel/retry;
   frontend resume/progress;
   DOM adapters/fixtures;
   observability/circuit breaker/quotas;
   deployment isolation/egress.
2. Tìm và sửa bug/regression/security issue.
3. Chạy full validation matrix:
   - backend unit/integration tests;
   - frontend tests/lint/typecheck/build;
   - migrations up/down trên DB test;
   - local mock-source E2E;
   - SSE reconnect;
   - cancel/retry/resume;
   - duplicate concurrent import;
   - process crash/recovery;
   - SSRF redirect block;
   - bounded concurrency/load test;
   - log redaction scan.
4. Kiểm tra backward compatibility:
   - route cũ /api/import/url/fetch vẫn hoạt động;
   - browser session vẫn dùng persistent context;
   - fetch_with_stealth_sync wrapper vẫn hoạt động;
   - stealth_browser_headed method vẫn hoạt động.
5. Tạo docs/upgrade/RELEASE_REPORT.md gồm:
   - phạm vi hoàn thành;
   - test commands và kết quả;
   - migration/rollback checklist;
   - known limitations;
   - config defaults;
   - monitoring/alert checklist.

Release gate:
- Không gọi "production ready" nếu có test quan trọng chưa chạy.
- Mọi failure/skip phải được liệt kê trung thực.

Kết thúc bằng:
- executive summary;
- issues found và fixes;
- exact commands/results;
- migration/rollback readiness;
- remaining risks;
- quyết định GO / GO WITH CONDITIONS / NO-GO.
```

---

## Tóm tắt khác biệt

| Prompt | Thay đổi | Lý do |
|--------|----------|-------|
| Ranh giới #2 | Gỡ bỏ cấm bypass | Giữ functionality |
| P01 | Thêm `stealth_browser_headed` vào FetchMethod | Bypass vẫn được track |
| P08 | Giữ persistent context, thêm lifecycle | Không phá cơ chế hoạt động |
| P11 | Đổi badge text, không xóa | Giữ UX thông tin bypass |
| P16 | Verify bypass vẫn hoạt động | Đảm bảo không bị vô hiệu hóa |
