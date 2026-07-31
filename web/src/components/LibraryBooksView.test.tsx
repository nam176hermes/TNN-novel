import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { TranslatedBookSummary } from '../api/types';
import type { AsyncState } from '../state/types';
import LibraryBooksView from './LibraryBooksView';

const books: AsyncState<TranslatedBookSummary[]> = {
  data: [
    {
      id: 42,
      title: 'Phàm Nhân Tu Tiên',
      author: 'Vong Ngữ',
      source: 'ebook',
      source_url: '',
      cover_url: '/covers/pham-nhan.jpg',
      total_chapters: 5,
      translated_chapters: 3,
      audio_chapters: 0,
      failed_chapters: 0,
      qa_low_chapters: 0,
      first_translated_chapter_id: 101,
      latest_translated_chapter_id: 103,
      latest_chapter_number: 3,
      latest_chapter_title: 'Thất Huyền Môn',
      last_activity: '2026-06-20T00:00:00Z',
    },
    {
      id: 77,
      title: 'Đấu Phá Thương Khung',
      author: 'Thiên Tằm Thổ Đậu',
      source: 'ebook',
      source_url: '',
      cover_url: '/covers/dau-pha.jpg',
      total_chapters: 120,
      translated_chapters: 120,
      audio_chapters: 0,
      failed_chapters: 0,
      qa_low_chapters: 0,
      first_translated_chapter_id: 201,
      latest_translated_chapter_id: 320,
      latest_chapter_number: 120,
      latest_chapter_title: 'Dị hỏa',
      last_activity: '2026-06-22T00:00:00Z',
    },
    {
      id: 88,
      title: 'Thanh Sơn',
      author: 'Vô Danh',
      source: 'ebook',
      source_url: '',
      cover_url: '',
      total_chapters: 695,
      translated_chapters: 10,
      audio_chapters: 0,
      failed_chapters: 1,
      qa_low_chapters: 2,
      first_translated_chapter_id: 401,
      latest_translated_chapter_id: 410,
      latest_chapter_number: 10,
      latest_chapter_title: 'Trà thay rượu',
      last_activity: '2026-06-21T00:00:00Z',
    },
  ],
  error: '',
  state: 'ready',
};

describe('LibraryBooksView', () => {
  afterEach(() => {
    cleanup();
    window.localStorage.clear();
  });

  it('shows book cover thumbnails in the translated library', () => {
    render(
      <LibraryBooksView
        books={books}
        onOpenReader={vi.fn()}
        onOpenWorkbench={vi.fn()}
        onRefresh={vi.fn()}
      />,
    );

    expect(screen.getByRole('img', { name: 'Bìa Phàm Nhân Tu Tiên' })).toHaveAttribute(
      'src',
      '/covers/pham-nhan.jpg',
    );
  });

  it('exposes a delete action for translated books', async () => {
    const onDeleteBook = vi.fn();
    render(
      <LibraryBooksView
        books={books}
        onDeleteBook={onDeleteBook}
        onOpenReader={vi.fn()}
        onOpenWorkbench={vi.fn()}
        onRefresh={vi.fn()}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Xóa sách Phàm Nhân Tu Tiên' }));

    expect(onDeleteBook).toHaveBeenCalledWith(books.data[0]);
  });

  it('opens reader without forcing the first chapter so saved progress can resume', async () => {
    const onOpenReader = vi.fn();
    render(
      <LibraryBooksView
        books={books}
        onOpenReader={onOpenReader}
        onOpenWorkbench={vi.fn()}
        onRefresh={vi.fn()}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Đọc tiếp Phàm Nhân Tu Tiên' }));

    expect(onOpenReader).toHaveBeenCalledWith(42);
  });

  it('renders a visual cover grid with reader progress badges', () => {
    window.localStorage.setItem(
      'novel-reader-progress-v1',
      JSON.stringify({ 42: { chapterId: 102, position: 2, totalChapters: 5 } }),
    );

    render(
      <LibraryBooksView
        books={books}
        onOpenReader={vi.fn()}
        onOpenWorkbench={vi.fn()}
        onRefresh={vi.fn()}
      />,
    );

    const list = screen.getByRole('region', { name: 'Danh sách truyện đã dịch' });
    expect(list.querySelector('.translated-books-grid')).toBeInTheDocument();
    const card = screen.getByRole('article', { name: 'Sách Phàm Nhân Tu Tiên' });
    expect(within(card).getByText('40%')).toBeInTheDocument();
    expect(within(card).getByText('Đang đọc')).toBeInTheDocument();
  });

  it('searches translated books by title or author', async () => {
    render(
      <LibraryBooksView
        books={books}
        onOpenReader={vi.fn()}
        onOpenWorkbench={vi.fn()}
        onRefresh={vi.fn()}
      />,
    );

    await userEvent.type(screen.getByLabelText('Tìm sách'), 'thiên tàm');

    expect(screen.getByRole('article', { name: 'Sách Đấu Phá Thương Khung' })).toBeInTheDocument();
    expect(screen.queryByRole('article', { name: 'Sách Phàm Nhân Tu Tiên' })).not.toBeInTheDocument();
  });

  it('sorts books and filters by reading or completed state', async () => {
    window.localStorage.setItem(
      'novel-reader-progress-v1',
      JSON.stringify({ 42: { chapterId: 102, position: 2, totalChapters: 5 } }),
    );

    render(
      <LibraryBooksView
        books={books}
        onOpenReader={vi.fn()}
        onOpenWorkbench={vi.fn()}
        onRefresh={vi.fn()}
      />,
    );

    await userEvent.selectOptions(screen.getByLabelText('Sắp xếp'), 'title');
    expect(screen.getAllByRole('article').map((card) => card.getAttribute('aria-label'))).toEqual([
      'Sách Đấu Phá Thương Khung',
      'Sách Phàm Nhân Tu Tiên',
      'Sách Thanh Sơn',
    ]);

    await userEvent.click(screen.getByRole('button', { name: 'Đang đọc' }));
    expect(screen.getByRole('article', { name: 'Sách Phàm Nhân Tu Tiên' })).toBeInTheDocument();
    expect(screen.queryByRole('article', { name: 'Sách Đấu Phá Thương Khung' })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Hoàn tất' }));
    expect(screen.getByRole('article', { name: 'Sách Đấu Phá Thương Khung' })).toBeInTheDocument();
    expect(screen.queryByRole('article', { name: 'Sách Phàm Nhân Tu Tiên' })).not.toBeInTheDocument();
    expect(screen.queryByRole('article', { name: 'Sách Thanh Sơn' })).not.toBeInTheDocument();
  });

  it('opens a book card at the last-read chapter when progress exists', async () => {
    const onOpenReader = vi.fn();
    window.localStorage.setItem(
      'novel-reader-progress-v1',
      JSON.stringify({ 42: { chapterId: 102, position: 2, totalChapters: 5 } }),
    );
    render(
      <LibraryBooksView
        books={books}
        onOpenReader={onOpenReader}
        onOpenWorkbench={vi.fn()}
        onRefresh={vi.fn()}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Mở sách Phàm Nhân Tu Tiên' }));

    expect(onOpenReader).toHaveBeenCalledWith(42, 102);
  });

  it('adds and changes translated book covers', async () => {
    const onUpdateCover = vi.fn();
    const noCoverBook = { ...books.data[0], cover_url: '' };
    const file = new File(['cover'], 'cover.jpg', { type: 'image/jpeg' });
    const { rerender } = render(
      <LibraryBooksView
        books={{ ...books, data: [noCoverBook] }}
        onOpenReader={vi.fn()}
        onOpenWorkbench={vi.fn()}
        onRefresh={vi.fn()}
        onUpdateCover={onUpdateCover}
      />,
    );

    await userEvent.upload(screen.getByLabelText('Thêm bìa sách Phàm Nhân Tu Tiên'), file);

    expect(onUpdateCover).toHaveBeenCalledWith(noCoverBook, file);

    rerender(
      <LibraryBooksView
        books={books}
        onOpenReader={vi.fn()}
        onOpenWorkbench={vi.fn()}
        onRefresh={vi.fn()}
        onUpdateCover={onUpdateCover}
      />,
    );

    expect(screen.getByLabelText('Đổi bìa sách Phàm Nhân Tu Tiên')).toBeInTheDocument();
  });

  it('paginates translated books with the page-size control', async () => {
    const manyBooks = Array.from({ length: 13 }, (_, index) => ({
      ...books.data[0],
      id: index + 1,
      title: `Book ${String(index + 1).padStart(2, '0')}`,
      last_activity: `2026-06-${String(index + 1).padStart(2, '0')}T00:00:00Z`,
    }));
    render(
      <LibraryBooksView
        books={{ ...books, data: manyBooks }}
        onOpenReader={vi.fn()}
        onOpenWorkbench={vi.fn()}
        onRefresh={vi.fn()}
      />,
    );

    await userEvent.selectOptions(screen.getByLabelText('Sắp xếp'), 'title');

    expect(screen.getByRole('article', { name: 'Sách Book 01' })).toBeInTheDocument();
    expect(screen.queryByRole('article', { name: 'Sách Book 13' })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Trang sau' }));

    expect(screen.getByRole('article', { name: 'Sách Book 13' })).toBeInTheDocument();
    expect(screen.queryByRole('article', { name: 'Sách Book 01' })).not.toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText('Số sách mỗi trang'), '24');

    expect(screen.getByRole('article', { name: 'Sách Book 01' })).toBeInTheDocument();
    expect(screen.getByRole('article', { name: 'Sách Book 13' })).toBeInTheDocument();
  });

  it('routes translated book overflow menu actions to existing handlers', async () => {
    const onOpenReader = vi.fn();
    const onOpenWorkbench = vi.fn();
    const onDeleteBook = vi.fn();
    render(
      <LibraryBooksView
        books={books}
        onDeleteBook={onDeleteBook}
        onOpenReader={onOpenReader}
        onOpenWorkbench={onOpenWorkbench}
        onRefresh={vi.fn()}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Tùy chọn sách Phàm Nhân Tu Tiên' }));
    await userEvent.click(screen.getByRole('menuitem', { name: 'Sửa' }));

    expect(onOpenWorkbench).toHaveBeenCalledWith(42, 103);

    await userEvent.click(screen.getByRole('button', { name: 'Tùy chọn sách Phàm Nhân Tu Tiên' }));
    await userEvent.click(screen.getByRole('menuitem', { name: 'Đọc tiếp' }));

    expect(onOpenReader).toHaveBeenCalledWith(42);

    await userEvent.click(screen.getByRole('button', { name: 'Tùy chọn sách Phàm Nhân Tu Tiên' }));
    await userEvent.click(screen.getByRole('menuitem', { name: 'Xóa' }));

    expect(onDeleteBook).toHaveBeenCalledWith(books.data[0]);
  });
});
