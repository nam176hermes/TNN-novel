import { FileUp, Play } from 'lucide-react';
import type { BookSummary } from '../api/types';

type Props = {
  books: BookSummary[];
  activeBookId: number | null;
  onSelectBook: (bookId: number) => void;
  onImport?: () => void;
  onRunDaily?: () => void;
};

function progressValue(book: BookSummary): number {
  if (book.total <= 0) return 0;
  return Math.round((book.translated / book.total) * 100);
}

export default function LibraryRail({ books, activeBookId, onSelectBook, onImport, onRunDaily }: Props) {
  return (
    <section aria-label="Library" className="library-rail panel">
      <div className="rail-header">
        <div>
          <p className="section-label">Library</p>
          <h3>Books</h3>
        </div>
        <div className="rail-actions" aria-label="Library actions">
          <button className="icon-action" onClick={onImport} title="Import" type="button">
            <FileUp aria-hidden="true" size={16} />
          </button>
          <button className="icon-action" onClick={onRunDaily} title="Run Daily" type="button">
            <Play aria-hidden="true" size={16} />
          </button>
        </div>
      </div>

      <label className="rail-search">
        <span>Search books</span>
        <input placeholder="Filter library" type="search" />
      </label>

      <div className="book-list">
        {books.map((book) => {
          const progress = progressValue(book);

          return (
            <button
              aria-pressed={book.id === activeBookId}
              className={book.id === activeBookId ? 'book-row active' : 'book-row'}
              key={book.id}
              onClick={() => onSelectBook(book.id)}
              type="button"
            >
              <span className="book-title">{book.title}</span>
              <span className="book-meta">
                {book.translated}/{book.total} translated · {book.audio} audio · {book.failed} failed
              </span>
              <span
                aria-label={`${progress}% translated`}
                aria-valuemax={100}
                aria-valuemin={0}
                aria-valuenow={progress}
                className="book-progress"
                role="progressbar"
              >
                <span style={{ width: `${progress}%` }} />
              </span>
              {(book.qa_low ?? 0) > 0 ? <span className="book-alert">{book.qa_low} QA low</span> : null}
            </button>
          );
        })}
      </div>
    </section>
  );
}
