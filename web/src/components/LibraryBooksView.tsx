import {
  BookOpenCheck,
  CalendarDays,
  CheckSquare,
  Crown,
  Grid3X3,
  ImagePlus,
  MoreVertical,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  Wrench,
} from 'lucide-react';
import { useEffect, useMemo, useState, type ChangeEvent } from 'react';
import type { TranslatedBookSummary } from '../api/types';
import coverDocTu from '../assets/reference-ui/cover-doc-tu-clean.png';
import coverThanhSon from '../assets/reference-ui/cover-thanh-son-clean.png';
import { loadReaderProgressSnapshot } from '../state/readerProgress';
import type { AsyncState } from '../state/types';

export type LibraryBooksViewProps = {
  books: AsyncState<TranslatedBookSummary[]>;
  onDeleteBook?(book: TranslatedBookSummary): void;
  onOpenImport?(): void;
  onOpenReader(bookId: number, chapterId?: number | null): void;
  onOpenWorkbench(bookId: number, chapterId?: number | null): void;
  onRefresh(): void;
  onUpdateCover?(book: TranslatedBookSummary, cover: File): void;
};

type LibraryFilter = 'all' | 'reading' | 'completed' | 'attention';
type LibrarySort = 'recent' | 'title' | 'progress' | 'translated';

const filterOptions: Array<{ id: LibraryFilter; label: string }> = [
  { id: 'all', label: 'Tất cả' },
  { id: 'reading', label: 'Đang đọc' },
  { id: 'completed', label: 'Hoàn tất' },
  { id: 'attention', label: 'Cần xem' },
];

function formatLastActivity(value: string): string {
  if (!value) return 'Chưa rõ';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString('vi-VN');
}

function normalizeSearch(value: string): string {
  return value
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .replace(/đ/g, 'd')
    .replace(/Đ/g, 'D')
    .toLowerCase();
}

function fallbackBookCover(book: TranslatedBookSummary): string {
  const normalized = normalizeSearch(`${book.title} ${book.author}`);
  if (normalized.includes('doc tu')) return coverDocTu;
  if (normalized.includes('thanh son')) return coverThanhSon;
  return '';
}

function translatedPercent(book: TranslatedBookSummary): number {
  if (book.total_chapters <= 0) return 0;
  return Math.min(100, Math.max(0, Math.round((book.translated_chapters / book.total_chapters) * 100)));
}

function lastActivityTime(value: string): number {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? 0 : parsed.getTime();
}

export default function LibraryBooksView({
  books,
  onDeleteBook,
  onOpenImport,
  onOpenReader,
  onOpenWorkbench,
  onRefresh,
  onUpdateCover,
}: LibraryBooksViewProps) {
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState<LibraryFilter>('all');
  const [sortMode, setSortMode] = useState<LibrarySort>('recent');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(12);
  const [openMenuBookId, setOpenMenuBookId] = useState<number | null>(null);

  const bookRows = useMemo(() => books.data.map((book) => {
    const readerProgress = loadReaderProgressSnapshot(book.id);
    return {
      book,
      readerProgress,
      translatedPercent: translatedPercent(book),
    };
  }), [books.data]);

  const visibleBooks = useMemo(() => {
    const normalizedQuery = normalizeSearch(query.trim());
    return [...bookRows]
      .filter(({ book, readerProgress }) => {
        if (!normalizedQuery) return true;
        return normalizeSearch(`${book.title} ${book.author}`).includes(normalizedQuery);
      })
      .filter(({ book, readerProgress }) => {
        if (filter === 'reading') return Boolean(readerProgress);
        if (filter === 'completed') return book.total_chapters > 0 && book.translated_chapters >= book.total_chapters;
        if (filter === 'attention') return book.qa_low_chapters > 0 || book.failed_chapters > 0;
        return true;
      })
      .sort((left, right) => {
        if (sortMode === 'title') return left.book.title.localeCompare(right.book.title, 'vi');
        if (sortMode === 'progress') return (right.readerProgress?.percent ?? 0) - (left.readerProgress?.percent ?? 0);
        if (sortMode === 'translated') return right.translatedPercent - left.translatedPercent;
        return lastActivityTime(right.book.last_activity) - lastActivityTime(left.book.last_activity);
      });
  }, [bookRows, filter, query, sortMode]);
  const totalPages = Math.max(1, Math.ceil(visibleBooks.length / pageSize));
  const currentPage = Math.min(page, totalPages);
  const pagedBooks = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return visibleBooks.slice(start, start + pageSize);
  }, [currentPage, pageSize, visibleBooks]);

  useEffect(() => {
    setPage(1);
    setOpenMenuBookId(null);
  }, [filter, pageSize, query, sortMode]);

  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);

  function handleCoverChange(book: TranslatedBookSummary, event: ChangeEvent<HTMLInputElement>): void {
    const cover = event.currentTarget.files?.[0] ?? null;
    event.currentTarget.value = '';
    if (!cover || !onUpdateCover) return;
    onUpdateCover(book, cover);
  }

  function openReader(book: TranslatedBookSummary): void {
    const readerProgress = loadReaderProgressSnapshot(book.id);
    if (readerProgress) {
      onOpenReader(book.id, readerProgress.chapterId);
      return;
    }
    onOpenReader(book.id);
  }

  return (
    <section aria-labelledby="translated-library-title" className="workflow-management-view translated-library-view">
      <header className="panel workbench-title">
        <div className="translated-library-heading">
          <span className="translated-library-heading-icon" aria-hidden="true">
            <BookOpenCheck size={24} />
          </span>
          <div>
            <h2 id="translated-library-title">Thư viện đã dịch</h2>
            <p>Quản lý và đọc các truyện đã dịch</p>
          </div>
        </div>
        <button className="secondary-action" disabled={books.state === 'loading'} onClick={onRefresh} type="button">
          <RefreshCw aria-hidden="true" size={16} />
          Làm mới
        </button>
      </header>

      <section aria-label="Bộ lọc thư viện đã dịch" className="panel translated-library-controls">
        <label className="translated-library-search">
          <span>Tìm sách</span>
          <Search aria-hidden="true" size={18} />
          <input
            aria-label="Tìm sách"
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Tên truyện hoặc tác giả"
            type="search"
            value={query}
          />
        </label>

        <label className="translated-library-sort">
          <span>Sắp xếp</span>
          <select
            aria-label="Sắp xếp"
            onChange={(event) => setSortMode(event.target.value as LibrarySort)}
            value={sortMode}
          >
            <option value="recent">Mới cập nhật</option>
            <option value="title">Tên A-Z</option>
            <option value="progress">Tiến độ đọc</option>
            <option value="translated">Độ hoàn thiện</option>
          </select>
        </label>

        <div aria-label="Lọc thư viện" className="segmented-control translated-library-filter" role="group">
          {filterOptions.map((option) => {
            const Icon = option.id === 'all'
              ? Grid3X3
              : option.id === 'reading'
                ? BookOpenCheck
                : option.id === 'completed'
                  ? CheckSquare
                  : Crown;
            return (
            <button
              aria-pressed={filter === option.id}
              key={option.id}
              onClick={() => setFilter(option.id)}
              type="button"
            >
              <Icon aria-hidden="true" size={15} />
              {option.label}
            </button>
          );
          })}
        </div>
      </section>

      <section aria-label="Danh sách truyện đã dịch" className="translated-books-panel">
        {books.state === 'loading' ? <p className="empty-detail">Đang tải truyện đã dịch...</p> : null}
        {books.error ? (
          <p className="status-error" role="alert">
            {books.error}
          </p>
        ) : null}
        {books.data.length === 0 && (books.state === 'idle' || books.state === 'empty') ? (
          <p className="empty-detail">Chưa có truyện đã dịch.</p>
        ) : null}
        {books.data.length > 0 && visibleBooks.length === 0 ? (
          <p className="panel empty-detail">Không có truyện phù hợp với bộ lọc hiện tại.</p>
        ) : null}

        {visibleBooks.length > 0 ? (
          <div className="translated-books-grid">
            {pagedBooks.map(({ book, readerProgress, translatedPercent }) => {
              const readerPercent = readerProgress?.percent ?? 0;
              const readerState = readerProgress
                ? readerPercent >= 100 ? 'Đã đọc xong' : 'Đang đọc'
                : 'Chưa đọc';
              const coverUrl = fallbackBookCover(book) || book.cover_url;
              const menuOpen = openMenuBookId === book.id;
              return (
                <article aria-label={`Sách ${book.title}`} className="translated-book-card" key={book.id}>
                  <button
                    aria-controls={`translated-book-menu-${book.id}`}
                    aria-expanded={menuOpen}
                    aria-label={`Tùy chọn sách ${book.title}`}
                    className="translated-book-kebab"
                    onClick={() => setOpenMenuBookId(menuOpen ? null : book.id)}
                    type="button"
                  >
                    <MoreVertical aria-hidden="true" size={16} />
                  </button>
                  {menuOpen ? (
                    <div className="translated-book-menu" id={`translated-book-menu-${book.id}`} role="menu">
                      <button
                        disabled={!book.first_translated_chapter_id}
                        onClick={() => {
                          openReader(book);
                          setOpenMenuBookId(null);
                        }}
                        role="menuitem"
                        type="button"
                      >
                        Đọc tiếp
                      </button>
                      <button
                        onClick={() => {
                          onOpenWorkbench(book.id, book.latest_translated_chapter_id);
                          setOpenMenuBookId(null);
                        }}
                        role="menuitem"
                        type="button"
                      >
                        Mở bàn dịch
                      </button>
                      {onDeleteBook ? (
                        <button
                          className="danger-menu-item"
                          onClick={() => {
                            onDeleteBook(book);
                            setOpenMenuBookId(null);
                          }}
                          role="menuitem"
                          type="button"
                        >
                          Xóa sách
                        </button>
                      ) : null}
                    </div>
                  ) : null}
                  <h3 className="sr-only">{book.title}</h3>
                  <button
                    aria-label={`Mở sách ${book.title}`}
                    className="translated-book-card-open"
                    disabled={!book.first_translated_chapter_id}
                    onClick={() => openReader(book)}
                    type="button"
                  >
                    <span className="translated-book-cover-frame">
                      {coverUrl ? (
                        <img
                          alt={`Bìa ${book.title}`}
                          className="translated-book-cover"
                          src={coverUrl}
                        />
                      ) : (
                        <span aria-hidden="true" className="translated-book-cover-placeholder">
                          <BookOpenCheck size={26} />
                        </span>
                      )}
                      <span className="translated-book-progress-badge">{readerPercent}%</span>
                    </span>

                    <span className="translated-book-main">
                      <strong>{book.title}</strong>
                      <span>{book.author || 'Chưa rõ tác giả'}</span>
                    </span>
                  </button>

                  <div className="translated-book-card-body">
                    <p className="translated-book-reading-state">{readerState}</p>
                    <div className="translated-book-stats">
                      <span>
                        <strong>{book.translated_chapters}/{book.total_chapters}</strong>
                        <small>Chương đã dịch</small>
                      </span>
                      <span>
                        <strong>{translatedPercent}%</strong>
                        <small>Tiến độ</small>
                      </span>
                      <span>
                        <strong>Ch. {book.latest_chapter_number || '-'}</strong>
                        <small>{book.latest_chapter_title || 'Chưa rõ'}</small>
                      </span>
                    </div>
                    <p className="translated-book-completion-summary">
                      {book.translated_chapters}/{book.total_chapters} chương đã dịch
                    </p>
                    <p className="book-meta">
                      {book.latest_chapter_title
                        ? `Mới nhất: Ch. ${book.latest_chapter_number} · ${book.latest_chapter_title}`
                        : 'Chưa rõ chương mới nhất'}
                    </p>
                    <p className="book-meta translated-book-updated">
                      <CalendarDays aria-hidden="true" size={14} />
                      Cập nhật {formatLastActivity(book.last_activity)}
                    </p>
                  </div>

                <div className="translated-book-actions">
                  <button
                    className="primary-action"
                    disabled={!book.first_translated_chapter_id}
                    onClick={() => openReader(book)}
                    type="button"
                  >
                    <BookOpenCheck aria-hidden="true" size={16} />
                    Đọc <span className="sr-only">{book.title}</span>
                  </button>
                  <button
                    className="secondary-action"
                    onClick={() => onOpenWorkbench(book.id, book.latest_translated_chapter_id)}
                    type="button"
                  >
                    <Wrench aria-hidden="true" size={16} />
                    Sửa
                  </button>
                  {onUpdateCover ? (
                    <label className="secondary-action cover-upload-action">
                      <ImagePlus aria-hidden="true" size={16} />
                      {book.cover_url ? 'Đổi bìa' : 'Thêm bìa'} <span className="sr-only">sách {book.title}</span>
                      <input
                        accept="image/jpeg,image/png,image/webp,image/gif"
                        aria-label={`${book.cover_url ? 'Đổi bìa' : 'Thêm bìa'} sách ${book.title}`}
                        onChange={(event) => handleCoverChange(book, event)}
                        type="file"
                      />
                    </label>
                  ) : null}
                  {onDeleteBook ? (
                    <button
                      className="danger-action"
                      onClick={() => onDeleteBook(book)}
                      type="button"
                    >
                      <Trash2 aria-hidden="true" size={16} />
                      Xóa <span className="sr-only">sách {book.title}</span>
                    </button>
                  ) : null}
                </div>
                </article>
              );
            })}
          </div>
        ) : null}
        {visibleBooks.length > 0 ? (
          <>
            <div className="translated-library-empty-add">
              <span aria-hidden="true">
                <BookOpenCheck size={28} />
              </span>
              <strong>Chưa có truyện nào khác</strong>
              <p>Thêm truyện từ mục Nhập chương hoặc Tìm kiếm nguồn</p>
              <button className="primary-action" disabled={!onOpenImport} onClick={onOpenImport} type="button">
                <Plus aria-hidden="true" size={16} />
                Thêm truyện mới
              </button>
            </div>
            <div className="translated-library-pagination" aria-label="Phân trang thư viện">
              <button
                aria-label="Trang trước"
                className="secondary-action"
                disabled={currentPage <= 1}
                onClick={() => setPage((value) => Math.max(1, value - 1))}
                type="button"
              >
                ‹
              </button>
              <span>{currentPage}</span>
              <button
                aria-label="Trang sau"
                className="secondary-action"
                disabled={currentPage >= totalPages}
                onClick={() => setPage((value) => Math.min(totalPages, value + 1))}
                type="button"
              >
                ›
              </button>
              <label>
                Hiển thị
                <select
                  aria-label="Số sách mỗi trang"
                  onChange={(event) => setPageSize(Number(event.target.value))}
                  value={String(pageSize)}
                >
                  <option value="12">12 / trang</option>
                  <option value="24">24 / trang</option>
                </select>
              </label>
            </div>
          </>
        ) : null}
      </section>
    </section>
  );
}
