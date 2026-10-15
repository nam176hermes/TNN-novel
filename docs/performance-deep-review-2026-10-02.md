# Kiểm tra sâu hiệu năng Novel-TNN — 2026-10-02

## Kết luận

**App còn cần cải thiện hiệu năng**, tập trung vào khả năng giữ phản hồi khi có công việc chậm, màn Raw khi thư viện lớn, tìm kiếm toàn sách, phân trang Reader với chương dài và chi phí xử lý audio. Không có bằng chứng cần viết lại toàn bộ app hoặc thay SQLite/framework.

Các số đo dưới đây được thực hiện mới trong lần audit này. Đây là đánh giá và benchmark; **không thay đổi code ứng dụng**. Số liệu provider dịch và giọng F5 thật chưa được kiểm chứng.

| Ưu tiên | Vấn đề | Bằng chứng mới | Hướng sửa nhỏ nhất |
|---|---|---|---|
| P1 | Công việc đồng bộ trong API `async` chặn event loop | Lookup có độ trễ giả lập 400 ms làm health chờ khoảng 410 ms; SQLite giữ khóa ghi 400 ms làm health chờ 429–435 ms | Đưa I/O đồng bộ ra worker; tái sử dụng mô hình job cho công việc dài |
| P1 | Màn Raw tải/render toàn thư viện | 500 sách → 500 request chương, 5.000 hàng Raw, 115.735 phần tử DOM; tác vụ giao diện dài nhất 6.037 ms | API tổng hợp Raw; tải danh sách chương theo sách đang mở; phân trang các hàng |
| P1 | Tìm kiếm toàn sách mở kết nối cho từng chương | 2.000 chương → 2.002 kết nối/query, median 2.756 ms | Tái sử dụng hàng chương đã tải, offload việc đọc/scan và giới hạn kết quả |
| P2 | Reader phân trang đo toàn bộ chương trên luồng giao diện | 2.000 đoạn / 446.888 ký tự → median 1.892 ms tới frame có nội dung; median tác vụ dài nhất 1.457 ms | Đo trang theo cửa sổ/chunk, lưu phép đo theo nội dung và bố cục |
| P2 | Ghép audio chạy FFmpeg riêng cho từng WAV | 64 đoạn WAV 1 giây → 66 tiến trình, median 6.435 ms | Dùng trực tiếp WAV đã đúng định dạng; chỉ decode các đầu vào cần chuyển đổi |
| P2, có điều kiện | Giới hạn nhiều job cùng chạy và tải thư viện cực lớn | Job dịch/TTS có offload nhưng chưa có hàng đợi giới hạn riêng theo provider/GPU; 5.000 sách trả khoảng 2 MB JSON | Đo tải provider thật trước khi chọn giới hạn; phân trang API khi dữ liệu thực tế đạt quy mô này |

## Phạm vi và độ tin cậy

- Source: `/home/thenam176/Novel-TNN`, HEAD `a41cd84dae42b745f196fac90a51356cf896a007`, branch `upgrade-b/00-baseline-and-agent-guidance`. Worktree có nhiều thay đổi từ các lượt trước; giữ nguyên toàn bộ.
- Kiểm tra hash của **729 file** xác nhận source vẫn khớp candidate refactor `/tmp/novel-tnn-refactor-rzkvim8g`. Dùng candidate này để tránh tác động dữ liệu operator.
- Python 3.11.15, Node 22.23.0, WSL2/Linux filesystem; DB và nội dung tổng hợp trong thư mục tạm riêng. `NOVEL_PIPELINE_IGNORE_DOTENV=1`.
- Backend: HTTPX ASGI, cùng một event loop, auth bypass chỉ trong tiến trình kiểm tra không mở cổng. Số đo gồm route/serialization nhưng không gồm TCP, proxy, TLS và chi phí đăng nhập.
- Browser: production Vite build, Chromium, CPU throttle 4×. Reader ở viewport 390×844; Library/Raw ở 1440×1000. API trả dữ liệu giả lập. CPU throttle không tương đương một mẫu điện thoại Android cụ thể.
- Mỗi tổ hợp có 3 mẫu, báo median và trường hợp quan sát lớn nhất. Số mẫu này không đủ để chứng nhận p95/p99 production.
- Audio: FFmpeg chạy thật, tone PCM tổng hợp; **không đo tổng hợp giọng nói, chất lượng phát âm hoặc tốc độ F5**.
- Không truy cập/chỉnh sửa DB operator, không gọi provider thật, không cài dependency, không đổi CI/config, không deploy.

Evidence và script đo nằm trong thư mục ignored `/home/thenam176/Novel-TNN/work/repo-research/novel-tnn/performance-deep-2026-10-02/`.

## 1. Giữ API phản hồi trong lúc công việc khác chậm

Trong [books.py](/home/thenam176/Novel-TNN/app/mobile_api/routers/books.py:435), route lookup là `async def` nhưng gọi trực tiếp `pipeline.lookup_reader_dictionary()`. Khi cache miss, [pipeline_service.py](/home/thenam176/Novel-TNN/app/mobile_api/services/pipeline_service.py:3068) đi tới hàm fetch dùng `urlopen()` đồng bộ. Timeout từ điển mặc định là 2 giây mỗi lời gọi mạng.

| Trường hợp | Thời gian request | Ảnh hưởng tới health |
|---|---:|---:|
| Lookup cache miss, chèn 400 ms tại bước fetch mạng | 419–420 ms | Hoàn thành trễ 409–410 ms so với thời điểm dự kiến |
| Lookup cache hit, cùng query | 14,4 ms | Trễ 4,6 ms |
| Lưu tiến độ Reader khi một writer giữ SQLite 400 ms | 439–445 ms | Trễ 429–435 ms |

Phép đo health tính cả **thời gian chưa được dispatch**. Chỉ đo thời gian sau khi health bắt đầu xử lý sẽ che mất sự đình trệ này. Độ trễ mạng 400 ms là giả lập có kiểm soát, còn đường route/service/cache là thật. Ca khóa SQLite dùng giao dịch và thread writer thật trên DB tạm.

Đây là ảnh hưởng trên **cùng worker/event loop**, không phải khẳng định mọi deployment nhiều worker đều đứng toàn bộ. Event loop chậm cũng có thể làm cập nhật tiến độ/heartbeat job trễ; mức ảnh hưởng tới lease chưa được thử với provider lâu hàng phút.

Các đường cùng kiểu gọi cần rà soát trong một patch riêng:

- [Reader explain](/home/thenam176/Novel-TNN/app/mobile_api/routers/books.py:476), X-Ray enrich, dịch lại/polish đoạn: gọi service/LLM đồng bộ từ route async.
- [QA chạy trực tiếp](/home/thenam176/Novel-TNN/app/mobile_api/routers/qa.py:40): gọi `svc.run_qa_check()` trực tiếp; thời gian provider chưa đo.
- [Import paste/file và preview ebook](/home/thenam176/Novel-TNN/app/mobile_api/routers/import_routes.py:437): còn các phần đọc/parse/commit đồng bộ.
- [Export TXT/DOCX/EPUB](/home/thenam176/Novel-TNN/app/mobile_api/routers/exports.py:59): vẫn tạo export trực tiếp. Export audiobook đã có `asyncio.to_thread`, không thuộc cùng thiếu sót.
- [Lưu Reader progress](/home/thenam176/Novel-TNN/app/mobile_api/routers/books.py:246) và các ghi SQLite ngắn: bình thường nhanh nhưng có thể chờ khóa. `busy_timeout` hiện là 5 giây.

Hướng sửa: dùng cách offload sẵn có trong repo cho tác vụ đồng bộ; công việc dài dùng job đã có. Giữ nguyên kiểm tra quyền, revision, cancellation và lỗi. Không chỉ đổi hàm thành `async` mà vẫn chạy I/O đồng bộ bên trong. Offload giúp event loop nhưng không tự làm scan CPU nhanh hơn hoặc giới hạn số job cùng chạy.

Acceptance đề xuất: với một tác vụ I/O trì hoãn 2 giây và một writer giữ khóa 400 ms, health/job-status vẫn hoàn thành dưới 100 ms ở mẫu local ổn định; không mất tiến độ, không sai revision, không nhân đôi job. Sau đó mới đo p95 trên runtime thật.

## 2. Màn Raw: request và DOM tăng theo toàn thư viện

[useLibraryCatalog.ts](/home/thenam176/Novel-TNN/web/src/state/useLibraryCatalog.ts:59) dùng `Promise.all(books.map(getChapters))`, lấy chương của mọi sách kể cả chương đã dịch. [RawBacklogView.tsx](/home/thenam176/Novel-TNN/web/src/components/RawBacklogView.tsx:209) render toàn bộ hàng Raw.

Fixture mỗi sách có 20 chương, 10 chương chưa dịch:

| Sách | Request lấy chương khi mở Raw | Hàng Raw | Phần tử DOM | Median tới khi có đủ hàng trong DOM | Tác vụ giao diện dài nhất |
|---:|---:|---:|---:|---:|---:|
| 20 | 20 | 200 | 4.855 | 628 ms | 247 ms |
| 100 | 100 | 1.000 | 23.335 | 1.121 ms | 1.186 ms |
| 500 | 500 | 5.000 | 115.735 | 4.381 ms | 6.037 ms |

Thời gian đủ hàng DOM không phải thời gian kết thúc paint/layout; vì vậy có thể ngắn hơn tác vụ giao diện dài nhất. API mock loại bỏ thời gian xử lý backend/mạng thật. Heap JS median sau mở Raw tăng từ khoảng 8,1 MiB lên 43,3 MiB; số này không phải tổng RAM của tab.

Hướng sửa: thêm truy vấn/API tổng hợp sách có backlog; lấy chương theo sách được mở và theo trang. Nếu cần dịch cả sách, chọn chương ở backend thay vì tải mọi ID lên UI trước. Chỉ thêm virtualization nếu phân trang/mở nhóm vẫn chưa đủ nhanh.

Acceptance: số request mở Raw không tăng tuyến tính theo tổng sách; một request tổng hợp và tối đa một request trang chương đang mở. Giới hạn số hàng render, ví dụ 50 hàng/trang. Với fixture 500 sách trên cùng CPU throttle, mục tiêu tới frame hữu ích dưới 1 giây và không có tác vụ trên 200 ms. Giữ đúng chọn chương/dịch batch và trạng thái không có raw.

## 3. Tìm kiếm toàn sách: N+1 kết nối và scan file đồng bộ

[search_reader_book()](/home/thenam176/Novel-TNN/app/mobile_api/services/pipeline_service.py:2364) đã lấy toàn bộ hàng chương, nhưng vòng lặp lại gọi `get_chapter_translation(id)`, đọc lại hàng chương từ DB trước khi đọc file. API tìm kiếm gọi hàm này trực tiếp.

Fixture có 12.240 byte/chương; query không xuất hiện trong sách nên phải scan toàn bộ:

| Chương | Nội dung scan | Kết nối/query | Median request | Health trễ lớn nhất |
|---:|---:|---:|---:|---:|
| 100 | 1,224 MB | 102 / 102 | 140 ms | 133 ms |
| 500 | 6,120 MB | 502 / 502 | 678 ms | 680 ms |
| 2.000 | 24,480 MB | 2.002 / 2.002 | 2.756 ms | 2.769 ms |

Thử nghiệm riêng thay bước đọc nội dung bằng hàng chương đã có, dùng khả năng `chapter=` sẵn trong `ContentFileService`:

- Còn **2 kết nối / 2 query**, median **768 ms**, giảm khoảng 72% so với fixture gốc.
- Event loop vẫn bị chặn khoảng 761 ms: bỏ N+1 chưa giải quyết toàn bộ vấn đề.
- Đây là thay thế trong tiến trình benchmark, **không phải bản sửa đã áp dụng vào app**.

Hướng sửa: tái sử dụng metadata đã tải, offload scan, giới hạn/paginate kết quả và bỏ request tìm kiếm cũ khi query đổi. Nếu sách thực tế vẫn chậm sau patch nhỏ này, mới xem xét SQLite FTS và chỉ mục theo content revision. Không thêm cache không có invalidation cho dịch/sửa chương.

Acceptance: số query không phụ thuộc số chương; cùng kết quả và vị trí match cho translation/note/highlight, Unicode/regex/whole-word. Với fixture trên, median dưới 1 giây và health dưới 100 ms khi search chạy. Regex vẫn cần xử lý như công việc có thể tốn CPU; offload thread không bảo đảm deadline cho mọi pattern.

## 4. Reader: chương dài, đặc biệt chế độ phân trang

Có cải thiện sẵn đáng giữ: scroll dài render theo từng đợt, khởi đầu 80 đoạn; nội dung dịch không cần chờ source/dictionary/audio. Tuy nhiên, [ReaderView.tsx](/home/thenam176/Novel-TNN/web/src/components/ReaderView.tsx:2297) tạo surface ẩn chứa toàn chương để [đo viewport](/home/thenam176/Novel-TNN/web/src/components/ReaderView.tsx:749) khi phân trang.

Số đo từ pointerdown tới frame có đoạn dịch nhìn thấy, CPU 4×, API mock:

| Đoạn / ký tự | Scroll: median hiện nội dung | Scroll: median tác vụ dài nhất | Paginated: median hiện nội dung | Paginated: median tác vụ dài nhất |
|---|---:|---:|---:|---:|
| 80 / 17.748 | 370 ms | 112 ms | 349 ms | 107 ms |
| 500 / 111.388 | 486 ms | 199 ms | 646 ms | 376 ms |
| 2.000 / 446.888 | 910 ms | 547 ms | 1.892 ms | 1.457 ms |

Với 2.000 đoạn, scroll sau khoảng chờ 700 ms có 160 block; paginated có 2.003 block, gồm surface đo và nội dung trang. Số đoạn scroll đã mở rộng phụ thuộc lịch idle; không dùng một snapshot này làm giới hạn cố định.

Hướng sửa: đo vùng trang cần dùng trước rồi bổ sung theo đợt; lưu phép đo theo chapter revision, kích thước viewport và thiết lập font. Với scroll, còn tác vụ dài ở chương rất lớn dù DOM ban đầu được giới hạn; cần tách thời gian parse/React/layout trước khi quyết định tối ưu phần nào. Không có bằng chứng yêu cầu thay cơ chế Reader cho chương bình thường.

Acceptance: fixture 2.000 đoạn hiện nội dung dưới 1 giây trên cấu hình đo, không có tác vụ trên 200 ms trong thao tác mở/chuyển trang. Không sai vị trí lưu/khôi phục, selection, annotation, paragraph dài vượt trang hoặc page-break của rich content.

18 mẫu Reader và 9 mẫu Library/Raw không ghi nhận `pageerror`. Không đo máy Android thật, mạng WAN, rich EPUB nhiều bảng/hình/ruby, QA overlay dài hay audiobook đang phát nền.

## 5. Audio: chi phí ghép và QA

[audio_merger.py](/home/thenam176/Novel-TNN/app/services/tts/audio_merger.py:66) decode từng input bằng một tiến trình FFmpeg, dù input đã là WAV mono PCM16 đúng 24 kHz. Ghép chương còn tạo silence và encode MP3.

| WAV đầu vào, mỗi đoạn 1 giây | Tiến trình FFmpeg | Median ghép chương |
|---:|---:|---:|
| 4 | 6 | 542 ms |
| 16 | 18 | 1.693 ms |
| 64 | 66 | 6.435 ms |

Decode chiếm khoảng 43–57% tổng thời gian ở một mẫu của mỗi cỡ. Số đo này làm rõ chi phí khởi động/quản lý nhiều process; không dự đoán chi phí encode một chương dài thật.

Hướng sửa: kiểm tra header và dùng trực tiếp WAV cùng sample rate/channel/sample width; giữ decode cho MP3 và đầu vào khác định dạng. Tận dụng cùng hướng cho M4B nếu số đo sách lớn xác nhận lợi ích. Giữ silence, loudness/rate/volume, chapter markers, atomic publication và kiểm tra lỗi file. Không đổi concat sang copy codec tùy tiện.

QA hiện đọc PCM theo block 8.192 frame, đã giới hạn bộ nhớ. Một WAV 1 giây mất median 4,7 ms để QA; MP3 tổng hợp 86 giây mất median 914,5 ms, gồm decode và scan. Không có cơ sở bỏ QA để tăng tốc. Resume/cache vẫn cần bằng chứng gắn với hash/nội dung.

Acceptance: fixture 64 WAV cùng định dạng giảm số process từ 66 xuống tối đa 2 nếu giữ cách tạo silence hiện tại; kiểm tra duration, codec, metadata, khoảng nghỉ, rate/volume và file lỗi. So sánh wall-clock mới trên cùng fixture; đây là mục tiêu, chưa phải kết quả bản sửa.

## 6. Import, thư viện dịch và nhiều job

**Import batch hiện khá tốt về cấu trúc:** benchmark có follow-up deterministic thật, không gọi LLM:

| Chương | Byte text | Median service | Kết nối | Commit |
|---:|---:|---:|---:|---:|
| 1.000 | 430.893 | 405 ms | 1 | 2 |
| 5.000 | 2.158.893 | 1.953 ms | 1 | 2 |

Cả 6 mẫu đủ số chương, không warning. Dữ liệu API/import khác parser/ebook thực tế nên không dùng số này để chứng nhận upload/preview end-to-end. Patch cần ưu tiên offload các entrypoint còn đồng bộ, không quay lại đổi transaction đã ổn định. Các timer nội bộ có phần lồng nhau, không cộng tất cả stage thành tổng thời gian.

**Thư viện dịch không còn N+1:**

| Sách / chương | Median API | Query/kết nối | JSON chưa nén |
|---|---:|---:|---:|
| 100 / 1.000 | 9 ms | 1 / 1 | 39 KB |
| 1.000 / 10.000 | 41 ms | 1 / 1 | 398 KB |
| 5.000 / 50.000 | 196 ms | 1 / 1 | 2.006 KB |

`LibraryBooksView` đã phân trang 12 card; browser fixture tới 500 sách vẫn chỉ render trang card đang xem. Quy mô 5.000 sách bắt đầu có vòng xử lý/serialize chặn loop tới 244 ms và payload khoảng 2 MB; phân trang API là cải thiện có điều kiện, ưu tiên thấp hơn Raw.

**Dịch/TTS background:** `JobService` offload công việc chính bằng `asyncio.to_thread`; chunk dịch giữ context đoạn trước, còn TTS tái sử dụng engine trong cùng batch. Không nên tăng parallel chunk tùy tiện vì có thể thay chất lượng dịch hoặc gây áp lực VRAM. Durable lease chống chạy trùng cùng job không thay thế giới hạn tổng số job theo provider/GPU. Kiểm tra source chưa thấy giới hạn chung tương ứng cho các job dịch/TTS độc lập; hiệu ứng khi nhiều F5 chạy thật **chưa đo**.

Runtime Python kiểm tra lần này không có `torch`, `f5_tts`, `vinorm`. Tốc độ sinh giọng, warm/cold model, RTF, VRAM, token/giây, retry 429 và chất lượng provider thật vẫn chưa được qualification. Không suy ra app production thiếu runtime từ môi trường audit này. Cần môi trường/model/reference được cấu hình để đo các mục đó.

Các vấn đề trong báo cáo cũ cần cập nhật cách hiểu: backup listing hiện đọc sidecar và trả `METADATA_MISSING` khi thiếu, không scan archive trong list; tạo backup đã dùng coordinator/job. Không tiếp tục coi hai đường này là lỗi chưa sửa chỉ vì số đo cũ. Lần này xác nhận bằng source, không benchmark lại archive operator.

## Thứ tự thực hiện đề xuất

1. Patch riêng cho API blocking, cùng regression về request đồng thời, SQLite lock và các luồng Reader/QA liên quan.
2. Patch riêng cho search, tái sử dụng metadata trước; FTS chỉ khi phép đo sau sửa vẫn không đạt.
3. Patch riêng cho Raw, giảm fan-out và lượng DOM bằng API tổng hợp + tải chương theo trang.
4. Patch riêng cho Reader dài, ưu tiên phân trang; đo parse/render/layout để chọn đúng phần sửa.
5. Patch riêng cho WAV merge fast path, giữ nguyên qualification audio và publication.
6. Sau khi provider/F5 thật sẵn sàng, đo concurrency/quota/VRAM và chọn giới hạn job. Chỉ tối ưu thư viện cực lớn theo dữ liệu thực tế.

Mỗi patch cần đủ kiểm tra hành vi trước khi sang patch kế tiếp. Audit này không mở thêm milestone triển khai hoặc chứng nhận T13/live provider hoàn tất.

## Lệnh, kết quả và bằng chứng

Các probe Python chạy bằng `.venv/bin/python`, `PYTHONPATH=/tmp/novel-tnn-refactor-rzkvim8g`, `NOVEL_PIPELINE_IGNORE_DOTENV=1`; script audit được gọi bằng đường tuyệt đối từ thư mục evidence nêu trên.

| Kiểm tra | Kết quả thực thi | Evidence |
|---|---|---|
| Hash source/candidate | 729 file khớp | `identity.json`, `final-validation.json` |
| `backend_probe.py` sau sửa fixture | Exit 0, 22 mẫu contention | `backend-v2.log`, `backend.json` |
| `backend_followup.py` | Exit 0, 3 mẫu row-reuse và 3 mẫu khóa ghi | `backend-followup.log/json` |
| `node browser_probe.mjs` | 18 mẫu Reader hoàn tất; exit 1 khi chuyển sang catalog do locator của harness | `browser.log`, phần Reader của `browser.json` |
| `node browser_probe.mjs --catalog-only` sau sửa locator | Exit 0, 9 mẫu catalog | `browser-catalog.log`, phần catalog của `browser.json` |
| `audio_probe.py` | Exit 0, 9 merge + 6 QA; FFmpeg/QA đều thành công | `audio.log/json` |
| `scripts/benchmark_import_transaction.py --counts 1000,5000 --runs 3 --large-bytes 0 --include-followups --work-root /tmp --output <audit>/import.json` | Exit 0, 6 mẫu | `import.log/json` |
| `git diff --check` và kiểm tra whitespace/link của báo cáo | Exit 0 | `final-validation.json` |

Probe backend đầu tiên exit 1 vì fixture metadata-only có artifact path ngoài root khi dictionary tự lấy X-Ray; đã đổi sang fixture Reader hợp lệ. Browser đầu tiên dùng sai tên navigation desktop; sửa locator, chỉ chạy lại phần catalog chưa có bằng chứng. Đây là lỗi harness, không phải lỗi app. 18 mẫu Reader được giữ từ phép đo trước sửa locator trong cùng lượt audit; không mô tả chúng là lần chạy lại mới.

Không chạy lại toàn bộ lint/typecheck/build/test/E2E vì source ứng dụng không đổi trong audit. Qualification refactor trước đó là evidence được giữ, không phải phép test mới ở đây. Các ngưỡng hiệu năng đề xuất chưa đạt không được gọi là PASS chỉ vì script benchmark exit 0.
