import {
  BookOpenText,
  Check,
  Download,
  FileText,
  Info,
  NotebookText,
} from 'lucide-react';
import { useState } from 'react';
import exportDocxIcon from '../assets/reference-ui/export-docx.png';
import exportEpubIcon from '../assets/reference-ui/export-epub.png';
import exportTxtIcon from '../assets/reference-ui/export-txt.png';
import type { BookSummary, ExportFormat, ExportResponse } from '../api/types';

export type ExportViewProps = {
  activeBookId: number | null;
  books: BookSummary[];
  error?: string;
  lastExport: ExportResponse | null;
  loading?: boolean;
  audioBatchBusy?: boolean;
  onBookChange(bookId: number): void;
  onCreateAudioBatch?(bookId: number, missingAudioCount: number): void | Promise<void>;
  onExport(format: ExportFormat): void | Promise<void>;
};

const formats: Array<{
  format: ExportFormat;
  label: string;
  detail: string;
  icon: string;
}> = [
  { format: 'txt', label: 'TXT', detail: 'Plain text', icon: exportTxtIcon },
  { format: 'docx', label: 'DOCX', detail: 'Word document', icon: exportDocxIcon },
  { format: 'epub', label: 'EPUB', detail: 'Ebook reader', icon: exportEpubIcon },
];

function formatBytes(sizeBytes: number): string {
  if (sizeBytes < 1024) return `${sizeBytes} B`;
  if (sizeBytes < 1024 * 1024) return `${(sizeBytes / 1024).toFixed(1)} KB`;
  return `${(sizeBytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function ExportView({
  activeBookId,
  books,
  error = '',
  lastExport,
  loading = false,
  audioBatchBusy = false,
  onBookChange,
  onCreateAudioBatch,
  onExport,
}: ExportViewProps) {
  const [helpOpen, setHelpOpen] = useState(false);
  const activeBook = books.find((book) => book.id === activeBookId) ?? null;
  const canExport = Boolean(activeBook && activeBook.translated > 0 && !loading);
  const missingAudioCount = activeBook ? Math.max(0, activeBook.translated - activeBook.audio) : 0;
  const canCreateAudioBatch = Boolean(activeBook && missingAudioCount > 0 && !audioBatchBusy && !loading);

  return (
    <section aria-labelledby="export-view-title" className="workflow-management-view export-view">
      <header className="panel workbench-title">
        <div>
          <p className="section-label">
            Book Export <span>/ Xuất file</span>
          </p>
          <h2 id="export-view-title">Xuất file</h2>
          <p className="view-subtitle">Xuất sách để đọc/nghe. Không phải backup hệ thống.</p>
        </div>
        <button
          aria-expanded={helpOpen}
          className="secondary-action help-action"
          onClick={() => setHelpOpen((current) => !current)}
          type="button"
        >
          <Info aria-hidden="true" size={16} />
          Hướng dẫn
        </button>
      </header>

      {helpOpen ? (
        <section aria-label="Hướng dẫn xuất file" className="panel inline-help-panel">
          <p>
            Chọn truyện đã có bản dịch, chọn TXT/DOCX/EPUB, rồi bấm bắt đầu xuất.
            File sẽ được tải qua trình duyệt sau khi backend tạo xong. Backup hệ thống nằm ở trang Trạng thái.
          </p>
        </section>
      ) : null}

      <section aria-labelledby="export-book-title" className="panel export-panel">
        <div className="panel-header">
          <h3 id="export-book-title">Chọn truyện</h3>
        </div>

        <label className="export-book-picker">
          <span>Book</span>
          <select
            disabled={books.length === 0 || loading}
            onChange={(event) => onBookChange(Number(event.target.value))}
            value={activeBookId ?? ''}
          >
            <option disabled value="">
              No book selected
            </option>
            {books.map((book) => (
              <option key={book.id} value={book.id}>
                {book.title}
              </option>
            ))}
          </select>
        </label>

        {activeBook ? (
          <dl className="run-stats export-stats">
            <div>
              <FileText aria-hidden="true" size={22} />
              <dt>Chapters</dt>
              <dd>{activeBook.total}</dd>
            </div>
            <div>
              <BookOpenText aria-hidden="true" size={22} />
              <dt>Translated</dt>
              <dd>{activeBook.translated}</dd>
            </div>
            <div>
              <NotebookText aria-hidden="true" size={22} />
              <dt>Audio</dt>
              <dd>{activeBook.audio}</dd>
            </div>
          </dl>
        ) : (
          <p className="empty-detail">No book available.</p>
        )}
      </section>

      <section aria-labelledby="export-format-title" className="panel">
        <div className="panel-header">
          <div>
            <p className="section-label">Format</p>
            <h3 id="export-format-title">Tải bản dịch</h3>
          </div>
        </div>

        <div className="export-format-grid">
          {formats.map((item) => (
            <button
              className="export-format-button"
              disabled={!canExport}
              key={item.format}
              onClick={() => {
                void onExport(item.format);
              }}
              type="button"
            >
              <span className="export-format-check" aria-hidden="true">
                <Check size={18} />
              </span>
              <img alt="" aria-hidden="true" className="export-format-icon export-format-image" src={item.icon} />
              <span>{item.label}</span>
              <small>{item.detail}</small>
              <em>Chuẩn bị</em>
            </button>
          ))}
        </div>

        {loading ? <p className="status-chip">Đang xuất file</p> : null}
        {error ? <p className="status-error">{error}</p> : null}
        {lastExport ? (
          <p className="export-result">
            {lastExport.filename} · {lastExport.chapter_count} chapters · {formatBytes(lastExport.size_bytes)}
          </p>
        ) : null}
      </section>

      <section aria-labelledby="export-options-title" className="panel export-options-panel">
        <div className="panel-header">
          <div>
            <p className="section-label">Không thể thay đổi</p>
            <h3 id="export-options-title">Thiết lập cố định</h3>
          </div>
        </div>
        <dl className="export-fixed-options">
          <div><dt>Phạm vi chương</dt><dd>Tất cả chương đã dịch</dd></div>
          <div><dt>Chú thích</dt><dd>Không kèm chú thích trong file sách</dd></div>
          <div><dt>Bìa sách</dt><dd>Không kèm bìa sách</dd></div>
          <div><dt>Mục lục</dt><dd>Theo mặc định của định dạng đã chọn</dd></div>
        </dl>
      </section>

      <section aria-label="Export notice" className="panel export-action-panel">
        <div className="export-notice">
          <Info aria-hidden="true" size={22} />
          <div>
            <strong>Lưu ý</strong>
            <ul>
              <li>Quá trình xuất có thể mất vài phút tùy vào số lượng chương.</li>
              <li>File sẽ được tải về trình duyệt sau khi quá trình hoàn tất.</li>
            </ul>
          </div>
        </div>
        <div className="export-start-area">
          <button
            className="secondary-action export-start-button"
            disabled={!canCreateAudioBatch || !onCreateAudioBatch}
            onClick={() => {
              if (activeBook) void onCreateAudioBatch?.(activeBook.id, missingAudioCount);
            }}
            type="button"
          >
            <Download aria-hidden="true" size={18} />
            {audioBatchBusy ? 'Đang tạo job audio...' : 'Tạo audio hàng loạt'}
          </button>
          <span>
            {activeBook
              ? missingAudioCount > 0
                ? `${missingAudioCount.toLocaleString()} chương đã dịch chưa có audio`
                : 'Audio đã đủ cho các chương đã dịch'
              : 'Chưa chọn truyện'}
          </span>
          <button
            className="primary-action export-start-button"
            disabled={!canExport}
            onClick={() => {
              void onExport('txt');
            }}
            type="button"
          >
            <Download aria-hidden="true" size={18} />
            Bắt đầu xuất
          </button>
          <span>{canExport ? 'Sẵn sàng để xuất file' : 'Chưa sẵn sàng để xuất file'}</span>
        </div>
      </section>
    </section>
  );
}
