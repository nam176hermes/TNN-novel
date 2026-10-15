import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { BookSummary, Chapter } from '../api/types';
import RawBacklogView from './RawBacklogView';

const books: BookSummary[] = [
  {
    id: 1,
    title: 'Thanh Sơn',
    total: 3,
    translated: 1,
    audio: 0,
    failed: 0,
  },
  {
    id: 2,
    title: 'Cầu Ma',
    total: 1,
    translated: 1,
    audio: 0,
    failed: 0,
  },
];

const chapters: Chapter[] = [
  {
    id: 11,
    book_id: 1,
    book_title: 'Thanh Sơn',
    chapter_number: 1,
    title: 'Vào núi',
    status: 'cleaned',
    audio_path: '',
    has_translation: false,
    source_preview: 'Có bản nguồn đã làm sạch',
  },
  {
    id: 12,
    book_id: 1,
    book_title: 'Thanh Sơn',
    chapter_number: 2,
    title: 'Kiếm ý',
    status: 'translated',
    audio_path: '',
    has_translation: true,
  },
  {
    id: 21,
    book_id: 2,
    book_title: 'Cầu Ma',
    chapter_number: 1,
    title: 'Man Khải',
    status: 'translated',
    audio_path: '',
    has_translation: true,
  },
];

describe('RawBacklogView', () => {
  afterEach(() => {
    cleanup();
  });

  it('lists only raw chapters that do not have translations', async () => {
    const onOpenWorkbench = vi.fn();

    render(
      <RawBacklogView
        books={books}
        chapters={{ data: chapters, error: '', state: 'ready' }}
        onOpenImport={vi.fn()}
        onOpenWorkbench={onOpenWorkbench}
        onRefresh={vi.fn()}
      />,
    );

    expect(screen.getByRole('heading', { name: 'Raw chưa dịch' })).toBeInTheDocument();
    expect(screen.getByText('Thanh Sơn')).toBeInTheDocument();
    expect(screen.getByText('Ch. 1 · Vào núi')).toBeInTheDocument();
    expect(screen.queryByText('Kiếm ý')).not.toBeInTheDocument();
    expect(screen.queryByText('Cầu Ma')).not.toBeInTheDocument();

    const row = screen.getByRole('article', { name: 'Thanh Sơn chương 1' });
    await userEvent.click(within(row).getByRole('button', { name: 'Mở bàn dịch Thanh Sơn chương 1' }));

    expect(onOpenWorkbench).toHaveBeenCalledWith(1, 11);
  });

  it('shows an empty state when every loaded chapter is translated', () => {
    render(
      <RawBacklogView
        books={books}
        chapters={{ data: chapters.filter((chapter) => chapter.has_translation), error: '', state: 'ready' }}
        onOpenImport={vi.fn()}
        onOpenWorkbench={vi.fn()}
        onRefresh={vi.fn()}
      />,
    );

    expect(screen.getByText('Không còn chương raw đang chờ dịch.')).toBeInTheDocument();
  });

  it('opens the first raw chapter from the book overflow control', async () => {
    const onOpenWorkbench = vi.fn();
    render(
      <RawBacklogView
        books={books}
        chapters={{ data: chapters, error: '', state: 'ready' }}
        onOpenImport={vi.fn()}
        onOpenWorkbench={onOpenWorkbench}
        onRefresh={vi.fn()}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Mở chương raw đầu tiên của Thanh Sơn' }));

    expect(onOpenWorkbench).toHaveBeenCalledWith(1, 11);
  });

  it('starts batch translation for the raw book group', async () => {
    const onBatchTranslate = vi.fn();
    render(
      <RawBacklogView
        books={books}
        chapters={{ data: chapters, error: '', state: 'ready' }}
        onBatchTranslate={onBatchTranslate}
        onOpenImport={vi.fn()}
        onOpenWorkbench={vi.fn()}
        onRefresh={vi.fn()}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Dịch 1 chương' }));

    expect(onBatchTranslate).toHaveBeenCalledWith(1, [11]);
  });

  it('uses server totals and translates the whole book across pages', async () => {
    const onBatchTranslateBook = vi.fn();
    const onPageChange = vi.fn();
    const onOpenWorkbench = vi.fn();
    render(<RawBacklogView
      books={books} chapters={{ data: [chapters[0]], error: '', state: 'ready' }}
      backlog={{ total_chapters: 117, total_books: 2, book_counts: { 1: 57 }, first_chapter_ids: { 1: 7 }, offset: 50, limit: 50 }}
      page={1}
      onBatchTranslateBook={onBatchTranslateBook} onPageChange={onPageChange}
      onOpenImport={vi.fn()} onOpenWorkbench={onOpenWorkbench} onRefresh={vi.fn()}
    />);
    expect(screen.getByText('117')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Dịch theo từng truyện' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: 'Dịch 57 chương' }));
    expect(onBatchTranslateBook).toHaveBeenCalledWith(1);
    await userEvent.click(screen.getByRole('button', { name: 'Mở chương raw đầu tiên của Thanh Sơn' }));
    expect(onOpenWorkbench).toHaveBeenCalledWith(1, 7);
    expect(screen.getByRole('button', { name: 'Trang raw trước' })).not.toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: 'Trang raw sau' }));
    expect(onPageChange).toHaveBeenCalledWith(2);
  });
});
