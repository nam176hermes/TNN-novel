import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ReaderDictionaryPanel from './ReaderDictionaryPanel';

describe('ReaderDictionaryPanel', () => {
  afterEach(() => {
    cleanup();
  });

  it('shows built-in CN-VI dictionary sources and cache status', () => {
    render(
      <ReaderDictionaryPanel
        error=""
        includeOnline
        loading={false}
        open
        query="灵石"
        result={{
          book_id: 1,
          cache: {
            hit: true,
            scope: 'online',
            stored: false,
            updated_at: '2026-06-29T10:00:00Z',
          },
          chapter_id: null,
          offline_count: 1,
          online: {
            count: 0,
            error: '',
            status: 'empty',
          },
          query: '灵石',
          sources: [
            {
              category: 'item',
              definition: 'Đá chứa linh khí, thường dùng để tu luyện.',
              provider: 'cn-vi-webnovel-lexicon',
              source: 'builtin',
              target: 'linh thạch',
              term: '灵石',
              variants: ['linh thạch'],
            },
          ],
        }}
        onClose={vi.fn()}
        onIncludeOnlineChange={vi.fn()}
        onRetry={vi.fn()}
      />,
    );

    const panel = screen.getByRole('dialog', { name: 'Từ điển đọc truyện' });
    expect(within(panel).getByText('1 offline · online empty · cache hit')).toBeInTheDocument();
    expect(within(panel).getByText('Built-in · cn-vi-webnovel-lexicon')).toBeInTheDocument();
    expect(within(panel).getByText('linh thạch')).toBeInTheDocument();
    expect(within(panel).getByText('Đá chứa linh khí, thường dùng để tu luyện.')).toBeInTheDocument();
  });

  it('shows file-backed offline dictionary sources with the dictionary filename', () => {
    render(
      <ReaderDictionaryPanel
        error=""
        includeOnline={false}
        loading={false}
        open
        query="đạo tâm"
        result={{
          book_id: 1,
          chapter_id: null,
          offline_count: 1,
          online: {
            count: 0,
            error: '',
            status: 'skipped',
          },
          query: 'đạo tâm',
          sources: [
            {
              category: 'concept',
              definition: 'Tâm cảnh tu đạo, căn cơ ý chí của tu sĩ.',
              provider: 'reader_cn_vi.tsv',
              source: 'offline_dictionary',
              target: 'đạo tâm',
              term: '道心',
              variants: ['dao tam'],
            },
          ],
        }}
        onClose={vi.fn()}
        onIncludeOnlineChange={vi.fn()}
        onRetry={vi.fn()}
      />,
    );

    const panel = screen.getByRole('dialog', { name: 'Từ điển đọc truyện' });
    expect(within(panel).getByText('Offline dictionary · reader_cn_vi.tsv')).toBeInTheDocument();
    expect(within(panel).getAllByText('đạo tâm').length).toBeGreaterThan(0);
  });
});
