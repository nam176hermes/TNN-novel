import type { CSSProperties } from 'react';
import { Highlighter, StickyNote } from 'lucide-react';
import type { Chapter } from '../../api/types';
import { richBlockNeedsTextMirror, type ReaderRichBlock } from '../../state/readerRichContent';
import type { LoadState } from '../../state/types';
import type { ReaderFontFamily, ReaderTheme, ReaderWidth } from '../ReaderView';

export type ReaderVisibleRange = {
  charEnd?: number;
  charStart?: number;
};

export type ReaderVisibleParagraph = ReaderVisibleRange & {
  index: number;
  paragraph: string;
};

export type ReaderVisibleRichBlock = ReaderRichBlock & ReaderVisibleRange;

export type ReaderTextSurfaceProps = {
  ariaLabel?: string;
  fontFamily: ReaderFontFamily;
  hasRichContent: boolean;
  hasTitleOnlyImportContent?: boolean;
  highlightedParagraphs: Set<number>;
  instantMode: boolean;
  isPaginatedMode: boolean;
  notesByParagraph: Map<number, { note: string }>;
  paragraphs: string[];
  readerStyle: CSSProperties;
  richBlocks: ReaderRichBlock[];
  selectedChapter: Chapter | null;
  textError: string;
  textState: LoadState;
  theme: ReaderTheme;
  visibleParagraphs: ReaderVisibleParagraph[];
  visibleRichBlocks: ReaderVisibleRichBlock[];
  width: ReaderWidth;
  onCaptureSelection?(): void;
  onOpenNote(paragraphIndex: number, text: string, range?: { charEnd: number; charStart: number }): void;
  onRichMediaLoad?(): void;
  onToggleChrome(): void;
  onToggleHighlight(paragraphIndex: number, text: string, range?: { charEnd: number; charStart: number }): void;
};

function visibleRange(item: ReaderVisibleRange): { charEnd: number; charStart: number } | undefined {
  if (
    Number.isInteger(item.charStart)
    && Number.isInteger(item.charEnd)
    && (item.charStart ?? 0) >= 0
    && (item.charEnd ?? 0) >= (item.charStart ?? 0)
  ) {
    return {
      charEnd: item.charEnd ?? 0,
      charStart: item.charStart ?? 0,
    };
  }
  return undefined;
}

function visibleRangeFromRichBlock(block: ReaderRichBlock): ReaderVisibleRange {
  const visibleBlock = block as ReaderVisibleRichBlock;
  return {
    charEnd: visibleBlock.charEnd,
    charStart: visibleBlock.charStart,
  };
}

function RichBlockText({ block }: { block: ReaderRichBlock }) {
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

export default function ReaderTextSurface({
  ariaLabel = 'Nội dung đọc tiếng Việt',
  fontFamily,
  hasRichContent,
  hasTitleOnlyImportContent = false,
  highlightedParagraphs,
  instantMode,
  isPaginatedMode,
  notesByParagraph,
  paragraphs,
  readerStyle,
  richBlocks,
  selectedChapter,
  textError,
  textState,
  theme,
  visibleParagraphs,
  visibleRichBlocks,
  width,
  onCaptureSelection,
  onOpenNote,
  onRichMediaLoad,
  onToggleChrome,
  onToggleHighlight,
	}: ReaderTextSurfaceProps) {
	  function handleChromeToggle(): void {
	    if (window.getSelection()?.toString().trim()) return;
	    onToggleChrome();
	  }

	  function handleOpenNote(paragraphIndex: number, text: string, rangeItem: ReaderVisibleRange): void {
	    const range = visibleRange(rangeItem);
	    if (range) {
	      onOpenNote(paragraphIndex, text, range);
	      return;
	    }
	    onOpenNote(paragraphIndex, text);
	  }

	  function handleToggleHighlight(paragraphIndex: number, text: string, rangeItem: ReaderVisibleRange): void {
	    const range = visibleRange(rangeItem);
	    if (range) {
	      onToggleHighlight(paragraphIndex, text, range);
	      return;
	    }
	    onToggleHighlight(paragraphIndex, text);
	  }

  return (
    <article
      aria-label={ariaLabel}
      className="reader-mode-content reader-page-content"
      data-font={fontFamily}
      data-instant-mode={instantMode ? 'true' : 'false'}
      data-reading-mode={isPaginatedMode ? 'paginated' : 'scroll'}
      data-theme={theme}
      data-width={width}
      onClick={handleChromeToggle}
      onKeyUp={onCaptureSelection}
      onLoadCapture={onRichMediaLoad}
      onErrorCapture={onRichMediaLoad}
      onMouseUp={onCaptureSelection}
      onTouchEnd={onCaptureSelection}
      style={readerStyle}
    >
      {selectedChapter ? (
        <header className="reader-chapter-title">
          <p className="section-label">Chương {selectedChapter.chapter_number}</p>
          <h3>{selectedChapter.title}</h3>
        </header>
      ) : null}

      {textState === 'loading' ? <p>Đang tải bản đọc...</p> : null}
      {textError ? (
        <p className="status-error" role="alert">
          {textError}
        </p>
      ) : null}
      {!selectedChapter && textState !== 'loading' ? <p>Chọn một truyện đã dịch để bắt đầu đọc.</p> : null}
      {selectedChapter && textState !== 'loading' && paragraphs.length === 0 && richBlocks.length === 0 && !hasRichContent && !textError ? (
        <p>Chưa có bản dịch tiếng Việt.</p>
      ) : null}
      {selectedChapter && textState !== 'loading' && hasTitleOnlyImportContent && !textError ? (
        <p className="status-warning">File import của chương này chỉ có tiêu đề/ảnh, chưa có nội dung chữ để đọc.</p>
      ) : null}
      {selectedChapter && textState !== 'loading' && hasRichContent && !textError ? (
        <div className={isPaginatedMode ? 'chapter-rich-page' : 'chapter-rich-content'}>
          {(isPaginatedMode ? visibleRichBlocks : richBlocks).map((block) => (
	          <div
	            className="reader-paragraph-block reader-rich-block"
	            data-char-end={(block as ReaderVisibleRichBlock).charEnd}
	            data-char-start={(block as ReaderVisibleRichBlock).charStart}
	            data-highlighted={highlightedParagraphs.has(block.index) ? 'true' : undefined}
	            data-has-note={notesByParagraph.has(block.index) ? 'true' : undefined}
	            data-paragraph-index={block.index}
	            data-rich-kind={block.kind}
            key={`rich-${block.index}-${block.text.slice(0, 24)}`}
          >
            <RichBlockText block={block} />
            {instantMode ? (
              <div aria-label={`Tác vụ đoạn ${block.index + 1}`} className="reader-paragraph-actions" role="group">
                <button
                  aria-label={`Đánh dấu đoạn ${block.index + 1}`}
                  aria-pressed={highlightedParagraphs.has(block.index)}
		                  onClick={(event) => {
		                    event.stopPropagation();
		                    handleToggleHighlight(block.index, block.text, visibleRangeFromRichBlock(block));
		                  }}
                  title="Đánh dấu đoạn"
                  type="button"
                >
                  <Highlighter aria-hidden="true" size={16} />
                </button>
                <button
                  aria-label={`Ghi chú đoạn ${block.index + 1}`}
		                  onClick={(event) => {
		                    event.stopPropagation();
		                    handleOpenNote(block.index, block.text, visibleRangeFromRichBlock(block));
		                  }}
                  title="Ghi chú đoạn"
                  type="button"
                >
                  <StickyNote aria-hidden="true" size={16} />
                </button>
              </div>
            ) : null}
            {notesByParagraph.has(block.index) ? (
              <button
                aria-label={`Mở ghi chú đoạn ${block.index + 1}`}
                className="reader-note-chip"
                onClick={(event) => {
		                  event.stopPropagation();
		                  handleOpenNote(block.index, block.text, visibleRangeFromRichBlock(block));
		                }}
                type="button"
              >
                {notesByParagraph.get(block.index)?.note}
              </button>
            ) : null}
          </div>
          ))}
        </div>
      ) : (
	        visibleParagraphs.map(({ charEnd, charStart, paragraph, index }) => (
	          <div
	            className="reader-paragraph-block"
	            data-char-end={charEnd}
	            data-char-start={charStart}
	            data-highlighted={highlightedParagraphs.has(index) ? 'true' : undefined}
	            data-has-note={notesByParagraph.has(index) ? 'true' : undefined}
	            data-paragraph-index={index}
            key={`${paragraph.slice(0, 24)}-${index}`}
          >
            <p className="reader-paragraph-text">{paragraph}</p>
            {instantMode ? (
              <div aria-label={`Tác vụ đoạn ${index + 1}`} className="reader-paragraph-actions" role="group">
                <button
                  aria-label={`Đánh dấu đoạn ${index + 1}`}
                  aria-pressed={highlightedParagraphs.has(index)}
		                  onClick={(event) => {
		                    event.stopPropagation();
		                    handleToggleHighlight(index, paragraph, { charEnd, charStart });
		                  }}
                  title="Đánh dấu đoạn"
                  type="button"
                >
                  <Highlighter aria-hidden="true" size={16} />
                </button>
                <button
                  aria-label={`Ghi chú đoạn ${index + 1}`}
		                  onClick={(event) => {
		                    event.stopPropagation();
		                    handleOpenNote(index, paragraph, { charEnd, charStart });
		                  }}
                  title="Ghi chú đoạn"
                  type="button"
                >
                  <StickyNote aria-hidden="true" size={16} />
                </button>
              </div>
            ) : null}
            {notesByParagraph.has(index) ? (
              <button
                aria-label={`Mở ghi chú đoạn ${index + 1}`}
                className="reader-note-chip"
                onClick={(event) => {
		                  event.stopPropagation();
		                  handleOpenNote(index, paragraph, { charEnd, charStart });
		                }}
                type="button"
              >
                {notesByParagraph.get(index)?.note}
              </button>
            ) : null}
          </div>
        ))
      )}
    </article>
  );
}
