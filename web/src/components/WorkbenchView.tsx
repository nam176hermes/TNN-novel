import {
  Activity,
  BookOpenCheck,
  CheckCircle2,
  ChevronRight,
  Database,
  Eye,
  EyeOff,
  ExternalLink,
  FilePlus2,
  LibraryBig,
  Maximize2,
  Save,
  Sparkles,
  Sun,
  TrendingUp,
} from 'lucide-react';
import { useState, type ReactNode } from 'react';
import type { Chapter, CostEstimate, JobStatus, StyleProfile, TranslationPreset } from '../api/types';
import type { LoadState } from '../state/types';
import CommandBar from './CommandBar';

export type WorkbenchViewMode = 'edit' | 'reader';

export type WorkbenchDashboardActivity = {
  id: string;
  label: string;
  timestampLabel: string;
};

export type WorkbenchDashboardSystemItem = {
  label: string;
  ok: boolean;
  statusLabel: string;
};

export type WorkbenchDashboardData = {
  activeJobCount: number;
  activities: WorkbenchDashboardActivity[];
  loading?: boolean;
  progressPercent: number;
  rawBookCount: number;
  rawChapterCount: number;
  systemItems: WorkbenchDashboardSystemItem[];
  translatedChapterCount: number;
};

export type WorkbenchViewProps = {
  activeJob: JobStatus | null;
  assistPanel?: ReactNode;
  chapter: Chapter | null;
  contentHtml: string;
  dashboard?: WorkbenchDashboardData;
  estimate: CostEstimate | null;
  estimateDisabledReason: string;
  isDirty: boolean;
  selectedPresetId: string;
  selectedStyleProfileId: string;
  sourceState: LoadState;
  sourceText: string;
  styleProfiles: StyleProfile[];
  translationPresets: TranslationPreset[];
  translateDisabledReason: string;
  translationText: string;
  translatedTitle: string;
  viewMode: WorkbenchViewMode;
  onCopyTranslation?: () => void;
  onDeleteChapter(): void;
  onDeleteTranslation(): void;
  onEstimate(): void;
  onOpenGlossary?(): void;
  onOpenImport?(): void;
  onOpenJobs?(): void;
  onOpenLibrary?(): void;
  onOpenStatus?(): void;
  onPresetChange(presetId: string): void;
  onSave(): void;
  onStyleProfileChange(styleProfileId: string): void;
  onTranslate(): void;
  onTranslationChange(text: string): void;
  onTranslatedTitleChange(title: string): void;
  onViewModeChange(mode: WorkbenchViewMode): void;
};

function formatChapterStatus(status: string): string {
  return ({imported: 'Đã nhập', cleaned: 'Đã làm sạch', translated: 'Đã dịch',
    qa_low: 'Cần xem lại', audio_done: 'Đã có audio', failed: 'Có lỗi'} as Record<string, string>)[status] ?? 'Chưa xử lý';
}

function splitReaderParagraphs(text: string): string[] {
  return text
    .split(/\n{2,}/)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean);
}

export default function WorkbenchView({
  activeJob,
  assistPanel,
  chapter,
  contentHtml,
  dashboard,
  estimate,
  estimateDisabledReason,
  isDirty,
  selectedPresetId,
  selectedStyleProfileId,
  sourceState,
  sourceText,
  styleProfiles,
  translationPresets,
  translateDisabledReason,
  translationText,
  translatedTitle,
  viewMode,
  onCopyTranslation,
  onDeleteChapter,
  onDeleteTranslation,
  onEstimate,
  onOpenGlossary,
  onOpenImport,
  onOpenJobs,
  onOpenLibrary,
  onOpenStatus,
  onPresetChange,
  onSave,
  onStyleProfileChange,
  onTranslate,
  onTranslationChange,
  onTranslatedTitleChange,
  onViewModeChange,
}: WorkbenchViewProps) {
  const [mobileSection, setMobileSection] = useState<'editor' | 'assist'>('editor');
  const [mobileEditorMode, setMobileEditorMode] = useState<'source' | 'translation' | 'parallel'>('translation');
  const [expandedPane, setExpandedPane] = useState<'source' | 'translation' | null>(null);
  const [translationHidden, setTranslationHidden] = useState(false);
  const readerParagraphs = splitReaderParagraphs(translationText);
  const hasRichContent = contentHtml.trim().length > 0;
  const bookLabel = chapter?.book_title || (chapter ? `Book ${chapter.book_id}` : '');
  const dashboardData = dashboard ?? {
    activeJobCount: activeJob ? 1 : 0,
    activities: [],
    loading: false,
    progressPercent: 0,
    rawBookCount: 0,
    rawChapterCount: 0,
    systemItems: [],
    translatedChapterCount: 0,
  };
  const metricSuffix = dashboardData.loading ? 'Đang cập nhật' : 'Dữ liệu hiện tại';

  if (!chapter) {
    return (
      <section aria-labelledby="workbench-empty-title" className="workbench-view workbench-dashboard-empty">
        <header className="workbench-dashboard-topbar">
          <span>Workbench</span>
          <i aria-hidden="true" />
          <button aria-label="Mở trạng thái hệ thống" disabled={!onOpenStatus} onClick={onOpenStatus} type="button">
            <Sun aria-hidden="true" size={18} />
          </button>
        </header>

        <div className="panel workbench-empty-hero">
          <span className="workbench-empty-hero-icon" aria-hidden="true">
            <BookOpenCheck size={46} />
          </span>
          <div>
            <h2 id="workbench-empty-title">Chưa chọn chương</h2>
            <p>Chọn một chương trong danh sách bên trái để bắt đầu biên tập bản dịch.</p>
          </div>
        </div>

        <section aria-label="Lối tắt bàn dịch" className="workbench-quick-grid">
          <button aria-label="Mở danh sách chương" disabled={!onOpenLibrary} onClick={onOpenLibrary} type="button">
            <BookOpenCheck aria-hidden="true" size={26} />
            <strong>Chọn chương</strong>
            <span>Mở danh sách chương để biên tập</span>
          </button>
          <button aria-label="Mở nhập chương mới" disabled={!onOpenImport} onClick={onOpenImport} type="button">
            <FilePlus2 aria-hidden="true" size={26} />
            <strong>Nhập chương mới</strong>
            <span>Paste, file hoặc ebook bản dịch</span>
          </button>
          <button aria-label="Mở kho truyện" disabled={!onOpenLibrary} onClick={onOpenLibrary} type="button">
            <LibraryBig aria-hidden="true" size={26} />
            <strong>Thư viện</strong>
            <span>Quản lý truyện của bạn</span>
          </button>
          <button aria-label="Mở thuật ngữ" disabled={!onOpenGlossary} onClick={onOpenGlossary} type="button">
            <BookOpenCheck aria-hidden="true" size={26} />
            <strong>Thuật ngữ</strong>
            <span>Quản lý thuật ngữ và văn phong</span>
          </button>
        </section>

        <section aria-label="Tổng quan hôm nay" className="panel workbench-overview-panel">
          <h3>
            <TrendingUp aria-hidden="true" size={20} />
            Tổng quan hôm nay
          </h3>
          <div className="workbench-overview-grid">
            <div>
              <BookOpenCheck aria-hidden="true" size={24} />
              <strong>{dashboardData.rawChapterCount.toLocaleString('vi-VN')}</strong>
              <span>Chương raw</span>
              <small>{dashboardData.rawBookCount.toLocaleString('vi-VN')} truyện · {metricSuffix}</small>
            </div>
            <div>
              <FilePlus2 aria-hidden="true" size={24} />
              <strong>{dashboardData.activeJobCount.toLocaleString('vi-VN')}</strong>
              <span>Truyện đang xử lý</span>
              <small>{activeJob ? activeJob.status : metricSuffix}</small>
            </div>
            <div>
              <LibraryBig aria-hidden="true" size={24} />
              <strong>{dashboardData.translatedChapterCount.toLocaleString('vi-VN')}</strong>
              <span>Chương đã dịch</span>
              <small>{metricSuffix}</small>
            </div>
            <div>
              <Activity aria-hidden="true" size={24} />
              <strong>{dashboardData.progressPercent}%</strong>
              <span>Tiến độ tổng</span>
              <small>Từ thư viện đã dịch</small>
            </div>
          </div>
        </section>

        <div className="workbench-dashboard-columns">
          <section aria-label="Hoạt động gần đây" className="panel workbench-activity-panel">
            <h3>
              <Activity aria-hidden="true" size={20} />
              Hoạt động gần đây
            </h3>
            {dashboardData.activities.length > 0 ? (
              <ul>
                {dashboardData.activities.map((activity) => (
                  <li key={activity.id}>
                    <span>{activity.label}</span>
                    <time>{activity.timestampLabel}</time>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="empty-detail">Chưa có hoạt động gần đây.</p>
            )}
            <button disabled={!onOpenJobs} onClick={onOpenJobs} type="button">Xem tất cả hoạt động</button>
          </section>

          <section aria-label="Trạng thái hệ thống" className="panel workbench-system-panel">
            <h3>Trạng thái hệ thống</h3>
            {(dashboardData.systemItems.length > 0 ? dashboardData.systemItems : [
              { label: 'API Server', ok: false, statusLabel: dashboardData.loading ? 'Đang kiểm tra' : 'Chưa tải' },
              { label: 'Dịch vụ dịch', ok: false, statusLabel: dashboardData.loading ? 'Đang kiểm tra' : 'Chưa tải' },
              { label: 'Cơ sở dữ liệu', ok: false, statusLabel: dashboardData.loading ? 'Đang kiểm tra' : 'Chưa tải' },
              { label: 'Lưu trữ', ok: false, statusLabel: dashboardData.loading ? 'Đang kiểm tra' : 'Chưa tải' },
            ]).map((item) => (
              <div data-ok={item.ok ? 'true' : 'false'} key={item.label}>
                <CheckCircle2 aria-hidden="true" size={18} />
                <span>{item.label}</span>
                <strong>{item.statusLabel}</strong>
              </div>
            ))}
            <button disabled={!onOpenStatus} onClick={onOpenStatus} type="button">Xem chi tiết hệ thống</button>
          </section>
        </div>

        <section aria-label="Mẹo sử dụng" className="panel workbench-tip-panel">
          <span aria-hidden="true">
            <Sparkles size={26} />
          </span>
          <div>
            <strong>Mẹo sử dụng</strong>
            <p>Bạn có thể nhập nhanh chương bằng cách paste nội dung hoặc kéo thả file .txt, .epub, .html vào mục Nhập chương.</p>
          </div>
          <button className="primary-action" disabled={!onOpenImport} onClick={onOpenImport} type="button">
            <Database aria-hidden="true" size={16} />
            Nhập chương ngay
          </button>
        </section>
      </section>
    );
  }

  return (
    <section
      aria-label="Workbench"
      className="workbench-view"
      data-expanded-pane={expandedPane ?? 'none'}
      data-mobile-editor-mode={mobileEditorMode}
      data-mobile-section={mobileSection}
      data-translation-hidden={translationHidden ? 'true' : 'false'}
      data-view-mode={viewMode}
    >
      <header className="workbench-reference-header">
        <div className="workbench-reference-heading">
          <nav aria-label="Bàn dịch breadcrumb" className="workbench-breadcrumb">
            <span>Bản dịch</span>
            <ChevronRight aria-hidden="true" size={14} />
            <span>{bookLabel}</span>
            <ChevronRight aria-hidden="true" size={14} />
            <span>Chương {chapter.chapter_number}</span>
          </nav>
          <h2>{chapter.title}</h2>
          {viewMode === 'edit' ? (
            <label className="workbench-translated-title">
              Tiêu đề bản dịch
              <input maxLength={300} onChange={(event) => onTranslatedTitleChange(event.target.value)}
                placeholder={chapter.title} type="text" value={translatedTitle} />
            </label>
          ) : null}
          {chapter.quality_status ? <p role="status">{({pass: 'Đã kiểm tra bản dịch', needs_review: 'Bản dịch cần xem lại',
            partial: 'Chưa kiểm tra hết bản dịch', stale: 'Cần kiểm tra lại sau khi sửa',
            legacy_unverified: 'Bản dịch cũ chưa xác minh', unreviewed: 'Bản dịch chưa kiểm tra'})[chapter.quality_status]}</p> : null}
        </div>
        <div className="workbench-title-actions workbench-reference-actions">
          <button className="primary-action" disabled={!isDirty} onClick={onSave} type="button">
            <Save aria-hidden="true" size={16} />
            Lưu
          </button>
          <button
            aria-pressed={viewMode === 'reader'}
            className="secondary-action"
            onClick={() => onViewModeChange(viewMode === 'reader' ? 'edit' : 'reader')}
            type="button"
          >
            <Eye aria-hidden="true" size={16} />
            {viewMode === 'reader' ? 'Sửa' : 'Đọc'}
          </button>
          <span className={`workbench-import-status status-${chapter.status.toLowerCase().replace(/\s+/g, '-')}`}>
            <ExternalLink aria-hidden="true" size={15} />
            {formatChapterStatus(chapter.status)}
          </span>
        </div>
      </header>

      {viewMode === 'edit' ? (
        <CommandBar
          activeJob={activeJob}
          estimate={estimate}
          estimateDisabledReason={estimateDisabledReason}
          isDirty={isDirty}
          onDeleteChapter={onDeleteChapter}
          onDeleteTranslation={onDeleteTranslation}
          onEstimate={onEstimate}
          onPresetChange={onPresetChange}
          onStyleProfileChange={onStyleProfileChange}
          onTranslate={onTranslate}
          selectedPresetId={selectedPresetId}
          selectedStyleProfileId={selectedStyleProfileId}
          styleProfiles={styleProfiles}
          translationPresets={translationPresets}
          translateDisabledReason={translateDisabledReason}
        />
      ) : null}

      {assistPanel && viewMode === 'edit' ? (
        <section aria-label="Mobile workbench panels" className="workbench-mobile-tabs" role="tablist">
          <button
            aria-selected={mobileSection === 'editor'}
            onClick={() => setMobileSection('editor')}
            role="tab"
            type="button"
          >
            Nội dung
          </button>
          <button
            aria-selected={mobileSection === 'assist'}
            onClick={() => setMobileSection('assist')}
            role="tab"
            type="button"
          >
            Trợ lý
          </button>
        </section>
      ) : null}

      {viewMode === 'reader' ? (
        <article aria-label="Bản đọc tiếng Việt" className="reader-mode-content">
          {hasRichContent ? (
            <div className="chapter-rich-content" dangerouslySetInnerHTML={{ __html: contentHtml }} />
          ) : readerParagraphs.length > 0 ? (
            readerParagraphs.map((paragraph, index) => <p key={`${paragraph.slice(0, 24)}-${index}`}>{paragraph}</p>)
          ) : (
            <p>Chưa có bản dịch tiếng Việt</p>
          )}
        </article>
      ) : (
        <div className="workbench-body">
          <div aria-label="Chế độ bàn dịch di động" className="workbench-editor-mode-tabs" role="tablist">
            <button
              aria-selected={mobileEditorMode === 'source'}
              onClick={() => setMobileEditorMode('source')}
              role="tab"
              type="button"
            >
              Bản gốc
            </button>
            <button
              aria-selected={mobileEditorMode === 'translation'}
              onClick={() => setMobileEditorMode('translation')}
              role="tab"
              type="button"
            >
              Bản dịch
            </button>
            <button
              aria-selected={mobileEditorMode === 'parallel'}
              onClick={() => setMobileEditorMode('parallel')}
              role="tab"
              type="button"
            >
              Song song
            </button>
          </div>
          <div className="editor-grid-v2">
            <section className="editor-pane" aria-labelledby="workbench-source-title">
              <header className="editor-pane-header">
                <h3 id="workbench-source-title">Bản gốc tiếng Trung</h3>
                <button
                  className="secondary-action"
                  onClick={() => setExpandedPane((current) => (current === 'source' ? null : 'source'))}
                  type="button"
                >
                  <Maximize2 aria-hidden="true" size={15} />
                  {expandedPane === 'source' ? 'Thu nhỏ' : 'Mở toàn màn hình'}
                </button>
              </header>
              <article className="source-reader">
                {sourceState === 'loading' ? 'Đang tải bản gốc...' : sourceText || 'Chưa tải bản gốc'}
              </article>
            </section>

            <section className="editor-pane">
              <header className="editor-pane-header">
                <h3>Bản dịch tiếng Việt</h3>
                <div className="editor-pane-actions">
                  <button
                    className="secondary-action"
                    onClick={() => setExpandedPane((current) => (current === 'translation' ? null : 'translation'))}
                    type="button"
                  >
                    <Maximize2 aria-hidden="true" size={15} />
                    {expandedPane === 'translation' ? 'Thu nhỏ' : 'Mở toàn màn hình'}
                  </button>
                  <button
                    aria-pressed={translationHidden}
                    className="secondary-action"
                    onClick={() => setTranslationHidden((current) => !current)}
                    type="button"
                  >
                    {translationHidden ? <Eye aria-hidden="true" size={15} /> : <EyeOff aria-hidden="true" size={15} />}
                    {translationHidden ? 'Hiện bản dịch' : 'Ẩn bản dịch'}
                  </button>
                </div>
              </header>
              {translationHidden ? (
                <div className="translation-hidden-state">
                  <EyeOff aria-hidden="true" size={18} />
                  Bản dịch đang được ẩn.
                </div>
              ) : (
                <label className="translation-editor">
                  <span className="sr-only">Bản dịch tiếng Việt</span>
                  <textarea
                    disabled={sourceState === 'loading'}
                    onChange={(event) => onTranslationChange(event.target.value)}
                    placeholder={'Chưa có bản dịch\nBắt đầu dịch để xem bản dịch tại đây.'}
                    value={translationText}
                  />
                </label>
              )}
              {onCopyTranslation ? (
                <button className="secondary-action" disabled={!translationText} onClick={onCopyTranslation} type="button">
                  Sao chép
                </button>
              ) : null}
              {hasRichContent ? (
                <article
                  aria-label="Minh họa trong chương"
                  className="chapter-rich-content chapter-rich-preview"
                  dangerouslySetInnerHTML={{ __html: contentHtml }}
                />
              ) : null}
            </section>
          </div>
          {assistPanel}
        </div>
      )}
      {expandedPane ? (
        <button className="workbench-expanded-backdrop" onClick={() => setExpandedPane(null)} type="button">
          <span className="sr-only">Đóng toàn màn hình</span>
        </button>
      ) : null}
    </section>
  );
}
