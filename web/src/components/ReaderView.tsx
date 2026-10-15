import {
  Bookmark,
  BookOpenText,
  Download,
  ScrollText,
  Trash2,
  Upload,
  Volume2,
  Wrench,
  X,
} from 'lucide-react';
import { lazy, Suspense, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import type { ApiClient } from '../api/client';
import type {
  Chapter,
  QaReport,
  ReaderAnnotationExportFormat,
  ReaderSearchResult,
  ReaderSyncConflict,
  TranslatedBookSummary
} from '../api/types';
import { useDialogFocusLifecycle } from '../hooks/useDialogFocusLifecycle';
import {
  absoluteCharOffsetForParagraph,
  bookProgressPercent,
  collapsedRangeRectAtTextOffset,
  countWords,
  estimateReadingMinutes,
  fallbackParagraphPages,
  findParagraphElement,
  getCurrentParagraphIndex,
  pageBreakOffsetsForViewportSlices,
  pageIndexForParagraph,
  paginateParagraphsByViewport,
  paragraphLocation,
  paragraphTextElement,
  readerTextLocationFromViewportAnchor,
  textLength,
  textNodeAtOffset,
  textOffsetFromPointInNode,
  textOffsetWithinNode,
  wordsRemainingForProgress,
  type ReaderFallbackPageHint,
  type ReaderViewportPage,
} from '../state/readerLocation';
import { loadReaderProgressSnapshot, type ReaderProgressSnapshot } from '../state/readerProgress';
import { buildReaderProgressTextAnchor, resolveReaderProgressTextAnchor } from '../state/readerProgressAnchor';
import {
  extractReaderRichBlocks,
  richBlockNeedsTextMirror,
  sliceReaderRichBlockHtml,
  type ReaderRichBlock
} from '../state/readerRichContent';
import { type LoadState } from '../state/types';
import type { ReaderBootstrap } from '../state/useReaderChapterData';
import ReaderAiPanel from './reader/ReaderAiPanel';
import { readerAnnotationExportScopes } from './reader/readerAnnotationTransfer';
import ReaderAudioSummary from './reader/ReaderAudioSummary';
import {
  ReaderChromeBottom,
  ReaderChromeTop,
  type ReaderChromeActions,
  type ReaderChromeNavigation,
  type ReaderChromeTitle,
} from './reader/ReaderChrome';
import { fallbackReaderCover, formatDictionarySize, formatReadingTime, formatReadingTimeRemaining, formatWordCount, formatWordsRemaining, offlineManifestCoverageLabel, offlineManifestResourcesLabel, sortChapters, translationLooksTitleOnly } from './reader/readerContentLabels';
import ReaderDictionaryPanel from './reader/ReaderDictionaryPanel';
import ReaderMarksPanel, { type ReaderMarkPanelItem } from './reader/ReaderMarksPanel';
import {
  ReaderQuickActionBar,
  ReaderQuickSettingsSheet,
  ReaderTextModeSwitcher,
  type ReaderQuickModeControls,
  type ReaderQuickSettingsControls,
} from './reader/ReaderQuickControls';
import ReaderSearchPanel from './reader/ReaderSearchPanel';
import ReaderSelectionPopover, { type ReaderSelectionAction } from './reader/ReaderSelectionPopover';
import {
  loadReaderSettings,
  loadReaderTextMode,
  saveReaderSettings,
  saveReaderTextMode,
} from './reader/readerSettings';
import {
  deriveReaderTextModeCapabilities,
  resolveReaderTextMode,
} from './reader/readerTextModeCapabilities';
import ReaderTextSurface, { type ReaderParagraphQaBadge, type ReaderVisibleRichBlock } from './reader/ReaderTextSurface';
import ReaderTocSheet, { type TocChapterPreview } from './reader/ReaderTocSheet';
import ReaderXrayPanel from './reader/ReaderXrayPanel';
import type {
  ReaderFontFamily,
  ReaderSelectionState,
  ReaderSettings,
  ReaderTextMode,
  ReaderTheme,
  ReaderWidth,
} from './reader/types';
import { useReaderAi } from './reader/useReaderAi';
import { useReaderAudio } from './reader/useReaderAudio';
import { useReaderDictionary } from './reader/useReaderDictionary';
import { useReaderMarks } from './reader/useReaderMarks';
import { useReaderOfflineCache } from './reader/useReaderOfflineCache';
import { useReaderSearch } from './reader/useReaderSearch';
import { useReaderSelection } from './reader/useReaderSelection';
import { useReaderXray } from './reader/useReaderXray';

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
  readerBootstrap?: ReaderBootstrap | null;
  apiClient?: ReaderApiClient;
  books: TranslatedBookSummary[];
  chapters: Chapter[];
  activeBookId: number | null;
  selectedChapter: Chapter | null;
  selectedChapterId: number | null;
  contentHtml: string;
  qaError: string;
  qaReport: QaReport | null;
  qaState: LoadState;
  sourceText: string;
  sourceError?: string;
  onLoadSource?(): Promise<void>;
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

const FALLBACK_PARAGRAPHS_PER_PAGE = 4;
const INITIAL_SCROLL_PARAGRAPH_LIMIT = 32;
const SCROLL_PARAGRAPH_CHUNK_SIZE = 32;
const PAGINATION_MEASURE_CHUNK_SIZE = 50;
const LAZY_SCROLL_DISTANCE_PX = 900;
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

      {textState === 'loading' ? <p className="reader-empty-state">Đang tải raw/source...</p> : null}
      {textError ? (
        <p className="status-error" role="alert">
          {textError}
        </p>
      ) : null}
      {selectedChapter && textState !== 'loading' && paragraphs.length === 0 && !textError ? (
        <p className="reader-empty-state">Chưa có raw/source text cho chương này.</p>
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

      {textState === 'loading' ? <p className="reader-empty-state">Đang tải bản đọc...</p> : null}
      {textError ? (
        <p className="status-error" role="alert">
          {textError}
        </p>
      ) : null}
      {selectedChapter && textState !== 'loading' && translatedParagraphs.length === 0 && !textError ? (
        <p className="reader-empty-state">Chưa có bản dịch tiếng Việt.</p>
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

export default function ReaderView({
  readerBootstrap,
  apiClient,
  books,
  chapters,
  activeBookId,
  selectedChapter,
  selectedChapterId,
  contentHtml,
  qaError,
  qaReport,
  qaState,
  sourceText,
  sourceError,
  onLoadSource,
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
  const [readerSettings, setReaderSettings] = useState<ReaderSettings>(() => loadReaderSettings());
  const [readerTextMode, setReaderTextModeState] = useState<ReaderTextMode>(() => loadReaderTextMode());
  useEffect(() => {
    if (readerTextMode === 'raw' || readerTextMode === 'split' || readerTextMode === 'raw-collapsed') {
      void onLoadSource?.();
    }
  }, [onLoadSource, readerTextMode, selectedChapterId]);
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
  const [moreOpen, setMoreOpen] = useState(false);
  const moreDialogRef = useDialogFocusLifecycle<HTMLDivElement>(moreOpen, () => setMoreOpen(false));
  const [marksPanelOpen, setMarksPanelOpen] = useState(false);
  const [currentPage, setCurrentPage] = useState(0);
  const [autoScrollEnabled, setAutoScrollEnabled] = useState(false);
  const [renderedParagraphLimit, setRenderedParagraphLimit] = useState(INITIAL_SCROLL_PARAGRAPH_LIMIT);
  const [viewportPages, setViewportPages] = useState<ReaderViewportPage[]>([]);
  const [paginationWindowStart, setPaginationWindowStart] = useState(0);
  const paginationWindowStartRef = useRef(0);
  const measuredPagesRef = useRef<ReaderViewportPage[]>([]);
  const cancelPaginationAdvanceRef = useRef<(() => void) | null>(null);
  const [pendingParagraphJump, setPendingParagraphJump] = useState<{
    charOffset?: number;
    chapterId: number;
    paragraphIndex: number;
  } | null>(null);
  const {
    dictionaryOpen, dictionaryQuery, dictionaryIncludeOnline, dictionaryResult,
    dictionaryLoading, dictionaryError, readerDictionaries, dictionaryListLoading,
    dictionaryDeletingFilename, dictionaryUploadLoading, dictionaryUploadStatus,
    openReaderDictionary: lookupReaderDictionary, retryReaderDictionary,
    updateDictionaryIncludeOnline, uploadReaderDictionaryFile, deleteReaderDictionaryFile,
    closeDictionary, refreshDictionaries,
  } = useReaderDictionary({ apiClient, activeBookId, selectedChapterId, moreOpen });
  const {
    readerAiOpen, readerAiMode, readerAiSelection, readerAiSpoilerMode, readerAiResult,
    readerAiLoading, readerAiError, readerAiCached, openReaderAi, retryReaderAi,
    updateReaderAiSpoilerMode, closeReaderAi,
  } = useReaderAi({ apiClient, activeBookId, selectedChapterId });
  const {
    xrayOpen, xraySpoilerMode, xrayData, xrayLoading, xrayEnriching,
    xrayEnrichingScope, xrayError, openReaderXray: showReaderXray, retryReaderXray,
    enrichReaderXray, enrichReaderXrayBook, updateReaderXraySpoilerMode, closeReaderXray,
  } = useReaderXray({ apiClient, activeBookId, selectedChapterId });

  function openReaderDictionary(selection: ReaderSelectionState): void {
    setMoreOpen(false);
    lookupReaderDictionary(selection);
  }

  function openReaderXray(): void {
    setMoreOpen(false);
    showReaderXray();
  }

  const translatedChapters = useMemo(
    () => sortChapters(chapters.filter((chapter) => chapter.has_translation)),
    [chapters],
  );
  const chapterIndexes = useMemo(
    () => new Map(translatedChapters.map((chapter, index) => [chapter.id, index])),
    [translatedChapters],
  );
  const selectedBook = books.find((book) => book.id === activeBookId);
  const {
    chapterMarks, bookmarked, highlightedParagraphs, notesByParagraph, markPanelItems,
    noteDraft, annotationExportStatus, annotationImportLoading, annotationExportKind,
    toggleBookmark, toggleHighlight, saveSelectionHighlight, openNoteEditor, saveNoteDraft,
    exportReaderAnnotations, importReaderAnnotationsFile, setAnnotationExportKind,
    closeNoteEditor, updateNoteDraftValue, marksError, setMarksError,
    readerSyncStatus, readerAnnotationConflicts, readerProgressConflict,
    consumeInitialProgressSave, persistReaderProgress, useRemoteReaderProgress,
    useLocalReaderProgress, useLocalReaderAnnotationConflict, useServerReaderAnnotationConflict,
  } = useReaderMarks({
    apiClient, activeBookId, selectedChapterId, selectedChapter, chapters,
    bookTitle: selectedBook?.title ?? 'reader', readerBootstrap, onSelectChapter,
    onDownload: triggerBrowserDownload,
  });
  const selectedIndex = translatedChapters.findIndex((chapter) => chapter.id === selectedChapterId);
  const currentPosition = selectedIndex >= 0 ? selectedIndex + 1 : 0;
  const previousChapter = selectedIndex > 0 ? translatedChapters[selectedIndex - 1] : null;
  const nextChapter = selectedIndex >= 0 && selectedIndex < translatedChapters.length - 1
    ? translatedChapters[selectedIndex + 1]
    : null;
  const backendCoverUrl = selectedBook?.cover_url?.trim() ?? '';
  const fallbackCoverUrl = fallbackReaderCover(selectedBook);
  const liveCoverUrl = fallbackCoverUrl || backendCoverUrl;
  const readerOfflineCache = useReaderOfflineCache({
    apiClient,
    audioUrl: apiClient && activeBookId && selectedChapterId && selectedChapter?.audio_status !== 'stale' && selectedChapter?.audio_version
      ? apiClient.chapterAudioUrl(activeBookId, selectedChapterId, selectedChapter.audio_version) : '',
    bookId: activeBookId,
    chapters: translatedChapters,
    coverUrl: fallbackCoverUrl ? '' : backendCoverUrl,
    liveCoverUrl,
    nextChapterId: nextChapter?.id ?? null,
    onError: setMarksError,
    selectedChapter,
    selectedChapterId,
  });
  const currentCachedChapter = readerOfflineCache.cachedChapter?.bookId === activeBookId
    && readerOfflineCache.cachedChapter.chapterId === selectedChapterId
    ? readerOfflineCache.cachedChapter
    : null;
  const useCachedChapterContent = Boolean(
    currentCachedChapter
    && (textState === 'loading' || textState === 'error'),
  );
  const readerTranslationText = useCachedChapterContent
    ? currentCachedChapter?.text ?? ''
    : translationText;
  const readerContentHtml = useCachedChapterContent
    ? currentCachedChapter?.html ?? ''
    : contentHtml;
  const readerSourceText = useCachedChapterContent
    ? currentCachedChapter?.sourceText ?? ''
    : sourceText;
  const readerTextState: LoadState = useCachedChapterContent ? 'ready' : textState;
  const readerTextError = useCachedChapterContent ? '' : textError;
  const selectAudioChapter = useCallback((chapterId: number) => {
    onSelectChapter(chapterId);
    setTocOpen(false);
    setReaderSearchOpen(false);
    setMoreOpen(false);
    setMarksPanelOpen(false);
    dismissReaderSelection();
    closeDictionary();
    closeReaderXray();
  }, [onSelectChapter]);
  const readerAudio = useReaderAudio({
    activeBookId,
    allowAutomaticAudioCache: readerOfflineCache.allowAutomaticAudioCache,
    apiClient,
    cachedAudioLoading: readerOfflineCache.metadataLoading,
    cachedAudioUrl: readerOfflineCache.cachedAudioUrl,
    cacheAudio: readerOfflineCache.cacheAudio,
    chapters,
    onDownload: triggerBrowserDownload,
    onError: setMarksError,
    onSelectChapter: selectAudioChapter,
    qaReport,
    selectedChapter,
    selectedChapterId,
    translationText: readerTranslationText,
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
      if (event.defaultPrevented) return;
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
  const {
    cacheStatus,
    currentAvailable: currentChapterAvailableOffline,
    loading: offlineCacheLoading,
    manifest: offlineManifest,
    message: offlineCacheStatus,
    cacheCurrentBook: cacheCurrentBookOffline,
    cacheCurrentChapter,
    removeCurrentBook: clearCurrentBookOfflineCache,
    removeCurrentChapter: clearCurrentChapterOfflineCache,
  } = readerOfflineCache;
  const cacheCurrentChapterOffline = () => cacheCurrentChapter(readerAudio.playback.streamUrl);
  const readerCoverUrl = readerOfflineCache.coverUrl;
  const paragraphs = useMemo(() => splitParagraphs(readerTranslationText), [readerTranslationText]);
  const rawText = readerSourceText.trim();
  const richBlocks = useMemo(() => extractReaderRichBlocks(readerContentHtml), [readerContentHtml]);
  const rawParagraphs = useMemo(() => splitParagraphs(rawText), [rawText]);
  const textModeCapabilities = {
    ...deriveReaderTextModeCapabilities({
    contentHtml: readerContentHtml,
    sourceText: readerSourceText,
    translationText: readerTranslationText,
    }),
    ...(onLoadSource ? {
      rawAvailable: true,
      rawCollapsedAvailable: Boolean(selectedChapter?.has_translation),
      splitAvailable: Boolean(selectedChapter?.has_translation),
      translationAvailable: Boolean(selectedChapter?.has_translation || readerTranslationText || readerContentHtml),
    } : {}),
  };
  const richContentAvailable = readerContentHtml.trim().length > 0;
  const hasRichContent = richContentAvailable;
  const progressTextBlocks = useMemo(
    () => (hasRichContent ? richBlocks.map((block) => block.text) : paragraphs),
    [hasRichContent, paragraphs, richBlocks],
  );
  const paginatedBlockCount = hasRichContent ? richBlocks.length : paragraphs.length;
  const paginationWindowEnd = Math.min(paginatedBlockCount, paginationWindowStart + PAGINATION_MEASURE_CHUNK_SIZE);
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
  const lazyScrollEnabled = (readerTextMode === 'translation' || readerTextMode === 'qa-overlay')
    && !isPaginatedMode
    && !hasRichContent
    && paragraphs.length > INITIAL_SCROLL_PARAGRAPH_LIMIT;
  const visibleScrollParagraphLimit = lazyScrollEnabled
    ? Math.min(paragraphs.length, renderedParagraphLimit)
    : paragraphs.length;
  const hasMoreScrollParagraphs = lazyScrollEnabled && visibleScrollParagraphLimit < paragraphs.length;
  const currentViewportPage = activeViewportPages[clampPageIndex(currentPage, pageCount)] ?? { startIndex: 0, endIndex: 0 };
  const currentPageStart = isPaginatedMode ? currentViewportPage.startIndex : 0;
  const currentPageEnd = isPaginatedMode ? currentViewportPage.endIndex : visibleScrollParagraphLimit;
  const visibleParagraphs = paragraphs
    .slice(currentPageStart, currentPageEnd)
    .map((paragraph, offset) => {
      const index = currentPageStart + offset;
      const range = isPaginatedMode ? pageCharRangeForBlock(currentViewportPage, index, paragraph.length) : null;
      return {
        charEnd: range?.charEnd,
        charStart: range?.charStart,
        index,
        paragraph: range ? paragraph.slice(range.charStart, range.charEnd) : paragraph,
      };
    });
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
  const selectedChapterStatText = readerTranslationText.trim() || rawText;
  const hasReadableChapterContent = paragraphs.length > 0 || hasRichContent;
  const hasTitleOnlyImportContent = useMemo(() => Boolean(
    selectedChapter
      && translationLooksTitleOnly(readerTranslationText, selectedChapter)
      && (!hasRichContent || !hasReadableRichText),
  ), [selectedChapter, readerTranslationText, hasRichContent, hasReadableRichText]);
  const compatibleReaderTextMode = resolveReaderTextMode(readerTextMode, textModeCapabilities);
  useEffect(() => {
    if (compatibleReaderTextMode !== readerTextMode) setReaderTextMode(compatibleReaderTextMode);
  }, [compatibleReaderTextMode, readerTextMode, setReaderTextMode]);

  const readerStyle = {
    '--reader-character-spacing': `${readerSettings.characterSpacing}px`,
    '--reader-font-size': `${readerSettings.fontSize}px`,
    '--reader-font-weight': String(readerSettings.fontWeight),
    '--reader-line-height': String(readerSettings.lineHeight),
    '--reader-margin-scale': String(readerSettings.marginScale),
    '--reader-paragraph-spacing': `${readerSettings.paragraphSpacing}em`,
  } as CSSProperties;
  const qaBadgesByParagraph = useMemo(
    () => buildReaderQaBadges(qaReport, paragraphs, rawParagraphs),
    [paragraphs, qaReport, rawParagraphs],
  );
  const { readerSelection, captureReaderSelection, clearReaderSelection, dismissReaderSelection }
    = useReaderSelection(readerMainRef, progressTextBlocks);
  const {
    readerSearchOpen, setReaderSearchOpen, readerSearchQuery, setReaderSearchQuery,
    readerSearchOptions, setReaderSearchOptions, bookSearchResults,
    bookSearchLoading, bookSearchError, currentSearchResults,
  } = useReaderSearch({ apiClient, activeBookId, selectedChapter, chapterMarks, progressTextBlocks });
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
  const currentChapterWordCount = useMemo(() => countWords(selectedChapterStatText), [selectedChapterStatText]);
  const currentChapterRemainingWords = wordsRemainingForProgress(currentChapterWordCount, chapterProgressPercent);
  const bookProgressLabel = `Sách ${bookPercent}%`;
  const wordsRemainingLabel = formatWordsRemaining(currentChapterRemainingWords);
  const timeRemainingLabel = formatReadingTimeRemaining(estimateReadingMinutes(currentChapterRemainingWords));
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
      const wordCount = chapter.id === selectedChapterId ? currentChapterWordCount : previewText ? countWords(previewText) : 0;
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
    currentChapterWordCount,
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

  const measureViewportPagesNow = useCallback(() => {
    if (!isPaginatedMode || paginatedBlockCount === 0 || !canMeasureViewportPages) return;
    const start = paginationWindowStartRef.current;
    const surface = paginationMeasureRef.current;
    if (Number(surface?.querySelector<HTMLElement>('[data-paragraph-index]')?.dataset.paragraphIndex) !== start) return;
    cancelPaginationAdvanceRef.current?.();
    const chunkPages = measuredViewportPages(
      readerMainRef.current,
      surface,
      paginatedBlockCount,
    );
    if (!chunkPages.length) return;
    // Carry the last page into the next window so chunk boundaries never cut a page.
    const nextMeasuredPages = [...measuredPagesRef.current.filter((page) => page.endIndex <= start), ...chunkPages];
    measuredPagesRef.current = nextMeasuredPages;
    const end = Math.min(paginatedBlockCount, start + PAGINATION_MEASURE_CHUNK_SIZE);
    const tailPages = end < paginatedBlockCount
      ? fallbackParagraphPages(paginatedBlockCount - end, FALLBACK_PARAGRAPHS_PER_PAGE, fallbackPageHints.slice(end))
        .map((page) => ({ startIndex: page.startIndex + end, endIndex: page.endIndex + end }))
      : [];
    const nextPages = [...nextMeasuredPages, ...tailPages];
    setViewportPages((current) => (sameViewportPages(current, nextPages) ? current : nextPages));
    const imagesPending = Array.from(surface?.querySelectorAll<HTMLImageElement>('img') ?? [])
      .some((image) => !image.complete);
    if (end < paginatedBlockCount && !imagesPending && document.fonts?.status !== 'loading') {
      const carryStart = chunkPages[chunkPages.length - 1].startIndex;
      cancelPaginationAdvanceRef.current = scheduleReaderIdle(() => {
        const nextStart = carryStart > start ? carryStart : end;
        paginationWindowStartRef.current = nextStart;
        setPaginationWindowStart(nextStart);
      });
    }
  }, [canMeasureViewportPages, fallbackPageHints, isPaginatedMode, paginatedBlockCount]);

  useLayoutEffect(() => {
    const resetMeasurement = () => {
      cancelPaginationAdvanceRef.current?.();
      measuredPagesRef.current = [];
      paginationWindowStartRef.current = 0;
      setPaginationWindowStart(0);
      setViewportPages([]);
    };
    resetMeasurement();
    if (!isPaginatedMode || paginatedBlockCount === 0 || !canMeasureViewportPages) {
      return undefined;
    }

    let cancelRestore = scheduleReaderRestore(measureViewportPagesNow);
    const invalidateMeasurement = () => {
      resetMeasurement();
      cancelRestore();
      cancelRestore = scheduleReaderRestore(measureViewportPagesNow);
    };
    window.addEventListener('resize', invalidateMeasurement);
    document.fonts?.addEventListener('loadingdone', invalidateMeasurement);
    document.fonts?.addEventListener('loadingerror', invalidateMeasurement);
    const ResizeObserverConstructor = window.ResizeObserver;
    const observer = ResizeObserverConstructor ? new ResizeObserverConstructor(invalidateMeasurement) : null;
    if (observer) {
      if (readerMainRef.current) observer.observe(readerMainRef.current);
    }

    return () => {
      cancelRestore();
      cancelPaginationAdvanceRef.current?.();
      window.removeEventListener('resize', invalidateMeasurement);
      document.fonts?.removeEventListener('loadingdone', invalidateMeasurement);
      document.fonts?.removeEventListener('loadingerror', invalidateMeasurement);
      observer?.disconnect();
    };
  }, [
    isPaginatedMode,
    canMeasureViewportPages,
    readerContentHtml,
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
    readerTranslationText,
  ]);

  useLayoutEffect(() => scheduleReaderRestore(measureViewportPagesNow), [measureViewportPagesNow, paginationWindowStart]);

  useEffect(() => {
    setRenderedParagraphLimit(INITIAL_SCROLL_PARAGRAPH_LIMIT);
  }, [readerContentHtml, readerSettings.readingMode, selectedChapterId, readerTranslationText]);

  useEffect(() => {
    if (!hasMoreScrollParagraphs) return;
    return scheduleReaderIdle(() => expandRenderedParagraphs());
  }, [expandRenderedParagraphs, hasMoreScrollParagraphs, renderedParagraphLimit]);

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
    readerContentHtml,
    expandRenderedParagraphs,
    isPaginatedMode,
    pageCount,
    progressTextBlocks,
    readerSettings.readingMode,
    selectedChapterId,
    readerTranslationText,
    updateScrollProgress,
    visibleScrollParagraphLimit,
  ]);

  useEffect(() => {
    setCurrentPage((page) => Math.min(page, pageCount - 1));
  }, [pageCount]);

  useEffect(() => {
    if (!activeBookId || !selectedChapterId || restorePendingRef.current) return;

    const mode = isPaginatedMode ? 'paginated' : 'scroll';
    if (consumeInitialProgressSave(activeBookId, selectedChapterId)) return;
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

    persistReaderProgress(activeBookId, progressSnapshot);
  }, [
    activeBookId,
    consumeInitialProgressSave,
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
    persistReaderProgress,
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
    readerContentHtml,
    currentPage,
    expandRenderedParagraphs,
    isPaginatedMode,
    pageCount,
    pendingParagraphJump,
    progressTextBlocks,
    selectedChapterId,
    readerTranslationText,
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

  function handleSelectChapter(chapterId: number, options: { keepAudioOpen?: boolean } = {}): void {
    onSelectChapter(chapterId);
    setTocOpen(false);
    setReaderSearchOpen(false);
    setMoreOpen(false);
    setMarksPanelOpen(false);
    dismissReaderSelection();
    closeDictionary();
    if (!options.keepAudioOpen) {
      readerAudio.actions.close();
    }
    closeReaderXray();
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
    rawAvailable: textModeCapabilities.rawAvailable,
    rawCollapsedAvailable: textModeCapabilities.rawCollapsedAvailable,
    splitAvailable: textModeCapabilities.splitAvailable,
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
      {sourceError && readerTextMode !== 'translation' ? <p role="alert">{sourceError}</p> : null}

      <ReaderAudioSummary audio={readerAudio} visible={chromeVisible} />
      {readerAudio.state.partialExportAvailable ? (
        <button className="reader-menu-action" onClick={() => { void readerAudio.actions.downloadAudiobook(true); }} type="button">
          Tải M4B chỉ các chương đã có audio
        </button>
      ) : null}

      {moreOpen ? (
        <div
          className="reader-more-backdrop"
          onClick={(event) => {
            if (event.currentTarget === event.target) setMoreOpen(false);
          }}
          role="presentation"
        >
        <div
          aria-label="Tùy chọn đọc"
          aria-modal="true"
          className="reader-more-popover"
          ref={moreDialogRef}
          role="dialog"
          tabIndex={-1}
        >
          <fieldset className="reader-tools-group">
          <legend>Đọc truyện</legend>
          <label>
            <span>Chọn truyện</span>
            <select
              data-dialog-initial-focus
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
          </fieldset>
          <fieldset className="reader-tools-group">
          <legend>Nghe và tải audio</legend>
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
          </fieldset>
          <fieldset className="reader-tools-group">
          <legend>Dấu đọc và ghi chú</legend>
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
          </fieldset>
          <fieldset className="reader-tools-group">
          <legend>Từ điển</legend>
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
                onClick={refreshDictionaries}
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
          </fieldset>
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
          <fieldset className="reader-tools-group">
          <legend>Lưu ngoại tuyến và đồng bộ</legend>
          <p className="reader-offline-cache-warning">
            Cache offline chỉ lưu những chương/audio bạn tải thủ công. Novel-TNN sẽ xóa nội dung Reader riêng tư
            khi bạn đăng xuất; bạn cũng có thể dùng các nút bên dưới để xóa sớm hơn.
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
          </fieldset>
        </div>
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
              richBlocks.slice(paginationWindowStart, paginationWindowEnd).map((block) => (
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
              paragraphs.slice(paginationWindowStart, paginationWindowEnd).map((paragraph, offset) => (
                <div
                  className="reader-paragraph-block"
                  data-paragraph-index={paginationWindowStart + offset}
                  key={`measure-${paginationWindowStart + offset}-${paragraph.slice(0, 24)}`}
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
            textError={readerTextError}
            textState={readerTextState}
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
            textError={readerTextError}
            textState={readerTextState}
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
              textError={readerTextError}
              textState={readerTextState}
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
              textError={readerTextError}
              textState={readerTextState}
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
            textError={readerTextError}
            textState={readerTextState}
            theme={readerSettings.theme}
            translatedParagraphs={paragraphs}
            width={readerSettings.width}
            onToggleChrome={() => setChromeVisible((current) => !current)}
          />
        ) : null}
        {readerTextMode === 'qa-overlay' ? (
          <div className="reader-qa-overlay-stack">
            <ReaderQaSummaryPanel
              error={qaError}
              report={qaReport}
              state={qaState}
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
              textError={readerTextError}
              textState={readerTextState}
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
        onClose={() => closeDictionary()}
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
        onClose={() => closeReaderAi()}
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
        onClose={() => closeReaderXray()}
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
                onClick={() => closeNoteEditor()}
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
                onChange={(event) => updateNoteDraftValue(event.target.value)}
                rows={5}
                value={noteDraft.value}
              />
            </label>
            <div className="reader-note-actions">
              <button
                className="secondary-action"
                onClick={() => closeNoteEditor()}
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
