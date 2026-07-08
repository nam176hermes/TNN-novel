import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ReaderMarksPanel, { type ReaderMarkPanelItem } from './ReaderMarksPanel';

const items: ReaderMarkPanelItem[] = [
  {
    id: 'bookmark-42-101',
    bookId: 42,
    chapterId: 101,
    chapterNumber: 1,
    chapterTitle: 'Sơn biên tiểu thôn',
    kind: 'bookmark',
    paragraphIndex: 0,
    text: 'Đánh dấu chương',
  },
  {
    id: 'highlight-7',
    annotationId: 7,
    bookId: 42,
    chapterId: 102,
    chapterNumber: 2,
    chapterTitle: 'Thanh Ngưu trấn',
    kind: 'highlight',
    paragraphIndex: 3,
    text: 'Hàn Lập khẽ gật đầu.',
  },
  {
    id: 'note-8',
    annotationId: 8,
    bookId: 42,
    chapterId: 102,
    chapterNumber: 2,
    chapterTitle: 'Thanh Ngưu trấn',
    kind: 'note',
    paragraphIndex: 4,
    text: 'Lục ca, ta cảm tạ huynh.',
    note: 'Giữ xưng hô cổ trang.',
  },
];

describe('ReaderMarksPanel', () => {
  afterEach(() => {
    cleanup();
  });

  it('does not render when closed', () => {
    render(<ReaderMarksPanel items={items} open={false} onClose={vi.fn()} onJump={vi.fn()} />);

    expect(screen.queryByRole('dialog', { name: 'Dấu đọc' })).not.toBeInTheDocument();
  });

  it('filters bookmarks, highlights, and notes and jumps to a paragraph', async () => {
    const onJump = vi.fn();
    render(<ReaderMarksPanel items={items} open onClose={vi.fn()} onJump={onJump} />);
    const panel = screen.getByRole('dialog', { name: 'Dấu đọc' });

    expect(within(panel).getByText('Ch. 1')).toBeInTheDocument();
    expect(within(panel).getByText('Sơn biên tiểu thôn')).toBeInTheDocument();
    expect(within(panel).queryByText('Hàn Lập khẽ gật đầu.')).not.toBeInTheDocument();

    await userEvent.click(within(panel).getByRole('button', { name: 'Highlights' }));
    expect(within(panel).getByText('Ch. 2')).toBeInTheDocument();
    expect(within(panel).getByText('Thanh Ngưu trấn')).toBeInTheDocument();
    await userEvent.click(within(panel).getByRole('button', { name: /Đến Ch. 2 đoạn 4/ }));
    expect(onJump).toHaveBeenCalledWith(items[1]);

    await userEvent.click(within(panel).getByRole('button', { name: 'Notes' }));
    expect(within(panel).getByText('Giữ xưng hô cổ trang.')).toBeInTheDocument();
  });

  it('exports the currently selected mark kind from the marks panel', async () => {
    const onExport = vi.fn();
    render(
      <ReaderMarksPanel
        items={items}
        open
        onClose={vi.fn()}
        onExport={onExport}
        onJump={vi.fn()}
      />,
    );
    const panel = screen.getByRole('dialog', { name: 'Dấu đọc' });

    await userEvent.click(within(panel).getByRole('button', { name: 'Highlights' }));
    await userEvent.click(within(panel).getByRole('button', { name: 'Xuất JSON highlights' }));

    expect(onExport).toHaveBeenCalledWith('json', 'highlight');
  });
});
