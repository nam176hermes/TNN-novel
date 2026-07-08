import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ReaderSearchResult } from '../../api/types';
import ReaderSearchPanel from './ReaderSearchPanel';

const currentResult: ReaderSearchResult = {
  chapter_id: 102,
  chapter_number: 2,
  chapter_title: 'Thanh Ngưu trấn',
  paragraph_index: 1,
  score: 99,
  snippet: 'Lục ca, ta cảm tạ huynh.',
  source: 'translation',
};

const bookResult: ReaderSearchResult = {
  chapter_id: 103,
  chapter_number: 3,
  chapter_title: 'Thất Huyền Môn',
  paragraph_index: 4,
  score: 85,
  snippet: 'Giữ xưng hô cổ trang.',
  source: 'note',
};

describe('ReaderSearchPanel', () => {
  afterEach(() => {
    cleanup();
  });

  it('does not render when closed', () => {
    render(
      <ReaderSearchPanel
        bookResults={[]}
        currentResults={[]}
        error=""
        loading={false}
        open={false}
        options={{}}
        query=""
        onClose={vi.fn()}
        onJump={vi.fn()}
        onOptionsChange={vi.fn()}
        onQueryChange={vi.fn()}
      />,
    );

    expect(screen.queryByRole('dialog', { name: 'Tìm trong truyện' })).not.toBeInTheDocument();
  });

  it('updates query and search options', async () => {
    const onOptionsChange = vi.fn();
    const onQueryChange = vi.fn();
    render(
      <ReaderSearchPanel
        bookResults={[]}
        currentResults={[]}
        error=""
        loading={false}
        open
        options={{ scopes: ['translation', 'notes', 'highlights'] }}
        query=""
        onClose={vi.fn()}
        onJump={vi.fn()}
        onOptionsChange={onOptionsChange}
        onQueryChange={onQueryChange}
      />,
    );

    const panel = screen.getByRole('dialog', { name: 'Tìm trong truyện' });
    await userEvent.type(within(panel).getByLabelText('Từ khóa'), 'Lục');
    await userEvent.click(within(panel).getByLabelText('Case sensitive'));
    await userEvent.click(within(panel).getByLabelText('Regex'));
    await userEvent.click(within(panel).getByLabelText('Highlights'));

    expect(onQueryChange).toHaveBeenLastCalledWith('c');
    expect(onOptionsChange).toHaveBeenCalledWith({
      scopes: ['translation', 'notes', 'highlights'],
      caseSensitive: true,
    });
    expect(onOptionsChange).toHaveBeenCalledWith({
      scopes: ['translation', 'notes', 'highlights'],
      regex: true,
    });
    expect(onOptionsChange).toHaveBeenCalledWith({
      scopes: ['translation', 'notes'],
    });
  });

  it('renders current and full-book results and jumps to the chosen paragraph', async () => {
    const onJump = vi.fn();
    render(
      <ReaderSearchPanel
        bookResults={[bookResult]}
        currentResults={[currentResult]}
        error=""
        loading
        open
        options={{}}
        query="Lục"
        onClose={vi.fn()}
        onJump={onJump}
        onOptionsChange={vi.fn()}
        onQueryChange={vi.fn()}
      />,
    );

    const panel = screen.getByRole('dialog', { name: 'Tìm trong truyện' });
    expect(within(panel).getByText('Lục ca, ta cảm tạ huynh.')).toBeInTheDocument();
    expect(within(panel).getByText('Giữ xưng hô cổ trang.')).toBeInTheDocument();
    expect(within(panel).getByLabelText('Đang tìm toàn bộ sách')).toBeInTheDocument();

    await userEvent.click(within(panel).getByRole('button', { name: 'Đến Ch. 3 đoạn 5' }));
    expect(onJump).toHaveBeenCalledWith(bookResult);
  });
});
