import { ArrowLeft, BookOpenCheck, RefreshCw, Search } from 'lucide-react';
import { useLayoutEffect, useMemo, useState } from 'react';
import type { KeyboardEvent } from 'react';
import type { Chapter, TranslatedBookSummary } from '../api/types';
import { useWindowedList } from '../hooks/useWindowedList';
import type { AsyncState } from '../state/types';
import { useReaderToc } from './reader/useReaderToc';

export type LibraryBookContentsProps = {
  book: TranslatedBookSummary;
  chapters: AsyncState<Chapter[]>;
  lastReadChapterId: number | null;
  onBack(): void;
  onOpenReader(bookId: number, chapterId: number): void;
  onRetry(): void;
};

export default function LibraryBookContents({
  book,
  chapters,
  lastReadChapterId,
  onBack,
  onOpenReader,
  onRetry,
}: LibraryBookContentsProps) {
  const bookChapters = useMemo(
    () => chapters.data.filter((chapter) => chapter.book_id === book.id),
    [book.id, chapters.data],
  );
  const {
    order,
    query,
    setOrder,
    setQuery,
    translatedChapterDatasetKey,
    translatedChapters,
    visibleChapters,
  } = useReaderToc({
    chapters: bookChapters,
    currentChapterId: lastReadChapterId,
  });
  const lastReadChapter = translatedChapters.find((chapter) => chapter.id === lastReadChapterId) ?? null;
  const lastReadVisibleIndex = visibleChapters.findIndex((chapter) => chapter.id === lastReadChapterId);
  const chapterWindowKey = `${book.id}:${translatedChapterDatasetKey}:${order}:${query}`;
  const chapterWindow = useWindowedList({
    count: visibleChapters.length,
    estimateSize: 72,
    initialIndex: Math.max(0, lastReadVisibleIndex),
    measureItems: true,
    resetKey: chapterWindowKey,
  });
  const windowedChapters = visibleChapters.slice(chapterWindow.startIndex, chapterWindow.endIndex);
  const [focusRequest, setFocusRequest] = useState<{
    index: number;
    key: string;
    sequence: number;
  } | null>(null);
  const isLoading = chapters.state === 'loading';
  const hasError = Boolean(chapters.error);
  const hasNoTranslatedChapters = !isLoading && !hasError && translatedChapters.length === 0;
  const hasNoSearchResult = (
    !isLoading
    && !hasError
    && translatedChapters.length > 0
    && visibleChapters.length === 0
  );

  useLayoutEffect(() => {
    setFocusRequest(null);
  }, [chapterWindowKey]);

  useLayoutEffect(() => {
    if (focusRequest === null || focusRequest.key !== chapterWindowKey) return;
    const target = chapterWindow.containerRef.current?.querySelector<HTMLButtonElement>(
      `[data-chapter-index="${focusRequest.index}"]`,
    );
    target?.focus();
  }, [chapterWindow.containerRef, chapterWindow.endIndex, chapterWindow.startIndex, chapterWindowKey, focusRequest]);

  function handleChapterKeyDown(event: KeyboardEvent<HTMLButtonElement>, chapterIndex: number): void {
    let targetIndex: number | null = null;
    if (event.key === 'ArrowUp') targetIndex = chapterIndex - 1;
    if (event.key === 'ArrowDown') targetIndex = chapterIndex + 1;
    if (event.key === 'Home') targetIndex = 0;
    if (event.key === 'End') targetIndex = visibleChapters.length - 1;
    if (targetIndex === null) return;

    event.preventDefault();
    const boundedIndex = Math.max(0, Math.min(visibleChapters.length - 1, targetIndex));
    chapterWindow.scrollToIndex(boundedIndex);
    setFocusRequest((current) => ({
      index: boundedIndex,
      key: chapterWindowKey,
      sequence: (current?.sequence ?? 0) + 1,
    }));
  }

  return (
    <section aria-labelledby="library-book-contents-title" className="library-book-contents">
      <button className="library-book-contents-back" onClick={onBack} type="button">
        <ArrowLeft aria-hidden="true" size={18} />
        Tất cả truyện
      </button>

      <header className="library-book-contents-header">
        <span aria-hidden="true" className="library-book-contents-icon">
          <BookOpenCheck size={25} />
        </span>
        <div>
          <h2 id="library-book-contents-title">Mục lục</h2>
          <h3>{book.title}</h3>
          <p>{book.author || 'Chưa rõ tác giả'}</p>
        </div>
        <div className="library-book-contents-summary">
          <strong>
            {book.translated_chapters}/{book.total_chapters} chương đã dịch
          </strong>
          {lastReadChapter ? (
            <span>
              Đọc gần nhất: Ch. {lastReadChapter.chapter_number} · {lastReadChapter.title}
            </span>
          ) : null}
        </div>
      </header>

      <div className="library-book-contents-controls">
        <label className="library-book-contents-search">
          <span>Tìm trong mục lục</span>
          <Search aria-hidden="true" size={18} />
          <input
            aria-label="Tìm trong mục lục"
            disabled={isLoading}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Số chương hoặc tên chương"
            type="search"
            value={query}
          />
        </label>

        <div aria-label="Thứ tự chương" className="library-book-contents-order" role="group">
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
      </div>

      {isLoading ? <p className="library-book-contents-state">Đang tải mục lục...</p> : null}
      {hasError ? (
        <div className="library-book-contents-state library-book-contents-error">
          <p className="status-error" role="alert">{chapters.error}</p>
          <button className="secondary-action" onClick={onRetry} type="button">
            <RefreshCw aria-hidden="true" size={16} />
            Thử tải lại mục lục
          </button>
        </div>
      ) : null}
      {hasNoTranslatedChapters ? (
        <p className="library-book-contents-state">Truyện này chưa có chương đã dịch.</p>
      ) : null}
      {hasNoSearchResult ? (
        <p className="library-book-contents-state">Không tìm thấy chương phù hợp.</p>
      ) : null}

      {translatedChapters.length > 0 ? (
        <div
          aria-label="Danh sách chương đã dịch"
          className="library-book-contents-list"
          onScroll={chapterWindow.onScroll}
          ref={chapterWindow.containerRef}
          role="list"
        >
          {chapterWindow.paddingTop > 0 ? (
            <div
              aria-hidden="true"
              className="library-book-contents-spacer"
              style={{ height: chapterWindow.paddingTop }}
            />
          ) : null}
          {windowedChapters.map((chapter, offset) => {
            const chapterIndex = chapterWindow.startIndex + offset;
            const isLastRead = chapter.id === lastReadChapterId;
            return (
              <div
                aria-posinset={chapterIndex + 1}
                aria-setsize={visibleChapters.length}
                className="library-book-contents-row"
                data-virtual-index={chapterIndex}
                key={chapter.id}
                role="listitem"
              >
                <button
                  aria-current={isLastRead ? 'true' : undefined}
                  aria-label={`Đọc Ch. ${chapter.chapter_number} ${chapter.title}`}
                  data-chapter-index={chapterIndex}
                  onClick={() => onOpenReader(book.id, chapter.id)}
                  onKeyDown={(event) => handleChapterKeyDown(event, chapterIndex)}
                  type="button"
                >
                  <span className="library-book-contents-number">Ch. {chapter.chapter_number}</span>
                  <strong>{chapter.title}</strong>
                  {isLastRead ? <small>Đọc gần nhất</small> : null}
                </button>
              </div>
            );
          })}
          {chapterWindow.paddingBottom > 0 ? (
            <div
              aria-hidden="true"
              className="library-book-contents-spacer"
              style={{ height: chapterWindow.paddingBottom }}
            />
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
