import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Chapter } from '../../api/types';
import {
  READER_CACHE_UPDATED_EVENT,
  getCachedChapterAsync,
  getCachedReaderAssetUrl,
  getCachedReaderAudioUrl,
  readerCacheStatusAsync,
  removeCachedBookAsync,
  removeCachedChapterAsync,
  type ReaderCachedChapter,
  type ReaderCacheStatus,
} from '../../state/readerCache';
import {
  cacheBookForOffline,
  cacheChapterForOffline,
  loadReaderOfflineManifest,
  removeReaderOfflineManifest,
  removeReaderOfflineManifestChapter,
  type CacheBookForOfflineOptions,
  type CacheChapterForOfflineOptions,
  type ReaderOfflineCacheClient,
  type ReaderOfflineCacheSummary,
  type ReaderOfflineManifest,
} from '../../state/readerOfflineCache';

export type ReaderOfflineState = 'online' | 'offline-with-cache' | 'offline-without-cache';

export type ReaderOfflineCacheDependencies = {
  cacheBook(options: CacheBookForOfflineOptions): Promise<ReaderOfflineCacheSummary>;
  cacheChapter(options: CacheChapterForOfflineOptions): Promise<ReaderOfflineCacheSummary>;
  getCachedAudioUrl(bookId: number, chapterId: number, url: string): Promise<string>;
  getCachedChapter(bookId: number, chapterId: number): Promise<ReaderCachedChapter | null>;
  getCachedCoverUrl(bookId: number, chapterId: number, url: string): Promise<string>;
  loadManifest(bookId: number): ReaderOfflineManifest | null;
  readStatus(options: {
    bookId: number;
    chapterId: number;
    nextChapterId?: number | null;
  }): Promise<ReaderCacheStatus>;
  removeBook(bookId: number): Promise<void>;
  removeChapter(bookId: number, chapterId: number): Promise<void>;
  removeManifest(bookId: number): void;
  removeManifestChapter(bookId: number, chapterId: number): void;
};

export type UseReaderOfflineCacheOptions = {
  apiClient?: ReaderOfflineCacheClient;
  audioUrl?: string;
  bookId: number | null;
  chapters: Chapter[];
  coverUrl?: string | null;
  dependencies?: ReaderOfflineCacheDependencies;
  liveCoverUrl?: string;
  nextChapterId?: number | null;
  onError(message: string): void;
  selectedChapter: Chapter | null;
  selectedChapterId: number | null;
};

const defaultDependencies: ReaderOfflineCacheDependencies = {
  cacheBook: cacheBookForOffline,
  cacheChapter: cacheChapterForOffline,
  getCachedAudioUrl: getCachedReaderAudioUrl,
  getCachedChapter: getCachedChapterAsync,
  getCachedCoverUrl: getCachedReaderAssetUrl,
  loadManifest: loadReaderOfflineManifest,
  readStatus: readerCacheStatusAsync,
  removeBook: removeCachedBookAsync,
  removeChapter: removeCachedChapterAsync,
  removeManifest: removeReaderOfflineManifest,
  removeManifestChapter: removeReaderOfflineManifestChapter,
};

function onlineNow(): boolean {
  return typeof navigator === 'undefined' || navigator.onLine !== false;
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

export function useReaderOfflineCache({
  apiClient,
  audioUrl = '',
  bookId,
  chapters,
  coverUrl = '',
  dependencies = defaultDependencies,
  liveCoverUrl = '',
  nextChapterId = null,
  onError,
  selectedChapter,
  selectedChapterId,
}: UseReaderOfflineCacheOptions) {
  const [cacheStatus, setCacheStatus] = useState<ReaderCacheStatus | null>(null);
  const [manifest, setManifest] = useState<ReaderOfflineManifest | null>(null);
  const [cachedChapter, setCachedChapter] = useState<ReaderCachedChapter | null>(null);
  const [cachedAudioUrl, setCachedAudioUrl] = useState('');
  const [resolvedCoverUrl, setResolvedCoverUrl] = useState(liveCoverUrl);
  const [metadataLoading, setMetadataLoading] = useState(Boolean(bookId && selectedChapterId));
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');
  const [online, setOnline] = useState(onlineNow);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const mountedRef = useRef(true);
  const identityRef = useRef(`${bookId ?? ''}:${selectedChapterId ?? ''}`);
  const operationGenerationRef = useRef(0);
  const activeOperationRef = useRef(0);

  const identity = `${bookId ?? ''}:${selectedChapterId ?? ''}`;

  useEffect(() => {
    identityRef.current = identity;
    operationGenerationRef.current += 1;
    activeOperationRef.current = 0;
    setLoading(false);
    setMessage('');
  }, [identity]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      operationGenerationRef.current += 1;
      activeOperationRef.current = 0;
    };
  }, []);

  useEffect(() => {
    const handleCacheUpdated = (): void => setRefreshVersion((current) => current + 1);
    const handleOnline = (): void => setOnline(true);
    const handleOffline = (): void => setOnline(false);

    window.addEventListener(READER_CACHE_UPDATED_EVENT, handleCacheUpdated);
    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);
    return () => {
      window.removeEventListener(READER_CACHE_UPDATED_EVENT, handleCacheUpdated);
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const normalizedCoverUrl = coverUrl?.trim() ?? '';
    const normalizedAudioUrl = audioUrl.trim();

    setMetadataLoading(Boolean(bookId && selectedChapterId));
    setManifest(bookId ? dependencies.loadManifest(bookId) : null);
    setCacheStatus(null);
    setCachedChapter(null);
    setCachedAudioUrl('');
    setResolvedCoverUrl(liveCoverUrl);

    if (!bookId || !selectedChapterId) {
      setMetadataLoading(false);
      return () => {
        cancelled = true;
      };
    }

    const statusRequest = dependencies.readStatus({
      bookId,
      chapterId: selectedChapterId,
      nextChapterId,
    }).catch(() => null);
    const chapterRequest = dependencies.getCachedChapter(bookId, selectedChapterId).catch(() => null);
    const audioRequest = normalizedAudioUrl
      ? dependencies.getCachedAudioUrl(bookId, selectedChapterId, normalizedAudioUrl).catch(() => '')
      : Promise.resolve('');
    const coverRequest = normalizedCoverUrl
      ? dependencies.getCachedCoverUrl(bookId, 0, normalizedCoverUrl).catch(() => '')
      : Promise.resolve('');

    void Promise.all([statusRequest, chapterRequest, audioRequest, coverRequest])
      .then(([nextStatus, nextCachedChapter, nextCachedAudioUrl, nextCachedCoverUrl]) => {
        if (cancelled) return;
        setCacheStatus(nextStatus);
        setCachedChapter(nextCachedChapter);
        setCachedAudioUrl(nextCachedAudioUrl);
        setResolvedCoverUrl(nextCachedCoverUrl || liveCoverUrl);
      })
      .finally(() => {
        if (!cancelled) setMetadataLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [
    audioUrl,
    bookId,
    coverUrl,
    dependencies,
    liveCoverUrl,
    nextChapterId,
    refreshVersion,
    selectedChapterId,
  ]);

  const currentAvailable = Boolean(
    cacheStatus?.currentCached
    || cachedChapter
    || (selectedChapterId && manifest?.chapterIds.includes(selectedChapterId)),
  );
  const offlineState: ReaderOfflineState = online
    ? 'online'
    : currentAvailable
      ? 'offline-with-cache'
      : 'offline-without-cache';

  const beginOperation = useCallback((): { identity: string; token: number } => {
    const token = operationGenerationRef.current + 1;
    operationGenerationRef.current = token;
    activeOperationRef.current = token;
    setLoading(true);
    return { identity: identityRef.current, token };
  }, []);

  const operationIsCurrent = useCallback((operation: { identity: string; token: number }): boolean => (
    mountedRef.current
    && operation.identity === identityRef.current
    && operation.token === activeOperationRef.current
  ), []);

  const finishOperation = useCallback((operation: { identity: string; token: number }): void => {
    if (!operationIsCurrent(operation)) return;
    activeOperationRef.current = 0;
    setLoading(false);
  }, [operationIsCurrent]);

  const refresh = useCallback(() => {
    setRefreshVersion((current) => current + 1);
  }, []);

  const cacheCurrentChapter = useCallback(async (): Promise<void> => {
    if (!apiClient || !bookId || !selectedChapter) {
      setMessage('Không thể cache chương: thiếu kết nối API hoặc chương đang đọc.');
      return;
    }
    if (!selectedChapter.has_translation) {
      setMessage('Chỉ cache offline được chương đã có bản dịch.');
      return;
    }

    const operation = beginOperation();
    setMessage(`Đang tải Chương ${selectedChapter.chapter_number} để đọc offline...`);
    try {
      const summary = await dependencies.cacheChapter({
        audioUrl,
        bookId,
        chapter: selectedChapter,
        client: apiClient,
      });
      if (!operationIsCurrent(operation)) return;
      setMessage([
        `Đã tải Chương ${selectedChapter.chapter_number} offline`,
        `${summary.assetsCached}/${summary.assetsTotal} asset`,
        `${summary.audioCached}/${summary.audioTotal} audio`,
      ].join(' · '));
      onError('');
      refresh();
    } catch (error: unknown) {
      if (!operationIsCurrent(operation)) return;
      setMessage('');
      onError(errorMessage(error, 'Failed to cache chapter offline'));
    } finally {
      finishOperation(operation);
    }
  }, [
    apiClient,
    audioUrl,
    beginOperation,
    bookId,
    dependencies,
    finishOperation,
    onError,
    operationIsCurrent,
    refresh,
    selectedChapter,
  ]);

  const removeCurrentChapter = useCallback(async (): Promise<void> => {
    if (!bookId || !selectedChapterId || !selectedChapter) {
      setMessage('Không thể xóa cache chương: chưa chọn chương.');
      return;
    }

    const operation = beginOperation();
    setMessage(`Đang xóa cache Chương ${selectedChapter.chapter_number}...`);
    try {
      await dependencies.removeChapter(bookId, selectedChapterId);
      if (!operationIsCurrent(operation)) return;
      dependencies.removeManifestChapter(bookId, selectedChapterId);
      setManifest(dependencies.loadManifest(bookId));
      setMessage(`Đã xóa cache offline Chương ${selectedChapter.chapter_number}.`);
      onError('');
      refresh();
    } catch (error: unknown) {
      if (!operationIsCurrent(operation)) return;
      setMessage('');
      onError(errorMessage(error, 'Failed to clear chapter offline cache'));
    } finally {
      finishOperation(operation);
    }
  }, [
    beginOperation,
    bookId,
    dependencies,
    finishOperation,
    onError,
    operationIsCurrent,
    refresh,
    selectedChapter,
    selectedChapterId,
  ]);

  const translatedChapters = useMemo(
    () => chapters.filter((chapter) => chapter.book_id === bookId && chapter.has_translation),
    [bookId, chapters],
  );

  const cacheCurrentBook = useCallback(async (): Promise<void> => {
    if (!apiClient || !bookId) {
      setMessage('Không thể cache offline: thiếu kết nối API hoặc truyện đang đọc.');
      return;
    }

    const operation = beginOperation();
    setMessage(`Đang cache offline 0/${translatedChapters.length} chương...`);
    try {
      const summary = await dependencies.cacheBook({
        bookId,
        chapters: translatedChapters,
        client: apiClient,
        coverUrl,
        onProgress: (progress) => {
          if (!operationIsCurrent(operation)) return;
          setMessage(`Đang cache offline ${progress.chaptersCached}/${progress.chaptersTotal} chương...`);
        },
      });
      if (!operationIsCurrent(operation)) return;
      setMessage([
        `Đã cache offline ${summary.chaptersCached}/${summary.chaptersTotal} chương`,
        `${summary.assetsCached}/${summary.assetsTotal} asset`,
        `${summary.audioCached}/${summary.audioTotal} audio`,
        summary.dictionaryCached ? 'đã cache từ điển' : 'chưa cache từ điển',
      ].join(' · '));
      onError('');
      refresh();
    } catch (error: unknown) {
      if (!operationIsCurrent(operation)) return;
      setMessage('');
      onError(errorMessage(error, 'Failed to cache book offline'));
    } finally {
      finishOperation(operation);
    }
  }, [
    apiClient,
    beginOperation,
    bookId,
    coverUrl,
    dependencies,
    finishOperation,
    onError,
    operationIsCurrent,
    refresh,
    translatedChapters,
  ]);

  const removeCurrentBook = useCallback(async (): Promise<void> => {
    if (!bookId) {
      setMessage('Không thể xóa cache offline: chưa chọn truyện.');
      return;
    }

    const operation = beginOperation();
    setMessage('Đang xóa cache offline...');
    try {
      await dependencies.removeBook(bookId);
      if (!operationIsCurrent(operation)) return;
      dependencies.removeManifest(bookId);
      setManifest(null);
      setMessage('Đã xóa cache offline của truyện này.');
      onError('');
      refresh();
    } catch (error: unknown) {
      if (!operationIsCurrent(operation)) return;
      setMessage('');
      onError(errorMessage(error, 'Failed to clear book offline cache'));
    } finally {
      finishOperation(operation);
    }
  }, [
    beginOperation,
    bookId,
    dependencies,
    finishOperation,
    onError,
    operationIsCurrent,
    refresh,
  ]);

  return {
    cacheStatus,
    cachedAudioUrl,
    cachedChapter,
    coverUrl: resolvedCoverUrl,
    currentAvailable,
    loading,
    manifest,
    message,
    metadataLoading,
    offlineState,
    cacheCurrentBook,
    cacheCurrentChapter,
    refresh,
    removeCurrentBook,
    removeCurrentChapter,
  };
}

export default useReaderOfflineCache;
