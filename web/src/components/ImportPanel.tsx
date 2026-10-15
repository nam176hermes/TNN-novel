import {
  ArrowRight,
  BookOpen,
  CircleHelp,
  Clipboard,
  Download,
  FileText,
  Globe2,
  Inbox,
  Lightbulb,
  Loader2,
  Search,
  Upload,
  UploadCloud,
} from 'lucide-react';
import { useState, type FormEvent } from 'react';
import type {
  EbookDuplicateStrategy,
  JobStartResponse
} from '../api/types';
import type { DetectedImportChapter, ImportContentKind } from '../state/importWizard';
import { EbookImportFlow, EbookPreviewPanel } from './import/EbookPreview';
import { formatBytes } from './import/importLabels';
import type { ImportMode, ImportPanelProps } from './import/types';
import { useEbookImport } from './import/useEbookImport';
import { useSourceImport } from './import/useSourceImport';
import { useTextImport } from './import/useTextImport';
import ImportJobProgress from './ImportJobProgress';
export type { ImportPanelProps } from './import/types';

const CJK_CHARACTER_PATTERN = /[\u3400-\u4dbf\u4e00-\u9fff]/g;
const EBOOK_ACCEPT = '.epub,.azw3,.mobi,.prc,.txt,.html,.htm,application/epub+zip,text/plain,text/html';
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
          <h4 id="paste-status-title">{canImport ? 'Sẵn sàng import' : 'Thiếu metadata'}</h4>
          <p>Đã nhận nội dung, kiểm tra metadata trước khi import.</p>
        </div>
        <span className={`status-chip ${canImport ? 'status-chip-success' : 'status-chip-warning'}`}>
          {canImport ? 'Sẵn sàng' : 'Cần tiêu đề'}
        </span>
      </div>
      <dl className="paste-status-grid">
        <div>
          <dt>Nội dung nguồn</dt>
          <dd>
            {stats.characters.toLocaleString()} ký tự · {stats.lines.toLocaleString()} dòng · {stats.cjkCharacters.toLocaleString()} ký tự Hán
          </dd>
        </div>
        <div>
          <dt>Truyện</dt>
          <dd>{hasTitle ? title.trim() : 'Thiếu tên truyện'}</dd>
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
          <h4>Sẵn sàng import</h4>
          <p>File đã sẵn sàng, kiểm tra metadata trước khi import.</p>
        </div>
        <span className="status-chip status-chip-success">Sẵn sàng</span>
      </div>
      <dl className="paste-status-grid">
        <div>
          <dt>File nguồn</dt>
          <dd>{file.name}</dd>
        </div>
        <div>
          <dt>Kích thước</dt>
          <dd>{formatBytes(file.size)}</dd>
        </div>
        <div>
          <dt>Truyện</dt>
          <dd>{hasTitle ? title.trim() : 'Thiếu tên truyện'}</dd>
        </div>
        <div>
          <dt>Chapter</dt>
          <dd>{chapterLabel}</dd>
        </div>
      </dl>
    </section>
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
    ['Chọn nguồn', 'Dán văn bản, TXT, EPUB, URL hoặc kho nguồn'],
    ['Phát hiện cấu trúc', 'Tựa truyện, ngôn ngữ, danh sách chương'],
    ['Làm sạch & preview', 'Kiểm tra cảnh báo và sửa metadata'],
    ['Chọn hành động', 'Lưu, dịch hoặc tạo audio'],
  ];

  return (
    <ol aria-label="Các bước nhập" className="import-wizard-steps">
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
          <p className="section-label">Bước 2 · Phát hiện cấu trúc</p>
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
  importJobClient,
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
  onFetchSourceChapters,
  onCreateTranslationJob,
  onCreateTtsJob,
  loadSourceCatalog,
  onOpenImportedBook,
  onOpenJob,
  onReturnToLibrary,
  onCancel,
  ebookImportHistory = [],
  loading = false,
  onRefreshEbookInbox,
}: ImportPanelProps) {
  const [mode, setMode] = useState<ImportMode>('paste');
  const [duplicateStrategy, setDuplicateStrategy] = useState<EbookDuplicateStrategy>('skip');
  const [targetBookId, setTargetBookId] = useState('');
  const [helpOpen, setHelpOpen] = useState(false);
  const [lastCreatedJob, setLastCreatedJob] = useState<JobStartResponse | null>(null);
  const {
    title, chapterNumber, chapterTitle, text, file, fileText, contentKind, finalAction,
    overwriteConfirmed, lastWizardResult, wizardError, importFields, textPreview,
    handleTitleChange, handleChapterNumberChange, handleChapterTitleChange, handleTextChange,
    handleFileChange, handleChapterEdit, submitWizardText, setContentKind,
    setFinalAction, setOverwriteConfirmed, clearWizardResult, applyPreviewTitle,
  } = useTextImport({ mode, books, chapters, targetBookId, duplicateStrategy,
    onImportWizardText, onCreateTranslationJob, onCreateTtsJob, onJobCreated: setLastCreatedJob });
  const {
    sourceUrl, sourcePreview, sourcePreviewState, sourcePreviewError,
    selectedChapterUrls, chapterPage, setChapterPage, rangeStart, setRangeStart, rangeEnd, setRangeEnd,
    fetchState, fetchResult, fetchError, catalogQuery, setCatalogQuery, catalogState, catalogError, catalog,
    importJob, sourceChapterPageCount, visibleSourceChapters, allVisibleChaptersSelected, durableImportActive,
    handlePreviewSourceUrl, toggleChapterSelection, toggleSelectVisibleChapters,
    selectChapterRange, handleFetchChapters, handleCatalogSearch, submitSourceUrl,
    updateSourceUrl, chooseCatalogSource,
  } = useSourceImport({ importJobClient, title, onPreviewTitle: applyPreviewTitle,
    onJobCreated: setLastCreatedJob, onPreviewImportUrl, onStartImportUrlJob, onFetchSourceChapters, loadSourceCatalog });
  const {
    ebookSource, ebookFile, selectedInboxFile, ebookPreview, ebookPreviewState, ebookPreviewError,
    confirmedExistingBookId, setConfirmedExistingBookId, ebookSubmissionBlocked,
    lastEbookImportResult, splitMode, selectedEbookFile, ebookHasBlockingWarning,
    existingBookConfirmed, ebookPreviewRetryAvailable,
    handleEbookFileChange, handleEbookDrop, handleEbookSourceChange, handleInboxFileChange,
    handleSplitModeChange, handleTargetBookChange, handleDuplicateStrategyChange,
    retryEbookPreview, submitTranslatedEbook, leaveEbookMode, enterEbookMode, cancelEbookPreview,
  } = useEbookImport({ ebookInboxDirectory, ebookInboxFiles, loading, duplicateStrategy, targetBookId,
    setDuplicateStrategy, setTargetBookId, onPreviewInboxEbook, onPreviewTranslatedEbook, onImportTranslatedEbook });

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
  let importActionStatus = 'Sẵn sàng import.';
  if (loading) {
    importActionStatus = 'Đang chạy import.';
  } else if (mode === 'paste' && !pastedTextReady) {
    importActionStatus = 'Dán nội dung nguồn để tiếp tục.';
  } else if ((mode === 'paste' || mode === 'file') && !titleReady) {
    importActionStatus = 'Cần tên truyện trước khi import.';
  } else if (mode === 'file' && !file) {
    importActionStatus = 'Chọn file nguồn để tiếp tục.';
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
    importActionStatus = 'Chọn file EPUB, AZW3, MOBI, PRC, TXT hoặc HTML.';
  } else if (mode === 'ebook' && ebookSource === 'inbox' && !selectedInboxFile) {
    importActionStatus = 'Chọn ebook từ server inbox.';
  } else if (mode === 'ebook' && ebookPreviewState === 'loading') {
    importActionStatus = 'Đang đọc preview ebook.';
  } else if (mode === 'ebook' && ebookPreviewState === 'error') {
    importActionStatus = 'Sửa lỗi preview ebook trước khi import.';
  } else if (mode === 'ebook' && ebookSubmissionBlocked) {
    importActionStatus = 'Chưa xác nhận được trạng thái import. Hãy kiểm tra Jobs hoặc lịch sử trước khi thử lại.';
  } else if (mode === 'ebook' && ebookHasBlockingWarning) {
    importActionStatus = 'Ebook preview không có nội dung chữ đủ để import.';
  } else if (mode === 'ebook' && !ebookPreview) {
    importActionStatus = 'Preview ebook trước khi import.';
  } else if (mode === 'ebook' && !existingBookConfirmed) {
    importActionStatus = 'Xác nhận gộp ebook vào truyện đã có trước khi import.';
  }
  const panelTitle =
    mode === 'ebook'
      ? 'Ebook bản dịch'
      : mode === 'file'
        ? 'Import file nguồn'
        : mode === 'url'
          ? 'Import từ URL'
          : mode === 'catalog'
            ? 'Kho nguồn'
            : 'Dán chương nguồn';
  const panelSubtitle =
    mode === 'ebook'
      ? 'Import ebook và thêm vào thư viện.'
      : mode === 'file'
        ? 'Tải file chứa nội dung chương cần import vào hệ thống.'
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

  function handleModeChange(nextMode: ImportMode): void {
    if (mode === 'ebook' && nextMode !== 'ebook') leaveEbookMode();
    setMode(nextMode);
    if (mode !== 'ebook' && nextMode === 'ebook') enterEbookMode();
  }

  function handleCancel(): void {
    if (mode === 'ebook') cancelEbookPreview();
    onCancel();
  }

  function returnToLibrary(): void {
    importJob.clearJob();
    onReturnToLibrary?.();
  }

  if (durableImportActive) {
    return (
      <section aria-labelledby="import-panel-title" className="import-panel import-reference-view panel">
        <div className="import-reference-header">
          <div>
            <p className="section-label">Nhập chương <span aria-hidden="true">›</span> Import từ URL</p>
            <h3 id="import-panel-title">Tiến độ import</h3>
            <p className="view-subtitle">Job tiếp tục chạy trên máy chủ kể cả khi kết nối trình duyệt bị gián đoạn.</p>
          </div>
        </div>
        <ImportJobProgress
          onCancel={importJob.cancelJob}
          onReset={importJob.clearJob}
          onRetryFailed={importJob.retryFailedTasks}
          onReturnToLibrary={onReturnToLibrary ? returnToLibrary : undefined}
          state={importJob.state}
        />
      </section>
    );
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

      <div aria-label="Chế độ nhập" className="segmented-actions import-mode-tabs">
        <button
          aria-label="Dán văn bản"
          aria-pressed={mode === 'paste'}
          className="secondary-action"
          onClick={() => handleModeChange('paste')}
          type="button"
        >
          <Clipboard aria-hidden="true" size={24} />
          <span>
            <strong>Dán văn bản</strong>
            <small>Dán văn bản</small>
          </span>
        </button>
        <button
          aria-label="Tải file"
          aria-pressed={mode === 'file'}
          className="secondary-action"
          onClick={() => handleModeChange('file')}
          type="button"
        >
          <FileText aria-hidden="true" size={24} />
          <span>
            <strong>Tải file</strong>
            <small>TXT / MD / HTML</small>
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
                Tải file
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
                    <p className="section-label">Bypass file local</p>
                    <h4 id="ebook-inbox-title">Server inbox</h4>
                  </div>
                  {onRefreshEbookInbox ? (
                    <button className="secondary-action" onClick={() => void onRefreshEbookInbox()} type="button">
                      Làm mới
                    </button>
                  ) : null}
                </div>
                <p>
                  Copy EPUB/AZW3/MOBI/PRC/TXT/HTML vào <code>{ebookInboxDirectory}</code>, rồi chọn file ở đây để tránh upload qua Cloudflare.
                </p>
                {ebookInboxError ? <p className="status-error">{ebookInboxError}</p> : null}
                <label>
                  <span>Ebook trong server inbox</span>
                  <select aria-label="Server inbox ebook" onChange={handleInboxFileChange} value={selectedInboxFile}>
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
                            chooseCatalogSource(entry.url);
                            setMode('url');
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
                  <p className="section-label">Bước 2 · Preview nguồn</p>
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
                <span>URL nguồn</span>
                <input
                  aria-label="Source URL"
                  inputMode="url"
                  onChange={(event) => {
                    updateSourceUrl(event.target.value);
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
                  {sourcePreview.bypass_used ? (
                    <p className="bypass-badge bypass-badge-active">
                      🔒 Auto-bypass: {sourcePreview.bypass_method || 'stealth browser'}
                    </p>
                  ) : (
                    <p className="bypass-badge bypass-badge-direct">
                      ✅ Kết nối trực tiếp
                    </p>
                  )}
                  {(importJobClient || onFetchSourceChapters) && sourcePreview.chapters.length > 0 ? (
                    <div className="url-fetch-panel">
                      <div className="url-fetch-header">
                        <label className="url-fetch-select-all">
                          <input
                            aria-label="Chọn tất cả chương đang hiển thị"
                            type="checkbox"
                            checked={allVisibleChaptersSelected}
                            onChange={toggleSelectVisibleChapters}
                          />
                          <span>Chọn trang này</span>
                        </label>
                        <button
                          className="primary-action url-fetch-btn"
                          disabled={selectedChapterUrls.size === 0 || fetchState === 'loading'}
                          onClick={() => void handleFetchChapters()}
                          type="button"
                        >
                          {fetchState === 'loading'
                            ? <><Loader2 aria-hidden="true" className="status-spinner" size={15} /> Đang tải...</>
                            : importJobClient
                              ? <><Download aria-hidden="true" size={15} /> Tạo job {selectedChapterUrls.size} chương</>
                              : <><Download aria-hidden="true" size={15} /> Tải {selectedChapterUrls.size > 0 ? selectedChapterUrls.size : ''} chương</>}
                        </button>
                      </div>
                      <div className="url-chapter-selection-tools">
                        <strong>Đã chọn {selectedChapterUrls.size}/{sourcePreview.chapters.length} chương</strong>
                        <div className="url-chapter-range">
                          <label>
                            <span>Từ chương</span>
                            <input
                              aria-label="Từ chương"
                              inputMode="numeric"
                              min="1"
                              onChange={(event) => setRangeStart(event.target.value)}
                              type="number"
                              value={rangeStart}
                            />
                          </label>
                          <label>
                            <span>Đến chương</span>
                            <input
                              aria-label="Đến chương"
                              inputMode="numeric"
                              min="1"
                              onChange={(event) => setRangeEnd(event.target.value)}
                              type="number"
                              value={rangeEnd}
                            />
                          </label>
                          <button
                            className="secondary-action"
                            disabled={!rangeStart || !rangeEnd}
                            onClick={selectChapterRange}
                            type="button"
                          >
                            Chọn khoảng chương
                          </button>
                        </div>
                      </div>
                      <ol className="ebook-preview-chapters url-chapter-list">
                        {visibleSourceChapters.map((chapter) => (
                          <li key={`${chapter.chapter_number}-${chapter.url}`}>
                            <label className="url-chapter-item">
                              <input
                                aria-label={`Chọn ${chapter.title || `Chương ${chapter.chapter_number}`}`}
                                type="checkbox"
                                checked={selectedChapterUrls.has(chapter.url)}
                                onChange={() => toggleChapterSelection(chapter.url)}
                              />
                              <div>
                                <span>#{chapter.chapter_number}</span>
                                <strong>{chapter.title || `Chương ${chapter.chapter_number}`}</strong>
                              </div>
                            </label>
                            <p className="url-chapter-link">{chapter.url}</p>
                            {fetchResult?.chapters.find((r) => r.url === chapter.url) ? (
                              <span className={`fetch-result-badge ${fetchResult.chapters.find((r) => r.url === chapter.url)?.success ? 'fetch-ok' : 'fetch-fail'}`}>
                                {fetchResult.chapters.find((r) => r.url === chapter.url)?.success
                                  ? `✅ ${fetchResult.chapters.find((r) => r.url === chapter.url)?.text_length.toLocaleString('vi-VN')} chars`
                                  : `❌ ${fetchResult.chapters.find((r) => r.url === chapter.url)?.error}`}
                              </span>
                            ) : null}
                          </li>
                        ))}
                      </ol>
                      {sourceChapterPageCount > 1 ? (
                        <nav aria-label="Phân trang chương nguồn" className="import-pagination">
                          <button
                            aria-label="Trang trước"
                            className="secondary-action"
                            disabled={chapterPage === 0}
                            onClick={() => setChapterPage((page) => Math.max(0, page - 1))}
                            type="button"
                          >
                            Trước
                          </button>
                          <span>Trang {chapterPage + 1}/{sourceChapterPageCount}</span>
                          <button
                            aria-label="Trang sau"
                            className="secondary-action"
                            disabled={chapterPage >= sourceChapterPageCount - 1}
                            onClick={() => setChapterPage((page) => Math.min(sourceChapterPageCount - 1, page + 1))}
                            type="button"
                          >
                            Sau
                          </button>
                        </nav>
                      ) : null}
                      {fetchError ? <p className="status-error" role="alert">{fetchError}</p> : null}
                      {fetchResult && fetchResult.succeeded > 0 ? (
                        <p className="status-chip status-chip-success">
                          ✅ Đã tải {fetchResult.succeeded}/{fetchResult.total} chương vào "{fetchResult.title}"
                        </p>
                      ) : null}
                    </div>
                  ) : (
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
                  )}
                </section>
              ) : null}
            </section>
          </>
        ) : (
          <>
            <label>
              <span>Tên truyện</span>
              <input
                aria-label="Book title"
                name="title"
                onChange={handleTitleChange}
                placeholder="Nhập tên truyện hoặc để trống nếu đã chọn từ Library"
                type="text"
                value={title}
              />
            </label>

            <label>
              <span>Số chương</span>
              <input
                aria-label="Chapter number"
                min="1"
                name="chapter_number"
                onChange={handleChapterNumberChange}
                type="number"
                value={chapterNumber}
              />
            </label>

            <label>
              <span>Tiêu đề chương</span>
              <input
                aria-label="Chapter title"
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
              <span>Nội dung nguồn</span>
              <textarea
                aria-label="Source text"
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
            <span>File nguồn</span>
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
              <button className="secondary-action" onClick={clearWizardResult} type="button">
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
          {importJobClient && (mode === 'url' || mode === 'catalog') ? null : (
            <button
              aria-describedby={importActionStatusId}
              className="primary-action"
              disabled={!canSubmit}
              type="submit"
            >
              {mode === 'paste' ? <Upload aria-hidden="true" size={16} /> : mode === 'file' ? <Upload aria-hidden="true" size={16} /> : <ArrowRight aria-hidden="true" size={16} />}
              {submitLabel}
            </button>
          )}
        </div>
      </form>
    </section>
  );
}
