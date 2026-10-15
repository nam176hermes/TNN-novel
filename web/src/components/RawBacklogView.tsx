import {
  BookOpenCheck,
  FilePlus2,
  FileText,
  LibraryBig,
  MoreVertical,
  RefreshCw,
  Send,
  UserRound,
  Wrench,
} from 'lucide-react';
import type { BookSummary, Chapter, RawBacklogPage } from '../api/types';
import coverDocTu from '../assets/reference-ui/cover-doc-tu-clean.png';
import coverThanhSon from '../assets/reference-ui/cover-thanh-son-clean.png';
import type { AsyncState } from '../state/types';

export type RawBacklogViewProps = {
  books: BookSummary[];
  chapters: AsyncState<Chapter[]>;
  batchBusy?: boolean;
  onOpenImport(): void;
  onOpenWorkbench(bookId: number, chapterId: number): void;
  onBatchTranslate?(bookId: number, rawChapterIds: number[]): void | Promise<void>;
  onBatchTranslateBook?(bookId: number): void | Promise<void>;
  backlog?: Omit<RawBacklogPage, 'chapters'>;
  page?: number;
  onPageChange?(page: number): void;
  onRefresh(): void;
};

type RawBookGroup = {
  book: BookSummary | { id: number; title: string };
  chapters: Chapter[];
};

function formatStatus(status: string): string {
  return status
    .split(/[_-]/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function rawSourceLabel(chapter: Chapter): string {
  if (chapter.source_preview) return chapter.source_preview;
  if (chapter.status === 'cleaned') return 'Có bản nguồn đã làm sạch';
  return 'Có bản raw';
}

function normalizeRawTitle(value: string): string {
  return value
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .replace(/đ/g, 'd')
    .replace(/Đ/g, 'D')
    .toLowerCase();
}

function fallbackRawCover(title: string): string {
  const normalized = normalizeRawTitle(title);
  if (normalized.includes('doc tu')) return coverDocTu;
  if (normalized.includes('thanh son')) return coverThanhSon;
  return '';
}

function groupRawChapters(books: BookSummary[], chapters: Chapter[]): RawBookGroup[] {
  const booksById = new Map(books.map((book) => [book.id, book]));
  const grouped = new Map<number, RawBookGroup>();

  chapters
    .filter((chapter) => chapter.has_translation !== true)
    .sort((left, right) => {
      if (left.book_id !== right.book_id) return left.book_id - right.book_id;
      if (left.chapter_number !== right.chapter_number) return left.chapter_number - right.chapter_number;
      return left.id - right.id;
    })
    .forEach((chapter) => {
      const book = booksById.get(chapter.book_id) ?? {
        id: chapter.book_id,
        title: chapter.book_title || `Book ${chapter.book_id}`,
      };
      const group = grouped.get(chapter.book_id) ?? { book, chapters: [] };
      group.chapters.push(chapter);
      grouped.set(chapter.book_id, group);
    });

  return [...grouped.values()];
}

export default function RawBacklogView({
  books,
  chapters,
  batchBusy = false,
  onBatchTranslate,
  onBatchTranslateBook,
  backlog,
  page = 0,
  onPageChange,
  onOpenImport,
  onOpenWorkbench,
  onRefresh,
}: RawBacklogViewProps) {
  const groups = groupRawChapters(books, chapters.data);
  const rawChapterCount = backlog?.total_chapters ?? groups.reduce((total, group) => total + group.chapters.length, 0);
  const rawBookCount = backlog?.total_books ?? groups.length;
  const pages = Math.max(1, Math.ceil(rawChapterCount / (backlog?.limit || 50)));

  return (
    <section aria-labelledby="raw-backlog-title" className="workflow-management-view raw-backlog-view">
      <header className="panel workbench-title">
        <div>
          <h2 id="raw-backlog-title">Raw chưa dịch</h2>
          <p>Quản lý các chương gốc đợi dịch</p>
        </div>
        <div className="raw-backlog-actions">
          <button
            className="secondary-action"
            disabled={
              (!onBatchTranslate && !onBatchTranslateBook)
              || batchBusy
              || rawChapterCount === 0
              || rawBookCount !== 1
              || chapters.state === 'loading'
            }
            onClick={() => {
              const firstGroup = groups[0];
              if (firstGroup) {
                if (onBatchTranslateBook) void onBatchTranslateBook(firstGroup.book.id);
                else void onBatchTranslate?.(firstGroup.book.id, firstGroup.chapters.map((chapter) => chapter.id));
              }
            }}
            type="button"
          >
            <Send aria-hidden="true" size={16} />
            {batchBusy ? 'Đang tạo job...' : rawBookCount > 1 ? 'Dịch theo từng truyện' : 'Dịch hàng loạt'}
          </button>
          <button className="secondary-action" disabled={chapters.state === 'loading'} onClick={onRefresh} type="button">
            <RefreshCw aria-hidden="true" size={16} />
            Làm mới
          </button>
          <button className="primary-action" onClick={onOpenImport} type="button">
            <FilePlus2 aria-hidden="true" size={16} />
            Nhập raw
          </button>
        </div>
      </header>

      <section aria-label="Tổng quan raw chưa dịch" className="panel raw-backlog-summary">
        <div>
          <span className="raw-stat-icon" aria-hidden="true"><LibraryBig size={20} /></span>
          <span>Truyện đang chờ</span>
          <strong>{rawBookCount.toLocaleString()}</strong>
          <small>Truyện</small>
        </div>
        <div>
          <span className="raw-stat-icon" aria-hidden="true"><FileText size={20} /></span>
          <span>Chương raw</span>
          <strong>{rawChapterCount.toLocaleString()}</strong>
          <small>Chương</small>
        </div>
        <div>
          <span className="raw-stat-icon" aria-hidden="true"><UserRound size={20} /></span>
          <span>Truyện trong app</span>
          <strong>{books.length.toLocaleString()}</strong>
          <small>Truyện</small>
        </div>
      </section>

      <section aria-label="Danh sách raw chưa dịch" className="panel raw-backlog-panel">
        {chapters.state === 'loading' ? <p className="empty-detail">Đang tải raw chưa dịch...</p> : null}
        {chapters.error ? (
          <p className="status-error" role="alert">
            {chapters.error}
          </p>
        ) : null}
        {groups.length === 0 && chapters.state !== 'loading' ? (
          <p className="empty-detail">Không còn chương raw đang chờ dịch.</p>
        ) : null}

        {groups.length > 0 ? (
          <div className="raw-book-list">
            {groups.map((group) => {
              const coverUrl = fallbackRawCover(group.book.title);
              const firstChapter = group.chapters[0];
              const chapterCount = backlog?.book_counts[group.book.id] ?? group.chapters.length;
              return (
              <article className="raw-book-group" key={group.book.id}>
                <header className="raw-book-group-header">
                  <span className="raw-book-cover" aria-hidden="true">
                    {coverUrl ? <img alt="" src={coverUrl} /> : <BookOpenCheck size={24} />}
                  </span>
                  <div>
                    <h3>{group.book.title}</h3>
                    <p>{chapterCount.toLocaleString()} chương còn bản raw chưa dịch</p>
                  </div>
                  <span className="raw-book-status">Đang chờ dịch</span>
                  {onBatchTranslate || onBatchTranslateBook ? (
                    <button
                      className="secondary-action"
                      disabled={batchBusy || group.chapters.length === 0}
                      onClick={() => {
                        if (onBatchTranslateBook) void onBatchTranslateBook(group.book.id);
                        else void onBatchTranslate?.(group.book.id, group.chapters.map((chapter) => chapter.id));
                      }}
                      type="button"
                    >
                      <Send aria-hidden="true" size={16} />
                      Dịch {chapterCount.toLocaleString()} chương
                    </button>
                  ) : null}
                  <button
                    aria-label={`Mở chương raw đầu tiên của ${group.book.title}`}
                    className="raw-kebab"
                    disabled={!firstChapter}
                    onClick={() => {
                      if (firstChapter) onOpenWorkbench(firstChapter.book_id,
                        backlog?.first_chapter_ids?.[group.book.id] ?? firstChapter.id);
                    }}
                    type="button"
                  >
                    <MoreVertical aria-hidden="true" size={16} />
                  </button>
                </header>
                <div className="raw-chapter-list">
                  {group.chapters.map((chapter) => (
                    <article
                      aria-label={`${group.book.title} chương ${chapter.chapter_number}`}
                      className="raw-chapter-row"
                      key={chapter.id}
                    >
                      <span className="raw-chapter-icon" aria-hidden="true">
                        <FileText size={17} />
                      </span>
                      <div>
                        <strong>
                          Ch. {chapter.chapter_number} · {chapter.title}
                        </strong>
                        <p>{rawSourceLabel(chapter)}</p>
                      </div>
                      <span className={`status-pill status-${chapter.status.toLowerCase().replace(/\s+/g, '-')}`}>
                        {formatStatus(chapter.status)}
                      </span>
                      <button
                        className="secondary-action"
                        onClick={() => onOpenWorkbench(chapter.book_id, chapter.id)}
                        type="button"
                      >
                        <Wrench aria-hidden="true" size={16} />
                        Mở bàn dịch <span className="sr-only">{group.book.title} chương {chapter.chapter_number}</span>
                      </button>
                      <button
                        aria-label={`Mở bàn dịch chương ${chapter.chapter_number}`}
                        className="raw-kebab"
                        onClick={() => onOpenWorkbench(chapter.book_id, chapter.id)}
                        type="button"
                      >
                        <MoreVertical aria-hidden="true" size={16} />
                      </button>
                    </article>
                  ))}
                </div>
              </article>
            );
            })}
          </div>
        ) : null}
      </section>
      {backlog && onPageChange && rawChapterCount > 0 ? (
        <nav aria-label="Phân trang raw" className="translated-library-pagination">
          <button aria-label="Trang raw trước" className="secondary-action" type="button"
            disabled={page <= 0 || chapters.state === 'loading'} onClick={() => onPageChange(page - 1)}>Trang trước</button>
          <span>Trang {page + 1} / {pages}</span>
          <button aria-label="Trang raw sau" className="secondary-action" type="button"
            disabled={page + 1 >= pages || chapters.state === 'loading'} onClick={() => onPageChange(page + 1)}>Trang sau</button>
        </nav>
      ) : null}
    </section>
  );
}
