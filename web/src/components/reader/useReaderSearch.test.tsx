import { act, renderHook } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { ReaderSearchResult } from '../../api/types';
import { useReaderSearch } from './useReaderSearch';

afterEach(() => vi.useRealTimers());

it('aborts an obsolete book search when the query changes or the reader closes', async () => {
  vi.useFakeTimers();
  const searchBook = vi.fn().mockImplementation(() => new Promise<ReaderSearchResult[]>(() => {}));
  const options = {
    apiClient: { searchBook }, activeBookId: 42, selectedChapter: null,
    chapterMarks: { bookmarked: false, highlights: [], notes: [] }, progressTextBlocks: [],
  };
  const { result, unmount } = renderHook(() => useReaderSearch(options));
  act(() => { result.current.setReaderSearchOpen(true); result.current.setReaderSearchQuery('first'); });
  await act(() => vi.advanceTimersByTimeAsync(301));
  const first = searchBook.mock.calls[0][3].signal as AbortSignal;
  expect(first.aborted).toBe(false);
  act(() => result.current.setReaderSearchQuery('second'));
  expect(first.aborted).toBe(true);
  await act(() => vi.advanceTimersByTimeAsync(301));
  const second = searchBook.mock.calls[1][3].signal as AbortSignal;
  expect(second.aborted).toBe(false);
  unmount();
  expect(second.aborted).toBe(true);
});
