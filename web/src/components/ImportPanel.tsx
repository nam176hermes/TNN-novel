import {
  ArrowRight,
  BookOpen,
  CircleHelp,
  Clipboard,
  FileText,
  Globe2,
  Inbox,
  Lightbulb,
  Loader2,
  Search,
  Upload,
  UploadCloud,
} from 'lucide-react';
import { useMemo, useRef, useState, type ChangeEvent, type DragEvent, type FormEvent } from 'react';
import { ApiError } from '../api/client';
import type {
  EbookDuplicateStrategy,
  EbookInboxFile,
  EbookImportHistoryRun,
  EbookImportRequest,
  EbookImportResult,
  EbookPreview,
  EbookSplitMode,
  ImportFileRequest,
  ImportPasteRequest,
  ImportUrlRequest,
  JobStartResponse,
  SourceCatalogList,
  SourceCatalogQuery,
  SourcePreview,
  WizardTextImportRequest,
  WizardTextImportResult,
} from '../api/types';
import {
  buildImportPreview,
  detectImportContentKind,
  type DetectedImportChapter,
  type ImportContentKind,
} from '../state/importWizard';
import { detectImportMetadata, type DetectedImportMetadata } from '../state/importMetadata';

export type ImportPanelProps = {
  onImportPaste: (request: ImportPasteRequest) => Promise<void> | void;
  onImportFile?: (request: ImportFileRequest) => Promise<void> | void;
  onImportWizardText?: (
    request: WizardTextImportRequest,
    options?: { finalAction: FinalImportAction },
  ) => Promise<WizardTextImportResult | void> | void;
  onPreviewTranslatedEbook?: (
    file: File,
    splitMode: EbookSplitMode,
    options?: { duplicateStrategy?: EbookDuplicateStrategy; targetBookId?: number | null },
  ) => Promise<EbookPreview>;
  onPreviewInboxEbook?: (
    filename: string,
    splitMode: EbookSplitMode,
    options?: { duplicateStrategy?: EbookDuplicateStrategy; targetBookId?: number | null },
  ) => Promise<EbookPreview>;
  onImportTranslatedEbook?: (request: EbookImportRequest) => Promise<EbookImportResult | void> | void;
  onPreviewImportUrl?: (url: string) => Promise<SourcePreview>;
  onStartImportUrlJob?: (request: ImportUrlRequest) => Promise<JobStartResponse | void> | void;
  onCreateTranslationJob?: (bookId: number, chapterIds: number[]) => Promise<JobStartResponse | void> | void;
  onCreateTtsJob?: (bookId: number, chapterIds: number[]) => Promise<JobStartResponse | void> | void;
  loadSourceCatalog?: (params: SourceCatalogQuery) => Promise<SourceCatalogList>;
  onOpenImportedBook?: (result: WizardTextImportResult) => void;
  onOpenJob?: (jobId: string) => void;
  onCancel: () => void;
  books?: Array<{ id: number; title: string }>;
  chapters?: Array<{ book_id: number; chapter_number: number; title?: string }>;
  ebookInboxDirectory?: string;
  ebookInboxError?: string;
  ebookInboxFiles?: EbookInboxFile[];
  ebookImportHistory?: EbookImportHistoryRun[];
  loading?: boolean;
  onRefreshEbookInbox?: () => Promise<void> | void;
};

type ImportMode = 'paste' | 'file' | 'ebook' | 'url' | 'catalog';
type EbookSource = 'upload' | 'inbox';
type EbookPreviewState = 'idle' | 'loading' | 'ready' | 'error';
type EbookPreviewFile = Pick<File, 'name' | 'size'>;
type FinalImportAction = 'save' | 'open' | 'translate' | 'tts';

const CJK_CHARACTER_PATTERN = /[\u3400-\u4dbf\u4e00-\u9fff]/g;
const EBOOK_ACCEPT = '.epub,.azw3,.mobi,.prc,.txt,.html,.htm,application/epub+zip,text/plain,text/html';
const MAX_BROWSER_EBOOK_UPLOAD_BYTES = 95 * 1024 * 1024;
const MAX_BROWSER_TEXT_UPLOAD_BYTES = 5 * 1024 * 1024;
const TEXT_IMPORT_SUFFIXES = new Set(['.txt', '.md', '.markdown', '.html', '.htm']);
const TEXT_IMPORT_MIME_TYPES = new Set(['', 'text/plain', 'text/markdown', 'text/html']);
const BLOCKING_EBOOK_WARNING_TYPES = new Set(['unreadable_ebook']);

function formatBytes(value: number): string {
  if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  if (value >= 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${value.toLocaleString()} bytes`;
}

function textByteLength(value: string): number {
  return new TextEncoder().encode(value).length;
}

function hasUnsupportedEncodingMarkers(value: string): boolean {
  const replacementCount = value.match(/\uFFFD/g)?.length ?? 0;
  if (replacementCount === 0) return false;
  return replacementCount > Math.max(4, value.length * 0.01);
}

function sourceTextStats(value: string) {
  const trimmed = value.trim();
  const lines = trimmed ? trimmed.split(/\r?\n/).filter((line) => line.trim()).length : 0;
  return {
    characters: trimmed.length,
    cjkCharacters: trimmed.match(CJK_CHARACTER_PATTERN)?.length ?? 0,
    lines,
  };
}

function isSupportedTextImportFile(file: File): boolean {
  const lowered = file.name.toLowerCase();
  const dotIndex = lowered.lastIndexOf('.');
  const suffix = dotIndex >= 0 ? lowered.slice(dotIndex) : '';
  return TEXT_IMPORT_SUFFIXES.has(suffix) && TEXT_IMPORT_MIME_TYPES.has(file.type);
}

function PasteTextStatus({
  canImport,
  chapterNumber,
  chapterTitle,
  text,
  title,
}: {
  canImport: boolean;
  chapterNumber: string;
  chapterTitle: string;
  text: string;
  title: string;
}) {
  const stats = sourceTextStats(text);
  const hasText = stats.characters > 0;
  const hasTitle = title.trim().length > 0;
  if (!hasText) return null;

  const chapterLabel = chapterTitle.trim()
    ? `#${chapterNumber || '1'} · ${chapterTitle.trim()}`
    : `#${chapterNumber || '1'}`;

  return (
    <section aria-labelledby="paste-status-title" className="paste-status-panel">
      <div className="paste-status-header">
        <Loader2 aria-hidden="true" className="status-spinner" size={36} />
        <div>
          <p className="section-label">Trạng thái xử lý</p>
          <h4 id="paste-status-title">{canImport ? 'Ready to import' : 'Missing metadata'}</h4>
          <p>Đã nhận nội dung, kiểm tra metadata trước khi import.</p>
        </div>
        <span className={`status-chip ${canImport ? 'status-chip-success' : 'status-chip-warning'}`}>
          {canImport ? 'Ready' : 'Needs title'}
        </span>
      </div>
      <dl className="paste-status-grid">
        <div>
          <dt>Source text</dt>
          <dd>
            {stats.characters.toLocaleString()} chars · {stats.lines.toLocaleString()} lines · {stats.cjkCharacters.toLocaleString()} Chinese chars
          </dd>
        </div>
        <div>
          <dt>Book</dt>
          <dd>{hasTitle ? title.trim() : 'Book title is missing'}</dd>
        </div>
        <div>
          <dt>Chapter</dt>
          <dd>{chapterLabel}</dd>
        </div>
      </dl>
    </section>
  );
}

function FileImportStatus({
  chapterNumber,
  chapterTitle,
  file,
  title,
}: {
  chapterNumber: string;
  chapterTitle: string;
  file: File | null;
  title: string;
}) {
  const hasTitle = title.trim().length > 0;
  if (!file) return null;

  const chapterLabel = chapterTitle.trim()
    ? `#${chapterNumber || '1'} · ${chapterTitle.trim()}`
    : `#${chapterNumber || '1'}`;

  return (
    <section aria-label="Import preview" className="import-preview paste-status-panel file-status-panel">
      <div className="paste-status-header">
        <Loader2 aria-hidden="true" className="status-spinner" size={36} />
        <div>
          <p className="section-label">Trạng thái xử lý</p>
          <h4>Ready to import</h4>
          <p>File đã sẵn sàng, kiểm tra metadata trước khi import.</p>
        </div>
        <span className="status-chip status-chip-success">Ready</span>
      </div>
      <dl className="paste-status-grid">
        <div>
          <dt>Source file</dt>
          <dd>{file.name}</dd>
        </div>
        <div>
          <dt>Kích thước</dt>
          <dd>{formatBytes(file.size)}</dd>
        </div>
        <div>
          <dt>Book</dt>
          <dd>{hasTitle ? title.trim() : 'Book title is missing'}</dd>
        </div>
        <div>
          <dt>Chapter</dt>
          <dd>{chapterLabel}</dd>
        </div>
      </dl>
    </section>
  );
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

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
    return `Chiến lược đã chọn: Dừng khi trùng. Sẽ dừng vì ${dryRun.would_error.toLocaleString('vi-VN')} chương trùng; chưa import chương nào.`;
  }
  if (dryRun.duplicate_strategy === 'overwrite') {
    return `Chiến lược đã chọn: Ghi đè chương trùng. Sẽ import ${dryRun.would_import.toLocaleString('vi-VN')} chương, gồm ghi đè ${dryRun.would_overwrite.toLocaleString('vi-VN')} chương trùng.`;
  }
  return `Chiến lược đã chọn: Bỏ qua chương trùng. Sẽ import ${dryRun.would_import.toLocaleString('vi-VN')} chương mới và bỏ qua ${dryRun.would_skip.toLocaleString('vi-VN')} chương trùng.`;
}

function EbookPreviewPanel({
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
    return <p>No ebook selected.</p>;
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

function EbookImportFlow({
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
      detail: selectedFile ? selectedFile.name : 'Upload file hoặc chọn từ Server inbox',
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

function contentKindLabel(value: ImportContentKind): string {
  if (value === 'raw') return 'Raw tiếng Trung';
  if (value === 'translated') return 'Bản dịch tiếng Việt';
  if (value === 'both') return 'Có cả raw và bản dịch';
  return 'Chưa xác định';
}

function WizardSteps({ activeStep }: { activeStep: number }) {
  const steps = [
    ['Chọn nguồn', 'Paste, TXT, EPUB, URL hoặc kho nguồn'],
    ['Phát hiện cấu trúc', 'Tựa truyện, ngôn ngữ, danh sách chương'],
    ['Làm sạch & preview', 'Kiểm tra cảnh báo và sửa metadata'],
    ['Chọn hành động', 'Lưu, dịch hoặc tạo audio'],
  ];

  return (
    <ol aria-label="Import wizard steps" className="import-wizard-steps">
      {steps.map(([label, detail], index) => {
        const stepNumber = index + 1;
        const state = stepNumber < activeStep ? 'done' : stepNumber === activeStep ? 'active' : 'pending';
        return (
          <li data-state={state} key={label}>
            <span className="ebook-step-number" aria-hidden="true">{stepNumber}</span>
            <div>
              <strong>{label}</strong>
              <span>{detail}</span>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function TextWizardPreview({
  chapters,
  contentKind,
  detectedKind,
  duplicateCount,
  onChapterEdit,
  warnings,
}: {
  chapters: DetectedImportChapter[];
  contentKind: ImportContentKind;
  detectedKind: ImportContentKind;
  duplicateCount: number;
  warnings: Array<{ type: string; message: string }>;
  onChapterEdit: (index: number, field: 'chapterNumber' | 'title', value: string) => void;
}) {
  if (chapters.length === 0) return null;

  return (
    <section aria-label="Wizard structure preview" className="import-preview wizard-preview-card">
      <div className="ebook-preview-header">
        <div>
          <p className="section-label">Step 2 · Detect structure</p>
          <h4>{chapters.length.toLocaleString('vi-VN')} chương được phát hiện</h4>
        </div>
        <span className={`status-chip ${contentKind === 'unknown' ? 'status-chip-warning' : 'status-chip-success'}`}>
          {contentKindLabel(contentKind)}
        </span>
      </div>
      <dl className="ebook-preview-meta">
        <div>
          <dt>Phát hiện</dt>
          <dd>{contentKindLabel(detectedKind)}</dd>
        </div>
        <div>
          <dt>Trùng chương</dt>
          <dd>{duplicateCount.toLocaleString('vi-VN')}</dd>
        </div>
        <div>
          <dt>Chương đầu</dt>
          <dd>{chapters[0]?.title || `Chương ${chapters[0]?.chapterNumber ?? 1}`}</dd>
        </div>
        <div>
          <dt>Chương cuối</dt>
          <dd>
            {chapters[chapters.length - 1]?.title || `Chương ${chapters[chapters.length - 1]?.chapterNumber ?? 1}`}
          </dd>
        </div>
      </dl>
      {warnings.length > 0 ? (
        <section className="ebook-preview-warnings" aria-label="Cảnh báo import">
          <h5>Cảnh báo trước khi lưu</h5>
          <ul>
            {warnings.map((warning, index) => (
              <li key={`${warning.type}-${index}`}>{warning.message}</li>
            ))}
          </ul>
        </section>
      ) : null}
      <section className="ebook-preview-section">
        <h5>Preview 3 chương đầu</h5>
        <ol className="ebook-preview-chapters">
          {chapters.slice(0, 3).map((chapter, index) => (
            <li key={`${chapter.chapterNumber}-${chapter.startChar}-${index}`}>
              <div className="wizard-chapter-edit-row">
                <label>
                  <span>Số chương</span>
                  <input
                    defaultValue={chapter.chapterNumber}
                    min="1"
                    onChange={(event) => onChapterEdit(index, 'chapterNumber', event.target.value)}
                    type="number"
                  />
                </label>
                <label>
                  <span>Tiêu đề</span>
                  <input
                    defaultValue={chapter.title}
                    onChange={(event) => onChapterEdit(index, 'title', event.target.value)}
                    type="text"
                  />
                </label>
              </div>
              <p>{chapter.text.slice(0, 220) || 'Không có preview.'}</p>
            </li>
          ))}
        </ol>
      </section>
    </section>
  );
}

export default function ImportPanel({
  books = [],
  chapters = [],
  ebookInboxDirectory = 'inbox/ebooks',
  ebookInboxError = '',
  ebookInboxFiles = [],
  onImportPaste,
  onImportFile,
  onImportWizardText,
  onPreviewInboxEbook,
  onPreviewTranslatedEbook,
  onImportTranslatedEbook,
  onPreviewImportUrl,
  onStartImportUrlJob,
  onCreateTranslationJob,
  onCreateTtsJob,
  loadSourceCatalog,
  onOpenImportedBook,
  onOpenJob,
  onCancel,
  ebookImportHistory = [],
  loading = false,
  onRefreshEbookInbox,
}: ImportPanelProps) {
  const [mode, setMode] = useState<ImportMode>('paste');
  const [title, setTitle] = useState('');
  const [chapterNumber, setChapterNumber] = useState('1');
  const [chapterTitle, setChapterTitle] = useState('');
  const [text, setText] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [titleDirty, setTitleDirty] = useState(false);
  const [chapterNumberDirty, setChapterNumberDirty] = useState(false);
  const [chapterTitleDirty, setChapterTitleDirty] = useState(false);
  const [ebookSource, setEbookSource] = useState<EbookSource>('upload');
  const [ebookFile, setEbookFile] = useState<File | null>(null);
  const [selectedInboxFile, setSelectedInboxFile] = useState('');
  const [ebookPreview, setEbookPreview] = useState<EbookPreview | null>(null);
  const [ebookPreviewState, setEbookPreviewState] = useState<EbookPreviewState>('idle');
  const [ebookPreviewError, setEbookPreviewError] = useState('');
  const [confirmedExistingBookId, setConfirmedExistingBookId] = useState<number | null>(null);
  const [ebookSubmissionBlocked, setEbookSubmissionBlocked] = useState(false);
  const ebookPreviewRequestToken = useRef(0);
  const [lastEbookImportResult, setLastEbookImportResult] = useState<EbookImportResult | null>(null);
  const [duplicateStrategy, setDuplicateStrategy] = useState<EbookDuplicateStrategy>('skip');
  const [targetBookId, setTargetBookId] = useState('');
  const [splitMode, setSplitMode] = useState<EbookSplitMode>('auto');
  const [helpOpen, setHelpOpen] = useState(false);
  const [fileText, setFileText] = useState('');
  const [contentKind, setContentKind] = useState<ImportContentKind>('unknown');
  const [finalAction, setFinalAction] = useState<FinalImportAction>('open');
  const [overwriteConfirmed, setOverwriteConfirmed] = useState(false);
  const [chapterEdits, setChapterEdits] = useState<Record<number, { chapterNumber?: string; title?: string }>>({});
  const [lastWizardResult, setLastWizardResult] = useState<WizardTextImportResult | null>(null);
  const [lastCreatedJob, setLastCreatedJob] = useState<JobStartResponse | null>(null);
  const [wizardError, setWizardError] = useState('');
  const [sourceUrl, setSourceUrl] = useState('');
  const [sourcePreview, setSourcePreview] = useState<SourcePreview | null>(null);
  const [sourcePreviewState, setSourcePreviewState] = useState<EbookPreviewState>('idle');
  const [sourcePreviewError, setSourcePreviewError] = useState('');
  const [catalogQuery, setCatalogQuery] = useState('');
  const [catalogState, setCatalogState] = useState<EbookPreviewState>('idle');
  const [catalogError, setCatalogError] = useState('');
  const [catalog, setCatalog] = useState<SourceCatalogList | null>(null);

  const parsedChapterNumber = Number.parseInt(chapterNumber, 10);
  const selectedInboxEntry = ebookInboxFiles.find((entry) => entry.name === selectedInboxFile) ?? null;
  const selectedEbookFile: EbookPreviewFile | null =
    ebookSource === 'inbox'
      ? selectedInboxEntry
        ? { name: selectedInboxEntry.name, size: selectedInboxEntry.size }
        : null
      : ebookFile;
  const importFields = {
    title,
    chapter_number: Number.isNaN(parsedChapterNumber) ? 1 : parsedChapterNumber,
    chapter_title: chapterTitle,
  };
  const textDraft = mode === 'file' ? fileText : text;
  const selectedTargetBookId = targetBookId ? Number.parseInt(targetBookId, 10) : null;
  const inferredTargetBook = !selectedTargetBookId && title.trim()
    ? books.find((book) => book.title.trim().toLowerCase() === title.trim().toLowerCase())
    : null;
  const effectiveTargetBookId = selectedTargetBookId ?? inferredTargetBook?.id ?? null;
  const existingChaptersForTarget = useMemo(
    () => (
      effectiveTargetBookId
        ? chapters.filter((chapter) => chapter.book_id === effectiveTargetBookId)
        : []
    ),
    [chapters, effectiveTargetBookId],
  );
  const textPreview = useMemo(
    () => (
      textDraft.trim()
        ? buildImportPreview({
          text: textDraft,
          selectedKind: contentKind,
          existingChapters: existingChaptersForTarget,
        })
        : null
    ),
    [contentKind, existingChaptersForTarget, textDraft],
  );
  const ebookHasBlockingWarning = Boolean(
    ebookPreview?.warnings?.some((warning) => BLOCKING_EBOOK_WARNING_TYPES.has(warning.type)),
  );
  const existingBookId = ebookPreview?.dry_run?.existing_book_id ?? null;
  const requiresExistingBookConfirmation = Boolean(
    ebookPreview?.dry_run?.requires_existing_book_confirmation,
  );
  const existingBookConfirmed = !requiresExistingBookConfirmation
    || (existingBookId !== null && confirmedExistingBookId === existingBookId);
  const ebookPreviewRetryAvailable =
    !loading
    && ebookPreviewState !== 'loading'
    && (ebookSource === 'inbox'
      ? Boolean(selectedInboxFile && onPreviewInboxEbook)
      : Boolean(
        ebookFile
        && ebookFile.size <= MAX_BROWSER_EBOOK_UPLOAD_BYTES
        && onPreviewTranslatedEbook,
      ));
  const titleReady = title.trim().length > 0;
  const pastedTextReady = text.trim().length > 0;
  const wizardDuplicateCount = textPreview?.duplicateChapterNumbers.length ?? 0;
  const overwriteNeedsConfirmation =
    Boolean(onImportWizardText)
    && (mode === 'paste' || mode === 'file')
    && duplicateStrategy === 'overwrite'
    && wizardDuplicateCount > 0
    && !overwriteConfirmed;
  const canSubmit =
    !loading
    && !overwriteNeedsConfirmation
    && (mode === 'paste'
      ? titleReady && pastedTextReady && (!onImportWizardText || (contentKind !== 'unknown' && contentKind !== 'both'))
      : mode === 'file'
        ? onImportWizardText
          ? titleReady && Boolean(file) && fileText.trim().length > 0 && contentKind !== 'unknown' && contentKind !== 'both'
          : titleReady && Boolean(file && onImportFile)
        : mode === 'url'
          ? Boolean(sourcePreview && sourcePreviewState === 'ready' && sourcePreview.automation_allowed && onStartImportUrlJob)
          : mode === 'catalog'
            ? Boolean(sourcePreview && sourcePreviewState === 'ready' && sourcePreview.automation_allowed && onStartImportUrlJob)
            : Boolean(
              ebookPreview
              && ebookPreviewState === 'ready'
              && !ebookSubmissionBlocked
              && onImportTranslatedEbook
              && !ebookHasBlockingWarning
              && existingBookConfirmed,
            ));
  const importActionStatusId = 'import-action-status';
  let importActionStatus = 'Ready to import.';
  if (loading) {
    importActionStatus = 'Import is running.';
  } else if (mode === 'paste' && !pastedTextReady) {
    importActionStatus = 'Paste source text to continue.';
  } else if ((mode === 'paste' || mode === 'file') && !titleReady) {
    importActionStatus = 'Book title is required before import.';
  } else if (mode === 'file' && !file) {
    importActionStatus = 'Select a source file to continue.';
  } else if ((mode === 'paste' || mode === 'file') && onImportWizardText && contentKind === 'unknown') {
    importActionStatus = 'Chọn raw tiếng Trung hoặc bản dịch tiếng Việt trước khi lưu.';
  } else if ((mode === 'paste' || mode === 'file') && onImportWizardText && contentKind === 'both') {
    importActionStatus = 'Nội dung có vẻ lẫn raw và bản dịch. Hãy chọn rõ raw hoặc bản dịch trước khi lưu.';
  } else if (overwriteNeedsConfirmation) {
    importActionStatus = 'Xác nhận ghi đè chương trùng trước khi import.';
  } else if (mode === 'url' && !sourcePreview) {
    importActionStatus = 'Preview URL trước khi bắt đầu import.';
  } else if (mode === 'url' && sourcePreviewState === 'error') {
    importActionStatus = 'URL không hợp lệ hoặc bị chặn bởi policy bảo mật.';
  } else if ((mode === 'url' || mode === 'catalog') && sourcePreview && !sourcePreview.automation_allowed) {
    importActionStatus = sourcePreview.automation_reason || 'Chỉ nguồn VERIFIED mới có thể tạo job import tự động.';
  } else if (mode === 'ebook' && ebookSource === 'upload' && !ebookFile) {
    importActionStatus = 'Select an EPUB, AZW3, MOBI, PRC, TXT, or HTML file.';
  } else if (mode === 'ebook' && ebookSource === 'inbox' && !selectedInboxFile) {
    importActionStatus = 'Select an ebook from the server inbox.';
  } else if (mode === 'ebook' && ebookPreviewState === 'loading') {
    importActionStatus = 'Reading ebook preview.';
  } else if (mode === 'ebook' && ebookPreviewState === 'error') {
    importActionStatus = 'Resolve the ebook preview error before import.';
  } else if (mode === 'ebook' && ebookSubmissionBlocked) {
    importActionStatus = 'Chưa xác nhận được trạng thái import. Hãy kiểm tra Jobs hoặc lịch sử trước khi thử lại.';
  } else if (mode === 'ebook' && ebookHasBlockingWarning) {
    importActionStatus = 'Ebook preview không có nội dung chữ đủ để import.';
  } else if (mode === 'ebook' && !ebookPreview) {
    importActionStatus = 'Preview the ebook before import.';
  } else if (mode === 'ebook' && !existingBookConfirmed) {
    importActionStatus = 'Xác nhận gộp ebook vào truyện đã có trước khi import.';
  }
  const panelTitle =
    mode === 'ebook'
      ? 'Ebook bản dịch'
      : mode === 'file'
        ? 'Import source file'
        : mode === 'url'
          ? 'Import từ URL'
          : mode === 'catalog'
            ? 'Kho nguồn'
            : 'Paste source chapter';
  const panelSubtitle =
    mode === 'ebook'
      ? 'Import ebook và thêm vào thư viện.'
      : mode === 'file'
        ? 'Upload file chứa nội dung chương cần import vào hệ thống.'
        : mode === 'url'
          ? 'Preview nguồn được hỗ trợ rồi tạo job import an toàn.'
          : mode === 'catalog'
            ? 'Tìm metadata nguồn, chỉ nguồn được hỗ trợ mới có thể import.'
            : 'Dán nội dung chương từ văn bản bạn có để import vào hệ thống.';
  const submitLabel =
    mode === 'ebook'
      ? 'Import vào Library'
      : mode === 'file'
        ? 'Import file'
        : mode === 'url' || mode === 'catalog'
          ? 'Tạo job import URL'
          : 'Import chapter';
  const wizardActiveStep =
    mode === 'ebook'
      ? ebookPreviewState === 'ready'
        ? 4
        : selectedEbookFile
          ? 2
          : 1
      : mode === 'url' || mode === 'catalog'
        ? sourcePreviewState === 'ready'
          ? 4
          : sourceUrl.trim()
            ? 2
            : 1
        : textPreview
          ? 3
          : 1;

  function applyDetectedMetadata(metadata: DetectedImportMetadata): void {
    if (metadata.title) {
      setTitle((current) => (!titleDirty ? metadata.title : current));
    }
    if (metadata.chapterNumber !== null) {
      setChapterNumber((current) => {
        return !chapterNumberDirty ? String(metadata.chapterNumber) : current;
      });
    }
    if (metadata.chapterTitle) {
      setChapterTitle((current) => (!chapterTitleDirty ? metadata.chapterTitle : current));
    }
  }

  function detectFromSource(nextText: string, filename = ''): void {
    applyDetectedMetadata(
      detectImportMetadata({
        title: titleDirty ? title : '',
        chapterNumber: chapterNumberDirty && !Number.isNaN(parsedChapterNumber) ? parsedChapterNumber : null,
        chapterTitle: chapterTitleDirty ? chapterTitle : '',
        text: nextText,
        filename,
      }),
    );
  }

  function updateDetectedContentKind(nextText: string): void {
    const detected = detectImportContentKind(nextText);
    if (detected !== 'unknown') {
      setContentKind((current) => (current === 'unknown' ? detected : current));
    }
  }

  function handleTitleChange(event: ChangeEvent<HTMLInputElement>): void {
    setTitleDirty(true);
    setTitle(event.target.value);
  }

  function handleChapterNumberChange(event: ChangeEvent<HTMLInputElement>): void {
    setChapterNumberDirty(true);
    setChapterNumber(event.target.value);
  }

  function handleChapterTitleChange(event: ChangeEvent<HTMLInputElement>): void {
    setChapterTitleDirty(true);
    setChapterTitle(event.target.value);
  }

  function handleTextChange(event: ChangeEvent<HTMLTextAreaElement>): void {
    const nextText = event.target.value;
    if (textByteLength(nextText) > MAX_BROWSER_TEXT_UPLOAD_BYTES) {
      setWizardError(`Pasted text is too large (${formatBytes(textByteLength(nextText))}). Split it into smaller imports or use server-side import.`);
      return;
    }
    setText(nextText);
    detectFromSource(nextText);
    updateDetectedContentKind(nextText);
    setLastWizardResult(null);
    setLastCreatedJob(null);
    setWizardError('');
  }

  async function handleFileChange(event: ChangeEvent<HTMLInputElement>): Promise<void> {
    const nextFile = event.target.files?.[0] ?? null;
    setFile(nextFile);
    setFileText('');
    setLastWizardResult(null);
    setLastCreatedJob(null);
    setWizardError('');
    if (!nextFile) return;
    if (onImportWizardText && !isSupportedTextImportFile(nextFile)) {
      setFile(null);
      setWizardError('Unsupported TXT import file type. Use TXT, Markdown, HTML, or the Ebook flow for EPUB/AZW3/MOBI/PRC.');
      return;
    }
    if (onImportWizardText && nextFile.size > MAX_BROWSER_TEXT_UPLOAD_BYTES) {
      setFile(null);
      setWizardError(`TXT file is too large (${formatBytes(nextFile.size)}). Use a smaller text file or server-side ebook import.`);
      return;
    }

    try {
      const nextText = await nextFile.text();
      if (onImportWizardText && hasUnsupportedEncodingMarkers(nextText)) {
        setFile(null);
        setWizardError('Encoding không được hỗ trợ hoặc file bị lỗi. Hãy lưu lại file dưới dạng UTF-8 rồi thử lại.');
        return;
      }
      if (onImportWizardText && !nextText.trim()) {
        setFile(null);
        setWizardError('File is empty.');
        return;
      }
      setFileText(nextText);
      detectFromSource(nextText, nextFile.name);
      updateDetectedContentKind(nextText);
    } catch {
      detectFromSource('', nextFile.name);
      setWizardError('Không đọc được file này trong trình duyệt. Hãy kiểm tra encoding hoặc dùng Server inbox nếu file lớn.');
    }
  }

  function handleChapterEdit(index: number, field: 'chapterNumber' | 'title', value: string): void {
    setChapterEdits((current) => ({
      ...current,
      [index]: {
        ...current[index],
        [field]: value,
      },
    }));
  }

  function reviewedChapter(chapter: DetectedImportChapter, index: number) {
    const edit = chapterEdits[index] ?? {};
    const editedNumber = Number.parseInt(edit.chapterNumber ?? '', 10);
    return {
      chapter_number: Number.isFinite(editedNumber) && editedNumber > 0 ? editedNumber : chapter.chapterNumber,
      chapter_title: (edit.title ?? chapter.title).trim() || `Chương ${chapter.chapterNumber}`,
      text: chapter.text,
    };
  }

  async function submitWizardText(sourceType: 'paste' | 'txt'): Promise<void> {
    if (!onImportWizardText || !textPreview) return;
    setWizardError('');
    setLastWizardResult(null);
    setLastCreatedJob(null);
    try {
      const result = await onImportWizardText({
        title: title.trim(),
        target_book_id: parsedTargetBookId() ?? undefined,
        content_kind: contentKind,
        duplicate_strategy: duplicateStrategy,
        source_type: sourceType,
        chapters: textPreview.chapters.map((chapter, index) => reviewedChapter(chapter, index)),
      }, { finalAction });
      const resolvedResult = result ?? null;
      setLastWizardResult(resolvedResult);
      if (!resolvedResult) return;

      if (finalAction === 'translate' && onCreateTranslationJob && resolvedResult.chapter_ids.length > 0) {
        const job = await onCreateTranslationJob(resolvedResult.book_id, resolvedResult.chapter_ids);
        setLastCreatedJob(job ?? null);
      } else if (finalAction === 'tts' && onCreateTtsJob && resolvedResult.chapter_ids.length > 0) {
        const job = await onCreateTtsJob(resolvedResult.book_id, resolvedResult.chapter_ids);
        setLastCreatedJob(job ?? null);
      }
    } catch (error) {
      setWizardError(errorMessage(error));
    }
  }

  async function handlePreviewSourceUrl(): Promise<void> {
    if (!onPreviewImportUrl || !sourceUrl.trim()) return;
    setSourcePreview(null);
    setSourcePreviewError('');
    setSourcePreviewState('loading');
    try {
      const preview = await onPreviewImportUrl(sourceUrl.trim());
      setSourcePreview(preview);
      setSourcePreviewState('ready');
      if (!titleDirty && preview.title) setTitle(preview.title);
    } catch (error) {
      setSourcePreviewState('error');
      setSourcePreviewError(errorMessage(error));
    }
  }

  async function handleCatalogSearch(): Promise<void> {
    if (!loadSourceCatalog) return;
    setCatalogState('loading');
    setCatalogError('');
    try {
      const result = await loadSourceCatalog({
        query: catalogQuery,
        supported: 'all',
        page: 1,
        page_size: 20,
      });
      setCatalog(result);
      setCatalogState('ready');
    } catch (error) {
      setCatalogState('error');
      setCatalogError(errorMessage(error));
    }
  }

  async function submitSourceUrl(): Promise<void> {
    if (!sourcePreview || !onStartImportUrlJob) return;
    try {
      const job = await onStartImportUrlJob({
        url: sourcePreview.source_url || sourceUrl,
        title: sourcePreview.title,
        author: sourcePreview.author,
        source: sourcePreview.source,
        chapters: sourcePreview.chapters,
        retry_limit: sourcePreview.policy?.retry_limit ?? 2,
        managed_source_id: sourcePreview.managed_source_id,
      });
      setLastCreatedJob(job ?? null);
    } catch (error) {
      setSourcePreviewError(errorMessage(error));
    }
  }

  function parsedTargetBookId(value = targetBookId): number | null {
    return value ? Number.parseInt(value, 10) : null;
  }

  function invalidateEbookPreviewRequests(): number {
    ebookPreviewRequestToken.current += 1;
    return ebookPreviewRequestToken.current;
  }

  async function previewEbookFile(
    nextFile: File,
    nextSplitMode: EbookSplitMode,
    nextDuplicateStrategy = duplicateStrategy,
    nextTargetBookId = targetBookId,
  ): Promise<void> {
    const requestToken = invalidateEbookPreviewRequests();
    setConfirmedExistingBookId(null);
    setEbookPreview(null);
    setEbookPreviewError('');
    setEbookSubmissionBlocked(false);

    if (!onPreviewTranslatedEbook) {
      setEbookPreviewState('error');
      setEbookPreviewError('Ebook preview is not available.');
      return;
    }

    setEbookPreviewState('loading');
    try {
      const preview = await onPreviewTranslatedEbook(nextFile, nextSplitMode, {
        duplicateStrategy: nextDuplicateStrategy,
        targetBookId: parsedTargetBookId(nextTargetBookId),
      });
      if (requestToken !== ebookPreviewRequestToken.current) return;
      setEbookPreview(preview);
      setEbookPreviewState('ready');
    } catch (error) {
      if (requestToken !== ebookPreviewRequestToken.current) return;
      setEbookPreviewState('error');
      setEbookPreviewError(errorMessage(error));
    }
  }

  async function previewInboxFile(
    filename: string,
    nextSplitMode: EbookSplitMode,
    nextDuplicateStrategy = duplicateStrategy,
    nextTargetBookId = targetBookId,
  ): Promise<void> {
    const requestToken = invalidateEbookPreviewRequests();
    setConfirmedExistingBookId(null);
    setEbookPreview(null);
    setEbookPreviewError('');
    setEbookSubmissionBlocked(false);

    if (!filename) {
      setEbookPreviewState('idle');
      return;
    }

    if (!onPreviewInboxEbook) {
      setEbookPreviewState('error');
      setEbookPreviewError('Server inbox preview is not available.');
      return;
    }

    setEbookPreviewState('loading');
    try {
      const preview = await onPreviewInboxEbook(filename, nextSplitMode, {
        duplicateStrategy: nextDuplicateStrategy,
        targetBookId: parsedTargetBookId(nextTargetBookId),
      });
      if (requestToken !== ebookPreviewRequestToken.current) return;
      setEbookPreview(preview);
      setEbookPreviewState('ready');
    } catch (error) {
      if (requestToken !== ebookPreviewRequestToken.current) return;
      setEbookPreviewState('error');
      setEbookPreviewError(errorMessage(error));
    }
  }

  function handleEbookFile(nextFile: File | null): void {
    invalidateEbookPreviewRequests();
    setConfirmedExistingBookId(null);
    setEbookSource('upload');
    setEbookFile(nextFile);
    setSelectedInboxFile('');
    setEbookPreview(null);
    setEbookPreviewError('');
    setEbookSubmissionBlocked(false);
    setLastEbookImportResult(null);
    if (nextFile && nextFile.size > MAX_BROWSER_EBOOK_UPLOAD_BYTES) {
      setEbookPreviewState('error');
      setEbookPreviewError(
        `File lớn hơn 95 MB (${formatBytes(nextFile.size)}). Cloudflare có thể chặn upload lớn; hãy copy file vào ${ebookInboxDirectory} rồi chọn Server inbox.`,
      );
      return;
    }
    setEbookPreviewState(nextFile ? 'loading' : 'idle');
    if (nextFile) {
      void previewEbookFile(nextFile, splitMode);
    }
  }

  function handleEbookFileChange(event: ChangeEvent<HTMLInputElement>): void {
    handleEbookFile(event.target.files?.[0] ?? null);
  }

  function handleEbookDrop(event: DragEvent<HTMLLabelElement>): void {
    event.preventDefault();
    handleEbookFile(event.dataTransfer.files[0] ?? null);
  }

  function handleEbookSourceChange(nextSource: EbookSource): void {
    invalidateEbookPreviewRequests();
    setConfirmedExistingBookId(null);
    setEbookSource(nextSource);
    setEbookPreview(null);
    setEbookPreviewError('');
    setEbookSubmissionBlocked(false);
    setLastEbookImportResult(null);
    if (nextSource === 'upload') {
      setSelectedInboxFile('');
      setEbookPreviewState('idle');
      return;
    }
    setEbookFile(null);
    setEbookPreviewState(selectedInboxFile ? 'loading' : 'idle');
    if (selectedInboxFile) {
      void previewInboxFile(selectedInboxFile, splitMode);
    }
  }

  function handleInboxFileChange(event: ChangeEvent<HTMLSelectElement>): void {
    const filename = event.target.value;
    invalidateEbookPreviewRequests();
    setConfirmedExistingBookId(null);
    setEbookSource('inbox');
    setEbookFile(null);
    setSelectedInboxFile(filename);
    setLastEbookImportResult(null);
    void previewInboxFile(filename, splitMode);
  }

  function handleSplitModeChange(event: ChangeEvent<HTMLSelectElement>): void {
    const nextSplitMode = event.target.value as EbookSplitMode;
    invalidateEbookPreviewRequests();
    setConfirmedExistingBookId(null);
    setSplitMode(nextSplitMode);
    if (ebookSource === 'inbox' && selectedInboxFile) {
      void previewInboxFile(selectedInboxFile, nextSplitMode);
    } else if (ebookFile && ebookFile.size <= MAX_BROWSER_EBOOK_UPLOAD_BYTES) {
      void previewEbookFile(ebookFile, nextSplitMode);
    }
  }

  function handleTargetBookChange(event: ChangeEvent<HTMLSelectElement>): void {
    const nextTargetBookId = event.target.value;
    invalidateEbookPreviewRequests();
    setConfirmedExistingBookId(null);
    setTargetBookId(nextTargetBookId);
    if (ebookSource === 'inbox' && selectedInboxFile) {
      void previewInboxFile(selectedInboxFile, splitMode, duplicateStrategy, nextTargetBookId);
    } else if (ebookFile && ebookFile.size <= MAX_BROWSER_EBOOK_UPLOAD_BYTES) {
      void previewEbookFile(ebookFile, splitMode, duplicateStrategy, nextTargetBookId);
    }
  }

  function handleDuplicateStrategyChange(nextDuplicateStrategy: EbookDuplicateStrategy): void {
    invalidateEbookPreviewRequests();
    setConfirmedExistingBookId(null);
    setDuplicateStrategy(nextDuplicateStrategy);
    setLastEbookImportResult(null);
    if (ebookSource === 'inbox' && selectedInboxFile) {
      void previewInboxFile(selectedInboxFile, splitMode, nextDuplicateStrategy, targetBookId);
    } else if (ebookFile && ebookFile.size <= MAX_BROWSER_EBOOK_UPLOAD_BYTES) {
      void previewEbookFile(ebookFile, splitMode, nextDuplicateStrategy, targetBookId);
    }
  }

  function retryEbookPreview(): void {
    if (!ebookPreviewRetryAvailable) return;
    if (ebookSource === 'inbox') {
      void previewInboxFile(selectedInboxFile, splitMode, duplicateStrategy, targetBookId);
      return;
    }
    if (ebookFile) {
      void previewEbookFile(ebookFile, splitMode, duplicateStrategy, targetBookId);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (!canSubmit) return;

    if (mode === 'file') {
      if (onImportWizardText) {
        void submitWizardText('txt');
        return;
      }
      if (!file || !onImportFile) return;

      void onImportFile({
        ...importFields,
        file,
      });
      return;
    }

    if (mode === 'ebook') {
      void submitTranslatedEbook();
      return;
    }

    if (mode === 'url' || mode === 'catalog') {
      void submitSourceUrl();
      return;
    }

    if (onImportWizardText) {
      void submitWizardText('paste');
      return;
    }

    void onImportPaste({
      ...importFields,
      text,
    });
  }

  async function submitTranslatedEbook(): Promise<void> {
    if (!onImportTranslatedEbook) return;
    if (ebookSource === 'upload' && !ebookFile) return;
    if (ebookSource === 'inbox' && !selectedInboxFile) return;

    setEbookPreviewError('');
    try {
      const result = await onImportTranslatedEbook({
        ...(ebookSource === 'upload'
          ? { file: ebookFile ?? undefined, uploadId: ebookPreview?.upload_id }
          : { inboxFile: ebookPreview?.inbox_file ?? selectedInboxFile }),
        duplicateStrategy,
        splitMode,
        targetBookId: targetBookId ? Number.parseInt(targetBookId, 10) : undefined,
        ...(confirmedExistingBookId !== null && confirmedExistingBookId === existingBookId
          ? { confirmedExistingBookId }
          : {}),
      });
      setLastEbookImportResult(result ?? null);
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        invalidateEbookPreviewRequests();
        setConfirmedExistingBookId(null);
        setEbookPreview(null);
        setEbookPreviewState('error');
        setEbookSubmissionBlocked(false);
      } else {
        setEbookSubmissionBlocked(true);
      }
      setEbookPreviewError(errorMessage(error));
    }
  }

  function handleModeChange(nextMode: ImportMode): void {
    if (mode === 'ebook' && nextMode !== 'ebook') {
      invalidateEbookPreviewRequests();
      setConfirmedExistingBookId(null);
      setEbookPreview(null);
      setEbookPreviewState('idle');
      setEbookPreviewError('');
      setEbookSubmissionBlocked(false);
    }
    setMode(nextMode);
    if (mode !== 'ebook' && nextMode === 'ebook') {
      if (ebookSource === 'inbox' && selectedInboxFile) {
        void previewInboxFile(selectedInboxFile, splitMode, duplicateStrategy, targetBookId);
      } else if (ebookFile && ebookFile.size <= MAX_BROWSER_EBOOK_UPLOAD_BYTES) {
        void previewEbookFile(ebookFile, splitMode, duplicateStrategy, targetBookId);
      }
    }
  }

  function handleCancel(): void {
    if (mode === 'ebook') {
      invalidateEbookPreviewRequests();
      setConfirmedExistingBookId(null);
    }
    onCancel();
  }

  return (
    <section aria-labelledby="import-panel-title" className="import-panel import-reference-view panel">
      <div className="import-reference-header">
        <div>
          <p className="section-label">
            <span>Nhập chương</span>
            <span aria-hidden="true">›</span>
            <span>{panelTitle}</span>
          </p>
          <h3 id="import-panel-title">{panelTitle}</h3>
          <p className="view-subtitle">{panelSubtitle}</p>
        </div>
        <button
          aria-expanded={helpOpen}
          className="secondary-action import-help-button"
          onClick={() => setHelpOpen((current) => !current)}
          type="button"
        >
          <CircleHelp aria-hidden="true" size={16} />
          Hướng dẫn
        </button>
      </div>

      {helpOpen ? (
        <section aria-label="Hướng dẫn nhập chương" className="import-inline-help inline-help-panel">
          <p>
            Wizard sẽ đi qua 4 bước: chọn nguồn, phát hiện cấu trúc, làm sạch và preview,
            sau đó chọn lưu, dịch hoặc tạo audio. URL và Kho nguồn vẫn dùng source policy hiện có.
          </p>
        </section>
      ) : null}

      <WizardSteps activeStep={wizardActiveStep} />

      <div aria-label="Import mode" className="segmented-actions import-mode-tabs">
        <button
          aria-label="Paste"
          aria-pressed={mode === 'paste'}
          className="secondary-action"
          onClick={() => handleModeChange('paste')}
          type="button"
        >
          <Clipboard aria-hidden="true" size={24} />
          <span>
            <strong>Paste</strong>
            <small>Dán văn bản</small>
          </span>
        </button>
        <button
          aria-label="File"
          aria-pressed={mode === 'file'}
          className="secondary-action"
          onClick={() => handleModeChange('file')}
          type="button"
        >
          <FileText aria-hidden="true" size={24} />
          <span>
            <strong>File</strong>
            <small>Upload file</small>
          </span>
        </button>
        <button
          aria-label="Ebook bản dịch"
          aria-pressed={mode === 'ebook'}
          className="secondary-action"
          onClick={() => handleModeChange('ebook')}
          type="button"
        >
          <BookOpen aria-hidden="true" size={24} />
          <span>
            <strong>Ebook bản dịch</strong>
            <small>Import từ ebook</small>
          </span>
        </button>
        <button
          aria-label="URL"
          aria-pressed={mode === 'url'}
          className="secondary-action"
          onClick={() => handleModeChange('url')}
          type="button"
        >
          <Globe2 aria-hidden="true" size={24} />
          <span>
            <strong>URL</strong>
            <small>Nguồn hỗ trợ</small>
          </span>
        </button>
        <button
          aria-label="Kho nguồn"
          aria-pressed={mode === 'catalog'}
          className="secondary-action"
          onClick={() => handleModeChange('catalog')}
          type="button"
        >
          <Search aria-hidden="true" size={24} />
          <span>
            <strong>Kho nguồn</strong>
            <small>Metadata</small>
          </span>
        </button>
      </div>

      <form className="import-form" onSubmit={handleSubmit}>
        {mode === 'ebook' ? (
          <>
            <EbookImportFlow
              canImport={canSubmit}
              previewState={ebookPreviewState}
              selectedFile={selectedEbookFile}
            />

            <div aria-label="Ebook source" className="segmented-actions ebook-source-tabs">
              <button
                aria-label="Upload file"
                aria-pressed={ebookSource === 'upload'}
                className="secondary-action"
                onClick={() => handleEbookSourceChange('upload')}
                type="button"
              >
                <Upload aria-hidden="true" size={15} />
                Upload file
              </button>
              <button
                aria-label="Server inbox"
                aria-pressed={ebookSource === 'inbox'}
                className="secondary-action"
                onClick={() => handleEbookSourceChange('inbox')}
                type="button"
              >
                <Inbox aria-hidden="true" size={15} />
                Server inbox
              </button>
            </div>

            {ebookSource === 'upload' ? (
              <label
                className="ebook-dropzone"
                onDragOver={(event) => event.preventDefault()}
                onDrop={handleEbookDrop}
              >
                <span>Ebook file</span>
                <UploadCloud aria-hidden="true" size={54} />
                <strong>Chọn file hoặc kéo & thả vào đây</strong>
                <small>Hỗ trợ: EPUB, TXT, HTML, AZW3, MOBI, PRC</small>
                <small>(Calibre ebook-convert trên máy)</small>
                <small className="sr-only">EPUB/TXT/HTML đã dịch đọc trực tiếp. AZW3, MOBI, PRC cần Calibre ebook-convert trên máy.</small>
                <span className="file-picker-row">
                  <span className="file-picker-button">Chọn file</span>
                  <span>{ebookFile ? ebookFile.name : 'Chưa chọn file nào'}</span>
                </span>
                <input
                  accept={EBOOK_ACCEPT}
                  aria-label="Ebook file"
                  name="ebook_file"
                  onChange={handleEbookFileChange}
                  type="file"
                />
              </label>
            ) : (
              <section aria-labelledby="ebook-inbox-title" className="ebook-inbox-panel">
                <div className="ebook-inbox-header">
                  <div>
                    <p className="section-label">Local file bypass</p>
                    <h4 id="ebook-inbox-title">Server inbox</h4>
                  </div>
                  {onRefreshEbookInbox ? (
                    <button className="secondary-action" onClick={() => void onRefreshEbookInbox()} type="button">
                      Refresh
                    </button>
                  ) : null}
                </div>
                <p>
                  Copy EPUB/AZW3/MOBI/PRC/TXT/HTML vào <code>{ebookInboxDirectory}</code>, rồi chọn file ở đây để tránh upload qua Cloudflare.
                </p>
                {ebookInboxError ? <p className="status-error">{ebookInboxError}</p> : null}
                <label>
                  <span>Server inbox ebook</span>
                  <select onChange={handleInboxFileChange} value={selectedInboxFile}>
                    <option value="">Chọn file trong inbox</option>
                    {ebookInboxFiles.map((entry) => (
                      <option key={entry.name} value={entry.name}>
                        {entry.name} · {formatBytes(entry.size)}
                      </option>
                    ))}
                  </select>
                </label>
              </section>
            )}

            <div className="ebook-import-grid">
              <label>
                <span>Cách tách chương</span>
                <select onChange={handleSplitModeChange} value={splitMode}>
                  <option value="auto">Tự động: ưu tiên mục lục</option>
                  <option value="single">Gộp thành 1 chương</option>
                </select>
              </label>

              <label>
                <span>Gộp vào truyện có sẵn</span>
                <select onChange={handleTargetBookChange} value={targetBookId}>
                  <option value="">Tự động theo tên truyện</option>
                  {books.map((book) => (
                    <option key={book.id} value={book.id}>
                      {book.title}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <fieldset className="ebook-import-options">
              <legend>Xử lý chương trùng</legend>
              <label>
                <input
                  checked={duplicateStrategy === 'skip'}
                  name="duplicate_strategy"
                  onChange={() => handleDuplicateStrategyChange('skip')}
                  type="radio"
                />
                <span>Bỏ qua chương trùng</span>
              </label>
              <label>
                <input
                  checked={duplicateStrategy === 'error'}
                  name="duplicate_strategy"
                  onChange={() => handleDuplicateStrategyChange('error')}
                  type="radio"
                />
                <span>Dừng khi trùng</span>
              </label>
              <label>
                <input
                  checked={duplicateStrategy === 'overwrite'}
                  name="duplicate_strategy"
                  onChange={() => handleDuplicateStrategyChange('overwrite')}
                  type="radio"
                />
                <span>Ghi đè chương trùng</span>
              </label>
            </fieldset>
          </>
        ) : mode === 'url' || mode === 'catalog' ? (
          <>
            {mode === 'catalog' ? (
              <section aria-labelledby="catalog-import-title" className="ebook-inbox-panel">
                <div className="ebook-inbox-header">
                  <div>
                    <p className="section-label">Step 1 · Kho nguồn</p>
                    <h4 id="catalog-import-title">Tìm trong source catalog</h4>
                  </div>
                  <button
                    className="secondary-action"
                    disabled={!loadSourceCatalog || catalogState === 'loading'}
                    onClick={() => void handleCatalogSearch()}
                    type="button"
                  >
                    {catalogState === 'loading' ? <Loader2 aria-hidden="true" className="status-spinner" size={15} /> : <Search aria-hidden="true" size={15} />}
                    Tìm
                  </button>
                </div>
                <p>Catalog chỉ là metadata. Chỉ nguồn đã VERIFIED trong Source Hub mới có thể tạo job import tự động.</p>
                <label>
                  <span>Tìm nguồn</span>
                  <input
                    onChange={(event) => setCatalogQuery(event.target.value)}
                    placeholder="Tên nguồn hoặc domain..."
                    type="search"
                    value={catalogQuery}
                  />
                </label>
                {!loadSourceCatalog ? <p className="status-error">Source catalog API chưa khả dụng trong phiên này.</p> : null}
                {catalogError ? <p className="status-error" role="alert">{catalogError}</p> : null}
                {catalog?.entries?.length ? (
                  <ol className="ebook-preview-chapters catalog-import-list">
                    {catalog.entries.slice(0, 10).map((entry) => (
                      <li key={entry.id}>
                        <div>
                          <span>{entry.domain || entry.url}</span>
                          <strong>{entry.name || entry.domain || 'Không tên'}</strong>
                        </div>
                        <p>
                          {(entry.tags ?? []).join(', ') || 'Không tag'} · {entry.supported ? 'supported' : 'unsupported'} · {entry.managed_status || 'UNMANAGED'}
                        </p>
                        <button
                          className="secondary-action"
                          disabled={!entry.can_use_in_jobs || !entry.url}
                          onClick={() => {
                            setSourceUrl(entry.url);
                            setMode('url');
                            setSourcePreview(null);
                            setSourcePreviewState('idle');
                          }}
                          type="button"
                        >
                          {entry.can_use_in_jobs ? 'Dùng nguồn đã xác minh' : 'Cần verify trong Source Hub'}
                        </button>
                      </li>
                    ))}
                  </ol>
                ) : catalogState === 'ready' ? (
                  <p>Không có nguồn phù hợp.</p>
                ) : null}
              </section>
            ) : null}

            <section aria-labelledby="url-import-title" className="ebook-inbox-panel">
              <div className="ebook-inbox-header">
                <div>
                  <p className="section-label">Step 2 · Preview nguồn</p>
                  <h4 id="url-import-title">Import từ URL được hỗ trợ</h4>
                </div>
                <button
                  className="secondary-action"
                  disabled={!sourceUrl.trim() || sourcePreviewState === 'loading' || !onPreviewImportUrl}
                  onClick={() => void handlePreviewSourceUrl()}
                  type="button"
                >
                  {sourcePreviewState === 'loading' ? <Loader2 aria-hidden="true" className="status-spinner" size={15} /> : <Search aria-hidden="true" size={15} />}
                  Preview URL
                </button>
              </div>
              <label>
                <span>Source URL</span>
                <input
                  inputMode="url"
                  onChange={(event) => {
                    setSourceUrl(event.target.value);
                    setSourcePreview(null);
                    setSourcePreviewState('idle');
                    setSourcePreviewError('');
                  }}
                  placeholder="https://www.69shuba.com/book/..."
                  type="url"
                  value={sourceUrl}
                />
              </label>
              {!onPreviewImportUrl ? <p className="status-error">URL preview API chưa được nối vào màn hình import.</p> : null}
              {sourcePreviewError ? <p className="status-error" role="alert">{sourcePreviewError}</p> : null}
              {sourcePreview ? (
                <section aria-label="URL preview result" className="ebook-preview-card">
                  <div className="ebook-preview-header">
                    <div>
                      <p className="section-label">{sourcePreview.source}</p>
                      <h4>{sourcePreview.title || 'Không rõ tiêu đề'}</h4>
                    </div>
                    <span className="status-chip status-chip-success">
                      {sourcePreview.chapter_count.toLocaleString('vi-VN')} chương
                    </span>
                  </div>
                  <dl className="ebook-preview-meta">
                    <div>
                      <dt>Tác giả</dt>
                      <dd>{sourcePreview.author || 'Không rõ'}</dd>
                    </div>
                    <div>
                      <dt>Policy</dt>
                      <dd>{sourcePreview.policy?.label || sourcePreview.adapter_label}</dd>
                    </div>
                    <div>
                      <dt>Delay</dt>
                      <dd>{sourcePreview.policy?.delay_seconds ?? 0}s</dd>
                    </div>
                    <div>
                      <dt>Concurrency</dt>
                      <dd>{sourcePreview.policy?.max_concurrency ?? 1}</dd>
                    </div>
                    <div>
                      <dt>Source Hub</dt>
                      <dd>{sourcePreview.managed_source_status || 'Chưa import'}</dd>
                    </div>
                    <div>
                      <dt>Automation</dt>
                      <dd>{sourcePreview.automation_allowed ? 'Được phép' : 'Bị khóa'}</dd>
                    </div>
                  </dl>
                  {sourcePreview.automation_reason ? (
                    <p className="source-invalid-reason">{sourcePreview.automation_reason}</p>
                  ) : null}
                  <ol className="ebook-preview-chapters">
                    {sourcePreview.chapters.slice(0, 5).map((chapter) => (
                      <li key={`${chapter.chapter_number}-${chapter.url}`}>
                        <div>
                          <span>#{chapter.chapter_number}</span>
                          <strong>{chapter.title || `Chương ${chapter.chapter_number}`}</strong>
                        </div>
                        <p>{chapter.url}</p>
                      </li>
                    ))}
                  </ol>
                </section>
              ) : null}
            </section>
          </>
        ) : (
          <>
            <label>
              <span>Book title</span>
              <input
                name="title"
                onChange={handleTitleChange}
                placeholder="Nhập tên truyện hoặc để trống nếu đã chọn từ Library"
                type="text"
                value={title}
              />
            </label>

            <label>
              <span>Chapter number</span>
              <input
                min="1"
                name="chapter_number"
                onChange={handleChapterNumberChange}
                type="number"
                value={chapterNumber}
              />
            </label>

            <label>
              <span>Chapter title</span>
              <input
                name="chapter_title"
                onChange={handleChapterTitleChange}
                placeholder="Nhập tiêu đề chương"
                type="text"
                value={chapterTitle}
              />
            </label>
          </>
        )}

        {mode === 'paste' ? (
          <>
            <label>
              <span>Source text</span>
              <textarea
                name="text"
                onChange={handleTextChange}
                placeholder="Dán nội dung chương vào đây..."
                rows={10}
                value={text}
              />
            </label>
            <PasteTextStatus
              canImport={canSubmit}
              chapterNumber={chapterNumber}
              chapterTitle={chapterTitle}
              text={text}
              title={title}
            />
          </>
        ) : mode === 'file' ? (
          <label className="source-file-dropzone">
            <span>Source file</span>
            <UploadCloud aria-hidden="true" size={54} />
            <strong>Chọn file hoặc kéo & thả vào đây</strong>
            <small>Hỗ trợ: TXT, HTML, EPUB, AZW3, MOBI, PRC</small>
            <span className="file-picker-row">
              <span className="file-picker-button">Chọn file</span>
              <span>{file ? file.name : 'Chưa chọn file nào'}</span>
            </span>
            <input
              accept=".txt,.md,.html,.htm,text/plain,text/markdown,text/html"
              aria-label="Source file"
              name="file"
              onChange={(event) => {
                void handleFileChange(event);
              }}
              type="file"
            />
          </label>
        ) : null}

        {mode === 'paste' && text ? (
          <section aria-label="Import preview" className="import-preview">
            <p>{text}</p>
          </section>
        ) : mode === 'file' && file ? (
          <FileImportStatus
            chapterNumber={chapterNumber}
            chapterTitle={chapterTitle}
            file={file}
            title={title}
          />
        ) : null}

        {(mode === 'paste' || mode === 'file') && textPreview ? (
          <>
            <TextWizardPreview
              chapters={textPreview.chapters}
              contentKind={contentKind}
              detectedKind={textPreview.contentKind}
              duplicateCount={textPreview.duplicateChapterNumbers.length}
              onChapterEdit={handleChapterEdit}
              warnings={textPreview.warnings}
            />

            <section aria-labelledby="wizard-clean-title" className="import-tip-panel wizard-options-panel">
              <Lightbulb aria-hidden="true" size={22} />
              <div>
                <strong id="wizard-clean-title">Step 3 · Làm sạch & preview</strong>
                <p>
                  Đã normalize line breaks, spacing và strip watermark/source lines phổ biến.
                  Preview 3 chương đầu ở trên trước khi lưu.
                </p>
              </div>
            </section>

            <section aria-labelledby="wizard-action-title" className="ebook-inbox-panel wizard-action-panel">
              <div className="ebook-inbox-header">
                <div>
                  <p className="section-label">Step 4 · Choose action</p>
                  <h4 id="wizard-action-title">Đích import và hành động</h4>
                </div>
                <span className="status-chip">
                  {textPreview.characterCount.toLocaleString('vi-VN')} ký tự
                </span>
              </div>
              <div className="ebook-import-grid">
                <label>
                  <span>Gộp vào truyện có sẵn</span>
                  <select aria-label="Target book" onChange={handleTargetBookChange} value={targetBookId}>
                    <option value="">Tạo mới hoặc tự động theo tên</option>
                    {books.map((book) => (
                      <option key={book.id} value={book.id}>
                        {book.title}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>Raw hay bản dịch</span>
                  <select
                    aria-label="Content mode"
                    onChange={(event) => {
                      const nextKind = event.target.value as ImportContentKind;
                      setContentKind(nextKind);
                      if ((nextKind === 'raw' && finalAction === 'tts') || (nextKind === 'translated' && finalAction === 'translate') || nextKind === 'both') {
                        setFinalAction('open');
                      }
                    }}
                    value={contentKind}
                  >
                    <option value="unknown">Tôi sẽ chọn sau</option>
                    <option value="raw">Raw tiếng Trung</option>
                    <option value="translated">Bản dịch tiếng Việt</option>
                    <option value="both">Có cả raw và bản dịch</option>
                  </select>
                </label>
              </div>
              <fieldset className="ebook-import-options">
                <legend>Xử lý chương trùng</legend>
                <label>
                  <input
                    checked={duplicateStrategy === 'skip'}
                    name="wizard_duplicate_strategy"
                    onChange={() => {
                      setDuplicateStrategy('skip');
                      setOverwriteConfirmed(false);
                    }}
                    type="radio"
                  />
                  <span>Bỏ qua chương trùng</span>
                </label>
                <label>
                  <input
                    checked={duplicateStrategy === 'error'}
                    name="wizard_duplicate_strategy"
                    onChange={() => {
                      setDuplicateStrategy('error');
                      setOverwriteConfirmed(false);
                    }}
                    type="radio"
                  />
                  <span>Dừng khi trùng</span>
                </label>
                <label>
                  <input
                    checked={duplicateStrategy === 'overwrite'}
                    name="wizard_duplicate_strategy"
                    onChange={() => {
                      setDuplicateStrategy('overwrite');
                      setOverwriteConfirmed(false);
                    }}
                    type="radio"
                  />
                  <span>Ghi đè chương trùng đã xác nhận</span>
                </label>
              </fieldset>
              {textPreview.duplicateChapterNumbers.length > 0 ? (
                <section className="ebook-preview-warnings" aria-label="Tóm tắt chương trùng">
                  <h5>Duplicate handling summary</h5>
                  <ul>
                    <li>Chapters detected: {textPreview.chapterCount.toLocaleString('vi-VN')}</li>
                    <li>Chương mới: {(textPreview.chapterCount - textPreview.duplicateChapterNumbers.length).toLocaleString('vi-VN')}</li>
                    <li>
                      {duplicateStrategy === 'overwrite'
                        ? `Chương sẽ ghi đè: ${textPreview.duplicateChapterNumbers.length.toLocaleString('vi-VN')}`
                        : duplicateStrategy === 'skip'
                          ? `Chương sẽ bỏ qua: ${textPreview.duplicateChapterNumbers.length.toLocaleString('vi-VN')}`
                          : `Chương sẽ báo lỗi: ${textPreview.duplicateChapterNumbers.length.toLocaleString('vi-VN')}`}
                    </li>
                  </ul>
                  {duplicateStrategy === 'overwrite' ? (
                    <label className="danger-confirmation">
                      <input
                        checked={overwriteConfirmed}
                        onChange={(event) => setOverwriteConfirmed(event.target.checked)}
                        type="checkbox"
                      />
                      <span>Tôi xác nhận ghi đè chương trùng và đã kiểm tra bản dịch hiện có.</span>
                    </label>
                  ) : null}
                </section>
              ) : null}
              <fieldset className="ebook-import-options">
                <legend>Hành động sau import</legend>
                <label>
                  <input
                    checked={finalAction === 'save'}
                    name="wizard_final_action"
                    onChange={() => setFinalAction('save')}
                    type="radio"
                  />
                  <span>Save only</span>
                </label>
                <label>
                  <input
                    checked={finalAction === 'open'}
                    name="wizard_final_action"
                    onChange={() => setFinalAction('open')}
                    type="radio"
                  />
                  <span>Save and add to reader/library</span>
                </label>
                <label>
                  <input
                    checked={finalAction === 'translate'}
                    disabled={contentKind === 'translated' || !onCreateTranslationJob}
                    name="wizard_final_action"
                    onChange={() => setFinalAction('translate')}
                    type="radio"
                  />
                  <span>Save and create translation job</span>
                </label>
                <label>
                  <input
                    checked={finalAction === 'tts'}
                    disabled={contentKind === 'raw' || !onCreateTtsJob}
                    name="wizard_final_action"
                    onChange={() => setFinalAction('tts')}
                    type="radio"
                  />
                  <span>Save and create TTS job</span>
                </label>
              </fieldset>
            </section>
          </>
        ) : null}

        {wizardError ? (
          <p className="status-error" role="alert">
            {wizardError}
          </p>
        ) : null}

        {lastWizardResult ? (
          <section aria-label="Kết quả import" className="ebook-import-result" role="status">
            <strong>
              Đã lưu {lastWizardResult.imported_chapters.toLocaleString('vi-VN')} chương vào {lastWizardResult.title}
            </strong>
            <span>
              Bỏ qua {lastWizardResult.skipped_chapters.toLocaleString('vi-VN')} chương trùng
              {lastWizardResult.overwritten_chapters
                ? `, ghi đè ${lastWizardResult.overwritten_chapters.toLocaleString('vi-VN')} chương`
                : ''}
            </span>
            {lastCreatedJob ? <span>Job đã tạo: {lastCreatedJob.job_id}</span> : null}
            {(lastWizardResult.warnings ?? []).length > 0 ? (
              <ul>
                {(lastWizardResult.warnings ?? []).map((warning, index) => (
                  <li key={`${warning.type ?? 'warning'}-${index}`}>{warning.message}</li>
                ))}
              </ul>
            ) : null}
            <div className="topbar-actions">
              {onOpenImportedBook ? (
                <button className="secondary-action" onClick={() => onOpenImportedBook(lastWizardResult)} type="button">
                  Open reader/book
                </button>
              ) : null}
              {lastCreatedJob && onOpenJob ? (
                <button className="secondary-action" onClick={() => onOpenJob(lastCreatedJob.job_id)} type="button">
                  View job status
                </button>
              ) : null}
              <button className="secondary-action" onClick={() => setLastWizardResult(null)} type="button">
                Import more
              </button>
            </div>
          </section>
        ) : null}

        {lastCreatedJob && (mode === 'url' || mode === 'catalog') ? (
          <section aria-label="Kết quả import URL" className="ebook-import-result" role="status">
            <strong>Đã tạo job import URL: {lastCreatedJob.job_id}</strong>
            <span>{lastCreatedJob.message}</span>
          </section>
        ) : null}

        {mode === 'ebook' ? (
          <>
            <section aria-label="Import preview" className="import-preview">
              <EbookPreviewPanel
                confirmedExistingBookId={confirmedExistingBookId}
                error={ebookPreviewError}
                file={selectedEbookFile}
                onConfirmedExistingBookIdChange={setConfirmedExistingBookId}
                onRetry={retryEbookPreview}
                preview={ebookPreview}
                retryDisabled={!ebookPreviewRetryAvailable}
                state={ebookPreviewState}
              />
            </section>
            {lastEbookImportResult ? (
              <section
                aria-label="Kết quả import ebook"
                className="ebook-import-result"
                role="status"
              >
                <strong>Đã import {lastEbookImportResult.imported_chapters.toLocaleString()} chương vào {lastEbookImportResult.title}</strong>
                <span>
                  Bỏ qua {lastEbookImportResult.skipped_chapters.toLocaleString()} chương trùng
                  {lastEbookImportResult.overwritten_chapters
                    ? `, ghi đè ${lastEbookImportResult.overwritten_chapters.toLocaleString()} chương`
                    : ''}
                </span>
              </section>
            ) : null}
            {ebookImportHistory.length > 0 ? (
              <section aria-labelledby="ebook-import-history-title" className="ebook-import-history">
                <h4 id="ebook-import-history-title">Lịch sử import ebook</h4>
                <ol>
                  {ebookImportHistory.slice(0, 5).map((run) => (
                    <li key={run.id}>
                      <span className="ebook-history-thumb" aria-hidden="true">
                        <BookOpen size={19} />
                      </span>
                      <div>
                        <strong>{run.title || run.filename}</strong>
                        <span>{run.filename}</span>
                      </div>
                      <p>
                        Đã import {run.imported_chapters.toLocaleString()}, bỏ qua{' '}
                        {run.skipped_chapters.toLocaleString()}, ghi đè{' '}
                        {run.overwritten_chapters.toLocaleString()}
                      </p>
                    </li>
                  ))}
                </ol>
              </section>
            ) : null}
          </>
        ) : null}

        {(mode === 'paste' || mode === 'file') ? (
          <section className="import-tip-panel" aria-label="Mẹo nhỏ">
            <Lightbulb aria-hidden="true" size={22} />
            <div>
              <strong>Mẹo nhỏ</strong>
              <p>
                {mode === 'file'
                  ? 'Nên sử dụng file UTF-8 để tránh lỗi ký tự. Hệ thống sẽ tự động phân tích và chuẩn hóa trước khi lưu.'
                  : 'Bạn có thể copy nội dung từ bất kỳ nguồn nào và dán vào đây. Hệ thống sẽ tự động phân tích và chuẩn hóa nội dung trước khi lưu.'}
              </p>
            </div>
          </section>
        ) : null}

        <div className="topbar-actions">
          <p
            className={`import-submit-status ${canSubmit ? 'is-ready' : 'is-blocked'}`}
            id={importActionStatusId}
          >
            {importActionStatus}
          </p>
          <button aria-label="Cancel" className="secondary-action" disabled={loading} onClick={handleCancel} type="button">
            Hủy
          </button>
          <button
            aria-describedby={importActionStatusId}
            className="primary-action"
            disabled={!canSubmit}
            type="submit"
          >
            {mode === 'paste' ? <Upload aria-hidden="true" size={16} /> : mode === 'file' ? <Upload aria-hidden="true" size={16} /> : <ArrowRight aria-hidden="true" size={16} />}
            {submitLabel}
          </button>
        </div>
      </form>
    </section>
  );
}
