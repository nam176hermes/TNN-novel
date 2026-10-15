# Phương án cải thiện 5 điểm hiệu năng

Ngày thực hiện: 2026-10-02. Cơ sở: [audit hiệu năng](performance-deep-review-2026-10-02.md). Cả 5 phần đã triển khai và đạt tiêu chí đo local bên dưới.

## Phạm vi và nguyên tắc

Thực hiện đủ 5 phần đã được yêu cầu, theo từng bước có kiểm tra. Không dừng ở phương án hoặc một phần triển khai; khi gặp blocker kỹ thuật, tìm nguyên nhân và sửa trong phạm vi. Không dùng kết quả giả lập để chứng nhận provider/GPU thật. Giữ nguyên auth, API cũ, revision, chọn chương, cancellation, chất lượng và publication audio; giữ toàn bộ thay đổi có sẵn.

Không thêm dependency, không sửa CI/global config, không chỉnh/reset dữ liệu operator, không push/deploy. Baseline source và trạng thái worktree được lưu dưới `work/repo-research/novel-tnn/performance-implementation/` (ignored). Chỉ tối ưu các cơ chế đã đo là chậm.

## 1. API tiếp tục phản hồi khi công việc đồng bộ chạy chậm

Trạng thái: **HOÀN TẤT**. Regression concurrency PASS; health phản hồi trong 2–12 ms ở các fixture contention, đạt mục tiêu dưới 100 ms.

- Các route không cần `await` chạy dưới dạng sync endpoint để dùng thread pool sẵn của FastAPI. Upload/SSE/job orchestration giữ async; offload phần đọc/parse/commit đồng bộ bên trong.
- Phạm vi: books/Reader, QA, export văn bản, import paste/file và preview/import ebook trực tiếp. Không đổi response hay cơ chế persistent browser.
- Regression: chặn service bằng event ở worker; health phải phản hồi trước khi service được thả. Kiểm tra cả lỗi/cleanup upload và khóa SQLite.
- Đo lại contention đã có: lookup chậm 400 ms, writer giữ khóa 400 ms, search sách lớn. Mục tiêu health local dưới 100 ms ở các fixture này.

## 2. Tìm kiếm toàn sách

Trạng thái: **HOÀN TẤT**. Regression query/Unicode/revision và abort request cũ PASS; median tìm 2.000 chương là 830 ms với 2 connection/query.

- Dùng hàng chương đã tải khi đọc translation; bỏ N+1 kết nối/query.
- Truyền `AbortSignal` từ Reader xuống API client, hủy request khi query đổi hoặc component unmount; giữ guard chặn kết quả cũ.
- Giữ thứ tự, vị trí, scopes, Unicode/regex/whole-word và lỗi hiện hành. API search đã offload ở bước 1.
- Kiểm tra số query không tăng theo số chương, parity kết quả và nội dung sau sửa chương. Không thêm cache lâu dài hoặc FTS trước khi cần.
- Benchmark cùng fixture 2.000 chương: từ 2.002 query xuống số cố định, median hướng tới dưới 1 giây; health không chờ hết search.

## 3. Raw: giảm request và lượng DOM

Trạng thái: **HOÀN TẤT**. API, stale-response, pagination và batch regression PASS; Raw 500 sách hiển thị trong median 329 ms.

- Thêm API đọc backlog có phân trang, tổng số chương/sách và lọc theo sách; trả chương chưa dịch, không tải chương của mọi sách.
- Cập nhật đồng thời schema/type/client, hook, view và tests. Chặn response cũ ghi đè trang/query mới; giữ refresh sau import/dịch.
- UI render một trang hữu hạn, thống kê dùng tổng server. Dịch batch vẫn chọn đủ chương của sách người dùng yêu cầu, không vô tình chỉ dịch trang hiện tại.
- Mỗi trang tải 50 hàng qua `/api/library/raw`; tổng và hàng dùng cùng SQLite read snapshot. API trả ID chương raw đầu sách để nút mở chương đầu vẫn đúng ở trang sau. Chỉ tải toàn bộ ID raw của một sách khi người dùng chọn dịch batch; chặn gửi batch trùng.
- Regression: nhiều sách, soft-delete, trang cuối/rỗng, chuyển trang nhanh, refresh, mở bàn dịch và batch đúng sách.
- Benchmark 500 sách: một request backlog mỗi trang, tối đa 50 hàng Raw; mục tiêu frame hữu ích dưới 1 giây và không có tác vụ giao diện trên 200 ms ở CPU throttle 4×.

## 4. Reader chương dài

Trạng thái: **HOÀN TẤT** trong phạm vi đo mở chương. 105 Reader regression PASS; 2.000 đoạn hiện nội dung trong median 464 ms (scroll) / 548 ms (phân trang), tác vụ dài nhất của 6 lượt đo là 177 ms.

- Tìm phần CPU thực sự tốn thời gian ở mở chương dài; giữ scroll progressive rendering hiện có.
- Thay surface phân trang toàn chương bằng đo theo từng cửa sổ/đợt, giữ khả năng đi xa/khôi phục vị trí và invalidation khi nội dung/font/viewport đổi.
- Scroll bắt đầu với 32 đoạn rồi tải thêm; pagination đo tối đa 50 đoạn ẩn mỗi đợt và mang trang cuối sang đợt kế để không tạo ngắt trang giả. Chờ ảnh/font của đợt hiện tại đo xong trước khi chuyển đợt. Cache word count theo nội dung và chỉ map đoạn đang hiển thị.
- Không làm sai selection/highlight/annotation, đoạn dài vượt trang, rich media và page-break. Tái sử dụng helper pagination/location hiện có.
- Kiểm tra Reader tests và E2E desktop/mobile; đo lại 80/500/2.000 đoạn với cùng dữ liệu và CPU 4×.
- Mục tiêu chương 2.000 đoạn: hiện nội dung dưới 1 giây, không có task trên 200 ms trong cửa sổ mở chương + 700 ms, cùng cách đo của audit gốc. Không dùng cửa sổ này để kết luận toàn bộ quá trình đọc không còn task dài.

## 5. WAV merge

Trạng thái: **HOÀN TẤT**. 7 regression FFmpeg thật và 30 TTS/API regression PASS; 64 WAV giảm còn 2 process, median 2.556 ms.

- Kiểm tra header WAV PCM mono/16-bit/sample rate phù hợp rồi dùng trực tiếp trong concat. Đầu vào khác vẫn decode bằng FFmpeg.
- Dùng stdlib `wave` và kiểm tra frame cuối tồn tại để không nhận nhầm WAV bị cắt cụt. Không thêm dependency hoặc bỏ decode cho định dạng không phù hợp.
- Không bỏ QA; giữ duration, silence, rate/volume áp dụng một lần, metadata/chapter markers, atomic output và lỗi file hỏng.
- Regression: WAV hợp lệ không bị decode lại; PCM khác định dạng, MP3 và file hỏng vẫn được xử lý đúng. Giữ kiểm tra audio thật bằng FFmpeg/ffprobe.
- Benchmark 64 WAV 1 giây: giảm từ 66 xuống tối đa 2 process và giảm wall-clock trên cùng fixture.

## Kiểm tra cuối và bàn giao

Các bước đã được kiểm tra theo thứ tự và lưu command/exit/log. Aggregate `NOVEL_PIPELINE_IGNORE_DOTENV=1 scripts/verify.sh --with-e2e` đã PASS trên candidate revision 2 với dữ liệu tách riêng. Sau đó chỉ sửa guard ảnh/font và regression Reader; revision 3 chạy lại toàn bộ frontend và E2E desktop/mobile. Hash xác nhận backend, backend tests, dependencies và scripts không đổi giữa hai candidate; giữ đúng receipt backend revision 2, không gắn lại thành một lượt aggregate revision 3.

Kết quả cuối phải gắn với source hash và nêu rõ phần đã đạt, số đo, giới hạn chưa đo. LLM/F5 thật, VRAM và máy Android thật không thuộc qualification local này. Các bước không được gọi hoàn tất chỉ vì test xanh nếu phép đo gốc vẫn cho thấy điểm nghẽn chưa được cải thiện.

## Kết quả thực hiện

Cả năm thay đổi đã triển khai trong mã nguồn. Số dưới đây là median trên fixture local, cùng dữ liệu trước/sau. Backend dùng ASGI transport và filesystem đã warm; giao diện dùng Vite production build, Chromium CPU throttle 4× và API mock; audio dùng FFmpeg thật với WAV tổng hợp. Đây không phải số đo production hoặc tốc độ provider dịch/TTS thật.

| Phần | Trước | Sau | Kết quả |
| --- | --- | --- | --- |
| Health khi lookup dictionary bị giữ 400 ms | 409 ms | 8 ms | Event loop tiếp tục phản hồi; dictionary vẫn phải chờ công việc riêng |
| Health khi SQLite writer giữ khóa 400 ms | 432 ms | 3 ms | Health không bị chặn theo writer; lệnh lưu vẫn chờ khóa đúng semantics |
| Search 2.000 chương | 2.756 ms; 2.002 connection/query | 830 ms; 2 connection/query | Đạt mục tiêu dưới 1 giây, bỏ N+1 |
| Raw 500 sách | 4.381 ms; 500 request chương; 5.000 hàng | 329 ms; 1 request backlog/trang; 50 hàng | Bỏ fan-out chương, giữ batch đủ chương của sách |
| Raw DOM / median task dài nhất | 115.735 node / 5.901 ms | 1.394 node / 96 ms | 9 lượt đo Raw đều dưới 1 giây và task dưới 200 ms |
| Reader 2.000 đoạn, scroll | 910 ms; median task dài nhất 547 ms | 464 ms; median task dài nhất 173 ms | Hiện nội dung dưới 1 giây |
| Reader 2.000 đoạn, phân trang | 1.892 ms; median task dài nhất 1.457 ms | 548 ms; median task dài nhất 165 ms | Tối đa 50 đoạn đo ẩn; 6 lượt 2.000 đoạn đều có task dưới 200 ms |
| Merge 64 WAV | 6.435 ms; 66 process | 2.556 ms; 2 process | Giảm khoảng 60% thời gian; QA vẫn chạy và PASS |

Raw API với 5.000 sách / 10.000 chương raw trả trang 50 hàng trong median 63,4 ms, dùng 1 connection / 2 query. Browser chạy 18 lượt Reader (80/500/2.000 đoạn, hai chế độ, ba lượt mỗi trường hợp) và 9 lượt Raw (20/100/500 sách); không có browser error trong các lượt đo. Chuyển trang Raw được kiểm tra thêm đúng một request và đúng các hàng tiếp theo.

### Kiểm chứng cuối

| Command / kiểm tra | Candidate | Exit | Kết quả |
| --- | --- | --- | --- |
| `NOVEL_PIPELINE_IGNORE_DOTENV=1 scripts/verify.sh --with-e2e` | Revision 2 | 0 | 10 gate PASS: compile, shell, environment, lint/typecheck, 1.390 backend tests, dependencies, 793 frontend tests, build, browser availability, 14 desktop E2E |
| `NOVEL_PIPELINE_IGNORE_DOTENV=1 npm --prefix web run test:e2e -- --project=mobile-chromium` | Revision 2 | 0 | 2 mobile E2E PASS |
| `npm --prefix web run typecheck` | Revision 3 cuối | 0 | Typecheck PASS |
| `npm --prefix web test` | Revision 3 cuối | 0 | 794 tests / 88 files PASS |
| `NOVEL_PIPELINE_IGNORE_DOTENV=1 npm --prefix web run test:e2e` | Revision 3 cuối | 0 | Build PASS trong webServer setup; 16 E2E PASS gồm 14 desktop + 2 mobile |
| Benchmark backend, writer-lock, audio, browser | Backend/audio revision 2; browser revision 3 | 0 | Tất cả tiêu chí đo nêu trên PASS |
| `git diff --check` và kiểm tra link tài liệu | Workspace cuối | 0 | Không có lỗi diff hoặc link local bị thiếu |

Hai case mobile-only được skip có chủ ý trong project desktop và đều PASS trong project mobile. Backend 1.390 tests là lượt chạy trong task này trên revision 2, được giữ làm bằng chứng cho đầu vào backend không đổi; không tuyên bố đã chạy lại full `verify.sh` trên revision 3. Source 734 file của workspace khớp candidate cuối; build assets cũng được lưu hash.

Lượt aggregate đầu thất bại ở setup Raw test do giữ settings cũ sau test reload config: 1.389 PASS / 1 FAIL. Đã sửa test dùng local app và live settings; regression theo thứ tự reload config → Raw/responsiveness 24 PASS, aggregate sau PASS. Auth sản phẩm không bị thay đổi để vượt lỗi. Cảnh báo còn lại là `passlib`/`crypt` deprecation và thông báo môi trường `NO_COLOR`/`FORCE_COLOR`, không có test failure còn tồn tại trong các gate trên.

### File thay đổi và bằng chứng

Task thay đổi 23 file đã có tại thời điểm bắt đầu, thêm 5 test file và tài liệu này (29 file); 706 source file baseline khác giữ nguyên. Worktree vốn có nhiều thay đổi trước task; không revert hoặc gộp chúng thành thành quả của lần tối ưu này.

File triển khai chính: `app/mobile_api/routers/{books,qa,exports,import_routes}.py`, `app/mobile_api/schemas/__init__.py`, `app/mobile_api/services/pipeline_service.py`, `app/database/chapter_repository.py`, `app/services/tts/audio_merger.py`, `web/src/App.tsx`, `web/src/api/{client,types}.ts`, `web/src/state/{useLibraryCatalog,useAppJobs}.ts`, `web/src/components/{RawBacklogView,ReaderView}.tsx`, `web/src/components/reader/useReaderSearch.ts`, `web/src/state/readerLocation.ts`.

Test mới: `tests/test_mobile_api_responsiveness.py`, `tests/test_raw_backlog.py`, `tests/test_reader_search_performance.py`, `web/src/components/reader/useReaderSearch.test.tsx`, `web/src/state/rawBacklog.test.tsx`. Các test audio, Reader, Raw, client, App integration và E2E hiện có cũng đã cập nhật. Tests dùng temp database/file và API/browser fixtures; không truy cập provider thật.

Bằng chứng local (ignored, lưu tại workspace):

- [Receipt cuối và source binding](../work/repo-research/novel-tnn/performance-implementation/final-validation.json), [diff chỉ của task](../work/repo-research/novel-tnn/performance-implementation/implementation.patch).
- [Aggregate revision 2](../work/repo-research/novel-tnn/performance-implementation/verify-final-v2.log), [frontend revision 3](../work/repo-research/novel-tnn/performance-implementation/frontend-v3-tests.log), [typecheck](../work/repo-research/novel-tnn/performance-implementation/frontend-v3-typecheck.log), [build/E2E revision 3](../work/repo-research/novel-tnn/performance-implementation/frontend-v3-e2e.log).
- [Backend benchmark](../work/repo-research/novel-tnn/performance-implementation/backend.json), [writer-lock benchmark](../work/repo-research/novel-tnn/performance-implementation/backend-followup.json), [audio benchmark](../work/repo-research/novel-tnn/performance-implementation/audio.json), [browser benchmark](../work/repo-research/novel-tnn/performance-implementation/browser.json), [build asset hashes](../work/repo-research/novel-tnn/performance-implementation/build-assets.json).

### Giới hạn còn lại

- Một lượt Reader scroll cold với 80 đoạn có task 390 ms. Sáu lượt 2.000 đoạn đều dưới 200 ms; không suy rộng thành mọi cold load đều dưới 200 ms.
- Browser long task chỉ được quan sát trong cửa sổ mở chương + 700 ms, không chứng nhận toàn bộ thời gian đọc/cuộn/đo hết chương.
- Chưa đo LLM/F5/GPU thật, VRAM, thiết bị Android thật hoặc production. Tối ưu WAV merge không chứng nhận chất lượng giọng đọc hay tốc độ inference; bộ QA/normalization/publication hiện có vẫn được giữ và kiểm tra.
- Search vẫn đọc các file chương; nếu sau này sách lớn hơn làm I/O thành nút thắt, cần đo lại trước khi thêm index/cache. Không thêm chúng ở task này vì fixture 2.000 chương đã đạt mục tiêu.

Mã nguồn chưa được deploy; task không sửa hoặc reset database operator. Kiểm tra diff và receipt cuối nằm cùng bộ bằng chứng nêu trên.

