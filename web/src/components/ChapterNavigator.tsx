import { FileUp, Pencil, X } from 'lucide-react';
import { useState } from 'react';
import type { BookSummary, Chapter } from '../api/types';

export type ChapterNavigatorProps = {
  books: BookSummary[];
  chapters: Chapter[];
  activeBookId: number | null;
  selectedChapterId: number | null;
  onSelectBook(bookId: number): void;
  onSelectChapter(chapterId: number): void;
  onImport(): void;
  onRenameBook?(bookId: number, title: string): Promise<void> | void;
};

function formatStatus(status: string): string {
  return status
    .split(/[_-]/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

export default function ChapterNavigator({
  books,
  chapters,
  activeBookId,
  selectedChapterId,
  onSelectBook,
  onSelectChapter,
  onImport,
  onRenameBook,
}: ChapterNavigatorProps) {
  const activeChapters = chapters.filter((chapter) => chapter.book_id === activeBookId);
  const [renameBookId, setRenameBookId] = useState<number | null>(null);
  const [renameTitle, setRenameTitle] = useState('');
  const [renameError, setRenameError] = useState('');
  const [renameSaving, setRenameSaving] = useState(false);

  function startRename(book: BookSummary): void {
    setRenameBookId(book.id);
    setRenameTitle(book.title);
    setRenameError('');
  }

  function cancelRename(): void {
    setRenameBookId(null);
    setRenameTitle('');
    setRenameError('');
  }

  async function submitRename(book: BookSummary): Promise<void> {
    if (!onRenameBook) return;

    const nextTitle = renameTitle.trim();
    if (!nextTitle) {
      setRenameError('Tên sách không được để trống.');
      return;
    }

    if (nextTitle === book.title) {
      cancelRename();
      return;
    }

    setRenameSaving(true);
    setRenameError('');
    try {
      await onRenameBook(book.id, nextTitle);
      cancelRename();
    } catch (error) {
      setRenameError(error instanceof Error ? error.message : 'Không thể đổi tên sách.');
    } finally {
      setRenameSaving(false);
    }
  }

  return (
    <section aria-label="Chapter navigator" className="chapter-navigator">
      <div className="rail-header">
        <div>
          <p className="section-label">Library</p>
          <h3>Books</h3>
        </div>
        <button className="icon-action" onClick={onImport} title="Import" type="button">
          <FileUp aria-hidden="true" size={16} />
          <span className="sr-only">Import</span>
        </button>
      </div>

      <div aria-label="Books" className="book-list">
        {books.map((book) => {
          const isRenaming = renameBookId === book.id;

          return (
            <div className={book.id === activeBookId ? 'book-row-shell active' : 'book-row-shell'} key={book.id}>
              <button
                aria-current={book.id === activeBookId ? 'page' : undefined}
                className={book.id === activeBookId ? 'book-row active' : 'book-row'}
                onClick={() => onSelectBook(book.id)}
                type="button"
              >
                <span className="book-title">{book.title}</span>
                <span className="book-meta">
                  {book.translated}/{book.total} translated · {book.audio} audio · {book.failed} failed
                </span>
              </button>
              {onRenameBook ? (
                <button
                  aria-label={`Đổi tên sách ${book.title}`}
                  className="icon-action book-rename-trigger"
                  onClick={() => startRename(book)}
                  title="Đổi tên sách"
                  type="button"
                >
                  <Pencil aria-hidden="true" size={15} />
                </button>
              ) : null}
              {isRenaming ? (
                <form
                  aria-label={`Đổi tên ${book.title}`}
                  className="book-rename-form"
                  onSubmit={(event) => {
                    event.preventDefault();
                    void submitRename(book);
                  }}
                >
                  <label className="sr-only" htmlFor={`book-rename-${book.id}`}>
                    Tên sách mới
                  </label>
                  <input
                    aria-label="Tên sách mới"
                    autoFocus
                    disabled={renameSaving}
                    id={`book-rename-${book.id}`}
                    onChange={(event) => setRenameTitle(event.target.value)}
                    value={renameTitle}
                  />
                  <button className="primary-action" disabled={renameSaving} type="submit">
                    Lưu
                  </button>
                  <button className="secondary-action" disabled={renameSaving} onClick={cancelRename} type="button">
                    <X aria-hidden="true" size={15} />
                    Hủy
                  </button>
                  {renameError ? (
                    <p className="book-rename-error" role="alert">
                      {renameError}
                    </p>
                  ) : null}
                </form>
              ) : null}
            </div>
          );
        })}
      </div>

      <div className="rail-header chapter-navigator-header">
        <div>
          <p className="section-label">Pipeline</p>
          <h3>Chapters</h3>
        </div>
      </div>

      <div aria-label="Chapters" className="book-list">
        {activeChapters.length > 0 ? (
          activeChapters.map((chapter) => (
            <button
              aria-current={chapter.id === selectedChapterId ? 'page' : undefined}
              className={chapter.id === selectedChapterId ? 'book-row active' : 'book-row'}
              key={chapter.id}
              onClick={() => onSelectChapter(chapter.id)}
              type="button"
            >
              <span className="chapter-number">Ch. {chapter.chapter_number}</span>
              <span className="book-title">{chapter.title}</span>
              <span className={`status-pill status-${chapter.status.toLowerCase().replace(/\s+/g, '-')}`}>
                {formatStatus(chapter.status)}
              </span>
            </button>
          ))
        ) : (
          <p className="book-meta">No chapters for the selected book.</p>
        )}
      </div>
    </section>
  );
}
