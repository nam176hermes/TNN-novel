import { Loader2 } from 'lucide-react';
import type { EbookPreview } from '../../api/types';
import { formatBytes } from './importLabels';
import type { EbookPreviewFile, EbookPreviewState } from './types';

function ebookSplitMethodLabel(preview: EbookPreview): string {
  const warnings = preview.warnings ?? [];
  if (preview.split_method !== 'toc' && warnings.some((warning) => warning.type === 'toc_unmapped')) {
    return 'Có mục lục nhưng không map được chapter';
  }
  if (preview.split_method === 'toc') {
    const tocCount = preview.toc_chapter_count ?? preview.chapter_count;
    return `Tách theo mục lục: ${tocCount.toLocaleString()} chương`;
  }
  if (preview.split_method === 'single') {
    return 'Import thành một chương';
  }
  if (preview.split_method === 'heading') {
    return 'Không tìm thấy mục lục, dùng heading fallback';
  }
  if (preview.split_method === 'regex') {
    return 'Tách bằng heading TXT/HTML';
  }
  if (preview.split_method === 'spine') {
    return 'Không tìm thấy mục lục, dùng spine fallback';
  }
  return 'Tự động: ưu tiên mục lục';
}

function ebookDuplicateStrategySummary(dryRun: NonNullable<EbookPreview['dry_run']>): string {
  if (dryRun.duplicate_strategy === 'error') {
    if (dryRun.would_error === 0) {
      return `Chiến lược đã chọn: Dừng khi trùng. Không có chương trùng; sẽ import ${dryRun.would_import.toLocaleString('vi-VN')} chương mới.`;
    }
    return `Chiến lược đã chọn: Dừng khi trùng. Có ${dryRun.would_import.toLocaleString('vi-VN')} chương mới và ${dryRun.would_error.toLocaleString('vi-VN')} chương trùng. Import sẽ dừng khi gặp chương trùng; các chương đứng trước đó có thể đã được import.`;
  }
  if (dryRun.duplicate_strategy === 'overwrite') {
    return `Chiến lược đã chọn: Ghi đè chương trùng. Sẽ import ${dryRun.would_import.toLocaleString('vi-VN')} chương, gồm ghi đè ${dryRun.would_overwrite.toLocaleString('vi-VN')} chương trùng.`;
  }
  return `Chiến lược đã chọn: Bỏ qua chương trùng. Sẽ import ${dryRun.would_import.toLocaleString('vi-VN')} chương mới và bỏ qua ${dryRun.would_skip.toLocaleString('vi-VN')} chương trùng.`;
}

export function EbookPreviewPanel({
  confirmedExistingBookId,
  error,
  file,
  onConfirmedExistingBookIdChange,
  onRetry,
  preview,
  retryDisabled,
  state,
}: {
  confirmedExistingBookId: number | null;
  error: string;
  file: EbookPreviewFile | null;
  onConfirmedExistingBookIdChange: (bookId: number | null) => void;
  onRetry: () => void;
  preview: EbookPreview | null;
  retryDisabled: boolean;
  state: EbookPreviewState;
}) {
  if (!file) {
    return <p>Chưa chọn ebook.</p>;
  }

  if (state === 'loading') {
    return (
      <div>
        <p>Đang đọc metadata và mục lục ebook.</p>
        <button className="secondary-action" disabled onClick={onRetry} type="button">
          <Loader2 aria-hidden="true" className="status-spinner" size={15} />
          Preview lại
        </button>
      </div>
    );
  }

  if (state === 'error') {
    return (
      <div>
        <p className="status-error" role="alert">
          {error || 'Không đọc được ebook này.'}
        </p>
        <button className="secondary-action" disabled={retryDisabled} onClick={onRetry} type="button">
          Preview lại
        </button>
      </div>
    );
  }

  if (!preview) {
    return <p>{file.name} · {formatBytes(file.size)}</p>;
  }

  const firstChapters = preview.first_chapters ?? preview.chapters.slice(0, 20);
  const lastChapters = preview.last_chapters ?? (
    preview.chapters.length > 20 ? preview.chapters.slice(-20) : preview.chapters
  );
  const samePreviewWindow =
    firstChapters.length === lastChapters.length
    && firstChapters.every((chapter, index) => {
      const lastChapter = lastChapters[index];
      return lastChapter
        && lastChapter.chapter_number === chapter.chapter_number
        && lastChapter.title === chapter.title;
    });
  const warnings = preview.warnings ?? [];
  const dryRun = preview.dry_run;
  const coverUrl = preview.cover_preview_url || preview.cover_url || '';

  function renderChapterList(label: string, chapters: EbookPreview['chapters']) {
    return (
      <section className="ebook-preview-section">
        <h5>{label}</h5>
        <ol className="ebook-preview-chapters">
          {chapters.map((chapter) => (
            <li key={`${label}-${chapter.chapter_number}-${chapter.title}`}>
              <div>
                <span>#{chapter.chapter_number}</span>
                <strong>{chapter.title || `Chương ${chapter.chapter_number}`}</strong>
              </div>
              <p>{chapter.sample || 'Không có sample.'}</p>
            </li>
          ))}
        </ol>
      </section>
    );
  }

  return (
    <div className="ebook-preview-card">
      {error ? (
        <p className="status-error" role="alert">
          {error}
        </p>
      ) : null}
      <div className="ebook-preview-header">
        {coverUrl ? (
          <img
            alt={`Bìa ${preview.title || file.name}`}
            className="ebook-preview-cover"
            src={coverUrl}
          />
        ) : null}
        <div>
          <p className="section-label">{preview.source_format.toUpperCase()} preview</p>
          <h4>{preview.title || file.name}</h4>
        </div>
        <span className="status-chip status-chip-success">{preview.chapter_count.toLocaleString()} chương</span>
      </div>
      <dl className="ebook-preview-meta">
        <div>
          <dt>Tác giả</dt>
          <dd>{preview.author || 'Không rõ'}</dd>
        </div>
        <div>
          <dt>Ngôn ngữ</dt>
          <dd>{preview.language || 'Không rõ'}</dd>
        </div>
        <div>
          <dt>Cover</dt>
          <dd>{preview.cover_present ? 'Có' : 'Không'}</dd>
        </div>
        <div>
          <dt>Cách tách</dt>
          <dd>{ebookSplitMethodLabel(preview)}</dd>
        </div>
      </dl>
      {dryRun ? (
        <>
          <dl className="ebook-dry-run">
            <div>
              <dt>Chương mới</dt>
              <dd>{dryRun.new_chapters.toLocaleString()}</dd>
            </div>
            <div>
              <dt>Chương trùng</dt>
              <dd>{dryRun.duplicate_chapters.toLocaleString()}</dd>
            </div>
            <div>
              <dt>Khi import</dt>
              <dd>
                <span>Sẽ import {dryRun.would_import.toLocaleString()} chương</span>
                {dryRun.would_skip ? <span>Bỏ qua {dryRun.would_skip.toLocaleString()} chương trùng</span> : null}
                {dryRun.would_overwrite ? <span>Ghi đè {dryRun.would_overwrite.toLocaleString()} chương trùng</span> : null}
                {dryRun.would_error ? <span>Sẽ dừng vì {dryRun.would_error.toLocaleString()} chương trùng</span> : null}
              </dd>
            </div>
          </dl>
          {dryRun.requires_existing_book_confirmation ? (
            <section className="ebook-preview-warnings" role="alert">
              <h5>
                {dryRun.book_match_reason === 'title'
                  ? 'Truyện này đã có trong Library'
                  : 'Sẽ gộp vào truyện đã chọn'}
              </h5>
              <p>
                {dryRun.existing_book_title} · {dryRun.existing_chapter_count.toLocaleString('vi-VN')} chương hiện có
              </p>
              <p>
                {dryRun.new_chapters.toLocaleString('vi-VN')} chương mới ·{' '}
                {dryRun.duplicate_chapters.toLocaleString('vi-VN')} chương trùng
              </p>
              <p>{ebookDuplicateStrategySummary(dryRun)}</p>
              <label>
                <input
                  checked={dryRun.existing_book_id !== null && confirmedExistingBookId === dryRun.existing_book_id}
                  onChange={(event) => onConfirmedExistingBookIdChange(
                    event.target.checked ? dryRun.existing_book_id : null,
                  )}
                  type="checkbox"
                />
                <span>Tôi xác nhận gộp ebook này vào truyện đã có.</span>
              </label>
            </section>
          ) : null}
        </>
      ) : null}
      {warnings.length > 0 ? (
        <section className="ebook-preview-warnings" aria-label="Cảnh báo preview">
          <h5>Cảnh báo preview</h5>
          <ul>
            {warnings.map((warning, index) => (
              <li key={`${warning.type}-${warning.chapter_number ?? index}-${warning.message}`}>
                {warning.message}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {renderChapterList(`${firstChapters.length} chương đầu`, firstChapters)}
      {samePreviewWindow ? null : renderChapterList(`${lastChapters.length} chương cuối`, lastChapters)}
    </div>
  );
}

export function EbookImportFlow({
  canImport,
  previewState,
  selectedFile,
}: {
  canImport: boolean;
  previewState: EbookPreviewState;
  selectedFile: EbookPreviewFile | null;
}) {
  const steps = [
    {
      label: '1. Chọn nguồn',
      detail: selectedFile ? selectedFile.name : 'Tải file hoặc chọn từ server inbox',
      state: selectedFile ? 'done' : 'active',
    },
    {
      label: '2. Preview mục lục',
      detail:
        previewState === 'ready'
          ? 'Đã đọc metadata, cover và chương mẫu'
          : previewState === 'loading'
            ? 'Đang đọc ebook'
            : previewState === 'error'
              ? 'Cần sửa lỗi preview'
              : 'Preview trước khi import',
      state: previewState === 'ready' ? 'done' : previewState === 'loading' ? 'active' : 'pending',
    },
    {
      label: '3. Import vào Library',
      detail: canImport ? 'Sẵn sàng thêm vào thư viện đã dịch' : 'Hoàn tất preview để mở khóa import',
      state: canImport ? 'active' : 'pending',
    },
  ];

  return (
    <ol aria-label="Luồng import ebook" className="ebook-import-flow">
      {steps.map((step) => (
        <li data-state={step.state} key={step.label}>
          <span className="ebook-step-number" aria-hidden="true">{step.label.split('.')[0]}</span>
          <div>
            <strong>
              <span className="sr-only">{step.label}</span>
              <span aria-hidden="true">{step.label.replace(/^\d+\.\s*/, '')}</span>
            </strong>
            <span>{step.detail}</span>
          </div>
        </li>
      ))}
    </ol>
  );
}

