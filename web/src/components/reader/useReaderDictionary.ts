import { useCallback, useEffect, useState } from 'react';
import type { ApiClient } from '../../api/client';
import type { ReaderDictionaryFile, ReaderDictionaryResponse } from '../../api/types';
import {
  loadCachedReaderDictionaryResult,
  lookupCachedReaderDictionaryPack,
  saveCachedReaderDictionaryPack,
  saveCachedReaderDictionaryResult,
} from '../../state/readerDictionaryCache';
import type { ReaderSelectionState } from './types';

export function useReaderDictionary({
  apiClient, activeBookId, selectedChapterId, moreOpen
}: {
  apiClient?: Pick<ApiClient, 'getReaderDictionaryPack' | 'listReaderDictionaries' | 'lookupReaderDictionary' | 'uploadReaderDictionary' | 'deleteReaderDictionary'>;
  activeBookId: number | null;
  selectedChapterId: number | null;
  moreOpen: boolean;
}) {
  const [dictionaryOpen, setDictionaryOpen] = useState(false);
  const [dictionarySelection, setDictionarySelection] = useState<ReaderSelectionState | null>(null);
  const [dictionaryQuery, setDictionaryQuery] = useState('');
  const [dictionaryIncludeOnline, setDictionaryIncludeOnline] = useState(false);
  const [dictionaryResult, setDictionaryResult] = useState<ReaderDictionaryResponse | null>(null);
  const [dictionaryLoading, setDictionaryLoading] = useState(false);
  const [dictionaryError, setDictionaryError] = useState('');
  const [readerDictionaries, setReaderDictionaries] = useState<ReaderDictionaryFile[]>([]);
  const [dictionaryListLoading, setDictionaryListLoading] = useState(false);
  const [dictionaryListVersion, setDictionaryListVersion] = useState(0);
  const [dictionaryDeletingFilename, setDictionaryDeletingFilename] = useState('');
  const [dictionaryUploadLoading, setDictionaryUploadLoading] = useState(false);
  const [dictionaryUploadStatus, setDictionaryUploadStatus] = useState('');

  useEffect(() => {
    if (!apiClient || !activeBookId || !dictionaryOpen) return;
    let cancelled = false;

    void apiClient.getReaderDictionaryPack(activeBookId, { chapterId: selectedChapterId })
      .then((pack) => {
        if (!cancelled) saveCachedReaderDictionaryPack(pack);
      })
      .catch(() => {
        // Dictionary pack is an offline acceleration layer; direct lookup remains authoritative.
      });

    return () => {
      cancelled = true;
    };
  }, [activeBookId, apiClient, dictionaryOpen, selectedChapterId]);

  useEffect(() => {
    if (!moreOpen || !apiClient) {
      setDictionaryListLoading(false);
      return undefined;
    }

    let cancelled = false;
    setDictionaryListLoading(true);
    void apiClient.listReaderDictionaries()
      .then((files) => {
        if (!cancelled) setReaderDictionaries(files);
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setDictionaryUploadStatus(error instanceof Error ? error.message : 'Failed to load reader dictionaries');
        }
      })
      .finally(() => {
        if (!cancelled) setDictionaryListLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [apiClient, dictionaryListVersion, moreOpen]);

  function loadReaderDictionary(
    selection: ReaderSelectionState,
    includeOnline = dictionaryIncludeOnline,
  ): void {
    setDictionaryQuery(selection.text);
    const cachedResult = activeBookId
      ? loadCachedReaderDictionaryResult(activeBookId, selection.text)
        ?? lookupCachedReaderDictionaryPack(activeBookId, selection.text, selectedChapterId)
      : null;
    if (!apiClient || !activeBookId) {
      setDictionaryLoading(false);
      if (cachedResult) {
        setDictionaryResult(cachedResult);
        setDictionaryError('');
      } else {
        setDictionaryError('Reader dictionary requires an API connection.');
      }
      return;
    }

    setDictionaryLoading(true);
    setDictionaryError('');
    setDictionaryResult(cachedResult);

    void apiClient.lookupReaderDictionary(activeBookId, selection.text, {
      chapterId: selectedChapterId,
      includeOnline,
    })
      .then((result) => {
        saveCachedReaderDictionaryResult(result);
        setDictionaryResult(result);
        setDictionaryError('');
      })
      .catch((error: unknown) => {
        const fallbackResult = loadCachedReaderDictionaryResult(activeBookId, selection.text)
          ?? lookupCachedReaderDictionaryPack(activeBookId, selection.text, selectedChapterId);
        if (fallbackResult) {
          setDictionaryResult(fallbackResult);
          setDictionaryError('');
        } else {
          setDictionaryError(error instanceof Error ? error.message : 'Failed to lookup reader dictionary');
        }
      })
      .finally(() => setDictionaryLoading(false));
  }

  function openReaderDictionary(selection: ReaderSelectionState): void {
    setDictionarySelection(selection);
    setDictionaryOpen(true);
    loadReaderDictionary(selection);
  }

  function retryReaderDictionary(): void {
    if (dictionarySelection) loadReaderDictionary(dictionarySelection);
  }

  function updateDictionaryIncludeOnline(value: boolean): void {
    setDictionaryIncludeOnline(value);
    if (dictionarySelection) loadReaderDictionary(dictionarySelection, value);
  }

  function uploadReaderDictionaryFile(file: File | null): void {
    if (!file) return;
    if (!apiClient) {
      setDictionaryUploadStatus('Không thể nạp từ điển: thiếu kết nối API.');
      return;
    }

    setDictionaryUploadLoading(true);
    setDictionaryUploadStatus('Đang nạp từ điển offline...');
    void apiClient.uploadReaderDictionary(file)
      .then((payload) => {
        setDictionaryUploadStatus(
          `Đã nạp từ điển ${payload.filename} · ${payload.entry_count.toLocaleString('vi-VN')} mục`,
        );
        setDictionaryListVersion((current) => current + 1);
        if (!activeBookId) return undefined;
        return apiClient.getReaderDictionaryPack(activeBookId, { chapterId: selectedChapterId })
          .then((pack) => {
            saveCachedReaderDictionaryPack(pack);
          });
      })
      .catch((error: unknown) => {
        setDictionaryUploadStatus(error instanceof Error ? error.message : 'Failed to upload reader dictionary');
      })
      .finally(() => setDictionaryUploadLoading(false));
  }

  function deleteReaderDictionaryFile(filename: string): void {
    if (!apiClient) {
      setDictionaryUploadStatus('Không thể xóa từ điển: thiếu kết nối API.');
      return;
    }

    setDictionaryDeletingFilename(filename);
    setDictionaryUploadStatus(`Đang xóa từ điển ${filename}...`);
    void apiClient.deleteReaderDictionary(filename)
      .then(() => {
        setReaderDictionaries((current) => current.filter((file) => file.filename !== filename));
        setDictionaryUploadStatus(`Đã xóa từ điển ${filename}`);
        setDictionaryListVersion((current) => current + 1);
        if (!activeBookId) return undefined;
        return apiClient.getReaderDictionaryPack(activeBookId, { chapterId: selectedChapterId })
          .then((pack) => {
            saveCachedReaderDictionaryPack(pack);
          });
      })
      .catch((error: unknown) => {
        setDictionaryUploadStatus(error instanceof Error ? error.message : 'Failed to delete reader dictionary');
      })
      .finally(() => setDictionaryDeletingFilename(''));
  }


  return {
    dictionaryOpen,
    dictionaryQuery,
    dictionaryIncludeOnline,
    dictionaryResult,
    dictionaryLoading,
    dictionaryError,
    readerDictionaries,
    dictionaryListLoading,
    dictionaryDeletingFilename,
    dictionaryUploadLoading,
    dictionaryUploadStatus,
    openReaderDictionary,
    retryReaderDictionary,
    updateDictionaryIncludeOnline,
    uploadReaderDictionaryFile,
    deleteReaderDictionaryFile,
    closeDictionary: useCallback(() => setDictionaryOpen(false), []),
    refreshDictionaries: () => setDictionaryListVersion((current) => current + 1),
  };
}
