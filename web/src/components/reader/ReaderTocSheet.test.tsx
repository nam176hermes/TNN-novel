import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Chapter } from '../../api/types';
import ReaderTocSheet, { type TocChapterPreview } from './ReaderTocSheet';

const chapters: Chapter[] = [
  { id: 12, book_id: 1, chapter_number: 2, title: 'Thanh Ngưu trấn', status: 'translated', audio_path: null, has_translation: true },
  { id: 11, book_id: 1, chapter_number: 1, title: 'Sơn biên tiểu thôn', status: 'translated', audio_path: null, has_translation: true },
  { id: 13, book_id: 1, chapter_number: 3, title: 'Thất Huyền Môn', status: 'translated', audio_path: null, has_translation: true },
  { id: 14, book_id: 1, chapter_number: 4, title: 'Chưa dịch', status: 'cleaned', audio_path: null, has_translation: false },
];

const previews = new Map<number, TocChapterPreview>([
  [12, {
    readingState: 'reading',
    stateLabel: 'Đang đọc',
    timeLabel: '2 phút đọc',
    wordLabel: '420 từ',
  }],
]);

function renderToc(overrides: Partial<Parameters<typeof ReaderTocSheet>[0]> = {}) {
  const props = {
    author: 'Vong Ngữ',
    chapters,
    currentChapterId: 12,
    open: true,
    previews,
    title: 'Phàm Nhân Tu Tiên',
    onClose: vi.fn(),
    onSelectChapter: vi.fn(),
    ...overrides,
  };
  render(<ReaderTocSheet {...props} />);
  return props;
}

function chapterButtons() {
  return within(screen.getByRole('dialog', { name: 'Mục lục' }))
    .getAllByRole('button', { name: /^Ch\. \d/ });
}

describe('ReaderTocSheet', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('derives the translated count and list from raw chapter data', () => {
    renderToc();
    const drawer = screen.getByRole('dialog', { name: 'Mục lục' });

    expect(within(drawer).getByText('3 chương đã dịch')).toBeInTheDocument();
    expect(chapterButtons()).toHaveLength(3);
    expect(within(drawer).queryByRole('button', { name: 'Ch. 4 Chưa dịch' })).not.toBeInTheDocument();
  });

  it('sorts translated chapters in either direction without changing or navigating the current chapter', async () => {
    const props = renderToc();
    const drawer = screen.getByRole('dialog', { name: 'Mục lục' });

    expect(chapterButtons().map((button) => button.getAttribute('aria-label'))).toEqual([
      'Ch. 1 Sơn biên tiểu thôn',
      'Ch. 2 Thanh Ngưu trấn',
      'Ch. 3 Thất Huyền Môn',
    ]);
    expect(within(drawer).getByRole('button', { name: 'Ch. 2 Thanh Ngưu trấn' }))
      .toHaveAttribute('aria-current', 'true');

    await userEvent.click(within(drawer).getByRole('button', { name: 'Cuối → đầu' }));

    expect(chapterButtons().map((button) => button.getAttribute('aria-label'))).toEqual([
      'Ch. 3 Thất Huyền Môn',
      'Ch. 2 Thanh Ngưu trấn',
      'Ch. 1 Sơn biên tiểu thôn',
    ]);
    expect(within(drawer).getByRole('button', { name: 'Ch. 2 Thanh Ngưu trấn' }))
      .toHaveAttribute('aria-current', 'true');
    expect(props.onSelectChapter).not.toHaveBeenCalled();
  });

  it('matches Vietnamese chapter titles with an unaccented query', async () => {
    renderToc();
    const drawer = screen.getByRole('dialog', { name: 'Mục lục' });

    await userEvent.type(within(drawer).getByLabelText('Tìm trong mục lục'), 'that huyen');

    expect(chapterButtons()).toHaveLength(1);
    expect(within(drawer).getByRole('button', { name: 'Ch. 3 Thất Huyền Môn' })).toBeInTheDocument();
  });

  it('selects the first and latest translated chapters from shortcuts', async () => {
    const props = renderToc();
    const drawer = screen.getByRole('dialog', { name: 'Mục lục' });

    await userEvent.click(within(drawer).getByRole('button', { name: 'Về chương đầu' }));
    await userEvent.click(within(drawer).getByRole('button', { name: 'Đến chương mới nhất' }));

    expect(props.onSelectChapter).toHaveBeenNthCalledWith(1, 11);
    expect(props.onSelectChapter).toHaveBeenNthCalledWith(2, 13);
  });

  it('highlights the current chapter and keeps its reading preview', () => {
    renderToc();
    const current = screen.getByRole('button', { name: 'Ch. 2 Thanh Ngưu trấn' });

    expect(current).toHaveAttribute('aria-current', 'true');
    expect(within(current).getByText('420 từ')).toBeInTheDocument();
    expect(within(current).getByText('2 phút đọc')).toBeInTheDocument();
    expect(within(current).getByText('Đang đọc')).toHaveAttribute('data-state', 'reading');
  });

  it('focuses and scrolls the current chapter into view when opened', async () => {
    const originalScrollIntoView = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollIntoView');
    const scrollIntoView = vi.fn();
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: scrollIntoView,
    });

    try {
      renderToc();
      const current = screen.getByRole('button', { name: 'Ch. 2 Thanh Ngưu trấn' });

      await waitFor(() => expect(current).toHaveFocus());
      expect(scrollIntoView).toHaveBeenCalledTimes(1);
      expect(scrollIntoView.mock.contexts[0]).toBe(current);
    } finally {
      cleanup();
      if (originalScrollIntoView) {
        Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', originalScrollIntoView);
      } else {
        Reflect.deleteProperty(HTMLElement.prototype, 'scrollIntoView');
      }
    }
  });

  it('anchors when current chapter data arrives without stealing focus during query or order changes', async () => {
    const originalScrollIntoView = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollIntoView');
    const scrollIntoView = vi.fn();
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: scrollIntoView,
    });
    const props = {
      author: 'Vong Ngữ',
      chapters: [] as Chapter[],
      currentChapterId: 12,
      open: true,
      previews,
      title: 'Phàm Nhân Tu Tiên',
      onClose: vi.fn(),
      onSelectChapter: vi.fn(),
    };

    try {
      const { rerender } = render(<ReaderTocSheet {...props} />);
      expect(scrollIntoView).not.toHaveBeenCalled();

      rerender(<ReaderTocSheet {...props} chapters={chapters} />);
      const current = screen.getByRole('button', { name: 'Ch. 2 Thanh Ngưu trấn' });
      await waitFor(() => expect(current).toHaveFocus());
      expect(scrollIntoView).toHaveBeenCalledTimes(1);

      const search = screen.getByRole('searchbox', { name: 'Tìm trong mục lục' });
      await userEvent.type(search, 'thanh');
      expect(search).toHaveFocus();
      expect(scrollIntoView).toHaveBeenCalledTimes(1);

      await userEvent.clear(search);
      const descending = screen.getByRole('button', { name: 'Cuối → đầu' });
      await userEvent.click(descending);
      expect(descending).toHaveFocus();
      expect(scrollIntoView).toHaveBeenCalledTimes(1);
    } finally {
      cleanup();
      if (originalScrollIntoView) {
        Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', originalScrollIntoView);
      } else {
        Reflect.deleteProperty(HTMLElement.prototype, 'scrollIntoView');
      }
    }
  });
});
