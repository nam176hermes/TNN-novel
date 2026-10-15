import { useCallback, useRef, useState } from 'react';
import type { ApiClient } from '../../api/client';
import type { ReaderExplainResponse, ReaderExplainSpoilerMode } from '../../api/types';
import type { ReaderAiPanelMode } from './ReaderAiPanel';
import type { ReaderSelectionState } from './types';

function readerAiCacheKey(input: {
  bookId: number;
  chapterId: number;
  mode: ReaderAiPanelMode;
  spoilerMode: ReaderExplainSpoilerMode;
  text: string;
}): string {
  return [
    input.bookId,
    input.chapterId,
    input.mode,
    input.spoilerMode,
    input.text.replace(/\s+/g, ' ').trim().toLowerCase(),
  ].join('|');
}


export function useReaderAi({
  apiClient, activeBookId, selectedChapterId
}: {
  apiClient?: Pick<ApiClient, 'explainReaderSelection'>;
  activeBookId: number | null;
  selectedChapterId: number | null;
}) {
  const readerAiCacheRef = useRef(new Map<string, ReaderExplainResponse>());
  const [readerAiOpen, setReaderAiOpen] = useState(false);
  const [readerAiMode, setReaderAiMode] = useState<ReaderAiPanelMode>('explain');
  const [readerAiSelection, setReaderAiSelection] = useState<ReaderSelectionState | null>(null);
  const [readerAiSpoilerMode, setReaderAiSpoilerMode] = useState<ReaderExplainSpoilerMode>('no_spoiler');
  const [readerAiResult, setReaderAiResult] = useState<ReaderExplainResponse | null>(null);
  const [readerAiLoading, setReaderAiLoading] = useState(false);
  const [readerAiError, setReaderAiError] = useState('');
  const [readerAiCached, setReaderAiCached] = useState(false);

  function loadReaderAi(
    selection: ReaderSelectionState,
    spoilerMode = readerAiSpoilerMode,
    mode = readerAiMode,
  ): void {
    if (!apiClient || !activeBookId || !selectedChapterId) {
      setReaderAiLoading(false);
      setReaderAiCached(false);
      setReaderAiError('Reader AI requires an API connection.');
      return;
    }

    const cacheKey = readerAiCacheKey({
      bookId: activeBookId,
      chapterId: selectedChapterId,
      mode,
      spoilerMode,
      text: selection.text,
    });
    const cachedResult = readerAiCacheRef.current.get(cacheKey);
    if (cachedResult) {
      setReaderAiLoading(false);
      setReaderAiCached(true);
      setReaderAiError('');
      setReaderAiResult(cachedResult);
      return;
    }

    setReaderAiLoading(true);
    setReaderAiCached(false);
    setReaderAiError('');
    setReaderAiResult(null);

    void apiClient.explainReaderSelection(activeBookId, selectedChapterId, {
      context_after: selection.contextAfter,
      context_before: selection.contextBefore,
      spoiler_mode: spoilerMode,
      text: selection.text,
    })
      .then((result) => {
        readerAiCacheRef.current.set(cacheKey, result);
        setReaderAiResult(result);
        setReaderAiCached(false);
        setReaderAiError('');
      })
      .catch((error: unknown) => {
        setReaderAiError(error instanceof Error ? error.message : 'Failed to explain selected text');
      })
      .finally(() => setReaderAiLoading(false));
  }

  function openReaderAi(selection: ReaderSelectionState, mode: ReaderAiPanelMode): void {
    setReaderAiMode(mode);
    setReaderAiSelection(selection);
    setReaderAiOpen(true);
    loadReaderAi(selection, readerAiSpoilerMode, mode);
  }

  function retryReaderAi(): void {
    if (readerAiSelection) loadReaderAi(readerAiSelection);
  }

  function updateReaderAiSpoilerMode(mode: ReaderExplainSpoilerMode): void {
    setReaderAiSpoilerMode(mode);
    if (readerAiSelection) loadReaderAi(readerAiSelection, mode);
  }


  return {
    readerAiOpen,
    readerAiMode,
    readerAiSelection,
    readerAiSpoilerMode,
    readerAiResult,
    readerAiLoading,
    readerAiError,
    readerAiCached,
    openReaderAi,
    retryReaderAi,
    updateReaderAiSpoilerMode,
    closeReaderAi: useCallback(() => setReaderAiOpen(false), []),
  };
}
