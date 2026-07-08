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
  it('loads glossary terms, derives pending count, finds source hits, and searches TM', async () => {
    const client = {
      getGlossaryTerms: vi.fn().mockResolvedValue([fixtureGlossaryTerm]),
      searchTm: vi.fn().mockResolvedValue([
        { source_text: '他筑基成功', translation_text: 'Hắn Trúc Cơ thành công', match_score: 92 },
      ]),
    } as unknown as ApiClient;

    const { result } = renderHook(() => useGlossary(client, true, 42, '他开始筑基。'));

    await waitFor(() => expect(result.current.terms.state).toBe('ready'));
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
