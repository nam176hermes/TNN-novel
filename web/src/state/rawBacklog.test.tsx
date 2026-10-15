import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { RawBacklogPage } from '../api/types';
import { fixtureChapter } from '../test/fixtures';
import { useLibraryCatalog } from './useLibraryCatalog';
import { useAppJobs } from './useAppJobs';

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => { resolve = next; });
  return { promise, resolve };
}

describe('raw backlog pagination', () => {
  it('loads one page, aborts stale responses and clamps pages when the backlog shrinks', async () => {
    const first = deferred<RawBacklogPage>();
    const page: RawBacklogPage = {
      chapters: [{ ...fixtureChapter, status: 'cleaned', translated_text_path: null, book_title: 'Raw Book' }],
      total_chapters: 60, total_books: 1, book_counts: { 42: 60 }, offset: 50, limit: 50,
    };
    const getRawBacklog = vi.fn().mockReturnValueOnce(first.promise).mockResolvedValue(page);
    const options = {
      session: { client: { getRawBacklog }, isAuthenticated: true }, expireSession: vi.fn(), activeView: 'raw',
    } as unknown as Parameters<typeof useLibraryCatalog>[0];
    const { result, unmount } = renderHook(() => useLibraryCatalog(options));
    await waitFor(() => expect(getRawBacklog).toHaveBeenCalledTimes(1));
    const signal = getRawBacklog.mock.calls[0][2].signal as AbortSignal;
    act(() => result.current.setRawPage(1));
    await waitFor(() => expect(result.current.rawBacklogChapters.data[0]?.book_title).toBe('Raw Book'));
    expect(signal.aborted).toBe(true);
    expect(getRawBacklog.mock.calls[1].slice(0, 2)).toEqual([50, 50]);
    await act(async () => first.resolve({ ...page, chapters: [], total_chapters: 0 }));
    expect(result.current.rawBacklogInfo.total_chapters).toBe(60);
    getRawBacklog.mockResolvedValue({ ...page, offset: 0, total_chapters: 1, book_counts: { 42: 1 } });
    getRawBacklog.mockResolvedValueOnce({ ...page, chapters: [], total_chapters: 1 });
    await act(async () => { await result.current.loadRawBacklog(); });
    await waitFor(() => expect(result.current.rawPage).toBe(0));
    await waitFor(() => expect(result.current.rawBacklogInfo.total_chapters).toBe(1));
    const lastSignal = getRawBacklog.mock.calls[getRawBacklog.mock.calls.length - 1][2].signal as AbortSignal;
    unmount();
    expect(lastSignal.aborted).toBe(true);
  });

  it('fetches all raw IDs for a book once before starting a batch and handles an emptied backlog', async () => {
    const pending = deferred<number[]>();
    const ids = Array.from({ length: 60 }, (_, i) => 4200 + i);
    const client = {
      getRawChapterIds: vi.fn().mockReturnValueOnce(pending.promise).mockResolvedValue([]),
      startBookTranslateJob: vi.fn().mockResolvedValue(null), listJobs: vi.fn().mockResolvedValue([]),
    };
    const options = {
      session: { client, isAuthenticated: true }, expireSession: vi.fn(),
      setBackendError: vi.fn(), setBackendSuccess: vi.fn(), handleJobError: vi.fn(), setActiveView: vi.fn(),
      activeView: 'raw', library: { selectedBookId: null, selectedChapter: null },
      chapterText: { sourceText: '' }, qaState: {},
      providersState: { estimateForSource: vi.fn().mockResolvedValue(null) }, styleState: {},
      translatedBooks: { state: 'idle' }, rawBacklogChapters: { state: 'ready' },
      loadRawBacklog: vi.fn().mockResolvedValue([]),
    } as unknown as Parameters<typeof useAppJobs>[0];
    const { result } = renderHook(() => useAppJobs(options));
    let batch!: Promise<void>;
    act(() => { batch = result.current.handleBatchTranslateBook(42); });
    expect(result.current.rawBatchLoading).toBe(true);
    await act(async () => { await result.current.handleBatchTranslateBook(42); });
    expect(client.getRawChapterIds).toHaveBeenCalledTimes(1);
    await act(async () => { pending.resolve(ids); await batch; });
    expect(client.startBookTranslateJob).toHaveBeenCalledWith(42, expect.any(String), undefined, undefined,
      { chapterIds: ids, limit: 60 });
    expect(result.current.rawBatchLoading).toBe(false);
    await act(async () => { await result.current.handleBatchTranslateBook(42); });
    expect(client.startBookTranslateJob).toHaveBeenCalledTimes(1);
    expect(options.loadRawBacklog).toHaveBeenCalledTimes(1);
    expect(options.handleJobError).not.toHaveBeenCalled();
  });
});
