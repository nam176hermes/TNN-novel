import { lazy, Suspense, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import {
  BookOpenText,
  Bookmark,
  Download,
  ScrollText,
  Trash2,
  Upload,
  Volume2,
  Wrench,
  X,
} from 'lucide-react';
import type { ApiClient } from '../api/client';
import type {
  Chapter,
  QaReport,
  ReaderAnnotationExportFormat,
  ReaderAnnotationImportItem,
  ReaderAnnotationKind,
  ReaderDictionaryFile,
  ReaderDictionaryResponse,
  ReaderExplainResponse,
  ReaderExplainSpoilerMode,
  ReaderSyncConflict,
  ReaderSyncProgress,
  ReaderSearchResult,
  ReaderXrayResponse,
  ReaderXraySpoilerMode,
  TranslatedBookSummary,
} from '../api/types';
import coverDocTu from '../assets/reference-ui/cover-doc-tu-clean.png';
import coverThanhSon from '../assets/reference-ui/cover-thanh-son-clean.png';
import {
  absoluteCharOffsetForParagraph,
  bookProgressPercent,
  collapsedRangeRectAtTextOffset,
  countWords,
  estimateReadingMinutes,
  fallbackParagraphPages,
  pageBreakOffsetsForViewportSlices,
  pageIndexForParagraph,
  paragraphLocation,
  paginateParagraphsByViewport,
  readerTextLocationFromViewportAnchor,
  readingStatsForText,
  textLength,
  textNodeAtOffset,
  textOffsetFromPointInNode,
  textOffsetWithinNode,
  type ReaderFallbackPageHint,
  type ReaderViewportPage,
} from '../state/readerLocation';
import {
  acceptReaderAnnotationConflictFromServer,
  annotationToLocalMark,
  chapterMarksKey,
  createEmptyChapterMarks,
  loadReaderMarks,
  markReaderAnnotationConflictForLocalResolution,
  mergeLocalAndRemoteMarks,
  readerMarksToSyncAnnotations,
  saveReaderMarks,
  sanitizeChapterMarks,
  type ReaderChapterMarks,
  type ReaderDeletedAnnotation,
  type ReaderHighlight,
  type ReaderMarksStore,
  type ReaderNote,
} from '../state/readerMarks';
import { formatError, type LoadState } from '../state/types';
import {
  READER_CACHE_UPDATED_EVENT,
  cacheReaderAudio,
  getCachedReaderAssetUrl,
  getCachedReaderAudioUrl,
  readerCacheStatusAsync,
  removeCachedBookAsync,
  removeCachedChapterAsync,
  type ReaderCacheStatus,
} from '../state/readerCache';
import {
  loadCachedReaderDictionaryResult,
  lookupCachedReaderDictionaryPack,
  saveCachedReaderDictionaryPack,
  saveCachedReaderDictionaryResult,
} from '../state/readerDictionaryCache';
import { loadReaderDeviceId } from '../state/readerDevice';
import {
  cacheBookForOffline,
  cacheChapterForOffline,
  loadReaderOfflineManifest,
  removeReaderOfflineManifestChapter,
  removeReaderOfflineManifest,
  type ReaderOfflineManifest,
} from '../state/readerOfflineCache';
import {
  chooseLatestReaderProgressSnapshot,
  loadReaderLastSyncAt,
  loadReaderProgressSnapshot,
  remoteReaderProgressToSnapshot,
  saveReaderLastSyncAt,
  saveReaderProgressSnapshot,
  type ReaderProgressSnapshot,
} from '../state/readerProgress';
import { buildReaderProgressTextAnchor, resolveReaderProgressTextAnchor } from '../state/readerProgressAnchor';
import {
  extractReaderRichBlocks,
  htmlTextContent,
  richBlockNeedsTextMirror,
  sliceReaderRichBlockHtml,
  type ReaderRichBlock,
} from '../state/readerRichContent';
import { searchCurrentChapter, type ReaderSearchOptions } from '../state/readerSearch';
import ReaderAudioSummary from './reader/ReaderAudioSummary';
import ReaderDictionaryPanel from './reader/ReaderDictionaryPanel';
import ReaderMarksPanel, { type ReaderMarkPanelItem } from './reader/ReaderMarksPanel';
import ReaderAiPanel, { type ReaderAiPanelMode } from './reader/ReaderAiPanel';
import {
  ReaderChromeBottom,
  ReaderChromeTop,
  type ReaderChromeActions,
  type ReaderChromeNavigation,
  type ReaderChromeTitle,
} from './reader/ReaderChrome';
import {
  ReaderQuickActionBar,
  ReaderQuickSettingsSheet,
  ReaderTextModeSwitcher,
  type ReaderQuickModeControls,
  type ReaderQuickSettingsControls,
} from './reader/ReaderQuickControls';
import ReaderSearchPanel from './reader/ReaderSearchPanel';
import ReaderSelectionPopover, { type ReaderSelectionAction } from './reader/ReaderSelectionPopover';
import ReaderTocSheet, { type TocChapterPreview } from './reader/ReaderTocSheet';
import ReaderTextSurface, { type ReaderParagraphQaBadge, type ReaderVisibleRichBlock } from './reader/ReaderTextSurface';
import ReaderXrayPanel from './reader/ReaderXrayPanel';
import { useReaderAudio } from './reader/useReaderAudio';
import {
  loadReaderSettings,
  loadReaderTextMode,
  saveReaderSettings,
  saveReaderTextMode,
} from './reader/readerSettings';
import type {
  ReaderFontFamily,
  ReaderSettings,
  ReaderTextMode,
  ReaderTheme,
  ReaderWidth,
} from './reader/types';

const ReaderAudioFeature = lazy(() => import('./reader/ReaderAudioFeature'));

export function ReaderAudioFeatureBoundary({
  active,
  audio,
}: {
  active: boolean;
  audio: ReturnType<typeof useReaderAudio>;
}) {
  if (!active) return null;
  return (
    <Suspense fallback={null}>
      <ReaderAudioFeature audio={audio} />
    </Suspense>
  );
}

export type ReaderApiClient = Pick<
  ApiClient,
  | 'chapterAudioDownloadUrl'
  | 'chapterAudioUrl'
  | 'cancelJob'
  | 'createReaderAnnotation'
  | 'deleteReaderAnnotation'
  | 'deleteReaderDictionary'
  | 'downloadAudiobookExport'
  | 'downloadReaderAnnotations'
  | 'enrichReaderXray'
  | 'explainReaderSelection'
  | 'getChapterContent'
  | 'getChapterTranslation'
  | 'getBookAudioPlaylist'
  | 'getJobStatus'
  | 'getQaReport'
  | 'getReaderDictionaryPack'
  | 'getReaderXray'
  | 'getReaderState'
  | 'getTtsJob'
  | 'importReaderAnnotations'
  | 'listReaderDictionaries'
  | 'lookupReaderDictionary'
  | 'retryTtsJob'
  | 'saveReaderProgress'
  | 'searchBook'
  | 'startBookTtsJob'
  | 'startTtsJob'
  | 'syncReaderState'
  | 'updateReaderAnnotation'
  | 'uploadReaderDictionary'
>;

export type ReaderViewProps = {
  apiClient?: ReaderApiClient;
  books: TranslatedBookSummary[];
  chapters: Chapter[];
  activeBookId: number | null;
  selectedChapter: Chapter | null;
  selectedChapterId: number | null;
  contentHtml: string;
  textError: string;
  textState: LoadState;
  translationText: string;
  onBackToLibrary(): void;
  onOpenWorkbench(): void;
  onSelectBook(bookId: number): void;
  onSelectChapter(chapterId: number): void;
};

function splitParagraphs(text: string): string[] {
  return text
    .split(/\n{2,}/)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean);
}

function containsHanText(text: string): boolean {
  return /[\u3400-\u9fff]/u.test(text);
}

function recordFromUnknown(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' ? value as Record<string, unknown> : null;
}

function readRecordString(record: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return '';
}

function readRecordNumber(record: Record<string, unknown>, keys: string[]): number | null {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === 'number' && Number.isFinite(value)) return Math.max(0, Math.round(value));
    if (typeof value === 'string' && value.trim() && Number.isFinite(Number(value))) {
      return Math.max(0, Math.round(Number(value)));
    }
  }
  return null;
}

function glossaryViolationsFromQaReport(report: QaReport | null): Array<Record<string, unknown>> {
  if (!report || !Array.isArray(report.glossary_violations)) return [];
  return report.glossary_violations.flatMap((item) => {
    const record = recordFromUnknown(item);
    return record ? [record] : [];
  });
}

function addReaderQaBadge(
  badgesByParagraph: Map<number, ReaderParagraphQaBadge[]>,
  paragraphIndex: number,
  badge: ReaderParagraphQaBadge,
): void {
  if (!Number.isInteger(paragraphIndex) || paragraphIndex < 0) return;
  const current = badgesByParagraph.get(paragraphIndex) ?? [];
  if (current.some((item) => item.key === badge.key)) return;
  badgesByParagraph.set(paragraphIndex, [...current, badge]);
}

function findQaViolationParagraphIndex(
  violation: Record<string, unknown>,
  translatedParagraphs: string[],
  rawParagraphs: string[],
): number {
  const explicitIndex = readRecordNumber(violation, ['paragraph_index', 'paragraphIndex', 'paragraph']);
  if (explicitIndex !== null) return explicitIndex;

  const sourceTerm = readRecordString(violation, ['source_term', 'sourceTerm', 'raw_text', 'rawText', 'term']);
  const expected = readRecordString(violation, ['expected_translation', 'expectedTranslation', 'preferred_translation']);
  if (sourceTerm) {
    const rawIndex = rawParagraphs.findIndex((paragraph) => paragraph.includes(sourceTerm));
    if (rawIndex >= 0) return rawIndex;
    const translatedIndex = translatedParagraphs.findIndex((paragraph) => paragraph.includes(sourceTerm));
    if (translatedIndex >= 0) return translatedIndex;
  }
  if (expected) {
    const translatedIndex = translatedParagraphs.findIndex((paragraph) => paragraph.includes(expected));
    if (translatedIndex >= 0) return translatedIndex;
  }
  return 0;
}

function buildReaderQaBadges(
  report: QaReport | null,
  translatedParagraphs: string[],
  rawParagraphs: string[],
): Map<number, ReaderParagraphQaBadge[]> {
  const badgesByParagraph = new Map<number, ReaderParagraphQaBadge[]>();
  if (!report) return badgesByParagraph;

  const leakageCount = Math.max(0, Math.round(report.chinese_leakage_count ?? 0));
  if (leakageCount > 0) {
    let marked = 0;
    translatedParagraphs.forEach((paragraph, index) => {
      if (marked >= leakageCount || !containsHanText(paragraph)) return;
      addReaderQaBadge(badgesByParagraph, index, {
        key: `cjk-${index}`,
        label: 'Rò chữ Trung',
        tone: 'fail',
      });
      marked += 1;
    });
  }

  glossaryViolationsFromQaReport(report).forEach((violation, index) => {
    const sourceTerm = readRecordString(violation, ['source_term', 'sourceTerm', 'raw_text', 'rawText', 'term']);
    const expected = readRecordString(violation, ['expected_translation', 'expectedTranslation', 'preferred_translation']);
    const reason = readRecordString(violation, ['reason', 'message', 'detail']);
    const detail = [
      sourceTerm ? `Term: ${sourceTerm}` : '',
      expected ? `Nên dùng: ${expected}` : '',
      reason,
    ].filter(Boolean).join(' · ');
    addReaderQaBadge(
      badgesByParagraph,
      findQaViolationParagraphIndex(violation, translatedParagraphs, rawParagraphs),
      {
        key: `glossary-${index}-${sourceTerm || expected || 'term'}`,
        label: 'Vi phạm thuật ngữ',
        detail,
        tone: report.term_consistency_status === 'FAIL' ? 'fail' : 'warning',
      },
    );
  });

  return badgesByParagraph;
}

function normalizedContentKey(value: string): string {
  return value.replace(/[\W_]+/gu, '').toLowerCase();
}

function normalizeReaderCoverName(value: string): string {
  return value
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .replace(/đ/g, 'd')
    .replace(/Đ/g, 'D')
    .toLowerCase();
}

function fallbackReaderCover(book: TranslatedBookSummary | null | undefined): string {
  if (!book) return '';
  const normalized = normalizeReaderCoverName(`${book.title} ${book.author}`);
  if (normalized.includes('doc tu')) return coverDocTu;
  if (normalized.includes('thanh son')) return coverThanhSon;
  return '';
}

function translationLooksTitleOnly(text: string, chapter: Chapter): boolean {
  const textKey = normalizedContentKey(text);
  if (!textKey || textKey.length > 120) return false;
  const title = chapter.title.trim();
  const candidates = [
    title,
    `Chương ${chapter.chapter_number} ${title}`,
    `Chuong ${chapter.chapter_number} ${title}`,
    `Chapter ${chapter.chapter_number} ${title}`,
    `Hồi ${chapter.chapter_number} ${title}`,
    `Hoi ${chapter.chapter_number} ${title}`,
  ];
  return candidates.some((candidate) => normalizedContentKey(candidate) === textKey);
}

function sortChapters(chapters: Chapter[]): Chapter[] {
  return [...chapters].sort((left, right) => {
    if (left.chapter_number !== right.chapter_number) return left.chapter_number - right.chapter_number;
    return left.id - right.id;
  });
}

function formatCount(value: number): string {
  return Math.max(0, value).toLocaleString('vi-VN');
}

function formatWordCount(value: number): string {
  return `${formatCount(value)} từ`;
}

function formatWordsRemaining(value: number): string {
  return `${formatCount(value)} từ còn lại`;
}

function formatReadingTime(minutes: number): string {
  return `${formatCount(minutes)} phút đọc`;
}

function formatReadingTimeRemaining(minutes: number): string {
  return `${formatCount(minutes)} phút còn lại`;
}

function formatDictionarySize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B';
  if (bytes < 1024) return `${Math.round(bytes)} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(bytes >= 10 * 1024 * 1024 ? 0 : 1)} MB`;
}

function offlineManifestCoverageLabel(manifest: ReaderOfflineManifest): string {
  const chapterTotal = manifest.chapters.length || manifest.chapterIds.length;
  const cachedChapters = manifest.chapters.filter((chapter) => chapter.cached && !chapter.failed).length;
  const failedChapters = manifest.chapters.filter((chapter) => chapter.failed).length
    || manifest.summary.chaptersFailed;
  return `Coverage ${formatCount(cachedChapters)}/${formatCount(chapterTotal)} chương · ${formatCount(failedChapters)} lỗi`;
}

function offlineManifestResourcesLabel(manifest: ReaderOfflineManifest): string {
  return [
    `Resources ${formatCount(manifest.summary.assetsCached)}/${formatCount(manifest.summary.assetsTotal)} asset`,
    `${formatCount(manifest.summary.audioCached)}/${formatCount(manifest.summary.audioTotal)} audio`,
    `${formatCount(manifest.dictionary.sourceCount)} mục từ điển`,
  ].join(' · ');
}

type ReaderScrollProgress = {
  canScroll: boolean;
  location: number;
  percent: number;
  total: number;
};

type ReaderTextProgress = {
  absoluteCharOffset: number;
  charOffset: number;
  paragraphIndex?: number;
  percent: number;
  totalChars: number;
};

type ReaderSelectionState = {
  anchor: { left: number; top: number };
  charEnd: number;
  charStart: number;
  contextAfter: string;
  contextBefore: string;
  paragraphIndex: number;
  text: string;
};

const RAW_READER_TEXT_MODES = new Set<ReaderTextMode>(['raw', 'split', 'raw-collapsed']);
const FALLBACK_PARAGRAPHS_PER_PAGE = 4;
const LONG_CHAPTER_PARAGRAPH_THRESHOLD = 120;
const INITIAL_SCROLL_PARAGRAPH_LIMIT = 80;
const SCROLL_PARAGRAPH_CHUNK_SIZE = 80;
const LAZY_SCROLL_DISTANCE_PX = 900;
const DEFAULT_READER_SEARCH_SCOPES: NonNullable<ReaderSearchOptions['scopes']> = [
  'translation',
  'notes',
  'highlights',
];
const READER_DICTIONARY_ACCEPT = [
  '.csv',
  '.dsl',
  '.json',
  '.jsonl',
  '.tsv',
  '.u8',
  '.txt',
  '.zip',
].join(',');
const readerAnnotationExportFormats: Array<{ format: ReaderAnnotationExportFormat; label: string }> = [
  { format: 'md', label: 'Markdown' },
  { format: 'json', label: 'JSON' },
  { format: 'csv', label: 'CSV' },
];
const readerAnnotationExportScopes: Array<{ kind: ReaderAnnotationKind | null; label: string }> = [
  { kind: null, label: 'All' },
  { kind: 'bookmark', label: 'Bookmarks' },
  { kind: 'highlight', label: 'Highlights' },
  { kind: 'note', label: 'Notes' },
];
function readerProgressSnapshotToSyncProgress(snapshot: ReaderProgressSnapshot): ReaderSyncProgress {
  const progress: ReaderSyncProgress = {
    chapter_id: snapshot.chapterId,
    absolute_char_offset: snapshot.absoluteCharOffset ?? 0,
    char_offset: snapshot.charOffset ?? 0,
    mode: snapshot.mode ?? 'scroll',
    page_index: snapshot.pageIndex ?? 0,
    paragraph_index: snapshot.paragraphIndex ?? 0,
    percent: snapshot.percent,
    updated_at: snapshot.updatedAt,
  };
  if (snapshot.anchor) progress.anchor = snapshot.anchor;
  return progress;
}

function RichBlockMeasurementText({ block }: { block: ReaderRichBlock }) {
  if (!richBlockNeedsTextMirror(block)) {
    return <div className="reader-paragraph-text" dangerouslySetInnerHTML={{ __html: block.html }} />;
  }

  return (
    <div className="reader-paragraph-text">
      <div className="reader-rich-html" dangerouslySetInnerHTML={{ __html: block.html }} />
      <span aria-hidden="true" className="reader-rich-text-mirror">
        {block.text}
      </span>
    </div>
  );
}

function ReaderRawTextSurface({
  fontFamily,
  paragraphs,
  readerStyle,
  selectedChapter,
  textError,
  textState,
  theme,
  width,
  onToggleChrome,
}: {
  fontFamily: ReaderFontFamily;
  paragraphs: string[];
  readerStyle: CSSProperties;
  selectedChapter: Chapter | null;
  textError: string;
  textState: LoadState;
  theme: ReaderTheme;
  width: ReaderWidth;
  onToggleChrome(): void;
}) {
  function handleChromeToggle(): void {
    if (window.getSelection()?.toString().trim()) return;
    onToggleChrome();
  }

  return (
    <article
      aria-label="Nội dung raw tiếng Trung"
      className="reader-mode-content reader-page-content reader-raw-content"
      data-font={fontFamily}
      data-reading-mode="scroll"
      data-theme={theme}
      data-width={width}
      onClick={handleChromeToggle}
      style={readerStyle}
    >
      {selectedChapter ? (
        <header className="reader-chapter-title">
          <p className="section-label">Raw tiếng Trung · Chương {selectedChapter.chapter_number}</p>
          <h3>{selectedChapter.title}</h3>
        </header>
      ) : null}

      {textState === 'loading' ? <p>Đang tải raw/source...</p> : null}
      {textError ? (
        <p className="status-error" role="alert">
          {textError}
        </p>
      ) : null}
      {selectedChapter && textState !== 'loading' && paragraphs.length === 0 && !textError ? (
        <p>Chưa có raw/source text cho chương này.</p>
      ) : null}
      {paragraphs.map((paragraph, index) => (
        <div className="reader-paragraph-block" data-paragraph-index={index} key={`raw-${index}-${paragraph.slice(0, 24)}`}>
          <p className="reader-paragraph-text">{paragraph}</p>
        </div>
      ))}
    </article>
  );
}

function ReaderQaSummaryPanel({
  error,
  report,
  state,
}: {
  error: string;
  report: QaReport | null;
  state: LoadState;
}) {
  const glossaryViolationCount = glossaryViolationsFromQaReport(report).length;
  const chineseLeakageCount = Math.max(0, Math.round(report?.chinese_leakage_count ?? 0));
  const overallStatus = report?.overall_status || (state === 'empty' ? 'NOT_RUN' : '');
  return (
    <section aria-label="Tóm tắt QA chương" className="reader-qa-summary-panel">
      <div>
        <p className="section-label">QA overlay</p>
        <h3>{overallStatus || 'Đang tải QA'}</h3>
      </div>
      {state === 'loading' ? <span>Đang tải QA...</span> : null}
      {state === 'error' ? <span className="status-error">{error || 'Không tải được QA report.'}</span> : null}
      {state === 'empty' || !report ? (
        <span>Chưa có QA report cho chương này.</span>
      ) : null}
      {report ? (
        <div className="reader-qa-summary-grid">
          <span>Rò chữ Trung: {chineseLeakageCount.toLocaleString('vi-VN')}</span>
          <span>Vi phạm thuật ngữ: {glossaryViolationCount.toLocaleString('vi-VN')}</span>
          <span>Lặp đoạn: {report.repetition_warning ? 'Có' : 'Không'}</span>
          {typeof report.length_ratio === 'number' ? (
            <span>Length ratio: {report.length_ratio.toFixed(2)}</span>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function ReaderCollapsedRawSurface({
  fontFamily,
  rawParagraphs,
  readerStyle,
  selectedChapter,
  textError,
  textState,
  theme,
  translatedParagraphs,
  width,
  onToggleChrome,
}: {
  fontFamily: ReaderFontFamily;
  rawParagraphs: string[];
  readerStyle: CSSProperties;
  selectedChapter: Chapter | null;
  textError: string;
  textState: LoadState;
  theme: ReaderTheme;
  translatedParagraphs: string[];
  width: ReaderWidth;
  onToggleChrome(): void;
}) {
  const [expandedParagraphs, setExpandedParagraphs] = useState<Set<number>>(() => new Set());

  function handleChromeToggle(): void {
    if (window.getSelection()?.toString().trim()) return;
    onToggleChrome();
  }

  function toggleRawParagraph(index: number): void {
    setExpandedParagraphs((current) => {
      const next = new Set(current);
      if (next.has(index)) {
        next.delete(index);
      } else {
        next.add(index);
      }
      return next;
    });
  }

  return (
    <article
      aria-label="Bản dịch tiếng Việt kèm raw gọn"
      className="reader-mode-content reader-page-content reader-raw-collapsed-content"
      data-font={fontFamily}
      data-reading-mode="scroll"
      data-theme={theme}
      data-width={width}
      onClick={handleChromeToggle}
      style={readerStyle}
    >
      {selectedChapter ? (
        <header className="reader-chapter-title">
          <p className="section-label">Bản dịch tiếng Việt · Raw gọn · Chương {selectedChapter.chapter_number}</p>
          <h3>{selectedChapter.title}</h3>
        </header>
      ) : null}

      {textState === 'loading' ? <p>Đang tải bản đọc...</p> : null}
      {textError ? (
        <p className="status-error" role="alert">
          {textError}
        </p>
      ) : null}
      {selectedChapter && textState !== 'loading' && translatedParagraphs.length === 0 && !textError ? (
        <p>Chưa có bản dịch tiếng Việt.</p>
      ) : null}
      {translatedParagraphs.map((paragraph, index) => {
        const rawParagraph = rawParagraphs[index] ?? '';
        const expanded = expandedParagraphs.has(index);
        return (
          <div className="reader-paragraph-block reader-collapsed-raw-block" data-paragraph-index={index} key={`collapsed-${index}-${paragraph.slice(0, 24)}`}>
            <p className="reader-paragraph-text">{paragraph}</p>
            {rawParagraph ? (
              <button
                aria-expanded={expanded}
                className="reader-inline-raw-toggle"
                onClick={(event) => {
                  event.stopPropagation();
                  toggleRawParagraph(index);
                }}
                type="button"
              >
                {expanded ? `Ẩn raw đoạn ${index + 1}` : `Mở raw đoạn ${index + 1}`}
              </button>
            ) : null}
            {expanded && rawParagraph ? (
              <blockquote className="reader-collapsed-raw-text">
                <span>Raw Chinese</span>
                <p>{rawParagraph}</p>
              </blockquote>
            ) : null}
          </div>
        );
      })}
    </article>
  );
}

function getReaderMarksKey(bookId: number | null, chapterId: number | null): string | null {
  if (!bookId || !chapterId) return null;
  return chapterMarksKey(bookId, chapterId);
}

function measureReaderScroll(element: HTMLElement | null): ReaderScrollProgress {
  if (!element) {
    return { canScroll: false, location: 0, percent: 0, total: 0 };
  }

  const total = Math.max(0, Math.round(element.scrollHeight - element.clientHeight));
  if (total <= 0) {
    return { canScroll: false, location: 0, percent: 0, total: 0 };
  }

  const location = Math.min(total, Math.max(0, Math.round(element.scrollTop)));
  return {
    canScroll: true,
    location,
    percent: Math.min(100, Math.max(0, Math.round((location / total) * 100))),
    total,
  };
}

function totalTextLength(blocks: string[]): number {
  return blocks.reduce(
    (total, block, index) => total + block.length + (index === blocks.length - 1 ? 0 : 2),
    0,
  );
}

function readerTextProgressForLocation(
  blocks: string[],
  paragraphIndex: number | undefined,
  charOffset: number | undefined,
): ReaderTextProgress {
  const totalChars = totalTextLength(blocks);
  const absoluteCharOffset = absoluteCharOffsetForParagraph(blocks, paragraphIndex, charOffset);
  const percent = totalChars > 0
    ? Math.min(100, Math.max(0, Math.round((absoluteCharOffset / totalChars) * 100)))
    : 0;
  return {
    absoluteCharOffset,
    charOffset: Math.max(0, Math.round(charOffset ?? 0)),
    paragraphIndex,
    percent,
    totalChars,
  };
}

function readerSyncConflictLabel(conflict: ReaderSyncConflict): string {
  const identity = readerSyncConflictIdentity(conflict);
  return `${identity} · ${conflict.reason || 'unknown'} · ${conflict.resolution || 'unknown'}`;
}

function readerSyncConflictIdentity(conflict: ReaderSyncConflict): string {
  return conflict.client_id ?? (conflict.id == null ? 'unknown' : `#${conflict.id}`);
}

function readerSyncAnnotationSummary(
  annotation: ReaderSyncConflict['server_annotation'] | ReaderSyncConflict['client_annotation'],
): string {
  if (!annotation) return '';
  const text = annotation.selected_text?.trim() || annotation.note?.trim() || annotation.kind;
  if (!text) return '';
  return text.length > 80 ? `${text.slice(0, 77)}...` : text;
}

function sameReaderTextProgress(left: ReaderTextProgress | null, right: ReaderTextProgress): boolean {
  return Boolean(
    left
    && left.absoluteCharOffset === right.absoluteCharOffset
    && left.charOffset === right.charOffset
    && left.paragraphIndex === right.paragraphIndex
    && left.percent === right.percent
    && left.totalChars === right.totalChars,
  );
}

function clampPageIndex(pageIndex: number, pageCount: number): number {
  if (!Number.isFinite(pageIndex) || pageCount <= 0) return 0;
  return Math.min(pageCount - 1, Math.max(0, Math.round(pageIndex)));
}

function findParagraphElement(container: HTMLElement | null, paragraphIndex: number): HTMLElement | null {
  if (!container || !Number.isInteger(paragraphIndex) || paragraphIndex < 0) return null;
  return container.querySelector<HTMLElement>(`.reader-paragraph-block[data-paragraph-index="${paragraphIndex}"]`);
}

function getCurrentParagraphIndex(container: HTMLElement | null): number | undefined {
  if (!container) return undefined;
  const blocks = Array.from(container.querySelectorAll<HTMLElement>('.reader-paragraph-block[data-paragraph-index]'));
  if (blocks.length === 0) return undefined;

  const containerRect = container.getBoundingClientRect();
  if (
    !Number.isFinite(containerRect.top)
    || !Number.isFinite(containerRect.bottom)
    || containerRect.bottom <= containerRect.top
  ) {
    return undefined;
  }
  const anchorY = containerRect.top + 12;
  const blockRects = blocks.map((block) => ({
    block,
    rect: block.getBoundingClientRect(),
  }));
  const currentBlock = [...blockRects]
    .reverse()
    .find(({ rect }) => rect.top <= anchorY && rect.bottom >= containerRect.top)
    ?.block
    ?? blockRects.find(({ rect }) => rect.top > anchorY && rect.bottom >= containerRect.top)?.block
    ?? blockRects.find(({ rect }) => rect.bottom >= containerRect.top)?.block
    ?? blocks[blocks.length - 1];
  const paragraphIndex = Number(currentBlock.dataset.paragraphIndex);
  return Number.isInteger(paragraphIndex) && paragraphIndex >= 0 ? paragraphIndex : undefined;
}

function paragraphTextElement(container: HTMLElement | null, paragraphIndex: number | undefined): HTMLElement | null {
  if (paragraphIndex === undefined) return null;
  const block = findParagraphElement(container, paragraphIndex);
  return block?.querySelector<HTMLElement>('.reader-paragraph-text') ?? block;
}

type CaretDocument = Document & {
  caretPositionFromPoint?: (x: number, y: number) => { offsetNode: Node; offset: number } | null;
  caretRangeFromPoint?: (x: number, y: number) => Range | null;
};

function caretRangeFromPoint(documentRef: Document, x: number, y: number): Range | null {
  const caretDocument = documentRef as CaretDocument;
  const position = caretDocument.caretPositionFromPoint?.(x, y);
  if (position) {
    const range = documentRef.createRange();
    range.setStart(position.offsetNode, position.offset);
    range.collapse(true);
    return range;
  }
  return caretDocument.caretRangeFromPoint?.(x, y) ?? null;
}

function exactCharOffsetForParagraph(
  container: HTMLElement | null,
  paragraphIndex: number | undefined,
): number | null {
  const textElement = paragraphTextElement(container, paragraphIndex);
  if (!container || !textElement) return null;
  const containerRect = container.getBoundingClientRect();
  const textRect = textElement.getBoundingClientRect();
  if (!Number.isFinite(textRect.height) || textRect.height <= 0) return null;

  const x = Math.min(textRect.right - 1, Math.max(textRect.left + 1, textRect.left + 8));
  const y = Math.min(textRect.bottom - 1, Math.max(textRect.top + 1, containerRect.top + 12));
  const range = caretRangeFromPoint(textElement.ownerDocument, x, y);
  if (range && textElement.contains(range.startContainer)) {
    return textOffsetWithinNode(textElement, range.startContainer, range.startOffset);
  }
  return textOffsetFromPointInNode(textElement, x, y);
}

function charOffsetForParagraph(
  container: HTMLElement | null,
  paragraphIndex: number | undefined,
  paragraphs: string[],
): number {
  const exactOffset = exactCharOffsetForParagraph(container, paragraphIndex);
  if (exactOffset !== null) return exactOffset;
  if (!container || paragraphIndex === undefined || paragraphIndex < 0) return 0;
  const paragraph = paragraphs[paragraphIndex] ?? '';
  if (!paragraph) return 0;
  const block = findParagraphElement(container, paragraphIndex);
  if (!block) return 0;
  const blockRect = block.getBoundingClientRect();
  const containerRect = container.getBoundingClientRect();
  const blockHeight = blockRect.height;
  if (!Number.isFinite(blockHeight) || blockHeight <= 0) return 0;
  const ratio = Math.min(1, Math.max(0, (containerRect.top - blockRect.top) / blockHeight));
  return Math.min(paragraph.length, Math.max(0, Math.round(paragraph.length * ratio)));
}

function exactScrollTopForParagraphLocation(
  container: HTMLElement | null,
  paragraphIndex: number | undefined,
  charOffset: number | undefined,
): number | null {
  const textElement = paragraphTextElement(container, paragraphIndex);
  if (!container || !textElement || !Number.isFinite(charOffset ?? 0)) return null;
  const target = textNodeAtOffset(textElement, Math.max(0, charOffset ?? 0));
  if (!target) return null;
  const rect = collapsedRangeRectAtTextOffset(textElement, charOffset ?? 0);
  if (!rect) return null;
  if (!Number.isFinite(rect.top) || !Number.isFinite(rect.height)) return null;
  const containerRect = container.getBoundingClientRect();
  return Math.max(0, Math.round(container.scrollTop + rect.top - containerRect.top - 8));
}

function blockScrollTop(container: HTMLElement, block: HTMLElement): number | null {
  if (Number.isFinite(block.offsetTop) && block.offsetTop > 0) {
    return Math.max(0, Math.round(block.offsetTop));
  }
  const containerRect = container.getBoundingClientRect();
  const blockRect = block.getBoundingClientRect();
  if (
    !Number.isFinite(containerRect.top)
    || !Number.isFinite(blockRect.top)
    || blockRect.top === 0
  ) {
    return null;
  }
  return Math.max(0, Math.round(container.scrollTop + blockRect.top - containerRect.top));
}

function scrollTopForParagraphLocation(
  container: HTMLElement | null,
  paragraphIndex: number | undefined,
  charOffset: number | undefined,
  paragraphs: string[],
): number | null {
  const exactScrollTop = exactScrollTopForParagraphLocation(container, paragraphIndex, charOffset);
  if (exactScrollTop !== null) return exactScrollTop;
  if (!container || paragraphIndex === undefined || paragraphIndex < 0) return null;
  const block = findParagraphElement(container, paragraphIndex);
  const paragraph = paragraphs[paragraphIndex] ?? '';
  if (!block || !paragraph || !Number.isFinite(charOffset ?? 0)) return null;
  if ((charOffset ?? 0) <= 0) return blockScrollTop(container, block);
  const height = block.offsetHeight || block.getBoundingClientRect().height;
  if (!Number.isFinite(height) || height <= 0) return null;
  const ratio = Math.min(1, Math.max(0, (charOffset ?? 0) / Math.max(1, paragraph.length)));
  const baseScrollTop = blockScrollTop(container, block);
  if (baseScrollTop === null) return null;
  return Math.max(0, Math.round(baseScrollTop + height * ratio));
}

function readableViewportHeight(container: HTMLElement): number {
  const styles = window.getComputedStyle(container);
  const paddingTop = Number.parseFloat(styles.paddingTop) || 0;
  const paddingBottom = Number.parseFloat(styles.paddingBottom) || 0;
  return Math.max(160, Math.round(container.clientHeight - paddingTop - paddingBottom));
}

function measuredViewportPages(
  container: HTMLElement | null,
  measureSurface: HTMLElement | null,
  paragraphCount: number,
): ReaderViewportPage[] {
  if (!container || !measureSurface || paragraphCount <= 0) return [];
  const containerHeight = readableViewportHeight(container);
  if (!Number.isFinite(containerHeight) || containerHeight <= 0) return [];
  const surfaceRect = measureSurface.getBoundingClientRect();
  const measurements = Array.from(
    measureSurface.querySelectorAll<HTMLElement>('.reader-paragraph-block[data-paragraph-index]'),
  ).map((block) => {
    const index = Number(block.dataset.paragraphIndex);
    const rect = block.getBoundingClientRect();
    const height = rect.bottom - rect.top;
    const textElement = block.querySelector('.reader-paragraph-text') ?? block;
    const richKind = block.dataset.richKind;
    const pageBreakAfter = block.dataset.pageBreakAfter === 'true';
    const pageBreakBefore = block.dataset.pageBreakBefore === 'true';
    const pageBreakInsideAvoid = block.dataset.pageBreakInsideAvoid === 'true';
    const isUnsplittableMediaBlock = richKind === 'image'
        || richKind === 'structure'
        || Boolean(block.querySelector('figure,img,table,pre,svg,video,audio,canvas,math'));
    const isMediaBlock = isUnsplittableMediaBlock || Boolean(block.querySelector('ol,ul'));
    const preferStandalone = pageBreakInsideAvoid || (isMediaBlock && height >= containerHeight * 0.35);
    return {
      bottom: rect.bottom - surfaceRect.top,
      canSplit: !isUnsplittableMediaBlock,
      charLength: textLength(textElement),
      index,
      pageBreakAfter,
      pageBreakBefore,
      pageBreakOffsets: !preferStandalone && height > containerHeight
        ? pageBreakOffsetsForViewportSlices(textElement, containerHeight)
        : undefined,
      preferStandalone,
      top: rect.top - surfaceRect.top,
    };
  });
  return paginateParagraphsByViewport(measurements, containerHeight);
}

function sameViewportPages(left: ReaderViewportPage[], right: ReaderViewportPage[]): boolean {
  return left.length === right.length
    && left.every((page, index) => (
      page.startIndex === right[index]?.startIndex
      && page.endIndex === right[index]?.endIndex
      && page.startChar === right[index]?.startChar
      && page.endChar === right[index]?.endChar
    ));
}

function pageCharRangeForBlock(
  page: ReaderViewportPage,
  blockIndex: number,
  textLengthValue: number,
): { charEnd: number; charStart: number } | null {
  if (
    page.startIndex !== blockIndex
    || page.endIndex !== blockIndex + 1
    || !Number.isInteger(page.startChar)
    || !Number.isInteger(page.endChar)
  ) {
    return null;
  }
  const textLengthSafe = Math.max(0, textLengthValue);
  const charStart = Math.min(textLengthSafe, Math.max(0, page.startChar ?? 0));
  const charEnd = Math.min(textLengthSafe, Math.max(charStart, page.endChar ?? textLengthSafe));
  return { charEnd, charStart };
}

function readerTextLocationWithinPage(
  location: { charOffset: number; paragraphIndex: number } | null,
  page: ReaderViewportPage,
): boolean {
  if (!location) return false;
  if (location.paragraphIndex < page.startIndex || location.paragraphIndex >= page.endIndex) return false;
  const pageIsSplitBlock = page.startIndex === location.paragraphIndex
    && page.endIndex === location.paragraphIndex + 1
    && Number.isInteger(page.startChar)
    && Number.isInteger(page.endChar);
  if (!pageIsSplitBlock) return true;
  const startChar = Math.max(0, page.startChar ?? 0);
  const endChar = Math.max(startChar, page.endChar ?? startChar);
  return location.charOffset >= startChar && location.charOffset <= endChar;
}

function elementFromSelectionNode(node: Node | null): Element | null {
  if (!node) return null;
  return node.nodeType === Node.ELEMENT_NODE ? node as Element : node.parentElement;
}

function paragraphIndexFromSelectionNode(node: Node | null): number | null {
  const element = elementFromSelectionNode(node);
  const block = element?.closest<HTMLElement>('.reader-paragraph-block[data-paragraph-index]');
  const rawIndex = block?.dataset.paragraphIndex;
  if (rawIndex == null) return null;
  const index = Number(rawIndex);
  return Number.isInteger(index) && index >= 0 ? index : null;
}

function selectionParagraphBlock(container: HTMLElement | null, node: Node | null): HTMLElement | null {
  if (!container) return null;
  const element = elementFromSelectionNode(node);
  const block = element?.closest<HTMLElement>('.reader-paragraph-block[data-paragraph-index]');
  return block && container.contains(block) ? block : null;
}

function paragraphTextElementFromBlock(block: HTMLElement | null): HTMLElement | null {
  if (!block) return null;
  return block.querySelector<HTMLElement>('.reader-paragraph-text') ?? block;
}

function charStartOffsetFromBlock(block: HTMLElement | null): number {
  const value = Number(block?.dataset.charStart);
  return Number.isInteger(value) && value >= 0 ? value : 0;
}

function selectionAnchorFromRect(rect: DOMRect): { left: number; top: number } {
  const fallbackLeft = Math.round(window.innerWidth / 2);
  const fallbackTop = 120;
  const rectLeft = Number.isFinite(rect.left) ? rect.left : fallbackLeft;
  const rectTop = Number.isFinite(rect.top) ? rect.top : fallbackTop;
  const rectWidth = Number.isFinite(rect.width) ? rect.width : 0;
  const maxLeft = Math.max(16, window.innerWidth - 16);
  const maxTop = Math.max(16, window.innerHeight - 92);
  return {
    left: Math.round(Math.min(maxLeft, Math.max(16, rectLeft + rectWidth / 2))),
    top: Math.round(Math.min(maxTop, Math.max(16, rectTop - 72))),
  };
}

function triggerBrowserDownload(blob: Blob, filename: string): void {
  if (typeof URL.createObjectURL !== 'function') return;
  const href = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = href;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(href), 0);
}

function scheduleReaderRestore(callback: () => void): () => void {
  if (typeof window.requestAnimationFrame === 'function') {
    const frame = window.requestAnimationFrame(callback);
    return () => window.cancelAnimationFrame(frame);
  }
  const timeout = window.setTimeout(callback, 0);
  return () => window.clearTimeout(timeout);
}

function scrollReaderParagraphIntoView(container: HTMLElement | null, paragraphIndex: number | undefined): boolean {
  if (!container || paragraphIndex === undefined) return false;
  const block = findParagraphElement(container, paragraphIndex);
  if (!block) return false;
  if (typeof block.scrollIntoView === 'function') {
    block.scrollIntoView({ block: 'start' });
    return true;
  }
  const containerRect = container.getBoundingClientRect();
  const blockRect = block.getBoundingClientRect();
  const nextTop = Number.isFinite(block.offsetTop) && block.offsetTop > 0
    ? block.offsetTop
    : Math.round(container.scrollTop + blockRect.top - containerRect.top);
  container.scrollTop = Math.max(0, nextTop);
  return true;
}

type ReaderIdleWindow = Window & {
  cancelIdleCallback?: (handle: number) => void;
  requestIdleCallback?: (callback: () => void, options?: { timeout?: number }) => number;
};

function scheduleReaderIdle(callback: () => void): () => void {
  const idleWindow = window as ReaderIdleWindow;
  if (typeof idleWindow.requestIdleCallback === 'function') {
    const handle = idleWindow.requestIdleCallback(callback, { timeout: 400 });
    return () => idleWindow.cancelIdleCallback?.(handle);
  }
  const timeout = window.setTimeout(callback, 48);
  return () => window.clearTimeout(timeout);
}

function parseReaderMarksKey(key: string): { bookId: number; chapterId: number } | null {
  const [bookIdRaw, chapterIdRaw] = key.split(':');
  const bookId = Number(bookIdRaw);
  const chapterId = Number(chapterIdRaw);
  if (!Number.isInteger(bookId) || !Number.isInteger(chapterId)) return null;
  return { bookId, chapterId };
}

function readerAiCacheKey(input: {
  bookId: number;
  chapterId: number;
  mode: ReaderAiPanelMode;
  spoilerMode: ReaderExplainSpoilerMode;
  text: string;
}): string {
  return [
    input.bookId,
    input.chapterId,
    input.mode,
    input.spoilerMode,
    input.text.replace(/\s+/g, ' ').trim().toLowerCase(),
  ].join('|');
}

function markChapterLabel(chapters: Chapter[], chapterId: number): { chapterNumber: number; chapterTitle: string } {
  const chapter = chapters.find((item) => item.id === chapterId);
  return {
    chapterNumber: chapter?.chapter_number ?? 0,
    chapterTitle: chapter?.title ?? 'Chương chưa rõ',
  };
}

function buildReaderMarkPanelItems(
  marksStore: ReaderMarksStore,
  chapters: Chapter[],
  activeBookId: number | null,
): ReaderMarkPanelItem[] {
  const items: ReaderMarkPanelItem[] = [];
  for (const [key, marks] of Object.entries(marksStore)) {
    const ids = parseReaderMarksKey(key);
    if (!ids || (activeBookId !== null && ids.bookId !== activeBookId)) continue;
    const chapterLabel = markChapterLabel(chapters, ids.chapterId);

    if (marks.bookmarked) {
      items.push({
        annotationId: marks.bookmarkAnnotationId,
        bookId: ids.bookId,
        chapterId: ids.chapterId,
        chapterNumber: chapterLabel.chapterNumber,
        chapterTitle: chapterLabel.chapterTitle,
        clientId: marks.bookmarkAnnotationId ? undefined : `bookmark-${ids.bookId}-${ids.chapterId}`,
        id: `bookmark-${ids.bookId}-${ids.chapterId}`,
        kind: 'bookmark',
        paragraphIndex: 0,
        text: 'Đánh dấu chương',
      });
    }

    for (const highlight of marks.highlights) {
      items.push({
        annotationId: highlight.annotationId,
        bookId: highlight.bookId ?? ids.bookId,
        chapterId: highlight.chapterId ?? ids.chapterId,
        chapterNumber: highlight.chapterNumber ?? chapterLabel.chapterNumber,
        chapterTitle: highlight.chapterTitle ?? chapterLabel.chapterTitle,
        charEnd: highlight.charEnd,
        charStart: highlight.charStart,
        clientId: highlight.clientId ?? (highlight.annotationId ? undefined : highlight.id),
        color: highlight.color,
        id: `highlight-${highlight.annotationId ?? highlight.id}`,
        kind: 'highlight',
        paragraphIndex: highlight.paragraphIndex,
        text: highlight.text,
      });
    }

    for (const note of marks.notes) {
      items.push({
        annotationId: note.annotationId,
        bookId: note.bookId ?? ids.bookId,
        chapterId: note.chapterId ?? ids.chapterId,
        chapterNumber: note.chapterNumber ?? chapterLabel.chapterNumber,
        chapterTitle: note.chapterTitle ?? chapterLabel.chapterTitle,
        charEnd: note.charEnd,
        charStart: note.charStart,
        clientId: note.clientId ?? (note.annotationId ? undefined : note.id),
        color: note.color,
        id: `note-${note.annotationId ?? note.id}`,
        kind: 'note',
        note: note.note,
        paragraphIndex: note.paragraphIndex,
        text: note.text,
      });
    }
  }

  return items.sort((left, right) => {
    if (left.chapterNumber !== right.chapterNumber) return left.chapterNumber - right.chapterNumber;
    if (left.paragraphIndex !== right.paragraphIndex) return left.paragraphIndex - right.paragraphIndex;
    return left.id.localeCompare(right.id);
  });
}

function readerHighlightRangeId(paragraphIndex: number, charStart: number, charEnd: number): string {
  return `highlight-${paragraphIndex}-${charStart}-${charEnd}`;
}

function upsertDeletedReaderAnnotation(
  deletedAnnotations: ReaderDeletedAnnotation[],
  deleted: ReaderDeletedAnnotation,
): ReaderDeletedAnnotation[] {
  return [
    ...deletedAnnotations.filter((item) => {
      if (deleted.annotationId && item.annotationId === deleted.annotationId) return false;
      if (deleted.clientId && item.clientId === deleted.clientId) return false;
      return true;
    }),
    deleted,
  ];
}

function readerHighlightRangeEnd(highlight: ReaderHighlight): number {
  return Number.isInteger(highlight.charEnd) ? highlight.charEnd ?? 0 : highlight.text.length;
}

function sameReaderHighlightRange(
  highlight: ReaderHighlight,
  paragraphIndex: number,
  charStart: number,
  charEnd: number,
): boolean {
  return highlight.paragraphIndex === paragraphIndex
    && (highlight.charStart ?? 0) === charStart
    && readerHighlightRangeEnd(highlight) === charEnd;
}

function readerExportSlug(value: string): string {
  const slug = value
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/đ/g, 'd')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return slug || 'reader';
}

function readerMarkExportRows(
  items: ReaderMarkPanelItem[],
  kind: ReaderAnnotationKind | null,
): Array<Record<string, string | number | undefined>> {
  return items
    .filter((item) => !kind || item.kind === kind)
    .map((item) => ({
      annotation_id: item.annotationId,
      book_id: item.bookId,
      char_end: item.charEnd,
      char_start: item.charStart,
      chapter_id: item.chapterId,
      chapter_number: item.chapterNumber,
      chapter_title: item.chapterTitle,
      client_id: item.clientId ?? (item.annotationId ? undefined : item.id),
      color: item.color,
      kind: item.kind,
      note: item.note,
      paragraph_index: item.paragraphIndex,
      selected_text: item.text,
      text: item.text,
    }));
}

function emptyReaderMarkKindCounts(): Record<ReaderAnnotationKind, number> {
  return {
    bookmark: 0,
    highlight: 0,
    note: 0,
  };
}

function readerMarkKindCounts(rows: Array<Record<string, string | number | undefined>>): Record<ReaderAnnotationKind, number> {
  const counts = emptyReaderMarkKindCounts();
  for (const row of rows) {
    if (row.kind === 'bookmark' || row.kind === 'highlight' || row.kind === 'note') {
      counts[row.kind] += 1;
    }
  }
  return counts;
}

function readerMarkExportScope(kind: ReaderAnnotationKind | null): { kinds: ReaderAnnotationKind[]; label: string } {
  if (!kind) return { kinds: [], label: 'annotations' };
  if (kind === 'bookmark') return { kinds: [kind], label: 'bookmarks' };
  if (kind === 'highlight') return { kinds: [kind], label: 'highlights' };
  return { kinds: [kind], label: 'notes' };
}

function localReaderMarkChapterGroups(rows: Array<Record<string, string | number | undefined>>) {
  const groups = new Map<string, {
    annotation_count: number;
    annotation_ids: number[];
    chapter_id: number;
    chapter_number: number;
    chapter_title: string;
    client_ids: string[];
    kind_counts: Record<ReaderAnnotationKind, number>;
  }>();

  for (const row of rows) {
    const chapterId = Number(row.chapter_id ?? 0);
    const chapterNumber = Number(row.chapter_number ?? 0);
    const chapterTitle = String(row.chapter_title ?? '');
    const key = `${chapterNumber}:${chapterId}:${chapterTitle}`;
    const group = groups.get(key) ?? {
      annotation_count: 0,
      annotation_ids: [],
      chapter_id: chapterId,
      chapter_number: chapterNumber,
      chapter_title: chapterTitle,
      client_ids: [],
      kind_counts: emptyReaderMarkKindCounts(),
    };
    group.annotation_count += 1;
    if (row.kind === 'bookmark' || row.kind === 'highlight' || row.kind === 'note') {
      group.kind_counts[row.kind] += 1;
    }
    if (typeof row.annotation_id === 'number') group.annotation_ids.push(row.annotation_id);
    if (typeof row.client_id === 'string' && row.client_id.trim()) group.client_ids.push(row.client_id);
    groups.set(key, group);
  }

  return [...groups.values()].sort((left, right) => {
    if (left.chapter_number !== right.chapter_number) return left.chapter_number - right.chapter_number;
    return left.chapter_id - right.chapter_id;
  });
}

function localReaderMarksJson(
  rows: Array<Record<string, string | number | undefined>>,
  bookTitle: string,
  kind: ReaderAnnotationKind | null,
): string {
  const chapters = localReaderMarkChapterGroups(rows);
  const firstRow = rows[0];
  return JSON.stringify({
    format: 'novel_tnn_reader_annotations',
    version: 2,
    exported_at: new Date().toISOString(),
    scope: readerMarkExportScope(kind),
    book: {
      id: Number(firstRow?.book_id ?? 0),
      title: bookTitle,
      author: '',
    },
    annotation_count: rows.length,
    kind_counts: readerMarkKindCounts(rows),
    chapter_count: chapters.length,
    chapters,
    annotations: rows,
  }, null, 2);
}

function csvCell(value: string | number | undefined): string {
  const text = value === undefined ? '' : String(value);
  return `"${text.replace(/"/g, '""')}"`;
}

function localReaderMarksMarkdown(rows: Array<Record<string, string | number | undefined>>): string {
  if (rows.length === 0) return '# Reader Marks\n\n_Chưa có dấu đọc._\n';
  return [
    '# Reader Marks',
    '',
    ...rows.map((row) => [
      `## Ch. ${row.chapter_number ?? ''} · ${row.chapter_title ?? ''}`,
      '',
      `- Loại: ${row.kind}`,
      `- Đoạn: ${Number(row.paragraph_index ?? 0) + 1}`,
      row.client_id ? `- Client ID: ${row.client_id}` : '',
      row.annotation_id ? `- Annotation ID: ${row.annotation_id}` : '',
      row.char_start !== undefined || row.char_end !== undefined
        ? `- Range: ${row.char_start ?? ''}-${row.char_end ?? ''}`
        : '',
      row.text ? `- Nội dung: ${row.text}` : '',
      row.note ? `- Ghi chú: ${row.note}` : '',
    ].filter(Boolean).join('\n')),
    '',
  ].join('\n');
}

function localReaderMarksCsv(rows: Array<Record<string, string | number | undefined>>): string {
  const headers = [
    'kind',
    'chapter_number',
    'chapter_title',
    'paragraph_index',
    'char_start',
    'char_end',
    'selected_text',
    'text',
    'note',
    'color',
    'annotation_id',
    'client_id',
    'book_id',
    'chapter_id',
  ];
  return [
    headers.join(','),
    ...rows.map((row) => headers.map((header) => csvCell(row[header])).join(',')),
  ].join('\n');
}

function localReaderMarksDownload(
  items: ReaderMarkPanelItem[],
  format: ReaderAnnotationExportFormat,
  bookTitle: string,
  kind: ReaderAnnotationKind | null,
): { blob: Blob; filename: string } {
  const rows = readerMarkExportRows(items, kind);
  const slug = readerExportSlug(bookTitle);
  const filename = `${slug}.reader-marks.${format}`;
  if (format === 'json') {
    return {
      blob: new Blob([localReaderMarksJson(rows, bookTitle, kind)], { type: 'application/json' }),
      filename,
    };
  }
  if (format === 'csv') {
    return {
      blob: new Blob([localReaderMarksCsv(rows)], { type: 'text/csv;charset=utf-8' }),
      filename,
    };
  }
  return {
    blob: new Blob([localReaderMarksMarkdown(rows)], { type: 'text/markdown;charset=utf-8' }),
    filename,
  };
}

function importNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? Math.max(0, Math.round(value)) : undefined;
}

function isReaderAnnotationKind(value: unknown): value is ReaderAnnotationKind {
  return value === 'bookmark' || value === 'highlight' || value === 'note';
}

function readerAnnotationImportItemsFromPayload(payload: unknown): ReaderAnnotationImportItem[] {
  const source = Array.isArray(payload)
    ? payload
    : payload && typeof payload === 'object' && Array.isArray((payload as { annotations?: unknown }).annotations)
      ? (payload as { annotations: unknown[] }).annotations
      : [];

  return source.flatMap((entry) => {
    if (!entry || typeof entry !== 'object') return [];
    const raw = entry as Record<string, unknown>;
    if (!isReaderAnnotationKind(raw.kind)) return [];
    const item: ReaderAnnotationImportItem = { kind: raw.kind };
    const chapterId = importNumber(raw.chapter_id);
    const chapterNumber = importNumber(raw.chapter_number);
    const paragraphIndex = importNumber(raw.paragraph_index);
    const charStart = importNumber(raw.char_start);
    const charEnd = importNumber(raw.char_end);
    if (chapterId !== undefined) item.chapter_id = chapterId;
    if (chapterNumber !== undefined) item.chapter_number = chapterNumber;
    if (paragraphIndex !== undefined) item.paragraph_index = paragraphIndex;
    if (charStart !== undefined) item.char_start = charStart;
    if (charEnd !== undefined) item.char_end = charEnd;
    if (typeof raw.client_id === 'string') item.client_id = raw.client_id;
    if (typeof raw.selected_text === 'string') item.selected_text = raw.selected_text;
    if (typeof raw.text === 'string' && item.selected_text === undefined) item.selected_text = raw.text;
    if (typeof raw.note === 'string') item.note = raw.note;
    if (typeof raw.color === 'string') item.color = raw.color;
    return [item];
  });
}

export default function ReaderView({
  apiClient,
  books,
  chapters,
  activeBookId,
  selectedChapter,
  selectedChapterId,
  contentHtml,
  textError,
  textState,
  translationText,
  onBackToLibrary,
  onOpenWorkbench,
  onSelectBook,
  onSelectChapter,
}: ReaderViewProps) {
  const readerMainRef = useRef<HTMLElement | null>(null);
  const paginationMeasureRef = useRef<HTMLDivElement | null>(null);
  const restorePendingRef = useRef(false);
  const skipInitialProgressSaveRef = useRef('');
  const readerAiCacheRef = useRef(new Map<string, ReaderExplainResponse>());
  const readerDeviceId = useMemo(() => loadReaderDeviceId(), []);
  const [readerSettings, setReaderSettings] = useState<ReaderSettings>(() => loadReaderSettings());
  const [readerTextMode, setReaderTextModeState] = useState<ReaderTextMode>(() => loadReaderTextMode());
  const [scrollProgress, setScrollProgress] = useState<ReaderScrollProgress>({
    canScroll: false,
    location: 0,
    percent: 0,
    total: 0,
  });
  const [scrollTextProgress, setScrollTextProgress] = useState<ReaderTextProgress | null>(null);
  const [chromeVisible, setChromeVisible] = useState(true);
  const [tocOpen, setTocOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [readerSearchOpen, setReaderSearchOpen] = useState(false);
  const [readerSearchQuery, setReaderSearchQuery] = useState('');
  const [readerSearchOptions, setReaderSearchOptions] = useState<ReaderSearchOptions>({
    scopes: ['translation', 'notes', 'highlights'],
  });
  const [bookSearchResults, setBookSearchResults] = useState<ReaderSearchResult[]>([]);
  const [bookSearchLoading, setBookSearchLoading] = useState(false);
  const [bookSearchError, setBookSearchError] = useState('');
  const [moreOpen, setMoreOpen] = useState(false);
  const [marksPanelOpen, setMarksPanelOpen] = useState(false);
  const [marksError, setMarksError] = useState('');
  const [readerSyncStatus, setReaderSyncStatus] = useState('');
  const [readerAnnotationConflicts, setReaderAnnotationConflicts] = useState<ReaderSyncConflict[]>([]);
  const [readerProgressConflict, setReaderProgressConflict] = useState<{
    local: ReaderProgressSnapshot;
    remote: ReaderProgressSnapshot;
  } | null>(null);
  const [marksStore, setMarksStore] = useState<ReaderMarksStore>(() => loadReaderMarks());
  const [currentPage, setCurrentPage] = useState(0);
  const [autoScrollEnabled, setAutoScrollEnabled] = useState(false);
  const [renderedParagraphLimit, setRenderedParagraphLimit] = useState(INITIAL_SCROLL_PARAGRAPH_LIMIT);
  const [readerCacheVersion, setReaderCacheVersion] = useState(0);
  const [cacheStatus, setCacheStatus] = useState<ReaderCacheStatus | null>(null);
  const [offlineManifest, setOfflineManifest] = useState<ReaderOfflineManifest | null>(null);
  const [viewportPages, setViewportPages] = useState<ReaderViewportPage[]>([]);
  const [pendingParagraphJump, setPendingParagraphJump] = useState<{
    charOffset?: number;
    chapterId: number;
    paragraphIndex: number;
  } | null>(null);
  const [noteDraft, setNoteDraft] = useState<{
    charEnd: number;
    charStart: number;
    paragraphIndex: number;
    text: string;
    value: string;
  } | null>(null);
  const [readerSelection, setReaderSelection] = useState<ReaderSelectionState | null>(null);
  const [dictionaryOpen, setDictionaryOpen] = useState(false);
  const [dictionarySelection, setDictionarySelection] = useState<ReaderSelectionState | null>(null);
  const [dictionaryQuery, setDictionaryQuery] = useState('');
  const [dictionaryIncludeOnline, setDictionaryIncludeOnline] = useState(false);
  const [dictionaryResult, setDictionaryResult] = useState<ReaderDictionaryResponse | null>(null);
  const [dictionaryLoading, setDictionaryLoading] = useState(false);
  const [dictionaryError, setDictionaryError] = useState('');
  const [readerDictionaries, setReaderDictionaries] = useState<ReaderDictionaryFile[]>([]);
  const [dictionaryListLoading, setDictionaryListLoading] = useState(false);
  const [dictionaryListVersion, setDictionaryListVersion] = useState(0);
  const [dictionaryDeletingFilename, setDictionaryDeletingFilename] = useState('');
  const [dictionaryUploadLoading, setDictionaryUploadLoading] = useState(false);
  const [dictionaryUploadStatus, setDictionaryUploadStatus] = useState('');
  const [readerCoverUrl, setReaderCoverUrl] = useState('');
  const [offlineCacheLoading, setOfflineCacheLoading] = useState(false);
  const [offlineCacheStatus, setOfflineCacheStatus] = useState('');
  const [annotationExportStatus, setAnnotationExportStatus] = useState('');
  const [annotationImportLoading, setAnnotationImportLoading] = useState(false);
  const [annotationExportKind, setAnnotationExportKind] = useState<ReaderAnnotationKind | null>(null);
  const [readerAiOpen, setReaderAiOpen] = useState(false);
  const [readerAiMode, setReaderAiMode] = useState<ReaderAiPanelMode>('explain');
  const [readerAiSelection, setReaderAiSelection] = useState<ReaderSelectionState | null>(null);
  const [readerAiSpoilerMode, setReaderAiSpoilerMode] = useState<ReaderExplainSpoilerMode>('no_spoiler');
  const [readerAiResult, setReaderAiResult] = useState<ReaderExplainResponse | null>(null);
  const [readerAiLoading, setReaderAiLoading] = useState(false);
  const [readerAiError, setReaderAiError] = useState('');
  const [readerAiCached, setReaderAiCached] = useState(false);
  const [xrayOpen, setXrayOpen] = useState(false);
  const [xraySpoilerMode, setXraySpoilerMode] = useState<ReaderXraySpoilerMode>('no_spoiler');
  const [xrayData, setXrayData] = useState<ReaderXrayResponse | null>(null);
  const [xrayLoading, setXrayLoading] = useState(false);
  const [xrayEnriching, setXrayEnriching] = useState(false);
  const [xrayEnrichingScope, setXrayEnrichingScope] = useState<'chapter' | 'book' | null>(null);
  const [xrayError, setXrayError] = useState('');
  const [readerQaReport, setReaderQaReport] = useState<QaReport | null>(null);
  const [readerQaState, setReaderQaState] = useState<LoadState>('idle');
  const [readerQaError, setReaderQaError] = useState('');
  const selectAudioChapter = useCallback((chapterId: number) => {
    onSelectChapter(chapterId);
    setTocOpen(false);
    setReaderSearchOpen(false);
    setMoreOpen(false);
    setMarksPanelOpen(false);
    setReaderSelection(null);
    setDictionaryOpen(false);
    setXrayOpen(false);
  }, [onSelectChapter]);
  const readerAudio = useReaderAudio({
    activeBookId,
    apiClient,
    cacheAudio: cacheReaderAudio,
    chapters,
    getCachedAudioUrl: getCachedReaderAudioUrl,
    onDownload: triggerBrowserDownload,
    onError: setMarksError,
    onSelectChapter: selectAudioChapter,
    qaReport: readerQaReport,
    selectedChapter,
    selectedChapterId,
    translationText,
  });
  const exitReader = useCallback(() => {
    const state = window.history.state as Record<string, unknown> | null;
    if (state?.novelTnnReader === true) {
      window.history.back();
      return;
    }
    onBackToLibrary();
  }, [onBackToLibrary]);

  useEffect(() => {
    const currentState = (window.history.state ?? {}) as Record<string, unknown>;
    if (currentState.novelTnnReader !== true) {
      window.history.pushState({ ...currentState, novelTnnReader: true }, '');
    }

    const handlePopState = () => onBackToLibrary();
    window.addEventListener('popstate', handlePopState);
    return () => {
      window.removeEventListener('popstate', handlePopState);
      const state = (window.history.state ?? {}) as Record<string, unknown>;
      if (state.novelTnnReader === true) {
        window.history.replaceState({ ...state, novelTnnReader: false }, '');
      }
    };
  }, [onBackToLibrary]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      if (tocOpen) {
        setTocOpen(false);
        return;
      }
      if (settingsOpen) {
        setSettingsOpen(false);
        return;
      }
      exitReader();
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [exitReader, settingsOpen, tocOpen]);

  const setReaderTextMode = useCallback((mode: ReaderTextMode) => {
    setReaderTextModeState(mode);
    saveReaderTextMode(mode);
  }, []);
  const translatedChapters = useMemo(
    () => sortChapters(chapters.filter((chapter) => chapter.has_translation)),
    [chapters],
  );
  const chapterIndexes = useMemo(
    () => new Map(translatedChapters.map((chapter, index) => [chapter.id, index])),
    [translatedChapters],
  );
  const selectedBook = books.find((book) => book.id === activeBookId);
  const selectedIndex = translatedChapters.findIndex((chapter) => chapter.id === selectedChapterId);
  const currentPosition = selectedIndex >= 0 ? selectedIndex + 1 : 0;
  const previousChapter = selectedIndex > 0 ? translatedChapters[selectedIndex - 1] : null;
  const nextChapter = selectedIndex >= 0 && selectedIndex < translatedChapters.length - 1
    ? translatedChapters[selectedIndex + 1]
    : null;
  const currentChapterInOfflineManifest = Boolean(
    selectedChapterId && offlineManifest?.chapterIds.includes(selectedChapterId),
  );
  const currentChapterAvailableOffline = Boolean(cacheStatus?.currentCached || currentChapterInOfflineManifest);
  const paragraphs = useMemo(() => splitParagraphs(translationText), [translationText]);
  const rawText = useMemo(() => htmlTextContent(contentHtml), [contentHtml]);
  const richBlocks = useMemo(() => extractReaderRichBlocks(contentHtml), [contentHtml]);
  const rawParagraphs = useMemo(() => {
    const blockTexts = richBlocks.map((block) => block.text.trim()).filter(Boolean);
    return blockTexts.length > 0 ? blockTexts : splitParagraphs(rawText);
  }, [rawText, richBlocks]);
  const rawContentAvailable = rawParagraphs.length > 0;
  const richContentAvailable = contentHtml.trim().length > 0;
  const contentHtmlLooksRawSource = translationText.trim().length > 0 && containsHanText(rawText);
  const hasRichContent = richContentAvailable && !contentHtmlLooksRawSource;
  const progressTextBlocks = useMemo(
    () => (hasRichContent ? richBlocks.map((block) => block.text) : paragraphs),
    [hasRichContent, paragraphs, richBlocks],
  );
  const paginatedBlockCount = hasRichContent ? richBlocks.length : paragraphs.length;
  const isPaginatedMode = readerTextMode === 'translation'
    && readerSettings.readingMode === 'paginated'
    && paginatedBlockCount > 0;
  const canMeasureViewportPages = typeof window.ResizeObserver === 'function';
  const fallbackPageHints = useMemo<ReaderFallbackPageHint[]>(
    () => (hasRichContent
      ? richBlocks.map((block) => ({
        pageBreakAfter: block.pageBreakAfter,
        pageBreakBefore: block.pageBreakBefore,
        preferStandalone: block.pageBreakInsideAvoid || block.kind === 'image' || block.kind === 'structure',
      }))
      : []),
    [hasRichContent, richBlocks],
  );
  const fallbackPages = useMemo(
    () => fallbackParagraphPages(paginatedBlockCount, FALLBACK_PARAGRAPHS_PER_PAGE, fallbackPageHints),
    [fallbackPageHints, paginatedBlockCount],
  );
  const activeViewportPages = isPaginatedMode && viewportPages.length > 0 ? viewportPages : fallbackPages;
  const pageCount = Math.max(1, activeViewportPages.length);
  const lazyScrollEnabled = readerTextMode === 'translation'
    && !isPaginatedMode
    && !hasRichContent
    && paragraphs.length > LONG_CHAPTER_PARAGRAPH_THRESHOLD;
  const visibleScrollParagraphLimit = lazyScrollEnabled
    ? Math.min(paragraphs.length, renderedParagraphLimit)
    : paragraphs.length;
  const hasMoreScrollParagraphs = lazyScrollEnabled && visibleScrollParagraphLimit < paragraphs.length;
  const currentViewportPage = activeViewportPages[clampPageIndex(currentPage, pageCount)] ?? { startIndex: 0, endIndex: 0 };
  const currentPageStart = isPaginatedMode ? currentViewportPage.startIndex : 0;
  const currentPageEnd = isPaginatedMode ? currentViewportPage.endIndex : visibleScrollParagraphLimit;
  const visibleParagraphs = paragraphs
    .map((paragraph, index) => {
      const range = isPaginatedMode ? pageCharRangeForBlock(currentViewportPage, index, paragraph.length) : null;
      return {
        charEnd: range?.charEnd,
        charStart: range?.charStart,
        index,
        paragraph: range ? paragraph.slice(range.charStart, range.charEnd) : paragraph,
      };
    })
    .slice(
      currentPageStart,
      currentPageEnd,
    );
  const visibleRichBlocks: ReaderVisibleRichBlock[] = richBlocks
    .slice(currentPageStart, currentPageEnd)
    .map((block) => {
      const range = isPaginatedMode ? pageCharRangeForBlock(currentViewportPage, block.index, block.text.length) : null;
      if (!range) return block;
      const text = block.text.slice(range.charStart, range.charEnd);
      return {
        ...block,
        charEnd: range.charEnd,
        charStart: range.charStart,
        html: block.kind === 'image' || block.kind === 'structure'
          ? block.html
          : sliceReaderRichBlockHtml(block.html, block.text, range.charStart, range.charEnd),
        text,
      };
    });
  const hasReadableRichText = rawText.length > 0;
  const selectedChapterStatText = translationText.trim() || rawText;
  const hasReadableChapterContent = paragraphs.length > 0 || hasRichContent;
  const hasTitleOnlyImportContent = Boolean(
    selectedChapter
      && translationLooksTitleOnly(translationText, selectedChapter)
      && (!hasRichContent || !hasReadableRichText),
  );
  useEffect(() => {
    if (!rawContentAvailable && RAW_READER_TEXT_MODES.has(readerTextMode)) {
      setReaderTextMode('translation');
    }
  }, [rawContentAvailable, readerTextMode, setReaderTextMode]);
  useEffect(() => {
    if (!apiClient || !activeBookId || !selectedChapterId) {
      setReaderQaReport(null);
      setReaderQaState('idle');
      setReaderQaError('');
      return undefined;
    }

    let cancelled = false;
    setReaderQaState('loading');
    setReaderQaError('');

    void apiClient.getQaReport(activeBookId, selectedChapterId)
      .then((report) => {
        if (cancelled) return;
        setReaderQaReport(report);
        setReaderQaState(report ? 'ready' : 'empty');
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setReaderQaReport(null);
        setReaderQaState('error');
        setReaderQaError(formatError(error));
      });

    return () => {
      cancelled = true;
    };
  }, [activeBookId, apiClient, selectedChapterId]);
  const readerStyle = {
    '--reader-character-spacing': `${readerSettings.characterSpacing}px`,
    '--reader-font-size': `${readerSettings.fontSize}px`,
    '--reader-font-weight': String(readerSettings.fontWeight),
    '--reader-line-height': String(readerSettings.lineHeight),
    '--reader-margin-scale': String(readerSettings.marginScale),
    '--reader-paragraph-spacing': `${readerSettings.paragraphSpacing}em`,
  } as CSSProperties;
  const activeMarksKey = getReaderMarksKey(activeBookId, selectedChapterId);
  const chapterMarks = activeMarksKey ? marksStore[activeMarksKey] ?? createEmptyChapterMarks() : createEmptyChapterMarks();
  const bookmarked = chapterMarks.bookmarked;
  const highlightedParagraphs = new Set(chapterMarks.highlights.map((highlight) => highlight.paragraphIndex));
  const notesByParagraph = new Map(chapterMarks.notes.map((note) => [note.paragraphIndex, note]));
  const qaBadgesByParagraph = useMemo(
    () => buildReaderQaBadges(readerQaReport, paragraphs, rawParagraphs),
    [paragraphs, rawParagraphs, readerQaReport],
  );
  const markPanelItems = buildReaderMarkPanelItems(marksStore, chapters, activeBookId);
  const readerSearchScopes = readerSearchOptions.scopes ?? DEFAULT_READER_SEARCH_SCOPES;
  const searchScopesKey = readerSearchScopes.join(',');
  const currentSearchResults = useMemo(
    () => searchCurrentChapter({
      chapter: selectedChapter,
      marks: chapterMarks,
      options: readerSearchOptions,
      paragraphs: progressTextBlocks,
      query: readerSearchQuery,
    }),
    [chapterMarks, progressTextBlocks, readerSearchOptions, readerSearchQuery, selectedChapter],
  );
  const totalProgressChars = totalTextLength(progressTextBlocks);
  const currentPageStartCharOffset = isPaginatedMode ? currentViewportPage.startChar ?? 0 : 0;
  const currentPageStartAbsoluteCharOffset = isPaginatedMode
    ? absoluteCharOffsetForParagraph(progressTextBlocks, currentPageStart, currentPageStartCharOffset)
    : 0;
  const currentPageEndBlockIndex = Math.max(currentPageStart, currentPageEnd - 1);
  const currentPageEndCharOffset = isPaginatedMode
    ? currentViewportPage.endChar ?? (progressTextBlocks[currentPageEndBlockIndex] ?? '').length
    : 0;
  const currentPageEndAbsoluteCharOffset = isPaginatedMode
    ? absoluteCharOffsetForParagraph(progressTextBlocks, currentPageEndBlockIndex, currentPageEndCharOffset)
    : 0;
  const paginatedProgressPercent = isPaginatedMode && selectedChapter && totalProgressChars > 0
    ? Math.min(100, Math.max(0, Math.round((currentPageEndAbsoluteCharOffset / totalProgressChars) * 100)))
    : 0;
  const hasMeasuredScrollTextProgress = scrollTextProgress?.paragraphIndex !== undefined
    && scrollTextProgress.totalChars > 0;
  const scrollChapterProgressPercent = hasMeasuredScrollTextProgress
    ? scrollTextProgress.percent
    : scrollProgress.percent;
  const chapterProgressPercent = isPaginatedMode
    ? paginatedProgressPercent
    : scrollProgress.canScroll
      ? scrollChapterProgressPercent
      : selectedChapter && hasReadableChapterContent
        ? 100
        : 0;
  const progressPercent = chapterProgressPercent;
  const bookPercent = selectedIndex >= 0
    ? bookProgressPercent({
        chapterCount: translatedChapters.length,
        chapterIndex: selectedIndex,
        chapterPercent: chapterProgressPercent,
      })
    : 0;
  const currentChapterReadingStats = readingStatsForText(selectedChapterStatText, chapterProgressPercent);
  const bookProgressLabel = `Sách ${bookPercent}%`;
  const wordsRemainingLabel = formatWordsRemaining(currentChapterReadingStats.remainingWords);
  const timeRemainingLabel = formatReadingTimeRemaining(currentChapterReadingStats.estimatedMinutesRemaining);
  const activeBookProgress = activeBookId ? loadReaderProgressSnapshot(activeBookId) : null;
  const tocProgressIndex = selectedIndex >= 0
    ? selectedIndex
    : activeBookProgress
      ? chapterIndexes.get(activeBookProgress.chapterId) ?? -1
      : -1;
  const tocProgressPercent = selectedIndex >= 0 ? chapterProgressPercent : activeBookProgress?.percent ?? 0;
  const tocChapterPreviews = useMemo(() => {
    const previews = new Map<number, TocChapterPreview>();
    for (const chapter of translatedChapters) {
      const chapterIndex = chapterIndexes.get(chapter.id) ?? -1;
      const previewText = chapter.id === selectedChapterId
        ? selectedChapterStatText
        : chapter.translation_preview ?? '';
      const wordCount = previewText ? countWords(previewText) : 0;
      const minutes = estimateReadingMinutes(wordCount);
      const readingState = chapterIndex < tocProgressIndex
        ? 'read'
        : chapterIndex === tocProgressIndex
          ? tocProgressPercent >= 100 ? 'read' : 'reading'
          : 'unread';
      previews.set(chapter.id, {
        readingState,
        stateLabel: readingState === 'read' ? 'Đã đọc' : readingState === 'reading' ? 'Đang đọc' : 'Chưa đọc',
        timeLabel: wordCount > 0 ? formatReadingTime(minutes) : 'Chưa tính thời gian',
        wordLabel: wordCount > 0 ? formatWordCount(wordCount) : 'Chưa có số từ',
      });
    }
    return previews;
  }, [
    chapterIndexes,
    selectedChapterId,
    selectedChapterStatText,
    tocProgressIndex,
    tocProgressPercent,
    translatedChapters,
  ]);
  const locationLabel = isPaginatedMode
    ? `Trang ${currentPage + 1}/${pageCount}`
    : scrollProgress.canScroll
    ? `Location ${scrollProgress.location} of ${scrollProgress.total}`
    : `Chương ${currentPosition || 0}/${translatedChapters.length}`;
  const progressLabel = currentPosition > 0
    ? `Chương ${selectedChapter?.chapter_number ?? currentPosition} · ${progressPercent}%`
    : 'Chưa chọn chương';
  const activeChapterTitle = selectedChapter
    ? `Chương ${selectedChapter.chapter_number} · ${selectedChapter.title}`
    : 'Chưa chọn chương';
  const canGoPrevious = isPaginatedMode
    ? currentPage > 0 || Boolean(previousChapter)
    : Boolean(previousChapter);
  const canGoNext = isPaginatedMode
    ? currentPage < pageCount - 1 || Boolean(nextChapter)
    : Boolean(nextChapter);

  const updateScrollProgress = useCallback(() => {
    const nextProgress = measureReaderScroll(readerMainRef.current);
    const exactLocation = readerTextLocationFromViewportAnchor(readerMainRef.current, progressTextBlocks);
    const paragraphIndex = exactLocation?.paragraphIndex ?? getCurrentParagraphIndex(readerMainRef.current);
    const charOffset = exactLocation?.charOffset
      ?? charOffsetForParagraph(readerMainRef.current, paragraphIndex, progressTextBlocks);
    const nextTextProgress = readerTextProgressForLocation(progressTextBlocks, paragraphIndex, charOffset);
    setScrollProgress(nextProgress);
    setScrollTextProgress((current) => (sameReaderTextProgress(current, nextTextProgress) ? current : nextTextProgress));
    return nextProgress;
  }, [progressTextBlocks]);

  const expandRenderedParagraphs = useCallback((targetParagraphIndex?: number) => {
    setRenderedParagraphLimit((current) => {
      const minimumLimit = targetParagraphIndex === undefined
        ? current + SCROLL_PARAGRAPH_CHUNK_SIZE
        : Math.max(current + SCROLL_PARAGRAPH_CHUNK_SIZE, targetParagraphIndex + SCROLL_PARAGRAPH_CHUNK_SIZE);
      return Math.min(paragraphs.length, Math.max(current, minimumLimit));
    });
  }, [paragraphs.length]);

  useEffect(() => {
    setAutoScrollEnabled(false);
  }, [selectedChapterId]);

  useEffect(() => {
    if (!autoScrollEnabled || isPaginatedMode) return undefined;

    const interval = window.setInterval(() => {
      const element = readerMainRef.current;
      if (!element) return;

      const maxScrollTop = Math.max(0, element.scrollHeight - element.clientHeight);
      if (element.scrollTop >= maxScrollTop) {
        setAutoScrollEnabled(false);
        return;
      }
      element.scrollTop = Math.min(maxScrollTop, element.scrollTop + 2);
      updateScrollProgress();
    }, 80);

    return () => window.clearInterval(interval);
  }, [autoScrollEnabled, isPaginatedMode, updateScrollProgress]);

  useEffect(() => {
    function handleCacheUpdated(): void {
      setReaderCacheVersion((current) => current + 1);
    }

    window.addEventListener(READER_CACHE_UPDATED_EVENT, handleCacheUpdated);
    return () => window.removeEventListener(READER_CACHE_UPDATED_EVENT, handleCacheUpdated);
  }, []);

  useEffect(() => {
    if (!activeBookId || !selectedChapterId) {
      setCacheStatus(null);
      return;
    }
    let cancelled = false;
    void readerCacheStatusAsync({
      bookId: activeBookId,
      chapterId: selectedChapterId,
      nextChapterId: nextChapter?.id ?? null,
    }).then((status) => {
      if (!cancelled) setCacheStatus(status);
    });
    return () => {
      cancelled = true;
    };
  }, [activeBookId, nextChapter?.id, readerCacheVersion, selectedChapterId]);

  useEffect(() => {
    setOfflineManifest(activeBookId ? loadReaderOfflineManifest(activeBookId) : null);
  }, [activeBookId, readerCacheVersion]);

  useEffect(() => {
    const backendCoverUrl = selectedBook?.cover_url?.trim() ?? '';
    const fallbackCoverUrl = fallbackReaderCover(selectedBook);
    const liveCoverUrl = fallbackCoverUrl || backendCoverUrl;
    setReaderCoverUrl(liveCoverUrl);
    if (!activeBookId || !backendCoverUrl || fallbackCoverUrl) return;

    let cancelled = false;
    void getCachedReaderAssetUrl(activeBookId, 0, backendCoverUrl)
      .then((cachedCoverUrl) => {
        if (!cancelled && cachedCoverUrl) setReaderCoverUrl(cachedCoverUrl);
      })
      .catch(() => {
        if (!cancelled) setReaderCoverUrl(liveCoverUrl);
      });

    return () => {
      cancelled = true;
    };
  }, [activeBookId, readerCacheVersion, selectedBook]);

  useEffect(() => {
    if (!apiClient || !activeBookId) return;
    let cancelled = false;

    void apiClient.getReaderDictionaryPack(activeBookId, { chapterId: selectedChapterId })
      .then((pack) => {
        if (!cancelled) saveCachedReaderDictionaryPack(pack);
      })
      .catch(() => {
        // Dictionary pack is an offline acceleration layer; direct lookup remains authoritative.
      });

    return () => {
      cancelled = true;
    };
  }, [activeBookId, apiClient, selectedChapterId]);

  const measureViewportPagesNow = useCallback(() => {
    if (!isPaginatedMode || paginatedBlockCount === 0 || !canMeasureViewportPages) return;
    const nextPages = measuredViewportPages(
      readerMainRef.current,
      paginationMeasureRef.current,
      paginatedBlockCount,
    );
    setViewportPages((current) => (sameViewportPages(current, nextPages) ? current : nextPages));
  }, [canMeasureViewportPages, isPaginatedMode, paginatedBlockCount]);

  useLayoutEffect(() => {
    if (!isPaginatedMode || paginatedBlockCount === 0 || !canMeasureViewportPages) {
      setViewportPages([]);
      return undefined;
    }

    const cancelRestore = scheduleReaderRestore(measureViewportPagesNow);
    window.addEventListener('resize', measureViewportPagesNow);
    const ResizeObserverConstructor = window.ResizeObserver;
    const observer = ResizeObserverConstructor ? new ResizeObserverConstructor(measureViewportPagesNow) : null;
    if (observer) {
      if (readerMainRef.current) observer.observe(readerMainRef.current);
      if (paginationMeasureRef.current) observer.observe(paginationMeasureRef.current);
    }

    return () => {
      cancelRestore();
      window.removeEventListener('resize', measureViewportPagesNow);
      observer?.disconnect();
    };
  }, [
    isPaginatedMode,
    canMeasureViewportPages,
    contentHtml,
    measureViewportPagesNow,
    paginatedBlockCount,
    readerSettings.characterSpacing,
    readerSettings.fontFamily,
    readerSettings.fontSize,
    readerSettings.fontWeight,
    readerSettings.fullscreen,
    readerSettings.lineHeight,
    readerSettings.marginScale,
    readerSettings.paragraphSpacing,
    readerSettings.width,
    translationText,
  ]);

  useEffect(() => {
    setRenderedParagraphLimit(INITIAL_SCROLL_PARAGRAPH_LIMIT);
  }, [contentHtml, readerSettings.readingMode, selectedChapterId, translationText]);

  useEffect(() => {
    if (!hasMoreScrollParagraphs) return;
    return scheduleReaderIdle(() => expandRenderedParagraphs());
  }, [expandRenderedParagraphs, hasMoreScrollParagraphs, renderedParagraphLimit]);

  useEffect(() => {
    if (!apiClient || !activeBookId) return;
    let cancelled = false;

    void apiClient.getReaderState(activeBookId)
      .then((state) => {
        if (cancelled) return;
        if (state.progress) {
          const localSnapshot = loadReaderProgressSnapshot(activeBookId);
          const remoteSnapshot = remoteReaderProgressToSnapshot(state.progress);
          const resolvedSnapshot = chooseLatestReaderProgressSnapshot(
            localSnapshot,
            remoteSnapshot,
          );
          if (!localSnapshot) {
            setReaderSyncStatus('Sync: tải tiến độ remote');
            setReaderProgressConflict(null);
          } else if (resolvedSnapshot === localSnapshot) {
            setReaderSyncStatus('Sync: giữ tiến độ local mới hơn remote');
            setReaderProgressConflict({ local: localSnapshot, remote: remoteSnapshot });
            skipInitialProgressSaveRef.current = `${activeBookId}:${resolvedSnapshot.chapterId}`;
          } else {
            setReaderSyncStatus('Sync: dùng tiến độ remote mới hơn local');
            setReaderProgressConflict({ local: localSnapshot, remote: remoteSnapshot });
          }
          saveReaderProgressSnapshot(
            activeBookId,
            resolvedSnapshot.chapterId,
            resolvedSnapshot.position,
            resolvedSnapshot.totalChapters,
            undefined,
            {
              absoluteCharOffset: resolvedSnapshot.absoluteCharOffset,
              charOffset: resolvedSnapshot.charOffset,
              mode: resolvedSnapshot.mode,
              pageIndex: resolvedSnapshot.pageIndex,
              percent: resolvedSnapshot.percent,
              paragraphIndex: resolvedSnapshot.paragraphIndex,
              updatedAt: resolvedSnapshot.updatedAt,
            },
          );
        } else {
          setReaderSyncStatus('');
          setReaderProgressConflict(null);
        }
        const mergedMarks = mergeLocalAndRemoteMarks(loadReaderMarks(), state.annotations);
        saveReaderMarks(mergedMarks);
        setMarksStore(mergedMarks);
        const localAnnotations = readerMarksToSyncAnnotations(mergedMarks, activeBookId);
        if (localAnnotations.length > 0) {
          void apiClient.syncReaderState(activeBookId, {
            annotations: localAnnotations,
            device_id: readerDeviceId,
            last_sync_at: loadReaderLastSyncAt(activeBookId),
          })
            .then((syncedState) => {
              if (cancelled) return;
              saveReaderLastSyncAt(activeBookId, syncedState.server_time);
              const next = mergeLocalAndRemoteMarks(loadReaderMarks(), syncedState.annotations);
              saveReaderMarks(next);
              setMarksStore(next);
              const annotationConflicts = syncedState.conflicts.filter((conflict) => conflict.entity === 'annotation');
              setReaderAnnotationConflicts(annotationConflicts);
              setReaderSyncStatus(
                annotationConflicts.length > 0
                  ? `Sync: ${annotationConflicts.length} xung đột dấu đọc`
                  : `Sync: đã đồng bộ ${localAnnotations.length} dấu đọc local`,
              );
            })
            .catch((error: unknown) => {
              if (!cancelled) handleMarksSyncError(error);
            });
        } else {
          setReaderAnnotationConflicts([]);
        }
        setMarksError('');
      })
      .catch((error: unknown) => {
        if (!cancelled) setMarksError(error instanceof Error ? error.message : 'Failed to load reader marks');
      });

    return () => {
      cancelled = true;
    };
  }, [activeBookId, apiClient, readerDeviceId]);

  useEffect(() => {
    if (!moreOpen || !apiClient) {
      setDictionaryListLoading(false);
      return undefined;
    }

    let cancelled = false;
    setDictionaryListLoading(true);
    void apiClient.listReaderDictionaries()
      .then((files) => {
        if (!cancelled) setReaderDictionaries(files);
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setDictionaryUploadStatus(error instanceof Error ? error.message : 'Failed to load reader dictionaries');
        }
      })
      .finally(() => {
        if (!cancelled) setDictionaryListLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [apiClient, dictionaryListVersion, moreOpen]);

  useEffect(() => {
    const query = readerSearchQuery.trim();
    if (!readerSearchOpen || !apiClient || !activeBookId || !query) {
      setBookSearchResults([]);
      setBookSearchLoading(false);
      setBookSearchError('');
      return;
    }

    let cancelled = false;
    setBookSearchLoading(true);
    setBookSearchError('');
    const timeout = window.setTimeout(() => {
      void apiClient.searchBook(activeBookId, query, {
        caseSensitive: readerSearchOptions.caseSensitive,
        regex: readerSearchOptions.regex,
        scopes: readerSearchScopes,
        wholeWord: readerSearchOptions.wholeWord,
      })
        .then((results) => {
          if (cancelled) return;
          setBookSearchResults(results);
          setBookSearchError('');
        })
        .catch((error: unknown) => {
          if (cancelled) return;
          setBookSearchResults([]);
          setBookSearchError(error instanceof Error ? error.message : 'Failed to search reader book');
        })
        .finally(() => {
          if (!cancelled) setBookSearchLoading(false);
        });
    }, 300);

    return () => {
      cancelled = true;
      window.clearTimeout(timeout);
    };
  }, [
    activeBookId,
    apiClient,
    readerSearchOpen,
    readerSearchOptions.caseSensitive,
    readerSearchOptions.regex,
    readerSearchOptions.wholeWord,
    readerSearchQuery,
    searchScopesKey,
  ]);

  function handleReaderScroll(): void {
    restorePendingRef.current = false;
    const nextProgress = updateScrollProgress();
    if (
      hasMoreScrollParagraphs
      && nextProgress.canScroll
      && nextProgress.total - nextProgress.location <= LAZY_SCROLL_DISTANCE_PX
    ) {
      expandRenderedParagraphs();
    }
  }

  useEffect(() => {
    const element = readerMainRef.current;
    const savedSnapshot = activeBookId ? loadReaderProgressSnapshot(activeBookId) : null;
    const shouldRestore = Boolean(savedSnapshot && savedSnapshot.chapterId === selectedChapterId);
    const savedAnchorLocation = shouldRestore && savedSnapshot
      ? resolveReaderProgressTextAnchor(progressTextBlocks, savedSnapshot)
      : null;
    const savedAbsoluteLocation = shouldRestore && !savedAnchorLocation && savedSnapshot?.absoluteCharOffset !== undefined
      ? paragraphLocation(
        progressTextBlocks.map((paragraph, index) => ({ index, paragraph })),
        savedSnapshot.absoluteCharOffset,
      )
      : null;
    const restoredLocation = savedAnchorLocation ?? savedAbsoluteLocation;
    const restoreParagraphIndex = restoredLocation?.paragraphIndex ?? savedSnapshot?.paragraphIndex;
    const restoreCharOffset = restoredLocation?.charOffset ?? savedSnapshot?.charOffset;
    const savedPageIndex = shouldRestore && savedSnapshot?.mode === 'paginated'
	      ? clampPageIndex(
	        restoreParagraphIndex !== undefined
	          ? pageIndexForParagraph(
	            restoreParagraphIndex,
	            activeViewportPages,
	            savedSnapshot.pageIndex ?? 0,
	            restoreCharOffset,
	          )
	          : savedSnapshot.pageIndex ?? 0,
	        pageCount,
	      )
      : 0;

    restorePendingRef.current = true;
    setCurrentPage(savedPageIndex);
    if (
      !isPaginatedMode
      && shouldRestore
      && restoreParagraphIndex !== undefined
      && restoreParagraphIndex >= visibleScrollParagraphLimit
    ) {
      expandRenderedParagraphs(restoreParagraphIndex);
    }

    if (!element) {
      restorePendingRef.current = false;
      return;
    }

    return scheduleReaderRestore(() => {
      const nextElement = readerMainRef.current;
      if (!nextElement) {
        restorePendingRef.current = false;
        return;
      }

      if (!shouldRestore) {
        nextElement.scrollTop = 0;
      } else {
        if (savedSnapshot?.mode === 'scroll') {
          const exactScrollTop = scrollTopForParagraphLocation(
            nextElement,
            restoreParagraphIndex,
            restoreCharOffset,
            progressTextBlocks,
          );
          if (exactScrollTop !== null) {
            nextElement.scrollTop = exactScrollTop;
          } else {
            if (restoreParagraphIndex !== undefined) {
              scrollReaderParagraphIntoView(nextElement, restoreParagraphIndex);
            }
            nextElement.scrollTop = savedSnapshot.position;
          }
        } else if (restoreParagraphIndex !== undefined) {
          scrollReaderParagraphIntoView(nextElement, restoreParagraphIndex);
        }
      }

      updateScrollProgress();
      restorePendingRef.current = false;
    });
  }, [
    activeBookId,
    activeViewportPages,
    contentHtml,
    expandRenderedParagraphs,
    isPaginatedMode,
    pageCount,
    progressTextBlocks,
    readerSettings.readingMode,
    selectedChapterId,
    translationText,
    updateScrollProgress,
    visibleScrollParagraphLimit,
  ]);

  useEffect(() => {
    setCurrentPage((page) => Math.min(page, pageCount - 1));
  }, [pageCount]);

  useEffect(() => {
    if (!activeBookId || !selectedChapterId || restorePendingRef.current) return;

    const mode = isPaginatedMode ? 'paginated' : 'scroll';
    const progressKey = `${activeBookId}:${selectedChapterId}`;
    if (skipInitialProgressSaveRef.current === progressKey) {
      skipInitialProgressSaveRef.current = '';
      return;
    }
    const measuredParagraphIndex = getCurrentParagraphIndex(readerMainRef.current);
    const viewportExactLocation = readerTextLocationFromViewportAnchor(
      readerMainRef.current,
      progressTextBlocks,
      isPaginatedMode
        ? {
          excludeBlockAncestorSelector: '.reader-pagination-measure',
          fallbackToBoundary: false,
          fallbackToGeometry: true,
        }
        : undefined,
    );
    const exactLocation = isPaginatedMode
      ? readerTextLocationWithinPage(viewportExactLocation, currentViewportPage) ? viewportExactLocation : null
      : viewportExactLocation;
    const paragraphIndex = isPaginatedMode
      ? exactLocation?.paragraphIndex ?? currentPageStart
      : exactLocation?.paragraphIndex ?? scrollTextProgress?.paragraphIndex ?? measuredParagraphIndex;
    const charOffset = isPaginatedMode
      ? exactLocation?.charOffset ?? currentPageStartCharOffset
      : exactLocation?.charOffset
        ?? scrollTextProgress?.charOffset
        ?? charOffsetForParagraph(readerMainRef.current, paragraphIndex, progressTextBlocks);
    const absoluteCharOffset = isPaginatedMode
      ? exactLocation?.absoluteCharOffset ?? currentPageStartAbsoluteCharOffset
      : exactLocation?.absoluteCharOffset
        ?? scrollTextProgress?.absoluteCharOffset
        ?? absoluteCharOffsetForParagraph(progressTextBlocks, paragraphIndex, charOffset);
    const position = isPaginatedMode
      ? currentPage + 1
      : scrollProgress.canScroll
        ? scrollProgress.location
        : currentPosition;
    const total = isPaginatedMode
      ? pageCount
      : scrollProgress.canScroll
        ? scrollProgress.total
        : translatedChapters.length;
    const characterProgressPercent = totalProgressChars > 0
      ? Math.min(100, Math.max(0, Math.round((absoluteCharOffset / totalProgressChars) * 100)))
      : progressPercent;
    const snapshotProgressPercent = (
      isPaginatedMode
      || Boolean(exactLocation)
      || scrollTextProgress?.paragraphIndex !== undefined
    )
      ? characterProgressPercent
      : progressPercent;

    const updatedAt = new Date().toISOString();
    const anchor = buildReaderProgressTextAnchor(progressTextBlocks, paragraphIndex, charOffset);
    const progressSnapshot: ReaderProgressSnapshot = {
      absoluteCharOffset,
      anchor,
      chapterId: selectedChapterId,
      charOffset,
      mode,
      pageIndex: isPaginatedMode ? currentPage : undefined,
      paragraphIndex,
      percent: snapshotProgressPercent,
      position,
      totalChapters: total,
      updatedAt,
    };

    saveReaderProgressSnapshot(
      activeBookId,
      selectedChapterId,
      position,
      total,
      undefined,
      {
        absoluteCharOffset,
        anchor,
        charOffset,
        mode,
        pageIndex: isPaginatedMode ? currentPage : undefined,
        percent: snapshotProgressPercent,
        paragraphIndex,
        updatedAt,
      },
    );

    if (apiClient) {
      void apiClient.syncReaderState(activeBookId, {
        device_id: readerDeviceId,
        last_sync_at: loadReaderLastSyncAt(activeBookId),
        progress: readerProgressSnapshotToSyncProgress(progressSnapshot),
      })
        .then((syncedState) => {
          saveReaderLastSyncAt(activeBookId, syncedState.server_time);
          const progressConflict = syncedState.conflicts.find((conflict) => conflict.entity === 'progress');
          if (progressConflict) {
            if (progressConflict.resolution === 'client_won') {
              setReaderProgressConflict(null);
            } else if (syncedState.progress) {
              setReaderProgressConflict({
                local: progressSnapshot,
                remote: remoteReaderProgressToSnapshot(syncedState.progress),
              });
            }
            setReaderSyncStatus(
              progressConflict.resolution === 'client_won'
                ? 'Sync: đã resolve tiến độ bằng local'
                : 'Sync: tiến độ server mới hơn local',
            );
          }
        })
        .catch((error: unknown) => {
          setMarksError(error instanceof Error ? error.message : 'Failed to sync reader progress');
        });
    }
  }, [
    activeBookId,
    apiClient,
    currentPage,
    currentViewportPage,
    currentPageStart,
    currentPageStartAbsoluteCharOffset,
    currentPageStartCharOffset,
    currentPosition,
    isPaginatedMode,
    pageCount,
    progressTextBlocks,
    progressPercent,
    readerDeviceId,
    scrollProgress.canScroll,
    scrollProgress.location,
    scrollProgress.total,
    scrollTextProgress,
    selectedChapterId,
    totalProgressChars,
    translatedChapters.length,
  ]);

  useEffect(() => {
    if (!pendingParagraphJump || pendingParagraphJump.chapterId !== selectedChapterId) return;
    if (isPaginatedMode) {
      const targetPage = clampPageIndex(
        pageIndexForParagraph(
          pendingParagraphJump.paragraphIndex,
          activeViewportPages,
          undefined,
          pendingParagraphJump.charOffset,
        ),
        pageCount,
      );
      if (targetPage !== currentPage) {
        setCurrentPage(targetPage);
        return;
      }
    }
    if (
      !isPaginatedMode
      && pendingParagraphJump.paragraphIndex >= visibleScrollParagraphLimit
    ) {
      expandRenderedParagraphs(pendingParagraphJump.paragraphIndex);
      return;
    }

    return scheduleReaderRestore(() => {
      const exactScrollTop = scrollTopForParagraphLocation(
        readerMainRef.current,
        pendingParagraphJump.paragraphIndex,
        pendingParagraphJump.charOffset,
        progressTextBlocks,
      );
      if (exactScrollTop !== null && readerMainRef.current) {
        readerMainRef.current.scrollTop = exactScrollTop;
      } else {
        scrollReaderParagraphIntoView(readerMainRef.current, pendingParagraphJump.paragraphIndex);
      }
      updateScrollProgress();
      setPendingParagraphJump(null);
    });
  }, [
    activeViewportPages,
    contentHtml,
    currentPage,
    expandRenderedParagraphs,
    isPaginatedMode,
    pageCount,
    pendingParagraphJump,
    progressTextBlocks,
    selectedChapterId,
    translationText,
    updateScrollProgress,
    visibleParagraphs.length,
    visibleScrollParagraphLimit,
  ]);

  function updateReaderSettings(patch: Partial<ReaderSettings>): void {
    setReaderSettings((current) => {
      const next = {
        ...current,
        ...patch,
      };
      saveReaderSettings(next);
      return next;
    });
  }

  function clearReaderSelection(): void {
    window.getSelection()?.removeAllRanges();
    setReaderSelection(null);
  }

  function captureReaderSelection(): void {
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed || selection.rangeCount === 0) {
      setReaderSelection(null);
      return;
    }

    const text = selection.toString().trim().slice(0, 2000);
    if (!text) {
      setReaderSelection(null);
      return;
    }

    const range = selection.getRangeAt(0);
    if (!readerMainRef.current?.contains(range.commonAncestorContainer)) {
      setReaderSelection(null);
      return;
    }

    const selectionBlock = selectionParagraphBlock(readerMainRef.current, range.startContainer)
      ?? selectionParagraphBlock(readerMainRef.current, range.commonAncestorContainer)
      ?? selectionParagraphBlock(readerMainRef.current, selection.anchorNode)
      ?? selectionParagraphBlock(readerMainRef.current, selection.focusNode);
    const paragraphIndex = paragraphIndexFromSelectionNode(selectionBlock)
      ?? paragraphIndexFromSelectionNode(range.commonAncestorContainer)
      ?? paragraphIndexFromSelectionNode(selection.anchorNode)
      ?? paragraphIndexFromSelectionNode(selection.focusNode)
      ?? getCurrentParagraphIndex(readerMainRef.current)
      ?? 0;
    const paragraphText = progressTextBlocks[paragraphIndex] ?? text;
    const paragraphElement = paragraphTextElementFromBlock(selectionBlock)
      ?? paragraphTextElement(readerMainRef.current, paragraphIndex);
    const rangeStart = paragraphElement
      ? textOffsetWithinNode(paragraphElement, range.startContainer, range.startOffset)
      : null;
    const rangeEnd = paragraphElement
      ? textOffsetWithinNode(paragraphElement, range.endContainer, range.endOffset)
      : null;
    const rangeBaseOffset = charStartOffsetFromBlock(selectionBlock);
    const fallbackStart = Math.max(0, paragraphText.indexOf(text));
    const charStart = rangeStart !== null ? rangeBaseOffset + rangeStart : fallbackStart;
    const charEnd = rangeEnd !== null ? rangeBaseOffset + rangeEnd : charStart + text.length;
    setReaderSelection({
      anchor: selectionAnchorFromRect(range.getBoundingClientRect()),
      charEnd,
      charStart,
      contextAfter: progressTextBlocks[paragraphIndex + 1] ?? '',
      contextBefore: progressTextBlocks[paragraphIndex - 1] ?? '',
      paragraphIndex,
      text,
    });
  }

  function handleSelectChapter(chapterId: number, options: { keepAudioOpen?: boolean } = {}): void {
    onSelectChapter(chapterId);
    setTocOpen(false);
    setReaderSearchOpen(false);
    setMoreOpen(false);
    setMarksPanelOpen(false);
    setReaderSelection(null);
    setDictionaryOpen(false);
    if (!options.keepAudioOpen) {
      readerAudio.actions.close();
    }
    setXrayOpen(false);
  }

  function updateChapterMarks(updater: (current: ReaderChapterMarks) => ReaderChapterMarks): void {
    if (!activeMarksKey) return;
    setMarksStore((currentStore) => {
      const currentMarks = currentStore[activeMarksKey] ?? createEmptyChapterMarks();
      const nextMarks = sanitizeChapterMarks(updater(currentMarks));
      const nextStore = {
        ...currentStore,
        [activeMarksKey]: nextMarks,
      };
      saveReaderMarks(nextStore);
      return nextStore;
    });
  }

  function mergeRemoteAnnotation(annotation: Parameters<typeof annotationToLocalMark>[0]): void {
    setMarksStore((currentStore) => {
      const nextStore = mergeLocalAndRemoteMarks(currentStore, [annotation]);
      saveReaderMarks(nextStore);
      return nextStore;
    });
    setMarksError('');
  }

  function handleMarksSyncError(error: unknown): void {
    setMarksError(error instanceof Error ? error.message : 'Failed to sync reader marks');
  }

  function saveSelectionHighlight(selection: ReaderSelectionState): void {
    const existingHighlight = chapterMarks.highlights.find((highlight) => (
      sameReaderHighlightRange(
        highlight,
        selection.paragraphIndex,
        selection.charStart,
        selection.charEnd,
      )
    ));
    const updatedAt = new Date().toISOString();
    updateChapterMarks((current) => ({
      ...current,
      highlights: [
        ...current.highlights.filter((highlight) => !sameReaderHighlightRange(
          highlight,
          selection.paragraphIndex,
          selection.charStart,
          selection.charEnd,
        )),
        {
          annotationId: existingHighlight?.annotationId,
          bookId: activeBookId ?? undefined,
          charEnd: selection.charEnd,
          charStart: selection.charStart,
          chapterId: selectedChapterId ?? undefined,
          chapterNumber: selectedChapter?.chapter_number,
          chapterTitle: selectedChapter?.title,
          clientId: existingHighlight?.clientId,
          createdAt: existingHighlight?.createdAt,
          id: existingHighlight?.id ?? readerHighlightRangeId(
            selection.paragraphIndex,
            selection.charStart,
            selection.charEnd,
          ),
          paragraphIndex: selection.paragraphIndex,
          syncPending: Boolean(existingHighlight?.annotationId),
          text: selection.text,
          updatedAt: existingHighlight?.annotationId ? updatedAt : existingHighlight?.updatedAt,
        },
      ],
    }));

    if (!apiClient || !activeBookId || !selectedChapterId) return;
    const payload = {
      char_end: selection.charEnd,
      char_start: selection.charStart,
      kind: 'highlight' as const,
      paragraph_index: selection.paragraphIndex,
      selected_text: selection.text,
    };
    if (existingHighlight?.annotationId) {
      void apiClient.updateReaderAnnotation(activeBookId, existingHighlight.annotationId, payload)
        .then(mergeRemoteAnnotation)
        .catch(handleMarksSyncError);
      return;
    }
    void apiClient.createReaderAnnotation(activeBookId, selectedChapterId, payload)
      .then(mergeRemoteAnnotation)
      .catch(handleMarksSyncError);
  }

  function toggleBookmark(): void {
    const wasBookmarked = bookmarked;
    const annotationId = chapterMarks.bookmarkAnnotationId;
    const deletedAt = new Date().toISOString();
    updateChapterMarks((current) => ({
      ...current,
      bookmarked: !current.bookmarked,
      bookmarkAnnotationId: current.bookmarked ? undefined : current.bookmarkAnnotationId,
      deletedAnnotations: current.bookmarked && annotationId && selectedChapterId
        ? upsertDeletedReaderAnnotation(current.deletedAnnotations ?? [], {
          annotationId,
          chapterId: selectedChapterId,
          deletedAt,
          kind: 'bookmark',
          paragraphIndex: 0,
          selectedText: activeChapterTitle,
          updatedAt: deletedAt,
        })
        : current.deletedAnnotations ?? [],
    }));

    if (!apiClient || !activeBookId || !selectedChapterId) return;
    if (wasBookmarked) {
      if (annotationId) {
        void apiClient.deleteReaderAnnotation(activeBookId, annotationId).catch(handleMarksSyncError);
      }
      return;
    }

    void apiClient.createReaderAnnotation(activeBookId, selectedChapterId, {
      kind: 'bookmark',
      paragraph_index: 0,
      selected_text: activeChapterTitle,
    })
      .then(mergeRemoteAnnotation)
      .catch(handleMarksSyncError);
  }

  function toggleHighlight(paragraphIndex: number, text: string, range?: { charEnd: number; charStart: number }): void {
    const charStart = range?.charStart ?? 0;
    const charEnd = range?.charEnd ?? text.length;
    const existingHighlight = chapterMarks.highlights.find((highlight) => (
      sameReaderHighlightRange(highlight, paragraphIndex, charStart, charEnd)
    ));
    const mutationTime = new Date().toISOString();
    updateChapterMarks((current) => {
      const exists = current.highlights.some((highlight) => (
        sameReaderHighlightRange(highlight, paragraphIndex, charStart, charEnd)
      ));
      const deletedChapterId = existingHighlight?.chapterId ?? selectedChapterId ?? 0;
      return {
        ...current,
        deletedAnnotations: exists && existingHighlight?.annotationId && deletedChapterId > 0
          ? upsertDeletedReaderAnnotation(current.deletedAnnotations ?? [], {
            annotationId: existingHighlight.annotationId,
            chapterId: deletedChapterId,
            charEnd: existingHighlight.charEnd,
            charStart: existingHighlight.charStart,
            clientId: existingHighlight.clientId,
            color: existingHighlight.color,
            deletedAt: mutationTime,
            kind: 'highlight',
            paragraphIndex: existingHighlight.paragraphIndex,
            selectedText: existingHighlight.text,
            updatedAt: mutationTime,
          })
          : current.deletedAnnotations ?? [],
        highlights: exists
          ? current.highlights.filter((highlight) => !sameReaderHighlightRange(
            highlight,
            paragraphIndex,
            charStart,
            charEnd,
          ))
          : [
            ...current.highlights,
            {
              id: readerHighlightRangeId(paragraphIndex, charStart, charEnd),
              charEnd,
              charStart,
              paragraphIndex,
              text,
              updatedAt: mutationTime,
            },
          ],
      };
    });

    if (!apiClient || !activeBookId || !selectedChapterId) return;
    if (existingHighlight?.annotationId) {
      void apiClient.deleteReaderAnnotation(activeBookId, existingHighlight.annotationId).catch(handleMarksSyncError);
      return;
    }
    if (existingHighlight) return;

    void apiClient.createReaderAnnotation(activeBookId, selectedChapterId, {
      char_end: charEnd,
      char_start: charStart,
      kind: 'highlight',
      paragraph_index: paragraphIndex,
      selected_text: text,
    })
      .then(mergeRemoteAnnotation)
      .catch(handleMarksSyncError);
  }

  function openNoteEditor(paragraphIndex: number, text: string, range?: { charEnd: number; charStart: number }): void {
    const existingNote = notesByParagraph.get(paragraphIndex);
    setNoteDraft({
      charEnd: range?.charEnd ?? existingNote?.charEnd ?? text.length,
      charStart: range?.charStart ?? existingNote?.charStart ?? 0,
      paragraphIndex,
      text,
      value: existingNote?.note ?? '',
    });
  }

  function saveNoteDraft(): void {
    if (!noteDraft) return;
    const note = noteDraft.value.trim();
    const existingNote = notesByParagraph.get(noteDraft.paragraphIndex);
    const mutationTime = new Date().toISOString();
    updateChapterMarks((current) => ({
      ...current,
      deletedAnnotations: !note && existingNote?.annotationId
        ? upsertDeletedReaderAnnotation(current.deletedAnnotations ?? [], {
          annotationId: existingNote.annotationId,
          chapterId: existingNote.chapterId ?? selectedChapterId ?? 0,
          charEnd: existingNote.charEnd,
          charStart: existingNote.charStart,
          clientId: existingNote.clientId,
          color: existingNote.color,
          deletedAt: mutationTime,
          kind: 'note',
          note: existingNote.note,
          paragraphIndex: existingNote.paragraphIndex,
          selectedText: existingNote.text,
          updatedAt: mutationTime,
        })
        : current.deletedAnnotations ?? [],
      notes: note
        ? [
          ...current.notes.filter((item) => item.paragraphIndex !== noteDraft.paragraphIndex),
          {
            annotationId: existingNote?.annotationId,
            bookId: existingNote?.bookId,
            chapterId: existingNote?.chapterId,
            chapterNumber: existingNote?.chapterNumber,
            chapterTitle: existingNote?.chapterTitle,
            charEnd: noteDraft.charEnd,
            charStart: noteDraft.charStart,
            clientId: existingNote?.clientId,
            color: existingNote?.color,
            createdAt: existingNote?.createdAt,
            id: existingNote?.id ?? `note-${noteDraft.paragraphIndex}`,
            note,
            paragraphIndex: noteDraft.paragraphIndex,
            syncPending: Boolean(existingNote?.annotationId),
            text: noteDraft.text,
            updatedAt: existingNote?.annotationId ? mutationTime : existingNote?.updatedAt,
          },
        ]
        : current.notes.filter((item) => item.paragraphIndex !== noteDraft.paragraphIndex),
    }));
    setNoteDraft(null);

    if (!apiClient || !activeBookId || !selectedChapterId) return;
    if (!note) {
      if (existingNote?.annotationId) {
        void apiClient.deleteReaderAnnotation(activeBookId, existingNote.annotationId).catch(handleMarksSyncError);
      }
      return;
    }

    if (existingNote?.annotationId) {
      void apiClient.updateReaderAnnotation(activeBookId, existingNote.annotationId, {
        char_end: noteDraft.charEnd,
        char_start: noteDraft.charStart,
        kind: 'note',
        note,
        paragraph_index: noteDraft.paragraphIndex,
        selected_text: noteDraft.text,
      })
        .then(mergeRemoteAnnotation)
        .catch(handleMarksSyncError);
      return;
    }

    void apiClient.createReaderAnnotation(activeBookId, selectedChapterId, {
      char_end: noteDraft.charEnd,
      char_start: noteDraft.charStart,
      kind: 'note',
      note,
      paragraph_index: noteDraft.paragraphIndex,
      selected_text: noteDraft.text,
    })
      .then(mergeRemoteAnnotation)
      .catch(handleMarksSyncError);
  }

  function loadReaderAi(
    selection: ReaderSelectionState,
    spoilerMode = readerAiSpoilerMode,
    mode = readerAiMode,
  ): void {
    if (!apiClient || !activeBookId || !selectedChapterId) {
      setReaderAiLoading(false);
      setReaderAiCached(false);
      setReaderAiError('Reader AI requires an API connection.');
      return;
    }

    const cacheKey = readerAiCacheKey({
      bookId: activeBookId,
      chapterId: selectedChapterId,
      mode,
      spoilerMode,
      text: selection.text,
    });
    const cachedResult = readerAiCacheRef.current.get(cacheKey);
    if (cachedResult) {
      setReaderAiLoading(false);
      setReaderAiCached(true);
      setReaderAiError('');
      setReaderAiResult(cachedResult);
      return;
    }

    setReaderAiLoading(true);
    setReaderAiCached(false);
    setReaderAiError('');
    setReaderAiResult(null);

    void apiClient.explainReaderSelection(activeBookId, selectedChapterId, {
      context_after: selection.contextAfter,
      context_before: selection.contextBefore,
      spoiler_mode: spoilerMode,
      text: selection.text,
    })
      .then((result) => {
        readerAiCacheRef.current.set(cacheKey, result);
        setReaderAiResult(result);
        setReaderAiCached(false);
        setReaderAiError('');
      })
      .catch((error: unknown) => {
        setReaderAiError(error instanceof Error ? error.message : 'Failed to explain selected text');
      })
      .finally(() => setReaderAiLoading(false));
  }

  function openReaderAi(selection: ReaderSelectionState, mode: ReaderAiPanelMode): void {
    setReaderAiMode(mode);
    setReaderAiSelection(selection);
    setReaderAiOpen(true);
    loadReaderAi(selection, readerAiSpoilerMode, mode);
  }

  function retryReaderAi(): void {
    if (readerAiSelection) loadReaderAi(readerAiSelection);
  }

  function updateReaderAiSpoilerMode(mode: ReaderExplainSpoilerMode): void {
    setReaderAiSpoilerMode(mode);
    if (readerAiSelection) loadReaderAi(readerAiSelection, mode);
  }

  function loadReaderDictionary(
    selection: ReaderSelectionState,
    includeOnline = dictionaryIncludeOnline,
  ): void {
    setDictionaryQuery(selection.text);
    const cachedResult = activeBookId
      ? loadCachedReaderDictionaryResult(activeBookId, selection.text)
        ?? lookupCachedReaderDictionaryPack(activeBookId, selection.text, selectedChapterId)
      : null;
    if (!apiClient || !activeBookId) {
      setDictionaryLoading(false);
      if (cachedResult) {
        setDictionaryResult(cachedResult);
        setDictionaryError('');
      } else {
        setDictionaryError('Reader dictionary requires an API connection.');
      }
      return;
    }

    setDictionaryLoading(true);
    setDictionaryError('');
    setDictionaryResult(cachedResult);

    void apiClient.lookupReaderDictionary(activeBookId, selection.text, {
      chapterId: selectedChapterId,
      includeOnline,
    })
      .then((result) => {
        saveCachedReaderDictionaryResult(result);
        setDictionaryResult(result);
        setDictionaryError('');
      })
      .catch((error: unknown) => {
        const fallbackResult = loadCachedReaderDictionaryResult(activeBookId, selection.text)
          ?? lookupCachedReaderDictionaryPack(activeBookId, selection.text, selectedChapterId);
        if (fallbackResult) {
          setDictionaryResult(fallbackResult);
          setDictionaryError('');
        } else {
          setDictionaryError(error instanceof Error ? error.message : 'Failed to lookup reader dictionary');
        }
      })
      .finally(() => setDictionaryLoading(false));
  }

  function openReaderDictionary(selection: ReaderSelectionState): void {
    setDictionarySelection(selection);
    setDictionaryOpen(true);
    setMoreOpen(false);
    loadReaderDictionary(selection);
  }

  function retryReaderDictionary(): void {
    if (dictionarySelection) loadReaderDictionary(dictionarySelection);
  }

  function updateDictionaryIncludeOnline(value: boolean): void {
    setDictionaryIncludeOnline(value);
    if (dictionarySelection) loadReaderDictionary(dictionarySelection, value);
  }

  function uploadReaderDictionaryFile(file: File | null): void {
    if (!file) return;
    if (!apiClient) {
      setDictionaryUploadStatus('Không thể nạp từ điển: thiếu kết nối API.');
      return;
    }

    setDictionaryUploadLoading(true);
    setDictionaryUploadStatus('Đang nạp từ điển offline...');
    void apiClient.uploadReaderDictionary(file)
      .then((payload) => {
        setDictionaryUploadStatus(
          `Đã nạp từ điển ${payload.filename} · ${payload.entry_count.toLocaleString('vi-VN')} mục`,
        );
        setDictionaryListVersion((current) => current + 1);
        if (!activeBookId) return undefined;
        return apiClient.getReaderDictionaryPack(activeBookId, { chapterId: selectedChapterId })
          .then((pack) => {
            saveCachedReaderDictionaryPack(pack);
          });
      })
      .catch((error: unknown) => {
        setDictionaryUploadStatus(error instanceof Error ? error.message : 'Failed to upload reader dictionary');
      })
      .finally(() => setDictionaryUploadLoading(false));
  }

  function deleteReaderDictionaryFile(filename: string): void {
    if (!apiClient) {
      setDictionaryUploadStatus('Không thể xóa từ điển: thiếu kết nối API.');
      return;
    }

    setDictionaryDeletingFilename(filename);
    setDictionaryUploadStatus(`Đang xóa từ điển ${filename}...`);
    void apiClient.deleteReaderDictionary(filename)
      .then(() => {
        setReaderDictionaries((current) => current.filter((file) => file.filename !== filename));
        setDictionaryUploadStatus(`Đã xóa từ điển ${filename}`);
        setDictionaryListVersion((current) => current + 1);
        if (!activeBookId) return undefined;
        return apiClient.getReaderDictionaryPack(activeBookId, { chapterId: selectedChapterId })
          .then((pack) => {
            saveCachedReaderDictionaryPack(pack);
          });
      })
      .catch((error: unknown) => {
        setDictionaryUploadStatus(error instanceof Error ? error.message : 'Failed to delete reader dictionary');
      })
      .finally(() => setDictionaryDeletingFilename(''));
  }

  function exportReaderAnnotations(format: ReaderAnnotationExportFormat, kindOverride?: ReaderAnnotationKind | null): void {
    if (!activeBookId) {
      setMarksError('Không thể xuất dấu đọc: chưa chọn truyện.');
      return;
    }

    const selectedKind = kindOverride !== undefined ? kindOverride : annotationExportKind;
    const scopeLabel = readerAnnotationExportScopes.find((scope) => scope.kind === selectedKind)?.label ?? 'All';
    const exportLocalMarks = (): void => {
      const download = localReaderMarksDownload(
        markPanelItems,
        format,
        selectedBook?.title ?? 'reader',
        selectedKind,
      );
      triggerBrowserDownload(download.blob, download.filename);
      setAnnotationExportStatus(`Đã xuất local ${download.filename}`);
      setMarksError('');
    };

    if (!apiClient) {
      exportLocalMarks();
      return;
    }

    const request = selectedKind
      ? apiClient.downloadReaderAnnotations(activeBookId, format, { kind: selectedKind })
      : apiClient.downloadReaderAnnotations(activeBookId, format);

    setAnnotationExportStatus(`Đang xuất ${scopeLabel} ${format.toUpperCase()}...`);
    void request
      .then((download) => {
        triggerBrowserDownload(download.blob, download.filename);
        setAnnotationExportStatus(`Đã xuất ${download.filename}`);
        setMarksError('');
      })
      .catch((error: unknown) => {
        if (markPanelItems.length > 0) {
          exportLocalMarks();
          setMarksError(error instanceof Error ? `Backend export lỗi, đã dùng local: ${error.message}` : 'Backend export lỗi, đã dùng local.');
        } else {
          setAnnotationExportStatus('');
          setMarksError(error instanceof Error ? error.message : 'Failed to export reader annotations');
        }
      });
  }

  function importReaderAnnotationsFile(file: File | null): void {
    if (!file) return;
    if (!apiClient || !activeBookId) {
      setMarksError('Không thể nhập dấu đọc: thiếu kết nối API hoặc chưa chọn truyện.');
      return;
    }

    setAnnotationImportLoading(true);
    setAnnotationExportStatus(`Đang nhập ${file.name}...`);
    void file.text()
      .then((text) => {
        const parsed = JSON.parse(text) as unknown;
        const annotations = readerAnnotationImportItemsFromPayload(parsed);
        if (annotations.length === 0) {
          throw new Error('File JSON không có dấu đọc hợp lệ.');
        }
        return apiClient.importReaderAnnotations(activeBookId, annotations);
      })
      .then((response) => {
        if (response.annotations.length > 0) {
          const nextStore = mergeLocalAndRemoteMarks(loadReaderMarks(), response.annotations);
          saveReaderMarks(nextStore);
          setMarksStore(nextStore);
        }
        setAnnotationExportStatus(
          `Đã nhập ${response.summary.imported} dấu đọc · bỏ qua ${response.summary.skipped}`,
        );
        setMarksError('');
      })
      .catch((error: unknown) => {
        setAnnotationExportStatus('');
        setMarksError(error instanceof Error ? error.message : 'Failed to import reader annotations');
      })
      .finally(() => setAnnotationImportLoading(false));
  }

  function cacheCurrentChapterOffline(): void {
    if (!apiClient || !activeBookId || !selectedChapter) {
      setOfflineCacheStatus('Không thể cache chương: thiếu kết nối API hoặc chương đang đọc.');
      return;
    }
    if (!selectedChapter.has_translation) {
      setOfflineCacheStatus('Chỉ cache offline được chương đã có bản dịch.');
      return;
    }

    setOfflineCacheLoading(true);
    setOfflineCacheStatus(`Đang tải Chương ${selectedChapter.chapter_number} để đọc offline...`);
    void cacheChapterForOffline({
      audioUrl: readerAudio.playback.streamUrl,
      bookId: activeBookId,
      chapter: selectedChapter,
      client: apiClient,
    })
      .then((summary) => {
        setOfflineCacheStatus([
          `Đã tải Chương ${selectedChapter.chapter_number} offline`,
          `${summary.assetsCached}/${summary.assetsTotal} asset`,
          `${summary.audioCached}/${summary.audioTotal} audio`,
        ].join(' · '));
        setMarksError('');
        setReaderCacheVersion((current) => current + 1);
      })
      .catch((error: unknown) => {
        setOfflineCacheStatus('');
        setMarksError(error instanceof Error ? error.message : 'Failed to cache chapter offline');
      })
      .finally(() => setOfflineCacheLoading(false));
  }

  function clearCurrentChapterOfflineCache(): void {
    if (!activeBookId || !selectedChapterId || !selectedChapter) {
      setOfflineCacheStatus('Không thể xóa cache chương: chưa chọn chương.');
      return;
    }

    setOfflineCacheLoading(true);
    setOfflineCacheStatus(`Đang xóa cache Chương ${selectedChapter.chapter_number}...`);
    void removeCachedChapterAsync(activeBookId, selectedChapterId)
      .then(() => {
        removeReaderOfflineManifestChapter(activeBookId, selectedChapterId);
        setOfflineManifest(loadReaderOfflineManifest(activeBookId));
        setOfflineCacheStatus(`Đã xóa cache offline Chương ${selectedChapter.chapter_number}.`);
        setMarksError('');
        setReaderCacheVersion((current) => current + 1);
      })
      .catch((error: unknown) => {
        setOfflineCacheStatus('');
        setMarksError(error instanceof Error ? error.message : 'Failed to clear chapter offline cache');
      })
      .finally(() => setOfflineCacheLoading(false));
  }

  function cacheCurrentBookOffline(): void {
    if (!apiClient || !activeBookId) {
      setOfflineCacheStatus('Không thể cache offline: thiếu kết nối API hoặc truyện đang đọc.');
      return;
    }

    setOfflineCacheLoading(true);
    setOfflineCacheStatus(`Đang cache offline 0/${translatedChapters.length} chương...`);
    void cacheBookForOffline({
      bookId: activeBookId,
      chapters: translatedChapters,
      client: apiClient,
      coverUrl: selectedBook?.cover_url ?? null,
      onProgress: (progress) => {
        setOfflineCacheStatus(`Đang cache offline ${progress.chaptersCached}/${progress.chaptersTotal} chương...`);
      },
    })
      .then((summary) => {
        setOfflineCacheStatus([
          `Đã cache offline ${summary.chaptersCached}/${summary.chaptersTotal} chương`,
          `${summary.assetsCached}/${summary.assetsTotal} asset`,
          `${summary.audioCached}/${summary.audioTotal} audio`,
          summary.dictionaryCached ? 'đã cache từ điển' : 'chưa cache từ điển',
        ].join(' · '));
        setMarksError('');
        setReaderCacheVersion((current) => current + 1);
      })
      .catch((error: unknown) => {
        setOfflineCacheStatus('');
        setMarksError(error instanceof Error ? error.message : 'Failed to cache book offline');
      })
      .finally(() => setOfflineCacheLoading(false));
  }

  function clearCurrentBookOfflineCache(): void {
    if (!activeBookId) {
      setOfflineCacheStatus('Không thể xóa cache offline: chưa chọn truyện.');
      return;
    }

    setOfflineCacheLoading(true);
    setOfflineCacheStatus('Đang xóa cache offline...');
    void removeCachedBookAsync(activeBookId)
      .then(() => {
        removeReaderOfflineManifest(activeBookId);
        setOfflineManifest(null);
        setOfflineCacheStatus('Đã xóa cache offline của truyện này.');
        setMarksError('');
        setReaderCacheVersion((current) => current + 1);
      })
      .catch((error: unknown) => {
        setOfflineCacheStatus('');
        setMarksError(error instanceof Error ? error.message : 'Failed to clear book offline cache');
      })
      .finally(() => setOfflineCacheLoading(false));
  }

  function loadReaderXray(mode = xraySpoilerMode): void {
    setXrayLoading(true);
    setXrayError('');

    if (!apiClient || !activeBookId) {
      setXrayLoading(false);
      setXrayError('Reader X-Ray requires an API connection.');
      return;
    }

    void apiClient.getReaderXray(activeBookId, selectedChapterId, mode)
      .then((result) => {
        setXrayData(result);
        setXrayError('');
      })
      .catch((error: unknown) => {
        setXrayError(error instanceof Error ? error.message : 'Failed to load reader X-Ray');
      })
      .finally(() => setXrayLoading(false));
  }

  function openReaderXray(): void {
    setXrayOpen(true);
    setMoreOpen(false);
    loadReaderXray();
  }

  function retryReaderXray(): void {
    loadReaderXray();
  }

  function enrichReaderXray(scope: 'chapter' | 'book' = 'chapter'): void {
    setXrayEnriching(true);
    setXrayEnrichingScope(scope);
    setXrayError('');

    if (!apiClient || !activeBookId) {
      setXrayEnriching(false);
      setXrayEnrichingScope(null);
      setXrayError('Reader X-Ray AI requires an API connection.');
      return;
    }

    void apiClient.enrichReaderXray(activeBookId, {
      chapterId: scope === 'book' ? null : selectedChapterId,
      spoilerMode: xraySpoilerMode,
    })
      .then((result) => {
        setXrayData(result);
        setXrayError('');
      })
      .catch((error: unknown) => {
        setXrayError(error instanceof Error ? error.message : 'Failed to enrich reader X-Ray');
      })
      .finally(() => {
        setXrayEnriching(false);
        setXrayEnrichingScope(null);
      });
  }

  function enrichReaderXrayBook(): void {
    enrichReaderXray('book');
  }

  function updateReaderXraySpoilerMode(mode: ReaderXraySpoilerMode): void {
    setXraySpoilerMode(mode);
    loadReaderXray(mode);
  }

  function saveResolvedReaderProgressSnapshot(snapshot: ReaderProgressSnapshot): void {
    if (!activeBookId) return;
    saveReaderProgressSnapshot(
      activeBookId,
      snapshot.chapterId,
      snapshot.position,
      snapshot.totalChapters,
      undefined,
      {
        absoluteCharOffset: snapshot.absoluteCharOffset,
        charOffset: snapshot.charOffset,
        mode: snapshot.mode,
        pageIndex: snapshot.pageIndex,
        percent: snapshot.percent,
        paragraphIndex: snapshot.paragraphIndex,
        updatedAt: snapshot.updatedAt,
      },
    );
  }

  function useRemoteReaderProgress(): void {
    if (!readerProgressConflict) return;
    saveResolvedReaderProgressSnapshot(readerProgressConflict.remote);
    setReaderSyncStatus('Sync: đã dùng tiến độ remote');
    setReaderProgressConflict(null);
    onSelectChapter(readerProgressConflict.remote.chapterId);
  }

  function useLocalReaderProgress(): void {
    if (!readerProgressConflict || !apiClient || !activeBookId) return;
    const local = readerProgressConflict.local;
    setReaderSyncStatus('Sync: đang gửi tiến độ local...');
    void apiClient.syncReaderState(activeBookId, {
      device_id: readerDeviceId,
      last_sync_at: loadReaderLastSyncAt(activeBookId),
      progress: readerProgressSnapshotToSyncProgress(local),
    })
      .then((syncedState) => {
        saveReaderLastSyncAt(activeBookId, syncedState.server_time);
        saveResolvedReaderProgressSnapshot(local);
        setReaderSyncStatus('Sync: đã dùng tiến độ local');
        setReaderProgressConflict(null);
      })
      .catch((error: unknown) => {
        setMarksError(error instanceof Error ? error.message : 'Failed to sync local reader progress');
      });
  }

  function useLocalReaderAnnotationConflict(conflict: ReaderSyncConflict): void {
    if (!apiClient || !activeBookId) return;
    const resolvedMarks = markReaderAnnotationConflictForLocalResolution(
      loadReaderMarks(),
      activeBookId,
      conflict,
    );
    const annotations = readerMarksToSyncAnnotations(resolvedMarks, activeBookId);
    if (annotations.length === 0) {
      setReaderSyncStatus('Sync: không tìm thấy dấu đọc local để gửi lại');
      return;
    }

    saveReaderMarks(resolvedMarks);
    setMarksStore(resolvedMarks);
    setReaderSyncStatus('Sync: đang dùng local cho dấu đọc...');
    void apiClient.syncReaderState(activeBookId, {
      annotations,
      device_id: readerDeviceId,
      last_sync_at: loadReaderLastSyncAt(activeBookId),
    })
      .then((syncedState) => {
        saveReaderLastSyncAt(activeBookId, syncedState.server_time);
        const next = mergeLocalAndRemoteMarks(loadReaderMarks(), syncedState.annotations);
        saveReaderMarks(next);
        setMarksStore(next);
        const annotationConflicts = syncedState.conflicts.filter((item) => item.entity === 'annotation');
        setReaderAnnotationConflicts(annotationConflicts);
        setReaderSyncStatus(
          annotationConflicts.length > 0
            ? `Sync: ${annotationConflicts.length} xung đột dấu đọc`
            : 'Sync: đã dùng local cho dấu đọc',
        );
      })
      .catch((error: unknown) => {
        setMarksError(error instanceof Error ? error.message : 'Failed to sync local reader annotation');
      });
  }

  function useServerReaderAnnotationConflict(conflict: ReaderSyncConflict): void {
    if (!activeBookId || !conflict.server_annotation) return;
    const resolvedMarks = acceptReaderAnnotationConflictFromServer(
      loadReaderMarks(),
      activeBookId,
      conflict,
    );
    saveReaderMarks(resolvedMarks);
    setMarksStore(resolvedMarks);
    setReaderAnnotationConflicts((current) => current.filter((item) => (
      item !== conflict
      && !(
        item.entity === conflict.entity
        && item.id === conflict.id
        && item.client_id === conflict.client_id
        && item.reason === conflict.reason
      )
    )));
    setReaderSyncStatus('Sync: đã dùng server cho dấu đọc');
  }

  function handleSelectionAction(action: ReaderSelectionAction): void {
    if (!readerSelection) return;
    const selection = readerSelection;
    if (action === 'highlight') {
      saveSelectionHighlight(selection);
      clearReaderSelection();
      return;
    }
    if (action === 'note') {
      openNoteEditor(selection.paragraphIndex, selection.text, {
        charEnd: selection.charEnd,
        charStart: selection.charStart,
      });
      clearReaderSelection();
      return;
    }
    if (action === 'copy') {
      const copyPromise = navigator.clipboard?.writeText(selection.text);
      if (copyPromise) {
        void copyPromise.catch(() => {
          setMarksError('Could not copy selected text');
        });
      }
      clearReaderSelection();
      return;
    }
    if (action === 'dictionary') {
      openReaderDictionary(selection);
      clearReaderSelection();
      return;
    }
    openReaderAi(selection, action === 'translate_term' ? 'translate_term' : 'explain');
    clearReaderSelection();
  }

  function scrollReaderToTop(): void {
    if (readerMainRef.current) {
      readerMainRef.current.scrollTop = 0;
      updateScrollProgress();
    }
  }

  function handlePreviousPageOrChapter(): void {
    if (isPaginatedMode && currentPage > 0) {
      setCurrentPage((page) => Math.max(0, page - 1));
      scrollReaderToTop();
      return;
    }
    if (previousChapter) handleSelectChapter(previousChapter.id);
  }

  function handleNextPageOrChapter(): void {
    if (isPaginatedMode && currentPage < pageCount - 1) {
      setCurrentPage((page) => Math.min(pageCount - 1, page + 1));
      scrollReaderToTop();
      return;
    }
    if (nextChapter) handleSelectChapter(nextChapter.id);
  }

  function handleJumpToMark(item: ReaderMarkPanelItem): void {
    setPendingParagraphJump({
      charOffset: item.charStart,
      chapterId: item.chapterId,
      paragraphIndex: item.paragraphIndex,
    });
    setMarksPanelOpen(false);
    setMoreOpen(false);
    if (item.chapterId !== selectedChapterId) {
      handleSelectChapter(item.chapterId);
    }
  }

  function handleJumpToSearchResult(result: ReaderSearchResult): void {
    setPendingParagraphJump({
      charOffset: result.char_start,
      chapterId: result.chapter_id,
      paragraphIndex: result.paragraph_index,
    });
    setReaderSearchOpen(false);
    setMoreOpen(false);
    if (result.chapter_id !== selectedChapterId) {
      handleSelectChapter(result.chapter_id);
    }
  }

  const chromeTitle: ReaderChromeTitle = {
    bookTitle: selectedBook?.title || 'Đọc truyện',
    chapterTitle: activeChapterTitle,
    cover: selectedBook && readerCoverUrl
      ? { alt: `Bìa ${selectedBook.title}`, src: readerCoverUrl }
      : undefined,
    offlineAvailable: currentChapterAvailableOffline,
  };
  const chromeNavigation: ReaderChromeNavigation = {
    bookProgressLabel,
    canGoNext,
    canGoPrevious,
    chapterCount: translatedChapters.length,
    chapterNumber: selectedChapter?.chapter_number ?? null,
    chapterPositionLabel: `${Math.max(currentPosition, 1).toLocaleString('vi-VN')} / ${Math.max(translatedChapters.length, 1).toLocaleString('vi-VN')}`,
    locationLabel,
    progressLabel,
    progressPercent,
    timeRemainingLabel,
    wordsRemainingLabel,
  };
  const chromeActions: ReaderChromeActions = {
    bookmarked,
    onExit: exitReader,
    onNext: handleNextPageOrChapter,
    onOpenSearch: () => {
      setReaderSearchOpen(true);
      setTocOpen(false);
      setMoreOpen(false);
      setChromeVisible(true);
    },
    onOpenSettings: () => setSettingsOpen(true),
    onOpenToc: () => setTocOpen(true),
    onPrevious: handlePreviousPageOrChapter,
    onToggleBookmark: toggleBookmark,
    onToggleMore: () => setMoreOpen((current) => !current),
  };
  const quickModes: ReaderQuickModeControls = {
    rawAvailable: rawContentAvailable,
    value: readerTextMode,
    onChange: setReaderTextMode,
  };
  const quickSettings: ReaderQuickSettingsControls = {
    audioAvailable: readerAudio.state.canPlay,
    audioBusy: readerAudio.state.jobLoading,
    autoScrollEnabled,
    canAutoScroll: hasReadableChapterContent,
    open: settingsOpen,
    value: readerSettings,
    onAudioAction: () => {
      if (readerAudio.state.canPlay) {
        readerAudio.actions.open();
        return;
      }
      void readerAudio.actions.startChapterJob();
    },
    onAutoScrollChange: (enabled) => {
      if (enabled && readerSettings.readingMode !== 'scroll') {
        updateReaderSettings({ readingMode: 'scroll' });
      }
      setAutoScrollEnabled(enabled);
    },
    onClose: () => setSettingsOpen(false),
    onOpen: () => setSettingsOpen(true),
    onToggleAutoScroll: () => {
      if (readerSettings.readingMode !== 'scroll') {
        updateReaderSettings({ readingMode: 'scroll' });
      }
      setAutoScrollEnabled((current) => !current);
    },
    onUpdate: updateReaderSettings,
  };

  return (
    <section
      aria-label="Trang đọc truyện"
      className="reader-view reader-immersive-view"
      data-chrome-visible={chromeVisible}
      data-fullscreen={readerSettings.fullscreen}
      data-theme={readerSettings.theme}
    >
      <h2 className="sr-only">Đọc truyện</h2>
      <ReaderChromeTop
        actions={chromeActions}
        navigation={chromeNavigation}
        title={chromeTitle}
        visible={chromeVisible}
      />

      <ReaderTextModeSwitcher modes={quickModes} visible={chromeVisible} />

      <ReaderAudioSummary audio={readerAudio} visible={chromeVisible} />

      {moreOpen ? (
        <div aria-label="Tùy chọn đọc" className="reader-more-popover" role="dialog">
          <label>
            <span>Chọn truyện</span>
            <select
              disabled={books.length === 0}
              onChange={(event) => {
                onSelectBook(Number(event.target.value));
                setMoreOpen(false);
              }}
              value={activeBookId ?? ''}
            >
              <option disabled value="">
                Chọn truyện đã dịch
              </option>
              {books.map((book) => (
                <option key={book.id} value={book.id}>
                  {book.title}
                </option>
              ))}
            </select>
          </label>
          <button
            className="reader-menu-action"
            disabled={markPanelItems.length === 0}
            onClick={() => {
              setMarksPanelOpen(true);
              setMoreOpen(false);
            }}
            type="button"
          >
            <Bookmark aria-hidden="true" size={16} />
            Mở dấu đọc
          </button>
          <button
            className="reader-menu-action"
            disabled={!selectedChapter}
            onClick={openReaderXray}
            type="button"
          >
            <ScrollText aria-hidden="true" size={16} />
            Mở X-Ray
          </button>
          <button
            className="reader-menu-action"
            disabled={!readerAudio.state.canPlay}
            onClick={() => {
              readerAudio.actions.open();
              setMoreOpen(false);
            }}
            type="button"
          >
            <Volume2 aria-hidden="true" size={16} />
            {readerAudio.state.canPlay ? 'Nghe audio chương' : 'Chưa có audio'}
          </button>
          {readerAudio.state.canPlay ? (
            <a className="reader-menu-action" href={readerAudio.playback.downloadUrl}>
              <Download aria-hidden="true" size={16} />
              Tải MP3 chương
            </a>
          ) : null}
          {!readerAudio.state.canPlay ? (
            <button
              aria-label="Tạo audio chương từ tùy chọn"
              className="reader-menu-action"
              disabled={!readerAudio.state.canStartChapterJob}
              onClick={() => { void readerAudio.actions.startChapterJob(); }}
              type="button"
            >
              <Volume2 aria-hidden="true" size={16} />
              {readerAudio.state.jobLoading ? 'Đang tạo audio...' : 'Tạo audio chương'}
            </button>
          ) : null}
          <button
            className="reader-menu-action"
            disabled={!readerAudio.state.canStartBookJob}
            onClick={() => {
              readerAudio.actions.requestBookJob();
              setMoreOpen(false);
            }}
            type="button"
          >
            <Volume2 aria-hidden="true" size={16} />
            {readerAudio.state.jobLoading ? 'Đang tạo audiobook...' : 'Tạo audiobook còn thiếu'}
          </button>
          <button
            className="reader-menu-action"
            disabled={!apiClient || !activeBookId || readerAudio.state.jobLoading}
            onClick={() => { void readerAudio.actions.downloadAudiobook(); }}
            type="button"
          >
            <Download aria-hidden="true" size={16} />
            Tải audiobook M4B
          </button>
          <div className="reader-export-format-group" aria-label="Phạm vi xuất dấu đọc" role="group">
            {readerAnnotationExportScopes.map((scope) => (
              <button
                aria-pressed={annotationExportKind === scope.kind}
                className="reader-menu-action"
                key={scope.label}
                onClick={() => setAnnotationExportKind(scope.kind)}
                type="button"
              >
                {scope.label}
              </button>
            ))}
          </div>
          <div className="reader-export-format-group" aria-label="Xuất dấu đọc" role="group">
            {readerAnnotationExportFormats.map((option) => (
              <button
                className="reader-menu-action"
                disabled={!activeBookId || markPanelItems.length === 0}
                key={option.format}
                onClick={() => exportReaderAnnotations(option.format)}
                type="button"
              >
                <Download aria-hidden="true" size={16} />
                Xuất {option.label}
              </button>
            ))}
          </div>
          <label className="reader-menu-action">
            <Upload aria-hidden="true" size={16} />
            {annotationImportLoading ? 'Đang nhập dấu đọc...' : 'Nhập JSON dấu đọc'}
            <input
              accept=".json,application/json"
              aria-label="Chọn file dấu đọc JSON"
              className="sr-only"
              disabled={!apiClient || !activeBookId || annotationImportLoading}
              onChange={(event) => {
                importReaderAnnotationsFile(event.currentTarget.files?.[0] ?? null);
                event.currentTarget.value = '';
              }}
              type="file"
            />
          </label>
          <button
            className="reader-menu-action"
            disabled={!readerSelection}
            onClick={() => {
              if (readerSelection) openReaderDictionary(readerSelection);
            }}
            type="button"
          >
            <BookOpenText aria-hidden="true" size={16} />
            Tra từ đang chọn
          </button>
          <label className="reader-menu-action">
            <Upload aria-hidden="true" size={16} />
            {dictionaryUploadLoading ? 'Đang nạp từ điển...' : 'Nạp từ điển offline'}
            <input
              accept={READER_DICTIONARY_ACCEPT}
              aria-label="Chọn file từ điển offline"
              className="sr-only"
              disabled={!apiClient || dictionaryUploadLoading}
              onChange={(event) => {
                uploadReaderDictionaryFile(event.currentTarget.files?.[0] ?? null);
                event.currentTarget.value = '';
              }}
              type="file"
            />
          </label>
          <div aria-label="Từ điển offline đã nạp" className="reader-dictionary-files">
            <div className="reader-dictionary-files-header">
              <span>Từ điển offline</span>
              <button
                className="reader-menu-action"
                disabled={!apiClient || dictionaryListLoading}
                onClick={() => setDictionaryListVersion((current) => current + 1)}
                type="button"
              >
                {dictionaryListLoading ? 'Đang tải...' : 'Làm mới'}
              </button>
            </div>
            {dictionaryListLoading ? <p>Đang tải danh sách từ điển...</p> : null}
            {!dictionaryListLoading && readerDictionaries.length === 0 ? <p>Chưa có từ điển offline.</p> : null}
            {readerDictionaries.map((dictionary) => (
              <div className="reader-dictionary-file-row" key={dictionary.filename}>
                <span>
                  <strong>{dictionary.filename}</strong>
                  <small>
                    {dictionary.entry_count.toLocaleString('vi-VN')} mục · {formatDictionarySize(dictionary.size_bytes)}
                  </small>
                </span>
                <button
                  aria-label={`Xóa từ điển ${dictionary.filename}`}
                  className="reader-icon-button"
                  disabled={dictionaryDeletingFilename === dictionary.filename}
                  onClick={() => deleteReaderDictionaryFile(dictionary.filename)}
                  title={`Xóa từ điển ${dictionary.filename}`}
                  type="button"
                >
                  <Trash2 aria-hidden="true" size={16} />
                </button>
              </div>
            ))}
          </div>
          {dictionaryUploadStatus ? <p className="reader-export-status">{dictionaryUploadStatus}</p> : null}
          <button
            className="reader-menu-action"
            disabled={!selectedChapter}
            onClick={() => {
              onOpenWorkbench();
              setMoreOpen(false);
            }}
            type="button"
          >
            <Wrench aria-hidden="true" size={16} />
            Mở bàn dịch
          </button>
          <div className="reader-marks-summary" aria-label="Dấu đọc">
            <span>{bookmarked ? 'Đã đánh dấu chương' : 'Chưa đánh dấu chương'}</span>
            <span>{chapterMarks.highlights.length} highlight</span>
            <span>{chapterMarks.notes.length} ghi chú</span>
          </div>
          {annotationExportStatus ? (
            <p className="reader-export-status">{annotationExportStatus}</p>
          ) : null}
          <p className="reader-offline-cache-warning">
            Cache offline chỉ lưu những chương/audio bạn tải thủ công và có thể vẫn còn trên thiết bị sau khi đăng xuất.
            Dùng các nút xóa cache bên dưới trước khi bàn giao thiết bị.
          </p>
          <button
            className="reader-menu-action"
            disabled={!apiClient || !activeBookId || !selectedChapter || !selectedChapter.has_translation || offlineCacheLoading}
            onClick={cacheCurrentChapterOffline}
            type="button"
          >
            <Download aria-hidden="true" size={16} />
            {offlineCacheLoading ? 'Đang tải offline...' : 'Tải chương hiện tại offline'}
          </button>
          <button
            className="reader-menu-action"
            disabled={!activeBookId || !selectedChapterId || offlineCacheLoading || !currentChapterAvailableOffline}
            onClick={clearCurrentChapterOfflineCache}
            type="button"
          >
            <Trash2 aria-hidden="true" size={16} />
            {offlineCacheLoading ? 'Đang xử lý offline...' : 'Xóa cache chương hiện tại'}
          </button>
          <button
            className="reader-menu-action"
            disabled={!apiClient || !activeBookId || offlineCacheLoading}
            onClick={cacheCurrentBookOffline}
            type="button"
          >
            <Download aria-hidden="true" size={16} />
            {offlineCacheLoading ? 'Đang cache offline...' : 'Cache toàn bộ truyện offline'}
          </button>
          <button
            className="reader-menu-action"
            disabled={!activeBookId || offlineCacheLoading || (!cacheStatus?.sizeBytes && !offlineManifest)}
            onClick={clearCurrentBookOfflineCache}
            type="button"
          >
            <Trash2 aria-hidden="true" size={16} />
            {offlineCacheLoading ? 'Đang xử lý offline...' : 'Xóa cache offline truyện này'}
          </button>
          {offlineCacheStatus ? <p className="reader-export-status">{offlineCacheStatus}</p> : null}
          {readerSyncStatus ? <p className="reader-export-status">{readerSyncStatus}</p> : null}
          {readerAnnotationConflicts.length > 0 ? (
            <div aria-label="Xung đột dấu đọc" className="reader-sync-conflicts">
              {readerAnnotationConflicts.slice(0, 5).map((conflict) => (
                <div className="reader-sync-conflict-row" key={`${conflict.entity}-${conflict.id ?? conflict.client_id ?? conflict.reason}`}>
                  <div className="reader-sync-conflict-copy">
                    <span>{readerSyncConflictLabel(conflict)}</span>
                    {readerSyncAnnotationSummary(conflict.server_annotation) ? (
                      <small>Server: {readerSyncAnnotationSummary(conflict.server_annotation)}</small>
                    ) : null}
                    {readerSyncAnnotationSummary(conflict.client_annotation) ? (
                      <small>Local: {readerSyncAnnotationSummary(conflict.client_annotation)}</small>
                    ) : null}
	                  </div>
	                  {conflict.server_annotation ? (
	                    <button
	                      className="reader-menu-action"
	                      onClick={() => useServerReaderAnnotationConflict(conflict)}
	                      type="button"
	                    >
	                      Dùng server cho {readerSyncConflictIdentity(conflict)}
	                    </button>
	                  ) : null}
	                  <button
	                    className="reader-menu-action"
	                    onClick={() => useLocalReaderAnnotationConflict(conflict)}
                    type="button"
                  >
                    Dùng local cho {readerSyncConflictIdentity(conflict)}
                  </button>
                </div>
              ))}
              {readerAnnotationConflicts.length > 5 ? (
                <span>+{readerAnnotationConflicts.length - 5} xung đột khác</span>
              ) : null}
            </div>
          ) : null}
          {readerProgressConflict ? (
            <div aria-label="Xử lý xung đột tiến độ" className="reader-export-format-group" role="group">
              <button className="reader-menu-action" onClick={useLocalReaderProgress} type="button">
                Dùng local
              </button>
              <button className="reader-menu-action" onClick={useRemoteReaderProgress} type="button">
                Dùng remote
              </button>
            </div>
          ) : null}
          {cacheStatus ? (
            <div className="reader-cache-summary" aria-label="Cache đọc offline">
              <span>Offline thủ công: chỉ chương/audio bạn đã tải</span>
              <span>{cacheStatus.currentCached ? 'Chương hiện tại đã cache' : 'Chương hiện tại chưa cache'}</span>
              <span>
                {cacheStatus.nextCached === null
                  ? 'Không có chương sau'
                  : cacheStatus.nextCached
                    ? 'Chương sau đã cache'
                    : 'Chương sau chưa cache'}
              </span>
              <span>Cache {cacheStatus.sizeLabel}</span>
              <span>
                {cacheStatus.assetCount > 0
                  ? `${cacheStatus.assetCount.toLocaleString('vi-VN')} asset ảnh · ${cacheStatus.assetSizeLabel}`
                  : 'Chưa có asset ảnh offline'}
              </span>
              <span>
                {cacheStatus.audioCount > 0
                  ? `${cacheStatus.audioCount.toLocaleString('vi-VN')} audio · ${cacheStatus.audioSizeLabel}`
                  : 'Chưa có audio offline'}
              </span>
              {offlineManifest ? (
                <>
                  <span>
                    Manifest {offlineManifest.chapterIds.length.toLocaleString('vi-VN')} chương · {offlineManifest.checksum}
                  </span>
                  <span>{offlineManifestCoverageLabel(offlineManifest)}</span>
                  <span>{offlineManifestResourcesLabel(offlineManifest)}</span>
                </>
              ) : null}
            </div>
          ) : null}
          {marksError ? <p className="reader-sync-error">{marksError}</p> : null}
        </div>
      ) : null}

      <ReaderAudioFeatureBoundary
        active={readerAudio.state.open || readerAudio.state.bulkConfirmOpen}
        audio={readerAudio}
      />

      <main
        aria-label="Vùng đọc chính"
        className="reader-immersive-main"
        onScroll={handleReaderScroll}
        ref={readerMainRef}
      >
        {isPaginatedMode && canMeasureViewportPages ? (
          <div
            aria-hidden="true"
            className="reader-mode-content reader-page-content reader-pagination-measure"
            data-font={readerSettings.fontFamily}
            data-reading-mode="paginated"
            data-theme={readerSettings.theme}
            data-width={readerSettings.width}
            onErrorCapture={measureViewportPagesNow}
            onLoadCapture={measureViewportPagesNow}
            ref={paginationMeasureRef}
            style={readerStyle}
          >
            {selectedChapter ? (
              <header className="reader-chapter-title">
                <p className="section-label">Chương {selectedChapter.chapter_number}</p>
                <h3>{selectedChapter.title}</h3>
              </header>
            ) : null}
            {hasRichContent ? (
              richBlocks.map((block) => (
                <div
                  className="reader-paragraph-block reader-rich-block"
                  data-page-break-after={block.pageBreakAfter ? 'true' : undefined}
                  data-page-break-before={block.pageBreakBefore ? 'true' : undefined}
                  data-page-break-inside-avoid={block.pageBreakInsideAvoid ? 'true' : undefined}
                  data-paragraph-index={block.index}
                  data-rich-kind={block.kind}
                  key={`measure-rich-${block.index}-${block.text.slice(0, 24)}`}
                >
                  <RichBlockMeasurementText block={block} />
                </div>
              ))
            ) : (
              paragraphs.map((paragraph, index) => (
                <div
                  className="reader-paragraph-block"
                  data-paragraph-index={index}
                  key={`measure-${index}-${paragraph.slice(0, 24)}`}
                >
                  <p className="reader-paragraph-text">{paragraph}</p>
                </div>
              ))
            )}
          </div>
        ) : null}
        {readerTextMode === 'translation' ? (
          <ReaderTextSurface
            fontFamily={readerSettings.fontFamily}
            hasRichContent={hasRichContent}
            hasTitleOnlyImportContent={hasTitleOnlyImportContent}
            highlightedParagraphs={highlightedParagraphs}
            instantMode={readerSettings.instantMode}
            isPaginatedMode={isPaginatedMode}
            notesByParagraph={notesByParagraph}
            paragraphs={paragraphs}
            readerStyle={readerStyle}
            richBlocks={richBlocks}
            selectedChapter={selectedChapter}
            textError={textError}
            textState={textState}
            theme={readerSettings.theme}
            visibleParagraphs={visibleParagraphs}
            visibleRichBlocks={visibleRichBlocks}
            width={readerSettings.width}
            onCaptureSelection={captureReaderSelection}
            onOpenNote={openNoteEditor}
            onRichMediaLoad={measureViewportPagesNow}
            onToggleChrome={() => setChromeVisible((current) => !current)}
            onToggleHighlight={toggleHighlight}
          />
        ) : null}
        {readerTextMode === 'raw' ? (
          <ReaderRawTextSurface
            fontFamily={readerSettings.fontFamily}
            paragraphs={rawParagraphs}
            readerStyle={readerStyle}
            selectedChapter={selectedChapter}
            textError={textError}
            textState={textState}
            theme={readerSettings.theme}
            width={readerSettings.width}
            onToggleChrome={() => setChromeVisible((current) => !current)}
          />
        ) : null}
        {readerTextMode === 'split' ? (
          <div className="reader-split-reading-grid">
            <ReaderRawTextSurface
              fontFamily={readerSettings.fontFamily}
              paragraphs={rawParagraphs}
              readerStyle={readerStyle}
              selectedChapter={selectedChapter}
              textError={textError}
              textState={textState}
              theme={readerSettings.theme}
              width={readerSettings.width}
              onToggleChrome={() => setChromeVisible((current) => !current)}
            />
            <ReaderTextSurface
              ariaLabel="Nội dung bản dịch tiếng Việt"
              fontFamily={readerSettings.fontFamily}
              hasRichContent={hasRichContent}
              hasTitleOnlyImportContent={hasTitleOnlyImportContent}
              highlightedParagraphs={highlightedParagraphs}
              instantMode={readerSettings.instantMode}
              isPaginatedMode={false}
              notesByParagraph={notesByParagraph}
              paragraphs={paragraphs}
              readerStyle={readerStyle}
              richBlocks={richBlocks}
              selectedChapter={selectedChapter}
              textError={textError}
              textState={textState}
              theme={readerSettings.theme}
              visibleParagraphs={paragraphs.map((paragraph, index) => ({ index, paragraph }))}
              visibleRichBlocks={richBlocks}
              width={readerSettings.width}
              onCaptureSelection={captureReaderSelection}
              onOpenNote={openNoteEditor}
              onRichMediaLoad={measureViewportPagesNow}
              onToggleChrome={() => setChromeVisible((current) => !current)}
              onToggleHighlight={toggleHighlight}
            />
          </div>
        ) : null}
        {readerTextMode === 'raw-collapsed' ? (
          <ReaderCollapsedRawSurface
            fontFamily={readerSettings.fontFamily}
            rawParagraphs={rawParagraphs}
            readerStyle={readerStyle}
            selectedChapter={selectedChapter}
            textError={textError}
            textState={textState}
            theme={readerSettings.theme}
            translatedParagraphs={paragraphs}
            width={readerSettings.width}
            onToggleChrome={() => setChromeVisible((current) => !current)}
          />
        ) : null}
        {readerTextMode === 'qa-overlay' ? (
          <div className="reader-qa-overlay-stack">
            <ReaderQaSummaryPanel
              error={readerQaError}
              report={readerQaReport}
              state={readerQaState}
            />
            <ReaderTextSurface
              ariaLabel="Bản dịch tiếng Việt với QA overlay"
              fontFamily={readerSettings.fontFamily}
              hasRichContent={hasRichContent}
              hasTitleOnlyImportContent={hasTitleOnlyImportContent}
              highlightedParagraphs={highlightedParagraphs}
              instantMode={readerSettings.instantMode}
              isPaginatedMode={false}
              notesByParagraph={notesByParagraph}
              paragraphs={paragraphs}
              qaBadgesByParagraph={qaBadgesByParagraph}
              readerStyle={readerStyle}
              richBlocks={richBlocks}
              selectedChapter={selectedChapter}
              showQaOverlay
              textError={textError}
              textState={textState}
              theme={readerSettings.theme}
              visibleParagraphs={paragraphs.map((paragraph, index) => ({ index, paragraph }))}
              visibleRichBlocks={richBlocks}
              width={readerSettings.width}
              onCaptureSelection={captureReaderSelection}
              onOpenNote={openNoteEditor}
              onRichMediaLoad={measureViewportPagesNow}
              onToggleChrome={() => setChromeVisible((current) => !current)}
              onToggleHighlight={toggleHighlight}
            />
          </div>
        ) : null}
        {hasMoreScrollParagraphs ? (
          <div aria-live="polite" className="reader-lazy-status">
            Đang nạp thêm đoạn {visibleScrollParagraphLimit.toLocaleString('vi-VN')}/{paragraphs.length.toLocaleString('vi-VN')}
          </div>
        ) : null}
      </main>

      <ReaderSelectionPopover
        anchor={readerSelection?.anchor ?? null}
        selectedText={readerSelection?.text ?? ''}
        visible={Boolean(readerSelection)}
        onAction={handleSelectionAction}
        onClose={clearReaderSelection}
      />

      <ReaderChromeBottom actions={chromeActions} navigation={chromeNavigation} visible={chromeVisible} />

      <ReaderQuickActionBar
        settings={quickSettings}
        visible={chromeVisible}
        onOpenToc={chromeActions.onOpenToc}
      />

      <ReaderTocSheet
        author={selectedBook?.author}
        chapters={chapters}
        currentChapterId={selectedChapterId}
        open={tocOpen}
        previews={tocChapterPreviews}
        title={selectedBook?.title || 'Truyện đã dịch'}
        onClose={() => setTocOpen(false)}
        onSelectChapter={handleSelectChapter}
      />

      <ReaderMarksPanel
        exportError={marksError}
        exportStatus={annotationExportStatus}
        items={markPanelItems}
        open={marksPanelOpen}
        onClose={() => setMarksPanelOpen(false)}
        onExport={(format, kind) => exportReaderAnnotations(format, kind)}
        onJump={handleJumpToMark}
      />

      <ReaderSearchPanel
        bookResults={bookSearchResults}
        currentResults={currentSearchResults}
        error={bookSearchError}
        loading={bookSearchLoading}
        open={readerSearchOpen}
        options={readerSearchOptions}
        query={readerSearchQuery}
        onClose={() => setReaderSearchOpen(false)}
        onJump={handleJumpToSearchResult}
        onOptionsChange={setReaderSearchOptions}
        onQueryChange={setReaderSearchQuery}
      />

      <ReaderDictionaryPanel
        error={dictionaryError}
        includeOnline={dictionaryIncludeOnline}
        loading={dictionaryLoading}
        open={dictionaryOpen}
        query={dictionaryQuery}
        result={dictionaryResult}
        onClose={() => setDictionaryOpen(false)}
        onIncludeOnlineChange={updateDictionaryIncludeOnline}
        onRetry={retryReaderDictionary}
      />

      <ReaderAiPanel
        cached={readerAiCached}
        error={readerAiError}
        loading={readerAiLoading}
        mode={readerAiMode}
        open={readerAiOpen}
        result={readerAiResult}
        selectedText={readerAiSelection?.text ?? ''}
        spoilerMode={readerAiSpoilerMode}
        onClose={() => setReaderAiOpen(false)}
        onRetry={retryReaderAi}
        onSpoilerModeChange={updateReaderAiSpoilerMode}
      />

      <ReaderXrayPanel
        data={xrayData}
        enriching={xrayEnriching}
        enrichingScope={xrayEnrichingScope}
        error={xrayError}
        loading={xrayLoading}
        open={xrayOpen}
        spoilerMode={xraySpoilerMode}
        onClose={() => setXrayOpen(false)}
        onEnrich={() => enrichReaderXray('chapter')}
        onEnrichBook={enrichReaderXrayBook}
        onRetry={retryReaderXray}
        onSpoilerModeChange={updateReaderXraySpoilerMode}
      />

      <ReaderQuickSettingsSheet modes={quickModes} settings={quickSettings} />

      {noteDraft ? (
        <div className="reader-sheet-backdrop">
          <section aria-label="Ghi chú đoạn đọc" className="reader-note-sheet" role="dialog">
            <header className="reader-sheet-header">
              <div>
                <p className="section-label">Note</p>
                <h2>Ghi chú đoạn đọc</h2>
              </div>
              <button
                aria-label="Đóng ghi chú"
                className="reader-icon-button"
                onClick={() => setNoteDraft(null)}
                title="Đóng ghi chú"
                type="button"
              >
                <X aria-hidden="true" size={22} />
              </button>
            </header>
            <blockquote>{noteDraft.text}</blockquote>
            <label className="reader-note-field">
              <span>Nội dung ghi chú</span>
              <textarea
                aria-label="Nội dung ghi chú"
                autoFocus
                onChange={(event) => setNoteDraft((current) => (
                  current ? { ...current, value: event.target.value } : current
                ))}
                rows={5}
                value={noteDraft.value}
              />
            </label>
            <div className="reader-note-actions">
              <button
                className="secondary-action"
                onClick={() => setNoteDraft(null)}
                type="button"
              >
                Hủy
              </button>
              <button
                className="primary-action"
                onClick={saveNoteDraft}
                type="button"
              >
                Lưu ghi chú
              </button>
            </div>
          </section>
        </div>
      ) : null}
    </section>
  );
}
