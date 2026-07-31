import { useState } from 'react';
import {
  BookOpen,
  CheckCircle2,
  Download,
  FileText,
  Globe2,
  Info,
  RefreshCw,
  Sparkles,
  Upload,
} from 'lucide-react';
import coverDocTu from '../assets/reference-ui/cover-doc-tu-clean.png';
import coverThanhSon from '../assets/reference-ui/cover-thanh-son-clean.png';
import WorkflowShell, { type WorkflowView } from './WorkflowShell';

type Props = {
  apiBaseUrl: string;
};

const demoJobs = [
  { id: 'review-translate-001', label: 'Dịch chương 18', progress: 68, state: 'TRANSLATING' },
  { id: 'review-audio-002', label: 'Tạo audio chương 2', progress: 100, state: 'COMPLETED' },
];

function ReviewBanner() {
  return (
    <section className="review-banner" role="status">
      <Info aria-hidden="true" size={18} />
      <div>
        <strong>Public review mode</strong>
        <span>Dữ liệu bên dưới là demo/sanitized. API thật, private assets, provider keys và thao tác ghi vẫn được bảo vệ.</span>
      </div>
    </section>
  );
}

function PageFrame({ eyebrow, title, children }: { eyebrow: string; title: string; children: React.ReactNode }) {
  return (
    <article className="review-page">
      <ReviewBanner />
      <header className="review-page-header">
        <p>{eyebrow}</p>
        <h2>{title}</h2>
      </header>
      {children}
    </article>
  );
}

function ReviewWorkbench() {
  return (
    <PageFrame eyebrow="Workbench" title="Bàn dịch">
      <section className="review-hero-panel">
        <BookOpen aria-hidden="true" size={44} />
        <div>
          <h3>Chưa chọn chương</h3>
          <p>Chọn chương trong danh sách để bắt đầu biên tập bản dịch.</p>
        </div>
      </section>
      <div className="review-grid review-grid-four">
        {[
          ['685', 'Chương raw'],
          ['2', 'Truyện đang xử lý'],
          ['128', 'Chương đã dịch'],
          ['32%', 'Tiến độ tổng'],
        ].map(([value, label]) => (
          <section className="review-card" key={label}>
            <strong>{value}</strong>
            <span>{label}</span>
          </section>
        ))}
      </div>
      <div className="review-grid review-grid-two">
        <section className="review-card">
          <h3>Hoạt động gần đây</h3>
          <ul className="review-list">
            <li>Đã dịch chương 20 của Thanh Sơn <span>10 phút trước</span></li>
            <li>Thêm thuật ngữ mới: “thần hồn” <span>1 giờ trước</span></li>
            <li>Đồng bộ nguồn truyện từ 69shuba <span>2 giờ trước</span></li>
          </ul>
        </section>
        <section className="review-card">
          <h3>Trạng thái hệ thống</h3>
          <ul className="review-list">
            <li><CheckCircle2 aria-hidden="true" size={16} /> API Server <span>Hoạt động</span></li>
            <li><CheckCircle2 aria-hidden="true" size={16} /> Dịch vụ dịch <span>Gemini</span></li>
            <li><CheckCircle2 aria-hidden="true" size={16} /> Lưu trữ <span>Được bảo vệ</span></li>
          </ul>
        </section>
      </div>
    </PageFrame>
  );
}

function ReviewRaw() {
  const rows = ['Ch. 10 - 第10章 蟪是苑', 'Ch. 11 - 第11章 小黑猫', 'Ch. 12 - 第12章 出诊', 'Ch. 13 - 第13章 重瞳'];
  return (
    <PageFrame eyebrow="Library" title="Raw chưa dịch">
      <div className="review-grid review-grid-three">
        <section className="review-card"><strong>1</strong><span>Truyện đang chờ</span></section>
        <section className="review-card"><strong>685</strong><span>Chương raw</span></section>
        <section className="review-card"><strong>2</strong><span>Truyện trong app</span></section>
      </div>
      <section className="review-card">
        <h3>Thanh Sơn <small>Đang chờ dịch</small></h3>
        <ul className="review-table-list">
          {rows.map((row) => (
            <li key={row}>
              <FileText aria-hidden="true" size={18} />
              <span>{row}</span>
              <em>Imported</em>
              <button type="button">Mở bản dịch</button>
            </li>
          ))}
        </ul>
      </section>
    </PageFrame>
  );
}

function ReviewLibrary() {
  return (
    <PageFrame eyebrow="Kho truyện" title="Thư viện">
      <div className="review-library-grid">
        {[
          { title: 'Độc Tu', author: 'Thủy Đạo Bất Cô', cover: coverDocTu, progress: '100%', chapters: '1400/1400' },
          { title: 'Thanh Sơn', author: 'Demo source', cover: coverThanhSon, progress: '1%', chapters: '10/695' },
        ].map((book) => (
          <section className="review-book-card" key={book.title}>
            <img alt="" src={book.cover} />
            <h3>{book.title}</h3>
            <p>{book.author}</p>
            <div className="review-book-stats">
              <span>{book.chapters}<small>Chương đã dịch</small></span>
              <span>{book.progress}<small>Tiến độ</small></span>
            </div>
            <div className="review-actions">
              <button type="button"><BookOpen aria-hidden="true" size={16} /> Đọc tiếp</button>
              <button type="button">Sửa</button>
            </div>
          </section>
        ))}
      </div>
    </PageFrame>
  );
}

function ReviewReader() {
  return (
    <PageFrame eyebrow="Reader" title="Đọc truyện">
      <section className="review-reader">
        <header>
          <img alt="" src={coverDocTu} />
          <div>
            <h3>Độc Tu</h3>
            <p>Chương 10 / 1400</p>
          </div>
          <button type="button">Aa</button>
        </header>
        <article>
          <p>Ngay tại thời khắc này, một luồng lực lượng thần bí nhẹ nhàng lau đi dấu vết còn sót lại.</p>
          <p>Chỉ trong chớp mắt, tất cả biến mất vô tung, để lại một mảnh da thịt trơn nhẵn bóng mượt.</p>
          <p>Gần như ngay sau đó, kỳ tích lại xảy ra.</p>
        </article>
        <footer>
          <button type="button">Mục lục</button>
          <button type="button">Tối ưu đọc</button>
          <button type="button">Cài đặt</button>
        </footer>
      </section>
    </PageFrame>
  );
}

function ReviewImport() {
  return (
    <PageFrame eyebrow="Nhập chương" title="Import source file">
      <section className="review-card">
        <div className="review-tab-row">
          <button type="button">Paste</button>
          <button className="is-active" type="button">File</button>
          <button type="button">Ebook bản dịch</button>
        </div>
        <label>Book title<input placeholder="Nhập tên truyện hoặc để trống nếu đã chọn từ Library" readOnly /></label>
        <label>Chapter number<input readOnly value="1" /></label>
        <div className="review-dropzone">
          <Upload aria-hidden="true" size={36} />
          <strong>Chọn file hoặc kéo & thả vào đây</strong>
          <span>Hỗ trợ: TXT, HTML, EPUB, AZW3, MOBI, PRC</span>
        </div>
      </section>
    </PageFrame>
  );
}

function ReviewSources() {
  return (
    <PageFrame eyebrow="Sources" title="Nguồn truyện">
      <section className="review-card">
        <div className="review-toolbar">
          <input placeholder="Tìm nguồn..." readOnly />
          <button type="button"><RefreshCw aria-hidden="true" size={16} /> Refresh</button>
        </div>
        <ul className="review-table-list">
          {['69shuba.com', 'biquge.tw', 'qidian.com', 'novel543.com'].map((domain) => (
            <li key={domain}>
              <Globe2 aria-hidden="true" size={18} />
              <span>{domain}</span>
              <em>supported</em>
              <small>10s delay · 1 concurrer</small>
            </li>
          ))}
        </ul>
      </section>
    </PageFrame>
  );
}

function ReviewGlossary() {
  return (
    <PageFrame eyebrow="Workflow" title="Thuật ngữ & Văn phong">
      <section className="review-card">
        <h3>Profile đang dùng</h3>
        <div className="review-grid review-grid-two">
          <p><strong>Quy tắc xưng hô</strong><span>Ưu tiên Hán Việt, giữ sắc thái tiên hiệp.</span></p>
          <p><strong>Mức Hán Việt</strong><span>high</span></p>
        </div>
      </section>
      <section className="review-card">
        <h3>Bảng thuật ngữ</h3>
        <ul className="review-table-list">
          {['Chu Thành Nghĩa', 'Giao Thỏ', 'Tinh Hà', 'sư chủ'].map((term) => (
            <li key={term}><span>{term}</span><em>Chờ duyệt</em><button type="button">Duyệt</button></li>
          ))}
        </ul>
      </section>
    </PageFrame>
  );
}

function ReviewProviders() {
  return (
    <PageFrame eyebrow="Workflow" title="Model API">
      <section className="review-card">
        <h3>Sử dụng hiện tại</h3>
        <div className="review-grid review-grid-two">
          <p><strong>465.909</strong><span>Tổng token</span></p>
          <p><strong>$0.0957</strong><span>Chi phí ước tính</span></p>
        </div>
      </section>
      <section className="review-card">
        <h3>Danh sách provider</h3>
        <ul className="review-table-list">
          {['DeepSeek', 'Gemini', 'Ollama', 'OpenRouter'].map((provider) => (
            <li key={provider}><Sparkles aria-hidden="true" size={18} /><span>{provider}</span><em>Đã cấu hình</em><button type="button">Test kết nối</button></li>
          ))}
        </ul>
      </section>
    </PageFrame>
  );
}

function ReviewJobs() {
  return (
    <PageFrame eyebrow="Workflow" title="Tác vụ">
      <section className="review-card">
        <h3>Danh sách tác vụ</h3>
        {demoJobs.map((job) => (
          <div className="review-job-row" key={job.id}>
            <div>
              <strong>{job.label}</strong>
              <span>{job.state}</span>
            </div>
            <progress max={100} value={job.progress} />
            <button type="button">Xem log</button>
          </div>
        ))}
      </section>
    </PageFrame>
  );
}

function ReviewStatus() {
  return (
    <PageFrame eyebrow="Runtime" title="Trạng thái hệ thống">
      <div className="review-grid review-grid-four">
        <section className="review-card"><strong>Sẵn sàng</strong><span>API Readiness</span></section>
        <section className="review-card"><strong>Gemini</strong><span>Active Provider</span></section>
        <section className="review-card"><strong>0 / 0</strong><span>Running Jobs</span></section>
        <section className="review-card"><strong>Bật</strong><span>System protection</span></section>
      </div>
      <section className="review-card">
        <h3>Nhật ký hệ thống</h3>
        <ul className="review-list">
          <li>System started successfully <span>INFO</span></li>
          <li>Provider changed to gemini <span>INFO</span></li>
          <li>Job review-translate-001 started <span>INFO</span></li>
        </ul>
      </section>
    </PageFrame>
  );
}

function ReviewExport() {
  return (
    <PageFrame eyebrow="Output" title="Xuất file">
      <section className="review-card">
        <h3>Chọn truyện</h3>
        <select aria-label="Book" value="Độc Tu" disabled>
          <option>Độc Tu</option>
        </select>
        <div className="review-grid review-grid-three">
          <span>Chapters <strong>1400</strong></span>
          <span>Translated <strong>1400</strong></span>
          <span>Audio <strong>2</strong></span>
        </div>
      </section>
      <section className="review-card">
        <h3>Tải bản dịch</h3>
        <div className="review-export-row">
          {['TXT', 'DOCX', 'EPUB'].map((format) => (
            <button key={format} type="button"><Download aria-hidden="true" size={18} /> {format}</button>
          ))}
        </div>
      </section>
    </PageFrame>
  );
}

function renderReviewView(view: WorkflowView): React.ReactNode {
  switch (view) {
    case 'raw':
      return <ReviewRaw />;
    case 'library':
      return <ReviewLibrary />;
    case 'reader':
      return <ReviewReader />;
    case 'import':
      return <ReviewImport />;
    case 'sources':
      return <ReviewSources />;
    case 'glossary':
      return <ReviewGlossary />;
    case 'providers':
      return <ReviewProviders />;
    case 'jobs':
      return <ReviewJobs />;
    case 'status':
      return <ReviewStatus />;
    case 'export':
      return <ReviewExport />;
    case 'workbench':
    default:
      return <ReviewWorkbench />;
  }
}

export default function ReviewModeApp({ apiBaseUrl }: Props) {
  const [activeView, setActiveView] = useState<WorkflowView>('workbench');

  return (
    <WorkflowShell
      activeView={activeView}
      apiBaseUrl={`${apiBaseUrl} · review only`}
      apiStatus="ready"
      onLogout={() => {
        window.location.href = '/';
      }}
      onOpenImport={() => setActiveView('import')}
      onViewChange={setActiveView}
      renderView={renderReviewView}
    />
  );
}
