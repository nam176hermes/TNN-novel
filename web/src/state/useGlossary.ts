import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ApiError, type ApiClient } from '../api/client';
import type { GlossaryTerm, GlossaryTermUpdate, TmSearchResult } from '../api/types';
import { formatError, type AsyncState, type LoadState } from './types';

const emptyTerms: AsyncState<GlossaryTerm[]> = { data: [], error: '', state: 'idle' };

export function useGlossary(
  client: ApiClient,
  enabled: boolean,
  bookId: number | null,
  sourceText: string,
  onAuthError?: () => void,
) {
  const [terms, setTerms] = useState<AsyncState<GlossaryTerm[]>>(emptyTerms);
  const [tmResults, setTmResults] = useState<TmSearchResult[]>([]);
  const [tmState, setTmState] = useState<LoadState>('idle');
  const [tmError, setTmError] = useState('');
  const termsRequestIdRef = useRef(0);
  const tmRequestIdRef = useRef(0);
  const bookIdRef = useRef(bookId);
  const enabledRef = useRef(enabled);

  bookIdRef.current = bookId;
  enabledRef.current = enabled;

  const resetTerms = useCallback(
    (state: LoadState = 'idle') => {
      termsRequestIdRef.current += 1;
      setTerms({ data: [], error: '', state });
    },
    [],
  );

  const resetTm = useCallback((state: LoadState = 'idle') => {
    tmRequestIdRef.current += 1;
    setTmResults([]);
    setTmState(state);
    setTmError('');
  }, []);

  const refresh = useCallback(async () => {
    if (!enabled || bookId === null) {
      resetTerms('idle');
      resetTm('idle');
      return [];
    }

    const requestId = termsRequestIdRef.current + 1;
    termsRequestIdRef.current = requestId;
    setTerms((current) => ({ data: current.data, error: '', state: 'loading' }));

    const requestedBookId = bookId;

    try {
      const nextTerms = await client.getGlossaryTerms(requestedBookId);
      if (
        requestId !== termsRequestIdRef.current ||
        !enabledRef.current ||
        bookIdRef.current !== requestedBookId
      ) {
        return nextTerms;
      }
      setTerms({
        data: nextTerms,
        error: '',
        state: nextTerms.length > 0 ? 'ready' : 'empty',
      });
      return nextTerms;
    } catch (error) {
      if (
        requestId !== termsRequestIdRef.current ||
        !enabledRef.current ||
        bookIdRef.current !== requestedBookId
      ) {
        return [];
      }
      if (error instanceof ApiError && error.status === 401) {
        onAuthError?.();
      }
      setTerms((current) => ({ data: current.data, error: formatError(error), state: 'error' }));
      throw error;
    }
  }, [bookId, client, enabled, onAuthError, resetTerms, resetTm]);

  const updateTerm = useCallback(
    async (termId: number, updates: GlossaryTermUpdate) => {
      const actionBookId = bookIdRef.current;
      if (!enabledRef.current || actionBookId === null) return;

      try {
        await client.updateGlossaryTerm(termId, updates);
        if (enabledRef.current && bookIdRef.current === actionBookId) {
          await refresh();
        }
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          onAuthError?.();
        }
        throw error;
      }
    },
    [client, onAuthError, refresh],
  );

  const toggleLock = useCallback(
    async (termId: number, locked: boolean) => {
      const actionBookId = bookIdRef.current;
      if (!enabledRef.current || actionBookId === null) return;

      try {
        if (locked) {
          await client.lockGlossaryTerm(termId);
        } else {
          await client.unlockGlossaryTerm(termId);
        }
        if (enabledRef.current && bookIdRef.current === actionBookId) {
          await refresh();
        }
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          onAuthError?.();
        }
        throw error;
      }
    },
    [client, onAuthError, refresh],
  );

  const approveTerm = useCallback(
    async (termId: number) => {
      const actionBookId = bookIdRef.current;
      if (!enabledRef.current || actionBookId === null) return;

      try {
        await client.approveGlossaryTerm(termId);
        if (enabledRef.current && bookIdRef.current === actionBookId) {
          await refresh();
        }
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          onAuthError?.();
        }
        throw error;
      }
    },
    [client, onAuthError, refresh],
  );

  const rejectTerm = useCallback(
    async (termId: number) => {
      const actionBookId = bookIdRef.current;
      if (!enabledRef.current || actionBookId === null) return;

      try {
        await client.rejectGlossaryTerm(termId);
        if (enabledRef.current && bookIdRef.current === actionBookId) {
          await refresh();
        }
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          onAuthError?.();
        }
        throw error;
      }
    },
    [client, onAuthError, refresh],
  );

  const saveAndApproveTerm = useCallback(
    async (termId: number, updates: GlossaryTermUpdate, locked: boolean) => {
      const actionBookId = bookIdRef.current;
      if (!enabledRef.current || actionBookId === null) return;

      try {
        await client.updateGlossaryTerm(termId, {
          ...updates,
          approved: 1,
          locked: locked ? 1 : 0,
        });
        if (enabledRef.current && bookIdRef.current === actionBookId) {
          await refresh();
        }
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          onAuthError?.();
        }
        throw error;
      }
    },
    [client, onAuthError, refresh],
  );

  const searchTranslationMemory = useCallback(
    async (query: string) => {
      if (!enabled || !query.trim()) {
        resetTm('idle');
        return [];
      }

      const requestId = tmRequestIdRef.current + 1;
      tmRequestIdRef.current = requestId;
      setTmError('');
      setTmState('loading');

      try {
        const results = await client.searchTm(query);
        if (requestId !== tmRequestIdRef.current) {
          return [];
        }
        setTmResults(results);
        setTmState(results.length > 0 ? 'ready' : 'empty');
        return results;
      } catch (error) {
        if (requestId !== tmRequestIdRef.current) return [];
        if (error instanceof ApiError && error.status === 401) {
          onAuthError?.();
        }
        setTmResults([]);
        setTmError(formatError(error));
        setTmState('error');
        throw error;
      }
    },
    [client, enabled, onAuthError, resetTm],
  );

  useEffect(() => {
    if (!enabled || bookId === null) {
      resetTerms('idle');
      resetTm('idle');
      return;
    }

    void refresh().catch(() => {});
  }, [bookId, enabled, refresh, resetTerms, resetTm]);

  const pendingCount = useMemo(
    () => terms.data.filter((term) => term.approved === 0 || term.approved === undefined).length,
    [terms.data],
  );
  const relevantTerms = useMemo(
    () => terms.data.filter((term) => Boolean(term.source_term) && sourceText.includes(term.source_term)),
    [sourceText, terms.data],
  );

  return {
    approveTerm,
    pendingCount,
    rejectTerm,
    refresh,
    relevantTerms,
    saveAndApproveTerm,
    searchTranslationMemory,
    terms,
    tmError,
    tmResults,
    tmState,
    toggleLock,
    updateTerm,
  };
}
