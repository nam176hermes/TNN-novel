import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ApiError, type ApiClient, type ApiRequestOptions } from '../api/client';
import type {
  GlossaryFacets,
  GlossaryBulkAction,
  GlossaryBulkTermRef,
  GlossaryImportItem,
  GlossaryPage,
  GlossaryQuery,
  GlossaryTerm,
  GlossaryTermUpdate,
  TmSearchResult,
} from '../api/types';
import { formatError, type AsyncState, type LoadState } from './types';

const emptyTerms: AsyncState<GlossaryTerm[]> = { data: [], error: '', state: 'idle' };
const emptyFacets: GlossaryFacets = { locked: {}, mode: {}, review_status: {}, scope: {}, term_type: {} };
const defaultQuery: GlossaryQuery = {
  page: 1,
  per_page: 50,
  q: '',
  review_status: 'NEEDS_REVIEW,CONFLICT',
  scope: 'book',
  sort: 'review',
};

export function useGlossary(
  client: ApiClient,
  enabled: boolean,
  bookId: number | null,
  sourceText: string,
  onAuthError?: () => void,
  reviewQueue = true,
) {
  const [terms, setTerms] = useState<AsyncState<GlossaryTerm[]>>(emptyTerms);
  const [query, setQueryState] = useState<GlossaryQuery>(defaultQuery);
  const [pageData, setPageData] = useState<Pick<GlossaryPage, 'facets' | 'page' | 'pages' | 'per_page' | 'scope' | 'total'>>({
    facets: emptyFacets,
    page: 1,
    pages: 0,
    per_page: 50,
    scope: 'book',
    total: 0,
  });
  const [tmResults, setTmResults] = useState<TmSearchResult[]>([]);
  const [tmState, setTmState] = useState<LoadState>('idle');
  const [tmError, setTmError] = useState('');
  const termsRequestIdRef = useRef(0);
  const termsAbortRef = useRef<AbortController | null>(null);
  const tmRequestIdRef = useRef(0);
  const bookIdRef = useRef(bookId);
  const enabledRef = useRef(enabled);
  const effectBookIdRef = useRef(bookId);
  const skipNextQueryRefreshRef = useRef(false);
  const latestRefreshRef = useRef<() => Promise<GlossaryTerm[]>>(async () => []);
  const queryGenerationRef = useRef(0);
  const latestQueryTokenRef = useRef('');
  const mutationContextRef = useRef({ bookId, enabled, generation: 0, token: '' });

  bookIdRef.current = bookId;
  enabledRef.current = enabled;
  const queryToken = JSON.stringify({
    archived: query.archived ?? false,
    bookId,
    enabled,
    locked: query.locked ?? null,
    mode: query.mode ?? '',
    page: query.page,
    perPage: query.per_page,
    q: query.q,
    reviewQueue,
    reviewStatus: query.review_status,
    scope: query.scope,
    sort: query.sort,
    termType: query.term_type ?? '',
  });
  if (latestQueryTokenRef.current !== queryToken) {
    latestQueryTokenRef.current = queryToken;
    queryGenerationRef.current += 1;
  }
  mutationContextRef.current = {
    bookId,
    enabled,
    generation: queryGenerationRef.current,
    token: queryToken,
  };

  const resetTerms = useCallback(
    (state: LoadState = 'idle') => {
      termsRequestIdRef.current += 1;
      termsAbortRef.current?.abort();
      setTerms({ data: [], error: '', state });
      setPageData((current) => ({ ...current, facets: emptyFacets, page: 1, pages: 0, total: 0 }));
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

    termsAbortRef.current?.abort();
    const controller = new AbortController();
    termsAbortRef.current = controller;
    const requestId = termsRequestIdRef.current + 1;
    termsRequestIdRef.current = requestId;
    setTerms((current) => ({ data: current.data, error: '', state: 'loading' }));

    const requestedBookId = bookId;

    try {
      const requestedQuery = { ...query, book_id: requestedBookId, per_page: Math.min(query.per_page, 50) };
      let nextPage: GlossaryPage;
      let reconciledPage: number | null = null;
      if (reviewQueue && typeof client.queryGlossaryTerms === 'function') {
        nextPage = await client.queryGlossaryTerms(requestedQuery, { signal: controller.signal });
        if (nextPage.pages < requestedQuery.page) {
          reconciledPage = Math.max(nextPage.pages, 1);
          nextPage = await client.queryGlossaryTerms(
            { ...requestedQuery, page: reconciledPage },
            { signal: controller.signal },
          );
        }
      } else {
        const items = await client.getGlossaryTerms(requestedBookId, { signal: controller.signal });
        nextPage = {
          facets: emptyFacets,
          items,
          page: 1,
          pages: items.length > 0 ? 1 : 0,
          per_page: 50,
          scope: 'book',
          total: items.length,
        };
      }
      if (!nextPage) return [];
      if (
        requestId !== termsRequestIdRef.current ||
        !enabledRef.current ||
        bookIdRef.current !== requestedBookId
      ) {
        return nextPage.items;
      }
      if (reconciledPage !== null && reconciledPage !== query.page) {
        skipNextQueryRefreshRef.current = true;
        setQueryState((current) => ({ ...current, page: reconciledPage }));
      }
      setTerms({
        data: nextPage.items,
        error: '',
        state: nextPage.items.length > 0 ? 'ready' : 'empty',
      });
      setPageData({
        facets: nextPage.facets,
        page: nextPage.page,
        pages: nextPage.pages,
        per_page: nextPage.per_page,
        scope: nextPage.scope,
        total: nextPage.total,
      });
      return nextPage.items;
    } catch (error) {
      if (controller.signal.aborted || (error instanceof DOMException && error.name === 'AbortError')) return [];
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
  }, [bookId, client, enabled, onAuthError, query, resetTerms, resetTm, reviewQueue]);
  latestRefreshRef.current = refresh;

  const captureMutationContext = useCallback(() => ({ ...mutationContextRef.current }), []);
  const refreshAfterMutation = useCallback(
    async (started: ReturnType<typeof captureMutationContext>) => {
      const latest = mutationContextRef.current;
      if (
        !latest.enabled
        || latest.bookId === null
        || latest.bookId !== started.bookId
        || latest.generation !== started.generation
        || latest.token !== started.token
      ) {
        return;
      }
      await latestRefreshRef.current();
    },
    [captureMutationContext],
  );

  const setQuery = useCallback((updates: Partial<GlossaryQuery>) => {
    setQueryState((current) => ({
      ...current,
      ...updates,
      page: updates.page ?? 1,
      per_page: Math.min(updates.per_page ?? current.per_page, 50),
    }));
  }, []);

  const updateTerm = useCallback(
    async (termId: number, updates: GlossaryTermUpdate) => {
      const actionContext = captureMutationContext();
      if (!actionContext.enabled || actionContext.bookId === null) return;

      try {
        const version = terms.data.find((term) => term.id === termId)?.version;
        await client.updateGlossaryTerm(termId, {
          ...updates,
          ...(version === undefined ? {} : { expected_version: version }),
        });
        await refreshAfterMutation(actionContext);
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          onAuthError?.();
        }
        throw error;
      }
    },
    [captureMutationContext, client, onAuthError, refreshAfterMutation, terms.data],
  );

  const toggleLock = useCallback(
    async (termId: number, locked: boolean) => {
      const actionContext = captureMutationContext();
      if (!actionContext.enabled || actionContext.bookId === null) return;

      try {
        if (locked) {
          await client.lockGlossaryTerm(termId);
        } else {
          await client.unlockGlossaryTerm(termId);
        }
        await refreshAfterMutation(actionContext);
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          onAuthError?.();
        }
        throw error;
      }
    },
    [captureMutationContext, client, onAuthError, refreshAfterMutation],
  );

  const approveTerm = useCallback(
    async (termId: number) => {
      const actionContext = captureMutationContext();
      if (!actionContext.enabled || actionContext.bookId === null) return;

      try {
        await client.approveGlossaryTerm(termId);
        await refreshAfterMutation(actionContext);
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          onAuthError?.();
        }
        throw error;
      }
    },
    [captureMutationContext, client, onAuthError, refreshAfterMutation],
  );

  const rejectTerm = useCallback(
    async (termId: number) => {
      const actionContext = captureMutationContext();
      if (!actionContext.enabled || actionContext.bookId === null) return;

      try {
        await client.rejectGlossaryTerm(termId);
        await refreshAfterMutation(actionContext);
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          onAuthError?.();
        }
        throw error;
      }
    },
    [captureMutationContext, client, onAuthError, refreshAfterMutation],
  );

  const saveAndApproveTerm = useCallback(
    async (termId: number, updates: GlossaryTermUpdate, locked: boolean) => {
      const actionContext = captureMutationContext();
      if (!actionContext.enabled || actionContext.bookId === null) return;

      try {
        const version = terms.data.find((term) => term.id === termId)?.version;
        await client.updateGlossaryTerm(termId, {
          ...updates,
          approved: 1,
          locked: locked ? 1 : 0,
          ...(version === undefined ? {} : { expected_version: version }),
        });
        await refreshAfterMutation(actionContext);
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          onAuthError?.();
        }
        throw error;
      }
    },
    [captureMutationContext, client, onAuthError, refreshAfterMutation, terms.data],
  );

  const createBookOverride = useCallback(
    async (term: GlossaryTerm) => {
      const actionContext = captureMutationContext();
      if (!actionContext.enabled || actionContext.bookId === null) return;
      await client.createGlossaryTerm({
        approved: 0,
        book_id: actionContext.bookId,
        category: term.category,
        genre: term.genre,
        locked: 0,
        mode: term.mode,
        priority: term.priority,
        review_status: 'NEEDS_REVIEW',
        source_context: term.source_context,
        source_term: term.source_term,
        target_term: term.target_term,
        term_type: term.term_type,
        variants: term.variants,
      });
      await refreshAfterMutation(actionContext);
    },
    [captureMutationContext, client, refreshAfterMutation],
  );

  const loadTermDetail = useCallback(
    (termId: number, options: ApiRequestOptions = {}) => client.getGlossaryTermDetail(termId, options),
    [client],
  );

  const phase4Mutation = useCallback(async (call: () => Promise<unknown>) => {
    const actionContext = captureMutationContext();
    if (!actionContext.enabled || actionContext.bookId === null) return;
    try {
      await call();
      await refreshAfterMutation(actionContext);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) onAuthError?.();
      throw error;
    }
  }, [captureMutationContext, onAuthError, refreshAfterMutation]);

  const bulkTerms = useCallback(
    (action: GlossaryBulkAction, refs: GlossaryBulkTermRef[]) => phase4Mutation(
      () => client.bulkGlossaryTerms(action, refs),
    ),
    [client, phase4Mutation],
  );
  const archiveTerm = useCallback(
    (termId: number) => phase4Mutation(() => client.archiveGlossaryTerm(termId)),
    [client, phase4Mutation],
  );
  const restoreTerm = useCallback(
    (termId: number) => phase4Mutation(() => client.restoreGlossaryTerm(termId)),
    [client, phase4Mutation],
  );
  const createTerm = useCallback(
    (term: GlossaryImportItem) => phase4Mutation(() => client.createGlossaryTerm({
      ...term,
      book_id: term.book_id ?? bookIdRef.current ?? 0,
    })),
    [client, phase4Mutation],
  );
  const loadConflicts = useCallback(
    (page = 1) => client.getGlossaryConflicts(bookIdRef.current ?? undefined, page),
    [client],
  );
  const previewMerge = useCallback(
    (canonicalId: number, duplicateIds: number[]) => client.previewGlossaryMerge(canonicalId, duplicateIds),
    [client],
  );
  const applyMerge = useCallback(
    (canonicalId: number, duplicateIds: number[], digest: string) => phase4Mutation(
      () => client.applyGlossaryMerge(canonicalId, duplicateIds, digest),
    ),
    [client, phase4Mutation],
  );
  const previewImport = useCallback(
    (
      items: GlossaryImportItem[],
      policy: 'skip_conflicts' | 'reject_conflicts' = 'skip_conflicts',
    ) => client.previewGlossaryImport(items, policy),
    [client],
  );
  const applyImport = useCallback(
    (
      items: GlossaryImportItem[],
      digest: string,
      policy: 'skip_conflicts' | 'reject_conflicts' = 'skip_conflicts',
    ) => phase4Mutation(
      () => client.applyGlossaryImport(items, digest, policy),
    ),
    [client, phase4Mutation],
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
    const bookChanged = effectBookIdRef.current !== bookId;
    effectBookIdRef.current = bookId;
    if (bookChanged && query.page !== 1) {
      resetTerms(enabled && bookId !== null ? 'loading' : 'idle');
      setQueryState((current) => ({ ...current, page: 1 }));
      return;
    }
    if (!enabled || bookId === null) {
      resetTerms('idle');
      resetTm('idle');
      return;
    }
    if (skipNextQueryRefreshRef.current) {
      skipNextQueryRefreshRef.current = false;
      return;
    }

    void refresh().catch(() => {});
  }, [bookId, enabled, query.page, refresh, resetTerms, resetTm]);

  const pendingCount = useMemo(
    () => terms.data.filter((term) => term.approved === 0 || term.approved === undefined).length,
    [terms.data],
  );
  const relevantTerms = useMemo(
    () => terms.data.filter((term) => Boolean(term.source_term) && sourceText.includes(term.source_term)),
    [sourceText, terms.data],
  );

  return {
    applyImport,
    applyMerge,
    approveTerm,
    archiveTerm,
    bulkTerms,
    createTerm,
    createBookOverride,
    facets: pageData.facets,
    loadTermDetail,
    loadConflicts,
    page: pageData.page,
    pages: pageData.pages,
    pendingCount,
    previewImport,
    previewMerge,
    perPage: pageData.per_page,
    query,
    rejectTerm,
    restoreTerm,
    refresh,
    relevantTerms,
    saveAndApproveTerm,
    searchTranslationMemory,
    setQuery,
    scope: pageData.scope,
    terms,
    tmError,
    tmResults,
    tmState,
    toggleLock,
    total: pageData.total,
    updateTerm,
  };
}
