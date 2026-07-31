import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Chapter, TranslatedBookSummary } from '../api/types';
import type { AsyncState } from '../state/types';
import LibraryBookContents from './LibraryBookContents';

const book: TranslatedBookSummary = {
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
  first_translated_chapter_id: 11,
  latest_translated_chapter_id: 13,
  latest_chapter_number: 3,
  latest_chapter_title: 'Thất Huyền Môn',
  last_activity: '2026-06-20T00:00:00Z',
};

const chapterRows: Chapter[] = [
  {
    id: 12,
    book_id: 42,
    chapter_number: 2,
    title: 'Thanh Ngưu trấn',
    status: 'translated',
    audio_path: null,
    has_translation: true,
  },
  {
    id: 11,
    book_id: 42,
    chapter_number: 1,
    title: 'Sơn biên tiểu thôn',
    status: 'translated',
    audio_path: null,
    has_translation: true,
  },
  {
    id: 13,
    book_id: 42,
    chapter_number: 3,
    title: 'Thất Huyền Môn',
    status: 'translated',
    audio_path: null,
    has_translation: true,
  },
  {
    id: 14,
    book_id: 42,
    chapter_number: 4,
    title: 'Chưa dịch',
    status: 'cleaned',
    audio_path: null,
    has_translation: false,
  },
];

const chapters: AsyncState<Chapter[]> = {
  data: chapterRows,
  error: '',
  state: 'ready',
};

function renderContents(overrides: Partial<Parameters<typeof LibraryBookContents>[0]> = {}) {
  const props = {
    book,
    chapters,
    lastReadChapterId: null,
    onBack: vi.fn(),
    onOpenReader: vi.fn(),
    onRetry: vi.fn(),
    ...overrides,
  };
  render(<LibraryBookContents {...props} />);
  return props;
}

function readableChapterButtons(): HTMLElement[] {
  return screen.queryAllByRole('button', { name: /^Đọc Ch\. \d/ });
}

describe('LibraryBookContents', () => {
  afterEach(() => {
    cleanup();
  });

  it('shows book context and exposes only translated chapters as exact Reader choices', async () => {
    const props = renderContents();

    expect(screen.getByRole('heading', { name: 'Mục lục' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Phàm Nhân Tu Tiên' })).toBeInTheDocument();
    expect(screen.getByText('Vong Ngữ')).toBeInTheDocument();
    expect(screen.getByText('3/5 chương đã dịch')).toBeInTheDocument();
    expect(readableChapterButtons()).toHaveLength(3);
    expect(screen.queryByRole('button', { name: 'Đọc Ch. 4 Chưa dịch' })).not.toBeInTheDocument();
    const firstListItem = screen.getAllByRole('listitem')[0];
    expect(firstListItem).toHaveAttribute('aria-posinset', '1');
    expect(firstListItem).toHaveAttribute('aria-setsize', '3');
    expect(firstListItem).toHaveAttribute('data-virtual-index', '0');
    expect(props.onOpenReader).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole('button', { name: 'Đọc Ch. 2 Thanh Ngưu trấn' }));
    expect(props.onOpenReader).toHaveBeenCalledWith(42, 12);

    await userEvent.click(screen.getByRole('button', { name: 'Tất cả truyện' }));
    expect(props.onBack).toHaveBeenCalledTimes(1);
  });

  it('searches Vietnamese titles without accents and orders the readable chapters', async () => {
    renderContents();
    const list = screen.getByRole('list', { name: 'Danh sách chương đã dịch' });

    expect(within(list).getAllByRole('button').map((button) => button.getAttribute('aria-label'))).toEqual([
      'Đọc Ch. 1 Sơn biên tiểu thôn',
      'Đọc Ch. 2 Thanh Ngưu trấn',
      'Đọc Ch. 3 Thất Huyền Môn',
    ]);

    await userEvent.click(screen.getByRole('button', { name: 'Cuối → đầu' }));
    expect(within(list).getAllByRole('button').map((button) => button.getAttribute('aria-label'))).toEqual([
      'Đọc Ch. 3 Thất Huyền Môn',
      'Đọc Ch. 2 Thanh Ngưu trấn',
      'Đọc Ch. 1 Sơn biên tiểu thôn',
    ]);

    await userEvent.type(screen.getByRole('searchbox', { name: 'Tìm trong mục lục' }), 'that huyen');
    expect(readableChapterButtons()).toHaveLength(1);
    expect(screen.getByRole('button', { name: 'Đọc Ch. 3 Thất Huyền Môn' })).toBeInTheDocument();
  });

  it('shows loading and request-error states with a retry action', async () => {
    const onRetry = vi.fn();
    const { rerender } = render(
      <LibraryBookContents
        book={book}
        chapters={{ data: [], error: '', state: 'loading' }}
        lastReadChapterId={null}
        onBack={vi.fn()}
        onOpenReader={vi.fn()}
        onRetry={onRetry}
      />,
    );

    expect(screen.getByText('Đang tải mục lục...')).toBeInTheDocument();
    expect(readableChapterButtons()).toHaveLength(0);

    rerender(
      <LibraryBookContents
        book={book}
        chapters={{ data: [], error: 'Mất kết nối', state: 'error' }}
        lastReadChapterId={null}
        onBack={vi.fn()}
        onOpenReader={vi.fn()}
        onRetry={onRetry}
      />,
    );

    expect(screen.getByRole('alert')).toHaveTextContent('Mất kết nối');
    await userEvent.click(screen.getByRole('button', { name: 'Thử tải lại mục lục' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('distinguishes no translated chapters from no search result', async () => {
    const { rerender } = render(
      <LibraryBookContents
        book={{ ...book, translated_chapters: 0 }}
        chapters={{ data: [chapterRows[3]], error: '', state: 'ready' }}
        lastReadChapterId={null}
        onBack={vi.fn()}
        onOpenReader={vi.fn()}
        onRetry={vi.fn()}
      />,
    );

    expect(screen.getByText('Truyện này chưa có chương đã dịch.')).toBeInTheDocument();

    rerender(
      <LibraryBookContents
        book={book}
        chapters={chapters}
        lastReadChapterId={null}
        onBack={vi.fn()}
        onOpenReader={vi.fn()}
        onRetry={vi.fn()}
      />,
    );
    await userEvent.type(screen.getByRole('searchbox', { name: 'Tìm trong mục lục' }), 'không tồn tại');

    expect(screen.getByText('Không tìm thấy chương phù hợp.')).toBeInTheDocument();
    expect(screen.queryByText('Truyện này chưa có chương đã dịch.')).not.toBeInTheDocument();
  });

  it('marks saved progress as last read without auto-opening it', () => {
    const onOpenReader = vi.fn();
    renderContents({ lastReadChapterId: 12, onOpenReader });

    const lastRead = screen.getByRole('button', { name: 'Đọc Ch. 2 Thanh Ngưu trấn' });
    expect(lastRead).toHaveAttribute('aria-current', 'true');
    expect(within(lastRead).getByText('Đọc gần nhất')).toBeInTheDocument();
    expect(screen.getByText('Đọc gần nhất: Ch. 2 · Thanh Ngưu trấn')).toBeInTheDocument();
    expect(onOpenReader).not.toHaveBeenCalled();
  });

  it('keeps a production-scale chapter list bounded', () => {
    const manyChapters = Array.from({ length: 700 }, (_, index): Chapter => ({
      id: 1000 + index,
      book_id: 42,
      chapter_number: index + 1,
      title: `Chương dài ${index + 1}`,
      status: 'translated',
      audio_path: null,
      has_translation: true,
    }));

    renderContents({
      chapters: { data: manyChapters, error: '', state: 'ready' },
      lastReadChapterId: manyChapters[649].id,
    });

    expect(readableChapterButtons().length).toBeGreaterThan(0);
    expect(readableChapterButtons().length).toBeLessThan(50);
    expect(screen.getByRole('button', { name: 'Đọc Ch. 650 Chương dài 650' })).toBeInTheDocument();
  });

  it('moves keyboard focus across virtual windows with Arrow, Home, and End', async () => {
    const user = userEvent.setup();
    const manyChapters = Array.from({ length: 120 }, (_, index): Chapter => ({
      id: 1000 + index,
      book_id: 42,
      chapter_number: index + 1,
      title: `Chương dài ${index + 1}`,
      status: 'translated',
      audio_path: null,
      has_translation: true,
    }));

    renderContents({
      chapters: { data: manyChapters, error: '', state: 'ready' },
      lastReadChapterId: manyChapters[59].id,
    });

    const chapter60 = screen.getByRole('button', { name: 'Đọc Ch. 60 Chương dài 60' });
    chapter60.focus();
    await user.keyboard('{ArrowDown}');
    expect(await screen.findByRole('button', { name: 'Đọc Ch. 61 Chương dài 61' })).toHaveFocus();

    await user.keyboard('{End}');
    expect(await screen.findByRole('button', { name: 'Đọc Ch. 120 Chương dài 120' })).toHaveFocus();
    expect(readableChapterButtons().length).toBeLessThan(50);

    await user.keyboard('{Home}');
    expect(await screen.findByRole('button', { name: 'Đọc Ch. 1 Chương dài 1' })).toHaveFocus();

    await user.keyboard('{ArrowUp}');
    expect(screen.getByRole('button', { name: 'Đọc Ch. 1 Chương dài 1' })).toHaveFocus();
    await user.keyboard('{ArrowDown}');
    expect(screen.getByRole('button', { name: 'Đọc Ch. 2 Chương dài 2' })).toHaveFocus();

    const search = screen.getByRole('searchbox', { name: 'Tìm trong mục lục' });
    await user.click(search);
    await user.type(search, '120');
    await user.clear(search);
    expect(search).toHaveFocus();
  });
});
