import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Chapter } from '../../api/types';
import {
  READER_CACHE_UPDATED_EVENT,
  cacheReaderAudio,
  getCachedChapterAsync,
  getCachedReaderAssetUrl,
  getCachedReaderAudioUrl,
  hydrateCachedReaderAssetUrls,
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
  cacheAudio(bookId: number, chapterId: number, url: string): Promise<{
    cached: boolean;
    failed: boolean;
    sizeBytes: number;
    url: string;
  }>;
  cacheChapter(options: CacheChapterForOfflineOptions): Promise<ReaderOfflineCacheSummary>;
  getCachedAudioUrl(bookId: number, chapterId: number, url: string): Promise<string>;
  getCachedChapter(bookId: number, chapterId: number): Promise<ReaderCachedChapter | null>;
  getCachedCoverUrl(bookId: number, chapterId: number, url: string): Promise<string>;
  hydrateCachedChapterHtml(
    bookId: number,
    chapterId: number,
    html: string,
    assetBase?: string,
  ): Promise<string>;
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
  cacheAudio: cacheReaderAudio,
  cacheBook: cacheBookForOffline,
  cacheChapter: cacheChapterForOffline,
  getCachedAudioUrl: getCachedReaderAudioUrl,
  getCachedChapter: getCachedChapterAsync,
  getCachedCoverUrl: getCachedReaderAssetUrl,
  hydrateCachedChapterHtml: hydrateCachedReaderAssetUrls,
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

function readerHtmlAssetBase(contentHtmlPath?: string | null): string | undefined {
  const path = contentHtmlPath?.trim() ?? '';
  if (!path) return undefined;
  if (/^https?:\/\//i.test(path) || path.startsWith('/book-assets/')) return path;
  return undefined;
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
  const [, setSuppressionVersion] = useState(0);
  const mountedRef = useRef(true);
  const identityRef = useRef(`${bookId ?? ''}:${selectedChapterId ?? ''}`);
  const operationGenerationRef = useRef(0);
  const activeOperationRef = useRef(0);
  const suppressedChapterIdentitiesRef = useRef(new Set<string>());
  const suppressedBookIdsRef = useRef(new Set<number>());
  const explicitlyAllowedAudioIdentitiesRef = useRef(new Set<string>());
  const audioCacheEpochByIdentityRef = useRef(new Map<string, number>());
  const pendingAudioCleanupByIdentityRef = useRef(new Map<string, Promise<void>>());

  const identity = `${bookId ?? ''}:${selectedChapterId ?? ''}`;

  const automaticAudioCacheAllowedFor = useCallback((targetBookId: number, targetChapterId: number) => {
    const targetIdentity = `${targetBookId}:${targetChapterId}`;
    if (suppressedChapterIdentitiesRef.current.has(targetIdentity)) return false;
    return !suppressedBookIdsRef.current.has(targetBookId)
      || explicitlyAllowedAudioIdentitiesRef.current.has(targetIdentity);
  }, []);

  useEffect(() => {
    const previousIdentity = identityRef.current;
    const previousBookId = Number(previousIdentity.split(':', 1)[0]);
    if (previousIdentity !== identity) {
      suppressedChapterIdentitiesRef.current.delete(previousIdentity);
      explicitlyAllowedAudioIdentitiesRef.current.delete(previousIdentity);
      if (Number.isFinite(previousBookId) && previousBookId !== bookId) {
        suppressedBookIdsRef.current.delete(previousBookId);
        for (const allowedIdentity of explicitlyAllowedAudioIdentitiesRef.current) {
          if (allowedIdentity.startsWith(`${previousBookId}:`)) {
            explicitlyAllowedAudioIdentitiesRef.current.delete(allowedIdentity);
          }
        }
      }
    }
    identityRef.current = identity;
    operationGenerationRef.current += 1;
    activeOperationRef.current = 0;
    setCacheStatus(null);
    setManifest(null);
    setCachedChapter(null);
    setCachedAudioUrl('');
    setResolvedCoverUrl(liveCoverUrl);
    setMetadataLoading(Boolean(bookId && selectedChapterId));
    setLoading(false);
    setMessage('');
  }, [identity]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      operationGenerationRef.current += 1;
      activeOperationRef.current = 0;
      audioCacheEpochByIdentityRef.current.clear();
      pendingAudioCleanupByIdentityRef.current.clear();
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
    const chapterRequest = dependencies.getCachedChapter(bookId, selectedChapterId)
      .then(async (chapter) => {
        const currentRevision = selectedChapter?.content_html_path?.trim() ?? '';
        if (chapter?.contentRevision && chapter.contentRevision !== currentRevision) return null;
        if (!chapter?.html.trim()) return chapter;
        const hydratedHtml = await dependencies.hydrateCachedChapterHtml(
          bookId,
          selectedChapterId,
          chapter.html,
          readerHtmlAssetBase(selectedChapter?.content_html_path),
        );
        return { ...chapter, html: hydratedHtml };
      })
      .catch(() => null);
    const audioRequest = dependencies.getCachedAudioUrl(
      bookId,
      selectedChapterId,
      normalizedAudioUrl,
    ).catch(() => '');
    const coverRequest = normalizedCoverUrl
      ? dependencies.getCachedCoverUrl(bookId, 0, normalizedCoverUrl).catch(() => '')
      : Promise.resolve('');

    void Promise.all([statusRequest, chapterRequest, audioRequest, coverRequest])
      .then(([nextStatus, nextCachedChapter, nextCachedAudioUrl, nextCachedCoverUrl]) => {
        if (cancelled) return;
        setCacheStatus(nextStatus);
        setCachedChapter(nextCachedChapter);
        setCachedAudioUrl(
          automaticAudioCacheAllowedFor(bookId, selectedChapterId) ? nextCachedAudioUrl : '',
        );
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
    automaticAudioCacheAllowedFor,
    bookId,
    coverUrl,
    dependencies,
    liveCoverUrl,
    nextChapterId,
    refreshVersion,
    selectedChapter?.content_html_path,
    selectedChapterId,
  ]);

  const manifestChapterAvailable = Boolean(manifest?.chapters.some((chapter) => (
    chapter.id === selectedChapterId
    && chapter.cached
    && !chapter.failed
  )));
  const currentAvailable = Boolean(
    cacheStatus?.currentCached
    || cachedChapter
    || manifestChapterAvailable,
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

  const prepareExplicitChapterCache = useCallback((targetBookId: number, targetChapterId: number) => {
    const targetIdentity = `${targetBookId}:${targetChapterId}`;
    suppressedChapterIdentitiesRef.current.delete(targetIdentity);
    if (suppressedBookIdsRef.current.has(targetBookId)) {
      explicitlyAllowedAudioIdentitiesRef.current.add(targetIdentity);
    }
    audioCacheEpochByIdentityRef.current.set(
      targetIdentity,
      (audioCacheEpochByIdentityRef.current.get(targetIdentity) ?? 0) + 1,
    );
    const pendingCleanup = pendingAudioCleanupByIdentityRef.current.get(targetIdentity);
    setSuppressionVersion((current) => current + 1);
    return pendingCleanup ?? null;
  }, []);

  const prepareExplicitBookCache = useCallback((targetBookId: number, chapterIds: number[]) => {
    const targetPrefix = `${targetBookId}:`;
    suppressedBookIdsRef.current.delete(targetBookId);
    for (const targetIdentity of suppressedChapterIdentitiesRef.current) {
      if (targetIdentity.startsWith(targetPrefix)) {
        suppressedChapterIdentitiesRef.current.delete(targetIdentity);
      }
    }
    for (const allowedIdentity of explicitlyAllowedAudioIdentitiesRef.current) {
      if (allowedIdentity.startsWith(targetPrefix)) {
        explicitlyAllowedAudioIdentitiesRef.current.delete(allowedIdentity);
      }
    }
    const targetIdentities = new Set(chapterIds.map((chapterId) => `${targetBookId}:${chapterId}`));
    for (const targetIdentity of audioCacheEpochByIdentityRef.current.keys()) {
      if (targetIdentity.startsWith(targetPrefix)) targetIdentities.add(targetIdentity);
    }
    for (const targetIdentity of pendingAudioCleanupByIdentityRef.current.keys()) {
      if (targetIdentity.startsWith(targetPrefix)) targetIdentities.add(targetIdentity);
    }
    const pendingCleanups: Promise<void>[] = [];
    for (const targetIdentity of targetIdentities) {
      audioCacheEpochByIdentityRef.current.set(
        targetIdentity,
        (audioCacheEpochByIdentityRef.current.get(targetIdentity) ?? 0) + 1,
      );
      const pendingCleanup = pendingAudioCleanupByIdentityRef.current.get(targetIdentity);
      if (pendingCleanup) pendingCleanups.push(pendingCleanup);
    }
    setSuppressionVersion((current) => current + 1);
    return pendingCleanups.length > 0
      ? Promise.all(pendingCleanups).then(() => undefined)
      : null;
  }, []);

  const suppressChapterAutomaticAudio = useCallback((targetBookId: number, targetChapterId: number) => {
    const targetIdentity = `${targetBookId}:${targetChapterId}`;
    suppressedChapterIdentitiesRef.current.add(targetIdentity);
    explicitlyAllowedAudioIdentitiesRef.current.delete(targetIdentity);
    setCachedAudioUrl('');
    setSuppressionVersion((current) => current + 1);
  }, []);

  const suppressBookAutomaticAudio = useCallback((targetBookId: number) => {
    suppressedBookIdsRef.current.add(targetBookId);
    for (const allowedIdentity of explicitlyAllowedAudioIdentitiesRef.current) {
      if (allowedIdentity.startsWith(`${targetBookId}:`)) {
        explicitlyAllowedAudioIdentitiesRef.current.delete(allowedIdentity);
      }
    }
    setCachedAudioUrl('');
    setSuppressionVersion((current) => current + 1);
  }, []);

  const reconcileLateAutomaticAudioWrite = useCallback(async (
    targetBookId: number,
    targetChapterId: number,
    expectedEpoch: number,
  ): Promise<boolean> => {
    const targetIdentity = `${targetBookId}:${targetChapterId}`;
    const existingCleanup = pendingAudioCleanupByIdentityRef.current.get(targetIdentity);
    if (existingCleanup) {
      await existingCleanup;
      return true;
    }
    if (
      (audioCacheEpochByIdentityRef.current.get(targetIdentity) ?? 0) !== expectedEpoch
      || automaticAudioCacheAllowedFor(targetBookId, targetChapterId)
    ) {
      return false;
    }

    let cleanup!: Promise<void>;
    cleanup = Promise.resolve()
      .then(async () => {
        await dependencies.removeChapter(targetBookId, targetChapterId);
        dependencies.removeManifestChapter(targetBookId, targetChapterId);
      })
      .finally(() => {
        if (pendingAudioCleanupByIdentityRef.current.get(targetIdentity) === cleanup) {
          pendingAudioCleanupByIdentityRef.current.delete(targetIdentity);
        }
    });
    pendingAudioCleanupByIdentityRef.current.set(targetIdentity, cleanup);
    await cleanup;
    if (mountedRef.current) refresh();
    return true;
  }, [automaticAudioCacheAllowedFor, dependencies, refresh]);

  const cacheAudio = useCallback(async (
    targetBookId: number,
    targetChapterId: number,
    url: string,
  ) => {
    const targetIdentity = `${targetBookId}:${targetChapterId}`;
    const audioCacheEpoch = audioCacheEpochByIdentityRef.current.get(targetIdentity) ?? 0;
    audioCacheEpochByIdentityRef.current.set(targetIdentity, audioCacheEpoch);
    const result = await dependencies.cacheAudio(targetBookId, targetChapterId, url);
    if (!result.cached) return result;
    if (await reconcileLateAutomaticAudioWrite(targetBookId, targetChapterId, audioCacheEpoch)) {
      return { ...result, cached: false };
    }
    const nextCachedUrl = await dependencies.getCachedAudioUrl(targetBookId, targetChapterId, url);
    if (
      mountedRef.current
      && identityRef.current === `${targetBookId}:${targetChapterId}`
    ) {
      setCachedAudioUrl(nextCachedUrl);
      refresh();
    }
    return result;
  }, [dependencies, reconcileLateAutomaticAudioWrite, refresh]);

  const cacheCurrentChapter = useCallback(async (audioUrlOverride = audioUrl): Promise<void> => {
    if (!apiClient || !bookId || !selectedChapter) {
      setMessage('Không thể cache chương: thiếu kết nối API hoặc chương đang đọc.');
      return;
    }
    if (!selectedChapter.has_translation) {
      setMessage('Chỉ cache offline được chương đã có bản dịch.');
      return;
    }

    const pendingAudioCleanup = prepareExplicitChapterCache(bookId, selectedChapter.id);

    const operation = beginOperation();
    setMessage(`Đang tải Chương ${selectedChapter.chapter_number} để đọc offline...`);
    try {
      if (pendingAudioCleanup) await pendingAudioCleanup;
      const summary = await dependencies.cacheChapter({
        audioUrl: audioUrlOverride,
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
    prepareExplicitChapterCache,
    refresh,
    selectedChapter,
  ]);

  const removeCurrentChapter = useCallback(async (): Promise<void> => {
    if (!bookId || !selectedChapterId || !selectedChapter) {
      setMessage('Không thể xóa cache chương: chưa chọn chương.');
      return;
    }

    suppressChapterAutomaticAudio(bookId, selectedChapterId);

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
    suppressChapterAutomaticAudio,
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

    const pendingAudioCleanups = prepareExplicitBookCache(
      bookId,
      translatedChapters.map((chapter) => chapter.id),
    );

    const operation = beginOperation();
    setMessage(`Đang cache offline 0/${translatedChapters.length} chương...`);
    try {
      if (pendingAudioCleanups) await pendingAudioCleanups;
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
    prepareExplicitBookCache,
    refresh,
    translatedChapters,
  ]);

  const removeCurrentBook = useCallback(async (): Promise<void> => {
    if (!bookId) {
      setMessage('Không thể xóa cache offline: chưa chọn truyện.');
      return;
    }

    suppressBookAutomaticAudio(bookId);

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
    suppressBookAutomaticAudio,
  ]);

  const allowAutomaticAudioCache = Boolean(
    bookId
    && selectedChapterId
    && automaticAudioCacheAllowedFor(bookId, selectedChapterId),
  );

  return {
    cacheStatus,
    allowAutomaticAudioCache,
    cacheAudio,
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
