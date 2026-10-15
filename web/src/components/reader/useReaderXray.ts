import { useCallback, useState } from 'react';
import type { ApiClient } from '../../api/client';
import type { ReaderXrayResponse, ReaderXraySpoilerMode } from '../../api/types';

export function useReaderXray({
  apiClient, activeBookId, selectedChapterId
}: {
  apiClient?: Pick<ApiClient, 'getReaderXray' | 'enrichReaderXray'>;
  activeBookId: number | null;
  selectedChapterId: number | null;
}) {
  const [xrayOpen, setXrayOpen] = useState(false);
  const [xraySpoilerMode, setXraySpoilerMode] = useState<ReaderXraySpoilerMode>('no_spoiler');
  const [xrayData, setXrayData] = useState<ReaderXrayResponse | null>(null);
  const [xrayLoading, setXrayLoading] = useState(false);
  const [xrayEnriching, setXrayEnriching] = useState(false);
  const [xrayEnrichingScope, setXrayEnrichingScope] = useState<'chapter' | 'book' | null>(null);
  const [xrayError, setXrayError] = useState('');

  function loadReaderXray(mode = xraySpoilerMode): void {
    setXrayLoading(true);
    setXrayError('');

    if (!apiClient || !activeBookId) {
      setXrayLoading(false);
      setXrayError('Reader X-Ray requires an API connection.');
      return;
    }

    void apiClient.getReaderXray(activeBookId, selectedChapterId, mode)
      .then((result) => {
        setXrayData(result);
        setXrayError('');
      })
      .catch((error: unknown) => {
        setXrayError(error instanceof Error ? error.message : 'Failed to load reader X-Ray');
      })
      .finally(() => setXrayLoading(false));
  }

  function openReaderXray(): void {
    setXrayOpen(true);
    loadReaderXray();
  }

  function retryReaderXray(): void {
    loadReaderXray();
  }

  function enrichReaderXray(scope: 'chapter' | 'book' = 'chapter'): void {
    setXrayEnriching(true);
    setXrayEnrichingScope(scope);
    setXrayError('');

    if (!apiClient || !activeBookId) {
      setXrayEnriching(false);
      setXrayEnrichingScope(null);
      setXrayError('Reader X-Ray AI requires an API connection.');
      return;
    }

    void apiClient.enrichReaderXray(activeBookId, {
      chapterId: scope === 'book' ? null : selectedChapterId,
      spoilerMode: xraySpoilerMode,
    })
      .then((result) => {
        setXrayData(result);
        setXrayError('');
      })
      .catch((error: unknown) => {
        setXrayError(error instanceof Error ? error.message : 'Failed to enrich reader X-Ray');
      })
      .finally(() => {
        setXrayEnriching(false);
        setXrayEnrichingScope(null);
      });
  }

  function enrichReaderXrayBook(): void {
    enrichReaderXray('book');
  }

  function updateReaderXraySpoilerMode(mode: ReaderXraySpoilerMode): void {
    setXraySpoilerMode(mode);
    loadReaderXray(mode);
  }


  return {
    xrayOpen,
    xraySpoilerMode,
    xrayData,
    xrayLoading,
    xrayEnriching,
    xrayEnrichingScope,
    xrayError,
    openReaderXray,
    retryReaderXray,
    enrichReaderXray,
    enrichReaderXrayBook,
    updateReaderXraySpoilerMode,
    closeReaderXray: useCallback(() => setXrayOpen(false), []),
  };
}
