import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import App from '../App';
import { clearToken, saveToken } from '../state/session';
import { fixtureUsage } from '../test/fixtures';
import ChapterDetailPanel from './ChapterDetailPanel';
import ChapterTable from './ChapterTable';
import LibraryRail from './LibraryRail';

describe('Pipeline dashboard components', () => {
  afterEach(() => {
    cleanup();
    clearToken();
    vi.unstubAllGlobals();
  });

  const book = {
    id: 1,
    title: 'Phàm Nhân Tu Tiên',
    translated: 8,
    audio: 3,
    failed: 1,
    total: 10,
  };

  const chapter = {
    id: 11,
    book_id: 1,
    chapter_number: 1,
    title: 'Sơn biên tiểu thôn',
    status: 'translated',
    qa_score: 8.2,
    audio_path: '',
  };

  it('renders library, chapter table, and detail panel', () => {
    render(
      <>
        <LibraryRail books={[book]} activeBookId={1} onSelectBook={() => undefined} />
        <ChapterTable chapters={[chapter]} selectedChapterId={11} onSelectChapter={() => undefined} />
        <ChapterDetailPanel chapter={chapter} />
      </>,
    );

    expect(screen.getByText('Phàm Nhân Tu Tiên')).toBeInTheDocument();
    expect(screen.getAllByText('Sơn biên tiểu thôn')[0]).toBeInTheDocument();
    expect(screen.getByText('QA 8.2')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Translate' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Run QA' })).toBeInTheDocument();
  });

  it('composes the app shell without runtime seed data', async () => {
    saveToken('access');
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: RequestInfo | URL) => {
        const target = String(url);

        if (target.endsWith('/api/providers')) return { ok: true, json: async () => ({ providers: [] }) };
        if (target.endsWith('/api/style-profiles')) return { ok: true, json: async () => ({ profiles: [] }) };
        if (target.endsWith('/api/library/books')) return { ok: true, json: async () => ({ books: [] }) };
        if (target.endsWith('/api/books')) return { ok: true, json: async () => [] };
        if (target.endsWith('/api/providers/usage')) {
          return { ok: true, json: async () => ({ usage: fixtureUsage }) };
        }

        throw new Error(`Unexpected URL: ${target}`);
      }),
    );

    render(<App />);

    expect(screen.getByRole('heading', { name: 'Novel-TNN' })).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'Quy trình' })).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: 'Thư viện' })).toBeInTheDocument();
    expect(screen.queryByText('Sơn biên tiểu thôn')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Chapter editor')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Translate' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Run QA' })).not.toBeInTheDocument();
  });
});
