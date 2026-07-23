import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '../api/client';
import { ApiClient } from '../api/client';
import { fixtureBook, fixtureChapter } from '../test/fixtures';
import { useLibrary } from './useLibrary';

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });

  return { promise, resolve };
}

describe('useLibrary', () => {
  it('loads books and chapters from backend and selects the first live chapter', async () => {
    const client = {
      getBooks: vi.fn().mockResolvedValue([fixtureBook]),
      getChapters: vi.fn().mockResolvedValue([fixtureChapter]),
    } as unknown as ApiClient;

    const { result } = renderHook(() => useLibrary(client, true));

    await waitFor(() => expect(result.current.books.state).toBe('ready'));
    await waitFor(() => expect(result.current.chapters.state).toBe('ready'));

    expect(result.current.books.data[0].title).toBe('Live Book');
    expect(result.current.selectedBookId).toBe(42);
    expect(result.current.selectedChapterId).toBe(4201);
    expect(client.getChapters).toHaveBeenCalledWith(42);
  });

  it('clears selection and chapters when backend returns no books', async () => {
    const client = {
      getBooks: vi.fn().mockResolvedValue([]),
      getChapters: vi.fn(),
    } as unknown as ApiClient;

    const { result } = renderHook(() => useLibrary(client, true));

    await waitFor(() => expect(result.current.books.state).toBe('empty'));

    expect(result.current.books.data).toEqual([]);
    expect(result.current.chapters.data).toEqual([]);
    expect(result.current.selectedBookId).toBeNull();
    expect(result.current.selectedChapterId).toBeNull();
    expect(client.getChapters).not.toHaveBeenCalled();
  });

  it('ignores stale out-of-order chapter results when switching books', async () => {
    const slowChapters = deferred<Array<typeof fixtureChapter>>();
    const fastChapters = deferred<Array<typeof fixtureChapter>>();
    const client = {
      getBooks: vi.fn().mockResolvedValue([
        fixtureBook,
        { ...fixtureBook, id: 43, title: 'Second Book' },
      ]),
      getChapters: vi.fn((bookId: number) => {
        if (bookId === 42) return slowChapters.promise;
        if (bookId === 43) return fastChapters.promise;
        throw new Error(`Unexpected book ${bookId}`);
      }),
    } as unknown as ApiClient;

    const { result } = renderHook(() => useLibrary(client, true));

    await waitFor(() => expect(result.current.selectedBookId).toBe(42));

    act(() => result.current.setSelectedBookId(43));

    await waitFor(() => expect(client.getChapters).toHaveBeenCalledWith(43));

    fastChapters.resolve([{ ...fixtureChapter, id: 4301, book_id: 43, title: 'Fresh Chapter' }]);

    await waitFor(() => expect(result.current.chapters.data[0]?.id).toBe(4301));
    expect(result.current.selectedBookId).toBe(43);
    expect(result.current.selectedChapterId).toBe(4301);

    slowChapters.resolve([fixtureChapter]);

    await waitFor(() => expect(result.current.chapters.data[0]?.id).toBe(4301));
    expect(result.current.selectedBookId).toBe(43);
    expect(result.current.selectedChapterId).toBe(4301);
    expect(result.current.chapters.data[0]?.book_id).toBe(43);
  });

  it('dedupes concurrent chapter refreshes for the same book', async () => {
    const chapters = deferred<Array<typeof fixtureChapter>>();
    const client = {
      getBooks: vi.fn().mockResolvedValue([fixtureBook]),
      getChapters: vi.fn().mockReturnValue(chapters.promise),
    } as unknown as ApiClient;

    const { result } = renderHook(() => useLibrary(client, true));

    await waitFor(() => expect(result.current.selectedBookId).toBe(42));
    await waitFor(() => expect(client.getChapters).toHaveBeenCalledTimes(1));

    void act(() => {
      void result.current.refreshChapters(42);
      void result.current.refreshChapters(42);
    });

    expect(client.getChapters).toHaveBeenCalledTimes(1);
    chapters.resolve([fixtureChapter]);

    await waitFor(() => expect(result.current.chapters.state).toBe('ready'));
    expect(result.current.chapters.data).toHaveLength(1);
  });

  it('calls onAuthError when books load returns 401', async () => {
    const onAuthError = vi.fn();
    const client = {
      getBooks: vi.fn().mockRejectedValue(new ApiError('Expired', 401)),
      getChapters: vi.fn(),
    } as unknown as ApiClient;

    renderHook(() => useLibrary(client, true, onAuthError));

    await waitFor(() => expect(onAuthError).toHaveBeenCalledTimes(1));
  });

  it('renames a loaded book while preserving chapter counters', async () => {
    const client = {
      getBooks: vi.fn().mockResolvedValue([fixtureBook]),
      getChapters: vi.fn().mockResolvedValue([fixtureChapter]),
      updateBook: vi.fn().mockResolvedValue({
        ...fixtureBook,
        title: 'Đạo Quỷ Dị Tiên',
      }),
    } as unknown as ApiClient;

    const { result } = renderHook(() => useLibrary(client, true));

    await waitFor(() => expect(result.current.chapters.state).toBe('ready'));

    await act(async () => {
      await result.current.renameBook(42, 'Đạo Quỷ Dị Tiên');
    });

    expect(client.updateBook).toHaveBeenCalledWith(42, { title: 'Đạo Quỷ Dị Tiên' });
    expect(result.current.books.data[0]).toMatchObject({
      id: 42,
      title: 'Đạo Quỷ Dị Tiên',
      translated: 1,
      total: 1,
    });
    expect(result.current.activeChapters[0]).toMatchObject({
      id: 4201,
      book_title: 'Đạo Quỷ Dị Tiên',
    });
  });

  it('refreshes books when rename merges into an existing book id', async () => {
    const mergedBook = {
      ...fixtureBook,
      id: 43,
      title: 'Thanh Sơn raw',
    };
    const client = {
      getBooks: vi
        .fn()
        .mockResolvedValueOnce([fixtureBook, mergedBook])
        .mockResolvedValueOnce([fixtureBook]),
      getChapters: vi.fn().mockResolvedValue([fixtureChapter]),
      updateBook: vi.fn().mockResolvedValue({
        ...fixtureBook,
        title: 'Live Book',
      }),
    } as unknown as ApiClient;

    const { result } = renderHook(() => useLibrary(client, true));

    await waitFor(() => expect(result.current.books.data).toHaveLength(2));

    await act(async () => {
      await result.current.renameBook(43, 'Live Book');
    });

    expect(client.updateBook).toHaveBeenCalledWith(43, { title: 'Live Book' });
    expect(client.getBooks).toHaveBeenCalledTimes(2);
    expect(result.current.books.data).toHaveLength(1);
    expect(result.current.books.data[0]).toMatchObject({ id: 42, title: 'Live Book' });
  });
});
