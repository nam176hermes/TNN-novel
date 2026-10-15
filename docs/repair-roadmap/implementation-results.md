# Kết quả triển khai kế hoạch T00–T14

Ngày triển khai: 2026-10-02. Tiếp tục triển khai toàn bộ phần độc lập; không dừng ở từng milestone. Không đánh dấu hoàn tất kiểm chứng provider thật khi thiếu cấu hình hoặc mẫu giọng.

T00–T12 đã hoàn tất phần code trong phạm vi đã chọn và được kiểm tra local. Candidate refactor revision 3 đã pass đủ 10 gate, gồm 1.377 test backend, 787 test frontend và 14 desktop E2E; 2 mobile E2E pass riêng. T13 vẫn `BLOCKED_EXTERNAL` ở kiểm chứng dịch/giọng/model thật; toàn bộ plan chưa được chứng nhận hoàn tất. Receipt candidate 4 bên dưới là lịch sử trước refactor.

## Thay đổi đã triển khai

| Phạm vi | Kết quả và đường code chính |
|---|---|
| T01–T02: dữ liệu, revision | [Chapter publication](../../app/storage/chapter_content.py) ghi artifact phiên bản mới, commit con trỏ DB rồi mới dọn file cũ. Lưu thất bại giữ nguyên dữ liệu đang dùng. [Chapter repository](../../app/database/chapter_repository.py) quản lý revision/hash, nguồn đã làm sạch, QA/audio stale và URL audio có version. Cập nhật API, CLI, daily/retry, dashboard, ebook và nhập nguồn cũ; không xóa dữ liệu legacy hàng loạt. |
| T03–T04: dịch, QA | [LLM transport](../../app/translation/ollama_client.py) dùng một tầng retry, từ chối output rỗng/sai định dạng/bị cắt và lỗi HTTP không thể retry. Cache theo prompt/context/provider hiệu lực. Preset balanced là mặc định cho API không chỉ định provider riêng. [Pipeline](../../app/mobile_api/services/pipeline_service.py) giữ provider/style của batch, QA toàn bộ chunk cuối và QA lại sau rewrite. [QA repository](../../app/database/qa_repository.py) lưu envelope atomically với revision; rule follow-up không che semantic FAIL, job QA nền cũng dùng cùng cơ chế. |
| T05: import | Follow-up dùng chung connection, hai transaction và savepoint từng chương. Lỗi follow-up không hủy các chương đã nhập thành công. |
| T06–T08: TTS | [TTS pipeline](../../app/services/tts/tts_pipeline.py) giữ manifest đầu vào, child job từng chương, retry/resume theo snapshot và chặn công bố sau edit/cancel. Normalizer xử lý số trước dấu câu; QA giải mã MP3/AAC thật; cache chỉ nhận audio có receipt QA khớp bytes/reference. [F5 worker](../../app/services/tts/f5_vietnamese_engine.py) chạy trong process, có deadline, terminate/join khi timeout/cancel, giữ model ấm trong batch và khóa GPU giữa process dùng chung volume. |
| T09: ghép/xuất audio | [Audio merger](../../app/services/tts/audio_merger.py) giải mã về PCM chung, thêm khoảng nghỉ, áp rate/volume/loudness một lần rồi encode. M4B có chapter markers, yêu cầu đủ chương mặc định; bản partial phải chọn rõ và có manifest. Các đường xuất kiểm tra lại snapshot để từ chối thay đổi trong lúc encode. |
| T10–T11: Reader, UX/UI | Thư viện là trang mặc định; Reader hiện bản dịch trước, tải source/dictionary/playlist theo nhu cầu và có một chủ sở hữu bootstrap. Giữ phục hồi offline, revision cache và chặn response cũ ghi đè chương mới. Nhóm các tùy chọn đọc/nghe/từ điển/offline bằng fieldset; menu có cuộn trong khung nhìn và nằm trên thanh công cụ; nút mở sách mobile có vùng bấm riêng đạt 44px. Thêm ô sửa tiêu đề tiếng Việt riêng; hiển thị trạng thái chất lượng bằng tiếng Việt. |
| T12: refactor — DONE | Reader hooks sở hữu progress/sync, marks/transfer, selection/search, dictionary, AI/Xray; Import hooks sở hữu text/file, ebook và URL/catalog; App hooks sở hữu workflow. Book/import/glossary/user/job có repository riêng; `db.py` giữ export tương thích. Book/import commit có service riêng, ebook staging/job chuyển về EbookImportService. Giữ nguyên API, migration, browser session và dependency. |

Các ranh giới đã triển khai trong lần tiếp tục:

| Vị trí | Chủ sở hữu hiện tại |
|---|---|
| [ReaderView.tsx](../../web/src/components/ReaderView.tsx) | View giữ DOM/pagination/resume và composition; state/action tính năng nằm trong [reader hooks](../../web/src/components/reader/useReaderMarks.ts). |
| [ImportPanel.tsx](../../web/src/components/ImportPanel.tsx) | Shared target/mode/result navigation; [source controllers](../../web/src/components/import/useSourceImport.ts) sở hữu preview, commit, cancellation và job lifecycle. |
| [App.tsx](../../web/src/App.tsx) | Session/navigation/selection; [workflow hooks](../../web/src/state/useAppJobs.ts) sở hữu loaders, effects và actions theo domain. |
| [PipelineService](../../app/mobile_api/services/pipeline_service.py), [db.py](../../app/database/db.py) | Façade tương thích; [BookService](../../app/mobile_api/services/book_service.py), [ImportCommitService](../../app/mobile_api/services/import_commit_service.py) và repository sở hữu logic. Database không còn import helper API trong các domain đã tách. |
| [Import routes](../../app/mobile_api/routers/import_routes.py) | HTTP/error mapping; [EbookImportService](../../app/mobile_api/services/ebook_import_service.py) sở hữu staging, retry/cleanup và background ebook job. |

Ranh giới trách nhiệm và các bất biến là tiêu chí nghiệm thu, không phải số dòng. Source/TTS repository, API-client subdivision và CSS lazy loading chỉ là đề xuất tương lai khi có lợi ích cụ thể. T12 không cần credentials LLM/F5 để kiểm tra cấu trúc và hành vi.

Các regression chính kiểm tra hành vi có thể gây mất dữ liệu hoặc trả kết quả sai:

| Bất biến | Test và phạm vi |
|---|---|
| Lưu thất bại không phá bản đang dùng; edit cũ trả conflict; source thay đổi làm QA/audio stale | [Publication](../../tests/test_chapter_publication.py), [DB/API](../../tests/test_mobile_api_db_logic.py), [legacy writers](../../tests/test_legacy_writer_integrity.py). Bao gồm CLI daily/retry, job QA nền, nhập nguồn trùng và URL note trùng. |
| Không công bố output rỗng/cắt; không retry lỗi vĩnh viễn; QA không lấy report cũ để đếm PASS | [Translation integrity](../../tests/test_translation_integrity.py), [QA integrity](../../tests/test_qa_integrity.py), [QA service](../../tests/test_qa_service.py). |
| Cancel/edit không công bố audio; retry giữ đầu vào; cache chỉ nhận QA đúng bytes/reference | [TTS pipeline](../../tests/test_tts_pipeline.py), [F5 process](../../tests/test_tts_f5_engine.py). F5 dùng injected runtime, không phải điểm chất lượng giọng thật. |
| QA MP3 và ghép mixed format thật; rate/volume áp một lần; M4B có chapter markers và không âm thầm partial | [Audio merger](../../tests/test_audio_merger.py), [audio QA](../../tests/test_tts_audio_qa.py), [export](../../tests/test_export_service.py), chạy FFmpeg/ffprobe thật. |
| Follow-up không mở transaction theo số chương; payload Xray sai không để lại graph một phần | [Import contracts](../../tests/test_import_transaction_performance_contracts.py), [Xray payload](../../tests/test_reader_xray_payload.py). |
| Source lỗi không chặn bản dịch; không tải dữ liệu optional sớm; keyboard/mobile/offline vẫn dùng được | [Chapter loading](../../web/src/state/useChapterText.test.tsx), [Reader](../../web/src/components/ReaderView.test.tsx), [browser E2E](../../web/e2e/novel-tnn.spec.ts). |

## Nghiệm thu refactor T12 — candidate revision 3

Candidate `/tmp/novel-tnn-refactor-rzkvim8g` dùng DB/logs/cấu hình fixture riêng,
Python 3.11.15 và Node 22.23.0/npm 10.9.8. 729 file nguồn/test/config được bound
trong `work/repo-research/novel-tnn/implementation/refactor/candidate.json`.
Các file operator ngoài phạm vi vẫn giữ hash trước refactor; hai báo cáo này
được phép cập nhật sau freeze.

| Controller/façade | Trước lần tiếp tục | Sau refactor | Ranh giới đã chuyển |
|---|---:|---:|---|
| ReaderView | 4.273 | 2.622 | Sync/progress, annotations/transfer, selection/search, dictionary, AI/Xray hooks |
| App | 2.145 | 970 | Catalog/jobs/import/operations/source/library/workbench workflows |
| ImportPanel | 2.454 | 1.456 | Text/file, ebook, URL/catalog controllers và ebook preview |
| db.py | 5.513 | 3.469 | Book/import/glossary/user/job repositories; metadata/job states về domain |
| PipelineService | 4.410 | 3.727 | BookService và ImportCommitService; chữ ký public giữ nguyên |
| Import routes | 1.451 | 1.299 | Ebook staging, retry cleanup và background job về EbookImportService |

80 hàm/class database được chuyển với AST giống hệt; export `db.py` vẫn là
cùng object của repository. SQL/migration và API public không đổi. Ba test ranh
giới ngăn database import API và ngăn façade có bản triển khai trùng. Test
benchmark bổ sung phát hiện phép đo giai đoạn bị mất sau khi đổi chủ sở hữu.

`NOVEL_PIPELINE_IGNORE_DOTENV=1 scripts/verify.sh --with-e2e`: **exit 0**, đủ
10 gate; backend 1.377 passed / 1 warning, 395,50 s; frontend 787 passed / 86
file; compile/shell/environment fixture/lint/typecheck/dependencies/build qua.
Desktop E2E 14 passed, 21,3 s; hai ca chỉ dành cho mobile skip ở desktop đã
pass 2/2 ở `--project=mobile-chromium`, 15,6 s. Log:
`refactor/candidate-release-verify.log`, `refactor/candidate-release-mobile.log`.

Lần aggregate đầu có 1.374 passed / 2 failed vì test inject vào namespace cũ.
Đã cập nhật điểm inject, giữ nguyên kiểm tra rollback và không resolve DNS;
19 test idempotency/transaction/ownership pass trước final rerun. Một bản chạy
trung gian bị dừng khi cùng hai failure đã biết xuất hiện. Không bỏ qua hoặc
giảm assertion; receipt thất bại/interrupted vẫn được giữ riêng.

Đo tuần tự sau khi test dừng, cùng dữ liệu tổng hợp và cách đo trước đó:

| Phép đo | Trước refactor | Candidate cuối |
|---|---:|---:|
| Import 120 chương, 3 mẫu, median | 52,891 ms | 46,379 ms; 1 connection / 2 commit |
| Import 500 chương, 3 mẫu, median | 195,195 ms | 173,774 ms; 1 connection / 2 commit |
| Thư viện dịch 1.000 sách, 5 mẫu, median | 36,217 ms | 34,957 ms; 1 connection / 1 query |
| Reader bình thường, 5 mẫu, median | 844 ms | 846 ms; 5/5 đọc được |
| Reader nguồn chậm 2 giây, 5 mẫu, median | 858 ms | 843 ms; 5/5 đọc được |
| Reader source 503, 5 mẫu, median | 852 ms | 852 ms; 5/5 đọc được |
| Bootstrap / optional requests khi mở | 1 / 0 | 1 / 0 ở cả 15 mẫu |

Không quy chênh lệch thời gian nhỏ cho refactor hoặc suy diễn SLA production.
Python gzip level 9: main 110.986 → 112.087 bytes; Reader 54.591 → 55.583;
Import 20.868; CSS giữ 38.091. Bundle main/Reader tăng nhẹ; không thêm frontend
dependency. Chi tiết `refactor/performance-summary.json`, import/library/Reader
JSON và `refactor/bundle-performance.json`. Preview do phiên này tạo đã dừng.

`git diff --check`, report-link validation và 729 hash nguồn/candidate đều
được kiểm tra ở receipt cuối `refactor/validation-final.json`. Không deploy,
migrate DB operator, commit/push hoặc đổi cấu hình dùng chung. Nghiệm thu này
chứng minh cấu trúc/hành vi local; T13 chất lượng dịch và giọng thật vẫn cần
provider, model và reference có thể sử dụng.


## Hiệu năng trước refactor (lịch sử)

Các số liệu dưới đây dùng dữ liệu tổng hợp và DB/HTTP fixture tách biệt. Baseline là báo cáo audit trước sửa, không phải một lần chạy lại trên production. Import: 3 lần mỗi cỡ; library và Reader: 5 lần mỗi cỡ/tình huống.

| Phép đo | Baseline audit | Sau triển khai |
|---|---:|---:|
| Import 500 chương, follow-up bật, median | 672,890 ms | 195,195 ms; giảm khoảng 71% |
| Kết nối / commit cho 500 chương | 1.001 / 501 | 1 / 2 |
| Import 120 chương, median | 167,525 ms | 52,891 ms |
| Thư viện 1.000 sách, median | 35,632 ms | 36,217 ms; gần tương đương, không tuyên bố nhanh hơn |
| Reader, nguồn bình thường | 821 ms, một quan sát | median 844 ms; 5/5 đọc được |
| Reader, nguồn chậm 2 giây | 2.356 ms, một quan sát | median 858 ms; 5/5 đọc được |
| Reader, source 503 | Bản dịch bị chặn | 5/5 đọc được; median 852 ms |
| Request optional khi vừa mở Reader | Có source/dictionary/playlist | 0; bootstrap đúng 1 lần mỗi mẫu |

Main JS gzip: 109.897 → 110.986 bytes; Reader JS gzip: 53.940 → 54.591 bytes; CSS gzip: 37.967 → 38.091 bytes. Import JS gần như không đổi. Cùng phép đo Python gzip level 9; số gzip Vite in ra dùng cách nén khác. Không thêm dependency frontend. Đây là tradeoff nhỏ để bổ sung các guard và UX; không ghi nhận cải thiện bundle size.

Chi tiết: `work/repo-research/novel-tnn/implementation-import.json`, `implementation-library.json`, `implementation/reader-performance.json` và `implementation/performance-summary.json`. Reader được đo lại sau sửa CSS trên candidate 4: 15/15 mẫu qua, không trùng lúc build; số liệu revision 3 giữ riêng. Những lần probe dùng sai thư mục preview hoặc trùng lúc build bị loại. Không suy diễn p95 production từ 5 mẫu.

## Xác minh trước refactor — candidate 4 (lịch sử)

- HEAD nguồn: `a41cd84dae42b745f196fac90a51356cf896a007`; branch: `upgrade-b/00-baseline-and-agent-guidance`.
- Candidate 4: `/tmp/novel-tnn-candidate-n3avcrwc`; Python 3.11.15, Node 22.23.0, npm 10.9.8. 694 file nguồn được SHA-256 bound trong `work/repo-research/novel-tnn/implementation/candidate.json`. Chỉ hai báo cáo tiến độ/kết quả được cập nhật sau freeze; product/test/config giữ nguyên. Metadata revision 3 được lưu riêng trước sửa CSS/E2E.
- Candidate dùng DB, logs và `.env` fixture riêng; Git metadata đọc-only và runtime/dependency đã cài được dùng lại. Python import xác nhận từ candidate. Không truy cập hay thay đổi DB vận hành.
- Gate lần đầu: backend 1.364 passed, exit 0; frontend 778 passed / 9 failed, exit 1. Các failure là giả định Bàn dịch mặc định; đã cập nhật theo Thư viện mặc định và 23 test liên quan qua. Receipt này là trung gian, không đủ để tuyên bố candidate cuối hoàn tất.
- Focused: backend 221 passed; bổ sung legacy/QA/publication/TTS 25 passed; source revision 2 passed; frontend 164 passed và Library integration 23 passed. Run repair lớn hơn có 121 passed / 1 failed vì test nhầm source API là cleaned text; sửa kỳ vọng để giữ raw-source contract, rồi hai ca source đều qua.
- Candidate 3: backend 1.373 passed / 1 warning, frontend 787 passed; compile/environment/lint/typecheck/dependencies/build qua. Wrapper exit 1 vì E2E có 11 passed / 3 failed / 2 skipped. Đã sửa menu bị thanh công cụ che, nút sách mobile không có bounding box và kỳ vọng màn hình mặc định cũ. Focused CSS/Library: 24 passed; ba E2E failure chạy lại đều qua, exit 0. Log `implementation/browser-repair-validation.log`.
- Mobile candidate 4: `npm --prefix web run test:e2e -- --project=mobile-chromium` — 2 passed, exit 0, 15,4 s, log `implementation/candidate-release-mobile.log`. Có touch-device shell và Library → Reader, kiểm tra translation-first, một bootstrap, optional requests, nhóm control và không tràn ngang. Receipt trước sửa CSS được giữ riêng, không gắn vào candidate cuối.
- Fixture audio: `NOVEL_PIPELINE_IGNORE_DOTENV=1 TTS_PROVIDER=edge_tts .venv/bin/python -m scripts.smoke_tts_audio` — 3/3 PASS, exit 0. Dùng engine fixture với FFmpeg thật; không phải kiểm chứng giọng Edge/F5 thật. Receipt trong turn này được giữ lại sau khi xác nhận backend không đổi ở revision 4; không gọi đây là một lần chạy mới.
- `NOVEL_PIPELINE_IGNORE_DOTENV=1 scripts/verify.sh --with-e2e`: **PASS, exit 0, candidate 4**; log `implementation/candidate-release-verify.log`. Đủ 10 gate: compile, shell syntax, môi trường fixture, lint/typecheck, 1.373 backend tests (428,40 s), dependency consistency, 787 frontend tests / 86 file, production frontend build, Chromium availability và 14 desktop E2E (21,6 s). Hai test mobile skip có chủ đích ở desktop và đều chạy PASS ở project mobile riêng; không bỏ qua gate bị lỗi.
- CLI entrypoint, compile và pyflakes qua; diff, links và source binding được kiểm tra riêng. Passlib `crypt` deprecation và Playwright `NO_COLOR` warning là cảnh báo môi trường, không phải failure. Không chạy Docker/deploy hay migrate DB vận hành; các PASS trên đây chỉ chứng minh candidate local với fixture tách biệt.
- Kiểm tra cuối: `git diff --check`, exit 0; 694 file nguồn/candidate không có hash mismatch; hai báo cáo không có link hỏng hoặc trailing whitespace; bundle cuối khớp record benchmark. Receipt `implementation/validation-final.json`. Preview do phiên này tạo đã dừng; candidate/log được giữ lại để review. Không commit hoặc push.

## Phần còn thiếu điều kiện bên ngoài

T13 chưa hoàn tất kiểm chứng chất lượng thực tế. Máy có RTX 3080 Ti/12 GiB, nhưng môi trường hiện không có Torch/F5/vinorm, checkpoint/vocab/reference được cấu hình, transcript reference hoặc API key provider. Endpoint Ollama local không truy cập được. `.env` trong repo không tồn tại và DB vận hành không đọc được. File production env tại vị trí được runbook chỉ định có thể đọc, nhưng không chứa cấu hình LLM key hoặc reference audio/transcript. Các availability flag được lưu trong `implementation/runtime-prerequisites.json`, `local-llm-prerequisites.json` và `documented-config-prerequisites.json`; không lưu giá trị credential.

Cần cấu hình/mẫu giọng truy cập được để chạy dịch/QA trên corpus phù hợp, đo thời gian và chi phí provider, nghe/chấm fidelity/phát âm/nhịp nghỉ và đo tốc độ/VRAM của F5 thật. Test process dùng runtime giả lập chỉ chứng minh deadline, khóa, cancellation và lifecycle; waveform fixture chỉ chứng minh pipeline/codec/metadata. Không dùng chúng làm điểm chất lượng dịch, ASR hoặc MOS.

Lệnh smoke thật đã có trong repo; chạy với DB tách biệt và scope nhỏ sau khi cấu hình đủ:

```bash
.venv/bin/python -m scripts.smoke_tts_audio --help
# Sau khi chọn DB/book và model/reference có thật:
.venv/bin/python -m scripts.smoke_tts_audio --real-provider \
  --db-path /path/to/isolated/pipeline.db --data-dir /path/to/isolated/data \
  --book-id BOOK_ID --chapter-limit 1 --max-chars 1500 --dry-run \
  --output-dir /path/to/qualification
```

Dry-run là kiểm tra preflight, không phải bằng chứng audio được tạo. Bước thực chạy và chấm chất lượng vẫn phải có receipt riêng. Không deploy/push, không đổi quyền dữ liệu operator, không thêm production dependency hay tự tạo giọng tham chiếu thay cho mẫu cần kiểm chứng.

Trạng thái từng T00–T14 và log/exit status cuối: [implementation-progress.md](implementation-progress.md).
