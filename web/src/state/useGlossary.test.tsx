import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ApiError, ApiClient } from '../api/client';
import { fixtureGlossaryTerm } from '../test/fixtures';
import { useGlossary } from './useGlossary';

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });

  return { promise, resolve };
}

describe('useGlossary', () => {
  it('exposes the phase 4 mutation and preview workflow through the current book', async () => {
    const page = {
      facets: { locked: {}, mode: {}, review_status: {}, scope: {}, term_type: {} },
      items: [{ ...fixtureGlossaryTerm, version: 3 }],
      page: 1, pages: 1, per_page: 50, scope: 'book' as const, total: 1,
    };
    const client = {
      applyGlossaryImport: vi.fn().mockResolvedValue({ added: 1, updated: 0, skipped: 0, errors: [] }),
      applyGlossaryMerge: vi.fn().mockResolvedValue({ merged: 1 }),
      archiveGlossaryTerm: vi.fn().mockResolvedValue(undefined),
      bulkGlossaryTerms: vi.fn().mockResolvedValue(undefined),
      createGlossaryTerm: vi.fn().mockResolvedValue(fixtureGlossaryTerm),
      getGlossaryConflicts: vi.fn().mockResolvedValue({ items: [], page: 1, pages: 0, per_page: 50, total: 0 }),
      previewGlossaryImport: vi.fn().mockResolvedValue({ digest: 'i'.repeat(64) }),
      previewGlossaryMerge: vi.fn().mockResolvedValue({ digest: 'm'.repeat(64) }),
      queryGlossaryTerms: vi.fn().mockResolvedValue(page),
      restoreGlossaryTerm: vi.fn().mockResolvedValue(undefined),
      searchTm: vi.fn(),
    } as unknown as ApiClient;
    const { result } = renderHook(() => useGlossary(client, true, 42, '', undefined, true));
    await waitFor(() => expect(result.current.terms.state).toBe('ready'));
    const refs = [{ id: 7, expected_version: 3 }];
    const items = [{ source_term: '新词', target_term: 'Từ mới' }];

    await act(async () => {
      await result.current.bulkTerms('approve', refs);
      await result.current.archiveTerm(7);
      await result.current.restoreTerm(7);
      await result.current.createTerm(items[0]);
      await result.current.loadConflicts();
      await result.current.previewMerge(7, [8]);
      await result.current.applyMerge(7, [8], 'm'.repeat(64));
      await result.current.previewImport(items);
      await result.current.applyImport(items, 'i'.repeat(64));
    });

    expect(client.bulkGlossaryTerms).toHaveBeenCalledWith('approve', refs);
    expect(client.createGlossaryTerm).toHaveBeenCalledWith(expect.objectContaining({ book_id: 42 }));
    expect(client.getGlossaryConflicts).toHaveBeenCalledWith(42, 1);
    expect(client.applyGlossaryMerge).toHaveBeenCalledWith(7, [8], 'm'.repeat(64));
    expect(client.applyGlossaryImport).toHaveBeenCalledWith(items, 'i'.repeat(64), 'skip_conflicts');
  });

  it('propagates phase 4 mutation failures and does not refresh stale success state', async () => {
    const failure = new ApiError('Conflict', 409, 'unresolved_conflict');
    const page = {
      facets: { locked: {}, mode: {}, review_status: {}, scope: {}, term_type: {} },
      items: [{ ...fixtureGlossaryTerm, version: 3 }],
      page: 1, pages: 1, per_page: 50, scope: 'book' as const, total: 1,
    };
    const client = {
      bulkGlossaryTerms: vi.fn().mockRejectedValue(failure),
      queryGlossaryTerms: vi.fn().mockResolvedValue(page),
      searchTm: vi.fn(),
    } as unknown as ApiClient;
    const { result } = renderHook(() => useGlossary(client, true, 42, '', undefined, true));
    await waitFor(() => expect(result.current.terms.state).toBe('ready'));

    await act(async () => {
      await expect(
        result.current.bulkTerms('approve', [{ id: 7, expected_version: 3 }]),
      ).rejects.toBe(failure);
    });

    expect(client.queryGlossaryTerms).toHaveBeenCalledTimes(1);
    expect(result.current.terms.data[0]?.version).toBe(3);
  });

  it('requests the default queue and aborts a stale server page request', async () => {
    const first = deferred<never>();
    const page = {
      facets: { locked: {}, mode: {}, review_status: {}, scope: {}, term_type: {} },
      items: [fixtureGlossaryTerm],
      page: 1,
      pages: 1,
      per_page: 50,
      scope: 'book' as const,
      total: 1,
    };
    const queryGlossaryTerms = vi
      .fn()
      .mockImplementationOnce((_query, options) => {
        options.signal.addEventListener('abort', () => first.resolve(undefined as never));
        return first.promise;
      })
      .mockResolvedValueOnce(page);
    const client = { queryGlossaryTerms, searchTm: vi.fn() } as unknown as ApiClient;
    const { result } = renderHook(() => useGlossary(client, true, 42, '筑基'));

    await waitFor(() => expect(queryGlossaryTerms).toHaveBeenCalledTimes(1));
    expect(queryGlossaryTerms.mock.calls[0][0]).toMatchObject({
      book_id: 42,
      page: 1,
      per_page: 50,
      review_status: 'NEEDS_REVIEW,CONFLICT',
      scope: 'book',
    });

    act(() => result.current.setQuery({ review_status: 'APPROVED' }));

    await waitFor(() => expect(queryGlossaryTerms).toHaveBeenCalledTimes(2));
    expect(queryGlossaryTerms.mock.calls[0][1].signal.aborted).toBe(true);
    await waitFor(() => expect(result.current.terms.data[0]?.source_term).toBe('筑基'));
  });

  it('loads glossary terms, derives pending count, finds source hits, and searches TM', async () => {
    const client = {
      getGlossaryTerms: vi.fn().mockResolvedValue([fixtureGlossaryTerm]),
      searchTm: vi.fn().mockResolvedValue([
        { source_text: '他筑基成功', translation_text: 'Hắn Trúc Cơ thành công', match_score: 92 },
      ]),
    } as unknown as ApiClient;

    const { result } = renderHook(() => useGlossary(client, true, 42, '他开始筑基。'));

    await waitFor(() => expect(result.current.terms.state).toBe('ready'));
    expect(client.getGlossaryTerms).toHaveBeenCalledWith(
      42,
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(result.current.pendingCount).toBe(1);
    expect(result.current.relevantTerms[0].source_term).toBe('筑基');

    await act(async () => result.current.searchTranslationMemory('他筑基成功'));
    expect(result.current.tmResults[0].match_score).toBe(92);
  });

  it('calls onAuthError when glossary load returns 401', async () => {
    const onAuthError = vi.fn();
    const client = {
      getGlossaryTerms: vi.fn().mockRejectedValue(new ApiError('Expired', 401)),
      searchTm: vi.fn(),
    } as unknown as ApiClient;

    renderHook(() => useGlossary(client, true, 42, '筑基', onAuthError));

    await waitFor(() => expect(onAuthError).toHaveBeenCalledTimes(1));
  });

  it('ignores stale glossary loads and stale TM searches', async () => {
    const slowTerms = deferred<typeof fixtureGlossaryTerm[]>();
    const fastTerms = deferred<typeof fixtureGlossaryTerm[]>();
    const slowTm = deferred<Array<{ source_text: string; translation_text: string; match_score: number }>>();
    const fastTm = deferred<Array<{ source_text: string; translation_text: string; match_score: number }>>();
    const client = {
      getGlossaryTerms: vi
        .fn()
        .mockImplementationOnce(() => slowTerms.promise)
        .mockImplementationOnce(() => fastTerms.promise),
      searchTm: vi
        .fn()
        .mockImplementationOnce(() => slowTm.promise)
        .mockImplementationOnce(() => fastTm.promise),
    } as unknown as ApiClient;

    const { result, rerender } = renderHook(
      ({ bookId, sourceText }) => useGlossary(client, true, bookId, sourceText),
      { initialProps: { bookId: 42 as number | null, sourceText: '筑基' } },
    );

    rerender({ bookId: 43, sourceText: '结丹' });

    fastTerms.resolve([{ ...fixtureGlossaryTerm, id: 8, book_id: 43, source_term: '结丹', target_term: 'Kết Đan' }]);
    await waitFor(() => expect(result.current.terms.data[0]?.source_term).toBe('结丹'));

    await act(async () => {
      const slowPromise = result.current.searchTranslationMemory('慢');
      const fastPromise = result.current.searchTranslationMemory('快');
      fastTm.resolve([{ source_text: '快', translation_text: 'Fast', match_score: 95 }]);
      await fastPromise;
      slowTm.resolve([{ source_text: '慢', translation_text: 'Slow', match_score: 10 }]);
      await expect(slowPromise).resolves.toEqual([]);
    });

    slowTerms.resolve([fixtureGlossaryTerm]);

    await waitFor(() => expect(result.current.terms.data[0]?.source_term).toBe('结丹'));
    expect(result.current.tmResults[0]?.source_text).toBe('快');
  });

  it('does not refresh an old book after a term update resolves post-navigation', async () => {
    const updateTerm = deferred<void>();
    const client = {
      getGlossaryTerms: vi.fn(async (bookId: number) => {
        if (bookId === 42) return [fixtureGlossaryTerm];
        if (bookId === 43) {
          return [
            { ...fixtureGlossaryTerm, id: 8, book_id: 43, source_term: '结丹', target_term: 'Kết Đan' },
          ];
        }
        throw new Error(`Unexpected glossary book ${bookId}`);
      }),
      updateGlossaryTerm: vi.fn().mockReturnValue(updateTerm.promise),
      searchTm: vi.fn(),
    } as unknown as ApiClient;

    const { result, rerender } = renderHook(
      ({ bookId, sourceText }) => useGlossary(client, true, bookId, sourceText),
      { initialProps: { bookId: 42 as number | null, sourceText: '筑基' } },
    );

    await waitFor(() => expect(result.current.terms.data[0]?.source_term).toBe('筑基'));

    let mutation!: Promise<void>;
    act(() => {
      mutation = result.current.updateTerm(7, { target_term: 'Trúc Cơ mới' });
    });

    rerender({ bookId: 43, sourceText: '结丹' });
    await waitFor(() => expect(result.current.terms.data[0]?.source_term).toBe('结丹'));

    updateTerm.resolve();
    await act(async () => {
      await mutation;
    });

    expect(result.current.terms.data[0]?.source_term).toBe('结丹');
    expect(client.getGlossaryTerms).toHaveBeenCalledTimes(2);
  });

  it('resets the review queue to page one before loading a different book', async () => {
    const queryGlossaryTerms = vi.fn(async (requestedQuery) => ({
      facets: { locked: {}, mode: {}, review_status: {}, scope: {}, term_type: {} },
      items: [{
        ...fixtureGlossaryTerm,
        book_id: requestedQuery.book_id,
        source_term: requestedQuery.book_id === 42 ? '筑基' : '结丹',
      }],
      page: requestedQuery.page,
      pages: requestedQuery.book_id === 42 ? 3 : 1,
      per_page: 50,
      scope: 'book' as const,
      total: requestedQuery.book_id === 42 ? 101 : 1,
    }));
    const client = { queryGlossaryTerms, searchTm: vi.fn() } as unknown as ApiClient;
    const { result, rerender } = renderHook(
      ({ bookId }) => useGlossary(client, true, bookId, ''),
      { initialProps: { bookId: 42 } },
    );
    await waitFor(() => expect(queryGlossaryTerms).toHaveBeenCalledTimes(1));

    act(() => result.current.setQuery({ page: 3 }));
    await waitFor(() => expect(queryGlossaryTerms).toHaveBeenCalledTimes(2));
    expect(queryGlossaryTerms.mock.calls[1][0]).toMatchObject({ book_id: 42, page: 3 });

    rerender({ bookId: 43 });

    await waitFor(() => expect(result.current.terms.data[0]?.source_term).toBe('结丹'));
    expect(queryGlossaryTerms.mock.calls[queryGlossaryTerms.mock.calls.length - 1]?.[0]).toMatchObject({
      book_id: 43,
      page: 1,
    });
    expect(result.current.query.page).toBe(1);
  });

  it('re-requests the final valid page after a mutation shrinks pagination', async () => {
    let pageTwoLoads = 0;
    let shrunk = false;
    const queryGlossaryTerms = vi.fn(async (requestedQuery) => {
      if (requestedQuery.page === 2) {
        pageTwoLoads += 1;
        if (pageTwoLoads > 1) {
          shrunk = true;
          return {
            facets: { locked: {}, mode: {}, review_status: {}, scope: {}, term_type: {} },
            items: [],
            page: 2,
            pages: 1,
            per_page: 50,
            scope: 'book' as const,
            total: 50,
          };
        }
      }
      return {
        facets: { locked: {}, mode: {}, review_status: {}, scope: {}, term_type: {} },
        items: [{ ...fixtureGlossaryTerm, id: requestedQuery.page === 2 ? 51 : 1 }],
        page: requestedQuery.page,
        pages: shrunk ? 1 : 2,
        per_page: 50,
        scope: 'book' as const,
        total: shrunk ? 50 : 51,
      };
    });
    const client = {
      approveGlossaryTerm: vi.fn().mockResolvedValue(undefined),
      queryGlossaryTerms,
      searchTm: vi.fn(),
    } as unknown as ApiClient;
    const { result } = renderHook(() => useGlossary(client, true, 42, ''));
    await waitFor(() => expect(result.current.terms.state).toBe('ready'));
    act(() => result.current.setQuery({ page: 2 }));
    await waitFor(() => expect(result.current.page).toBe(2));

    await act(async () => result.current.approveTerm(51));

    await waitFor(() => expect(result.current.page).toBe(1));
    expect(result.current.query.page).toBe(1);
    expect(result.current.terms.state).toBe('ready');
    expect(queryGlossaryTerms.mock.calls[queryGlossaryTerms.mock.calls.length - 1]?.[0]).toMatchObject({
      book_id: 42,
      page: 1,
    });
  });

  it('runs explicit review actions and refreshes the current glossary', async () => {
    const client = {
      getGlossaryTerms: vi.fn().mockResolvedValue([fixtureGlossaryTerm]),
      updateGlossaryTerm: vi.fn().mockResolvedValue(undefined),
      approveGlossaryTerm: vi.fn().mockResolvedValue(undefined),
      rejectGlossaryTerm: vi.fn().mockResolvedValue(undefined),
      searchTm: vi.fn(),
    } as unknown as ApiClient;

    const { result } = renderHook(() => useGlossary(client, true, 42, '筑基'));
    await waitFor(() => expect(result.current.terms.state).toBe('ready'));

    await act(async () => {
      await result.current.approveTerm(7);
      await result.current.rejectTerm(8);
      await result.current.saveAndApproveTerm(9, { target_term: 'Trúc Cơ kỳ' }, true);
    });

    expect(client.approveGlossaryTerm).toHaveBeenCalledWith(7);
    expect(client.rejectGlossaryTerm).toHaveBeenCalledWith(8);
    expect(client.updateGlossaryTerm).toHaveBeenCalledWith(9, {
      target_term: 'Trúc Cơ kỳ',
      approved: 1,
      locked: 1,
    });
    expect(client.getGlossaryTerms).toHaveBeenCalledTimes(4);
  });
});
