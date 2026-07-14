import { useLayoutEffect, useRef } from 'react';
import { X } from 'lucide-react';
import type { Chapter } from '../../api/types';
import { useReaderToc } from './useReaderToc';

export type TocChapterPreview = {
  readingState: 'read' | 'reading' | 'unread';
  stateLabel: string;
  timeLabel: string;
  wordLabel: string;
};

export type ReaderTocSheetProps = {
  author?: string;
  chapters: Chapter[];
  currentChapterId: number | null;
  open: boolean;
  previews: ReadonlyMap<number, TocChapterPreview>;
  title: string;
  onClose(): void;
  onSelectChapter(chapterId: number): void;
};

export default function ReaderTocSheet({
  author,
  chapters,
  currentChapterId,
  open,
  previews,
  title,
  onClose,
  onSelectChapter,
}: ReaderTocSheetProps) {
  const currentChapterRef = useRef<HTMLButtonElement | null>(null);
  const {
    currentChapterId: currentTocChapterId,
    firstChapter,
    latestChapter,
    order,
    query,
    setOrder,
    setQuery,
    translatedChapterDatasetKey,
    translatedChapters,
    visibleChapters,
  } = useReaderToc({ chapters, currentChapterId });
  const displayChapterCountLabel = query.trim()
    ? `${visibleChapters.length.toLocaleString()}/${translatedChapters.length.toLocaleString()} chương`
    : `${translatedChapters.length.toLocaleString()} chương đã dịch`;

  useLayoutEffect(() => {
    if (!open) return;
    const currentChapter = currentChapterRef.current;
    if (!currentChapter) return;
    currentChapter.focus();
    if (typeof currentChapter.scrollIntoView === 'function') {
      currentChapter.scrollIntoView({ block: 'nearest' });
    }
  }, [currentTocChapterId, open, translatedChapterDatasetKey]);

  if (!open) return null;

  return (
    <div className="reader-drawer-backdrop">
      <aside aria-label="Mục lục" className="reader-toc-drawer" role="dialog">
        <header className="reader-drawer-header">
          <div>
            <p className="section-label">Mục lục</p>
            <h2>{title}</h2>
            {author ? <span>{author}</span> : null}
            <span>{displayChapterCountLabel}</span>
          </div>
          <button
            aria-label="Đóng mục lục"
            className="reader-icon-button"
            onClick={onClose}
            title="Đóng mục lục"
            type="button"
          >
            <X aria-hidden="true" size={22} />
          </button>
        </header>

        <label className="reader-drawer-search">
          <span>Tìm trong mục lục</span>
          <input
            aria-label="Tìm trong mục lục"
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Số chương hoặc tên chương"
            type="search"
            value={query}
          />
        </label>

        <div aria-label="Thứ tự chương" className="reader-toc-order" role="group">
          <button
            aria-pressed={order === 'asc'}
            onClick={() => setOrder('asc')}
            type="button"
          >
            Đầu → cuối
          </button>
          <button
            aria-pressed={order === 'desc'}
            onClick={() => setOrder('desc')}
            type="button"
          >
            Cuối → đầu
          </button>
        </div>

        <div className="reader-toc-shortcuts">
          <button
            disabled={translatedChapters.length === 0}
            onClick={() => {
              if (firstChapter) onSelectChapter(firstChapter.id);
            }}
            type="button"
          >
            Về chương đầu
          </button>
          <button
            disabled={translatedChapters.length === 0}
            onClick={() => {
              if (latestChapter) onSelectChapter(latestChapter.id);
            }}
            type="button"
          >
            Đến chương mới nhất
          </button>
        </div>

        <div className="reader-toc-list reader-drawer-list">
          {visibleChapters.map((chapter) => {
            const selected = chapter.id === currentTocChapterId;
            const preview = previews.get(chapter.id);
            return (
              <button
                aria-current={selected ? 'true' : undefined}
                aria-label={`Ch. ${chapter.chapter_number} ${chapter.title}`}
                key={chapter.id}
                onClick={() => onSelectChapter(chapter.id)}
                ref={selected ? currentChapterRef : undefined}
                type="button"
              >
                <span>Ch. {chapter.chapter_number}</span>
                <strong>{chapter.title}</strong>
                {preview ? (
                  <small className="reader-toc-preview">
                    <span>{preview.wordLabel}</span>
                    <span>{preview.timeLabel}</span>
                    <span data-state={preview.readingState}>{preview.stateLabel}</span>
                  </small>
                ) : null}
              </button>
            );
          })}
          {visibleChapters.length === 0 ? <p>Không tìm thấy chương.</p> : null}
        </div>
      </aside>
    </div>
  );
}
