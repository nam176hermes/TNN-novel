import {
  ArrowRight,
  BookOpen,
  CircleHelp,
  Clipboard,
  FileText,
  Inbox,
  Lightbulb,
  Loader2,
  Upload,
  UploadCloud,
} from 'lucide-react';
import { useState, type ChangeEvent, type DragEvent, type FormEvent } from 'react';
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
} from '../api/types';
import { detectImportMetadata, type DetectedImportMetadata } from '../state/importMetadata';

export type ImportPanelProps = {
  onImportPaste: (request: ImportPasteRequest) => Promise<void> | void;
  onImportFile?: (request: ImportFileRequest) => Promise<void> | void;
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
  onCancel: () => void;
  books?: Array<{ id: number; title: string }>;
  ebookInboxDirectory?: string;
  ebookInboxError?: string;
  ebookInboxFiles?: EbookInboxFile[];
  ebookImportHistory?: EbookImportHistoryRun[];
  loading?: boolean;
  onRefreshEbookInbox?: () => Promise<void> | void;
};

type ImportMode = 'paste' | 'file' | 'ebook';
type EbookSource = 'upload' | 'inbox';
type EbookPreviewState = 'idle' | 'loading' | 'ready' | 'error';
type EbookPreviewFile = Pick<File, 'name' | 'size'>;

const CJK_CHARACTER_PATTERN = /[\u3400-\u4dbf\u4e00-\u9fff]/g;
const EBOOK_ACCEPT = '.epub,.azw3,.mobi,.prc,.txt,.html,.htm,application/epub+zip,text/plain,text/html';
const MAX_BROWSER_EBOOK_UPLOAD_BYTES = 95 * 1024 * 1024;
const BLOCKING_EBOOK_WARNING_TYPES = new Set(['unreadable_ebook']);

function formatBytes(value: number): string {
  if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  if (value >= 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${value.toLocaleString()} bytes`;
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

function EbookPreviewPanel({
  error,
  file,
  preview,
  state,
}: {
  error: string;
  file: EbookPreviewFile | null;
  preview: EbookPreview | null;
  state: EbookPreviewState;
}) {
  if (!file) {
    return <p>No ebook selected.</p>;
  }

  if (state === 'loading') {
    return <p>Đang đọc metadata và mục lục ebook.</p>;
  }

  if (state === 'error') {
    return (
      <p className="status-error" role="alert">
        {error || 'Không đọc được ebook này.'}
      </p>
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

export default function ImportPanel({
  books = [],
  ebookInboxDirectory = 'inbox/ebooks',
  ebookInboxError = '',
  ebookInboxFiles = [],
  onImportPaste,
  onImportFile,
  onPreviewInboxEbook,
  onPreviewTranslatedEbook,
  onImportTranslatedEbook,
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
  const [lastEbookImportResult, setLastEbookImportResult] = useState<EbookImportResult | null>(null);
  const [duplicateStrategy, setDuplicateStrategy] = useState<EbookDuplicateStrategy>('skip');
  const [targetBookId, setTargetBookId] = useState('');
  const [splitMode, setSplitMode] = useState<EbookSplitMode>('auto');
  const [helpOpen, setHelpOpen] = useState(false);

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
  const ebookHasBlockingWarning = Boolean(
    ebookPreview?.warnings?.some((warning) => BLOCKING_EBOOK_WARNING_TYPES.has(warning.type)),
  );
  const titleReady = title.trim().length > 0;
  const pastedTextReady = text.trim().length > 0;
  const canSubmit =
    !loading
    && (mode === 'paste'
      ? titleReady && pastedTextReady
      : mode === 'file'
        ? titleReady && Boolean(file && onImportFile)
        : Boolean(ebookPreview && ebookPreviewState === 'ready' && onImportTranslatedEbook && !ebookHasBlockingWarning));
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
  } else if (mode === 'ebook' && ebookSource === 'upload' && !ebookFile) {
    importActionStatus = 'Select an EPUB, AZW3, MOBI, PRC, TXT, or HTML file.';
  } else if (mode === 'ebook' && ebookSource === 'inbox' && !selectedInboxFile) {
    importActionStatus = 'Select an ebook from the server inbox.';
  } else if (mode === 'ebook' && ebookPreviewState === 'loading') {
    importActionStatus = 'Reading ebook preview.';
  } else if (mode === 'ebook' && ebookPreviewState === 'error') {
    importActionStatus = 'Resolve the ebook preview error before import.';
  } else if (mode === 'ebook' && ebookHasBlockingWarning) {
    importActionStatus = 'Ebook preview không có nội dung chữ đủ để import.';
  } else if (mode === 'ebook' && !ebookPreview) {
    importActionStatus = 'Preview the ebook before import.';
  }
  const panelTitle = mode === 'ebook' ? 'Ebook bản dịch' : mode === 'file' ? 'Import source file' : 'Paste source chapter';
  const panelSubtitle =
    mode === 'ebook'
      ? 'Import ebook và thêm vào thư viện.'
      : mode === 'file'
        ? 'Upload file chứa nội dung chương cần import vào hệ thống.'
        : 'Dán nội dung chương từ văn bản bạn có để import vào hệ thống.';
  const submitLabel = mode === 'ebook' ? 'Import vào Library' : mode === 'file' ? 'Import file' : 'Import chapter';

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
    setText(nextText);
    detectFromSource(nextText);
  }

  async function handleFileChange(event: ChangeEvent<HTMLInputElement>): Promise<void> {
    const nextFile = event.target.files?.[0] ?? null;
    setFile(nextFile);
    if (!nextFile) return;

    try {
      detectFromSource(await nextFile.text(), nextFile.name);
    } catch {
      detectFromSource('', nextFile.name);
    }
  }

  function parsedTargetBookId(value = targetBookId): number | null {
    return value ? Number.parseInt(value, 10) : null;
  }

  async function previewEbookFile(
    nextFile: File,
    nextSplitMode: EbookSplitMode,
    nextDuplicateStrategy = duplicateStrategy,
    nextTargetBookId = targetBookId,
  ): Promise<void> {
    setEbookPreview(null);
    setEbookPreviewError('');

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
      setEbookPreview(preview);
      setEbookPreviewState('ready');
    } catch (error) {
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
    setEbookPreview(null);
    setEbookPreviewError('');

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
      setEbookPreview(preview);
      setEbookPreviewState('ready');
    } catch (error) {
      setEbookPreviewState('error');
      setEbookPreviewError(errorMessage(error));
    }
  }

  function handleEbookFile(nextFile: File | null): void {
    setEbookSource('upload');
    setEbookFile(nextFile);
    setSelectedInboxFile('');
    setEbookPreview(null);
    setEbookPreviewError('');
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
    setEbookSource(nextSource);
    setEbookPreview(null);
    setEbookPreviewError('');
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
    setEbookSource('inbox');
    setEbookFile(null);
    setSelectedInboxFile(filename);
    setLastEbookImportResult(null);
    void previewInboxFile(filename, splitMode);
  }

  function handleSplitModeChange(event: ChangeEvent<HTMLSelectElement>): void {
    const nextSplitMode = event.target.value as EbookSplitMode;
    setSplitMode(nextSplitMode);
    if (ebookSource === 'inbox' && selectedInboxFile) {
      void previewInboxFile(selectedInboxFile, nextSplitMode);
    } else if (ebookFile && ebookFile.size <= MAX_BROWSER_EBOOK_UPLOAD_BYTES) {
      void previewEbookFile(ebookFile, nextSplitMode);
    }
  }

  function handleTargetBookChange(event: ChangeEvent<HTMLSelectElement>): void {
    const nextTargetBookId = event.target.value;
    setTargetBookId(nextTargetBookId);
    if (ebookSource === 'inbox' && selectedInboxFile) {
      void previewInboxFile(selectedInboxFile, splitMode, duplicateStrategy, nextTargetBookId);
    } else if (ebookFile && ebookFile.size <= MAX_BROWSER_EBOOK_UPLOAD_BYTES) {
      void previewEbookFile(ebookFile, splitMode, duplicateStrategy, nextTargetBookId);
    }
  }

  function handleDuplicateStrategyChange(nextDuplicateStrategy: EbookDuplicateStrategy): void {
    setDuplicateStrategy(nextDuplicateStrategy);
    setLastEbookImportResult(null);
    if (ebookSource === 'inbox' && selectedInboxFile) {
      void previewInboxFile(selectedInboxFile, splitMode, nextDuplicateStrategy, targetBookId);
    } else if (ebookFile && ebookFile.size <= MAX_BROWSER_EBOOK_UPLOAD_BYTES) {
      void previewEbookFile(ebookFile, splitMode, nextDuplicateStrategy, targetBookId);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (!canSubmit) return;

    if (mode === 'file') {
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

    void onImportPaste({
      ...importFields,
      text,
    });
  }

  async function submitTranslatedEbook(): Promise<void> {
    if (!onImportTranslatedEbook) return;
    if (ebookSource === 'upload' && !ebookFile) return;
    if (ebookSource === 'inbox' && !selectedInboxFile) return;

    const result = await onImportTranslatedEbook({
      ...(ebookSource === 'upload'
        ? { file: ebookFile ?? undefined, uploadId: ebookPreview?.upload_id }
        : { inboxFile: ebookPreview?.inbox_file ?? selectedInboxFile }),
      duplicateStrategy,
      splitMode,
      targetBookId: targetBookId ? Number.parseInt(targetBookId, 10) : undefined,
    });
    setLastEbookImportResult(result ?? null);
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
            Paste dùng cho văn bản chương đơn, File dùng cho file nguồn chương đơn,
            Ebook bản dịch dùng để preview mục lục rồi import vào thư viện.
          </p>
        </section>
      ) : null}

      <div aria-label="Import mode" className="segmented-actions import-mode-tabs">
        <button
          aria-label="Paste"
          aria-pressed={mode === 'paste'}
          className="secondary-action"
          onClick={() => setMode('paste')}
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
          onClick={() => setMode('file')}
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
          onClick={() => setMode('ebook')}
          type="button"
        >
          <BookOpen aria-hidden="true" size={24} />
          <span>
            <strong>Ebook bản dịch</strong>
            <small>Import từ ebook</small>
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

        {mode === 'ebook' ? (
          <>
            <section aria-label="Import preview" className="import-preview">
              <EbookPreviewPanel
                error={ebookPreviewError}
                file={selectedEbookFile}
                preview={ebookPreview}
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

        {mode !== 'ebook' ? (
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
          <button aria-label="Cancel" className="secondary-action" disabled={loading} onClick={onCancel} type="button">
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
