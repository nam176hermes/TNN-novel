import { act, renderHook, waitFor } from '@testing-library/react';
import { useEffect } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Chapter } from '../../api/types';
import { READER_CACHE_UPDATED_EVENT, type ReaderCachedChapter, type ReaderCacheStatus } from '../../state/readerCache';
import type { ReaderOfflineCacheSummary, ReaderOfflineManifest } from '../../state/readerOfflineCache';
import {
  useReaderOfflineCache,
  type ReaderOfflineCacheDependencies,
} from './useReaderOfflineCache';

const chapters: Chapter[] = [
  { id: 101, book_id: 42, chapter_number: 1, title: 'Sơn biên tiểu thôn', status: 'translated', audio_path: null, has_translation: true },
  { id: 102, book_id: 42, chapter_number: 2, title: 'Thanh Ngưu trấn', status: 'translated', audio_path: '/audio/chapter-102.mp3', has_translation: true },
  { id: 103, book_id: 42, chapter_number: 3, title: 'Thất Huyền Môn', status: 'translated', audio_path: null, has_translation: true },
];

const cacheStatus: ReaderCacheStatus = {
  audioCount: 1,
  audioSizeBytes: 20,
  audioSizeLabel: '20 B',
  assetCount: 2,
  assetSizeBytes: 30,
  assetSizeLabel: '30 B',
  currentCached: true,
  nextCached: false,
  sizeBytes: 100,
  sizeLabel: '1 KB',
};

function manifest(bookId = 42, chapterIds = [102]): ReaderOfflineManifest {
  return {
    assets: [],
    audio: [],
    bookId,
    cachedAt: '2026-07-14T00:00:00Z',
    chapterIds,
    chapters: chapterIds.map((id) => ({ cached: true, failed: false, htmlCached: true, id, textCached: true })),
    checksum: `manifest-${bookId}`,
    cover: null,
    dictionary: {
      cached: false,
      chapterPacks: [],
      counts: { builtin: 0, glossary: 0, offline_dictionary: 0, xray: 0 },
      files: [],
      generatedAt: '',
      sourceCount: 0,
    },
    summary: {
      assetsCached: 0,
      assetsFailed: 0,
      assetsTotal: 0,
      audioCached: 0,
      audioFailed: 0,
      audioTotal: 0,
      chaptersCached: chapterIds.length,
      chaptersFailed: 0,
      chaptersTotal: chapterIds.length,
      dictionaryCached: false,
    },
    version: 3,
  };
}

function cachedChapter(bookId = 42, chapterId = 102): ReaderCachedChapter {
  return {
    bookId,
    cachedAt: '2026-07-14T00:00:00Z',
    chapterId,
    html: '<p>Bản dịch đã cache</p>',
    sourceText: '原文',
    text: 'Bản dịch đã cache',
  };
}

function dependencies(overrides: Partial<ReaderOfflineCacheDependencies> = {}): ReaderOfflineCacheDependencies {
  return {
    cacheAudio: vi.fn().mockResolvedValue({
      cached: true,
      failed: false,
      sizeBytes: 10,
      url: '/api/books/42/chapters/102/audio',
    }),
    cacheBook: vi.fn().mockResolvedValue({
      assetsCached: 1,
      assetsFailed: 0,
      assetsTotal: 1,
      audioCached: 1,
      audioFailed: 0,
      audioTotal: 1,
      chaptersCached: 3,
      chaptersFailed: 0,
      chaptersTotal: 3,
      dictionaryCached: true,
    }),
    cacheChapter: vi.fn().mockResolvedValue({
      assetsCached: 1,
      assetsFailed: 0,
      assetsTotal: 1,
      audioCached: 1,
      audioFailed: 0,
      audioTotal: 1,
    }),
    getCachedAudioUrl: vi.fn().mockResolvedValue('blob:cached-audio'),
    getCachedChapter: vi.fn().mockResolvedValue(cachedChapter()),
    getCachedCoverUrl: vi.fn().mockResolvedValue('blob:cached-cover'),
    hydrateCachedChapterHtml: vi.fn(async (_bookId, _chapterId, html) => html),
    loadManifest: vi.fn().mockReturnValue(manifest()),
    readStatus: vi.fn().mockResolvedValue(cacheStatus),
    removeBook: vi.fn().mockResolvedValue(undefined),
    removeChapter: vi.fn().mockResolvedValue(undefined),
    removeManifest: vi.fn(),
    removeManifestChapter: vi.fn(),
    ...overrides,
  };
}

function options(deps: ReaderOfflineCacheDependencies, overrides: Record<string, unknown> = {}) {
  return {
    apiClient: {
      chapterAudioUrl: vi.fn((bookId: number, chapterId: number) => `/api/books/${bookId}/chapters/${chapterId}/audio`),
      getChapterContent: vi.fn(),
      getChapterTranslation: vi.fn(),
      getReaderDictionaryPack: vi.fn(),
    },
    audioUrl: '/api/books/42/chapters/102/audio',
    bookId: 42,
    chapters,
    coverUrl: '/covers/42.jpg',
    dependencies: deps,
    liveCoverUrl: '/covers/42.jpg',
    nextChapterId: 103,
    onError: vi.fn(),
    selectedChapter: chapters[1],
    selectedChapterId: 102,
    ...overrides,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

describe('useReaderOfflineCache', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    Object.defineProperty(window.navigator, 'onLine', { configurable: true, value: true });
  });

  it('loads manifest, status, cached content, audio and cover for the current chapter', async () => {
    const deps = dependencies();
    const { result } = renderHook(() => useReaderOfflineCache(options(deps)));

    await waitFor(() => expect(result.current.cacheStatus).toEqual(cacheStatus));

    expect(deps.readStatus).toHaveBeenCalledWith({ bookId: 42, chapterId: 102, nextChapterId: 103 });
    expect(deps.loadManifest).toHaveBeenCalledWith(42);
    expect(deps.getCachedChapter).toHaveBeenCalledWith(42, 102);
    expect(deps.getCachedAudioUrl).toHaveBeenCalledWith(42, 102, '/api/books/42/chapters/102/audio');
    expect(deps.getCachedCoverUrl).toHaveBeenCalledWith(42, 0, '/covers/42.jpg');
    expect(result.current.manifest?.checksum).toBe('manifest-42');
    expect(result.current.cacheStatus).toEqual(cacheStatus);
    expect(result.current.cachedChapter?.text).toBe('Bản dịch đã cache');
    expect(result.current.cachedAudioUrl).toBe('blob:cached-audio');
    expect(result.current.coverUrl).toBe('blob:cached-cover');
    expect(result.current.currentAvailable).toBe(true);
  });

  it('reloads metadata after the existing reader-cache update event', async () => {
    const deps = dependencies();
    const { result } = renderHook(() => useReaderOfflineCache(options(deps)));
    await waitFor(() => expect(result.current.cacheStatus).toEqual(cacheStatus));

    act(() => window.dispatchEvent(new Event(READER_CACHE_UPDATED_EVENT)));

    await waitFor(() => expect(deps.readStatus).toHaveBeenCalledTimes(2));
    expect(deps.loadManifest).toHaveBeenCalledTimes(2);
    expect(deps.getCachedChapter).toHaveBeenCalledTimes(2);
    expect(deps.getCachedAudioUrl).toHaveBeenCalledTimes(2);
  });

  it('keeps a successful cached audio URL stable across its update event and explicit refresh', async () => {
    const refreshedAudio = deferred<string>();
    const cacheAudio = vi.fn()
      .mockImplementationOnce(async () => {
        window.dispatchEvent(new Event(READER_CACHE_UPDATED_EVENT));
        return { cached: true, failed: false, sizeBytes: 10, url: '/live-audio' };
      })
      .mockResolvedValue({ cached: false, failed: false, sizeBytes: 0, url: '/live-audio' });
    const getCachedAudioUrl = vi.fn()
      .mockResolvedValueOnce('')
      .mockResolvedValueOnce('blob:stable-audio')
      .mockReturnValueOnce(refreshedAudio.promise)
      .mockResolvedValue('blob:stable-audio');
    const deps = dependencies({ cacheAudio, getCachedAudioUrl });

    const { result } = renderHook(() => {
      const cache = useReaderOfflineCache(options(deps));
      useEffect(() => {
        if (cache.cachedAudioUrl) return;
        void cache.cacheAudio(42, 102, '/live-audio');
      }, [cache.cacheAudio, cache.cachedAudioUrl]);
      return cache;
    });

    await waitFor(() => expect(getCachedAudioUrl).toHaveBeenCalledTimes(3));
    expect(cacheAudio).toHaveBeenCalledTimes(1);
    await act(async () => refreshedAudio.resolve('blob:stable-audio'));
    await waitFor(() => expect(result.current.cachedAudioUrl).toBe('blob:stable-audio'));
    act(() => result.current.refresh());
    await waitFor(() => expect(deps.readStatus).toHaveBeenCalledTimes(4));

    expect(cacheAudio).toHaveBeenCalledTimes(1);
    expect(result.current.cachedAudioUrl).toBe('blob:stable-audio');
  });

  it('hydrates cached rich HTML through the existing reader asset resolver before exposing it', async () => {
    const richCachedChapter = {
      ...cachedChapter(),
      html: [
        '<img src="./images/cover.jpg">',
        '<div style="background-image:url(\'./images/bg.jpg\')"></div>',
        '<video poster="./images/poster.jpg"><source src="./media/chapter.mp4"></video>',
      ].join(''),
    };
    const hydratedHtml = richCachedChapter.html
      .replace('./images/cover.jpg', 'blob:cover')
      .replace('./images/bg.jpg', 'blob:bg')
      .replace('./images/poster.jpg', 'blob:poster')
      .replace('./media/chapter.mp4', 'blob:video');
    const hydrateCachedChapterHtml = vi.fn().mockResolvedValue(hydratedHtml);
    const deps = dependencies({
      getCachedChapter: vi.fn().mockResolvedValue(richCachedChapter),
      hydrateCachedChapterHtml,
    } as unknown as Partial<ReaderOfflineCacheDependencies>);

    const { result } = renderHook(() => useReaderOfflineCache(options(deps, {
      selectedChapter: {
        ...chapters[1],
        content_html_path: '/book-assets/42/OEBPS/chapter-2.xhtml',
      },
    })));

    await waitFor(() => expect(result.current.cachedChapter?.html).toBe(hydratedHtml));
    expect(hydrateCachedChapterHtml).toHaveBeenCalledWith(
      42,
      102,
      richCachedChapter.html,
      '/book-assets/42/OEBPS/chapter-2.xhtml',
    );
    expect(result.current.cachedChapter?.html).toContain('blob:cover');
    expect(result.current.cachedChapter?.html).toContain('blob:bg');
    expect(result.current.cachedChapter?.html).toContain('blob:poster');
    expect(result.current.cachedChapter?.html).toContain('blob:video');
  });

  it('caches and removes the current chapter while preserving manifest ownership', async () => {
    const loadManifest = vi.fn()
      .mockReturnValueOnce(manifest())
      .mockReturnValueOnce(manifest(42, [102, 103]))
      .mockReturnValue(manifest(42, [103]));
    const deps = dependencies({ loadManifest });
    const onError = vi.fn();
    const { result } = renderHook(() => useReaderOfflineCache(options(deps, { onError })));
    await waitFor(() => expect(result.current.cacheStatus).toEqual(cacheStatus));

    await act(async () => result.current.cacheCurrentChapter());
    expect(deps.cacheChapter).toHaveBeenCalledWith(expect.objectContaining({
      audioUrl: '/api/books/42/chapters/102/audio',
      bookId: 42,
      chapter: chapters[1],
    }));
    expect(result.current.message).toBe('Đã tải Chương 2 offline · 1/1 asset · 1/1 audio');

    await act(async () => result.current.removeCurrentChapter());
    expect(deps.removeChapter).toHaveBeenCalledWith(42, 102);
    expect(deps.removeManifestChapter).toHaveBeenCalledWith(42, 102);
    expect(result.current.message).toBe('Đã xóa cache offline Chương 2.');
    expect(onError).toHaveBeenLastCalledWith('');
  });

  it('suppresses automatic audio caching after chapter removal until explicit cache or navigation', async () => {
    const cacheAudio = vi.fn().mockResolvedValue({ cached: true, failed: false, sizeBytes: 10, url: '/live' });
    const deps = dependencies({
      cacheAudio,
      getCachedAudioUrl: vi.fn()
        .mockResolvedValueOnce('blob:initial-audio')
        .mockResolvedValueOnce('')
        .mockResolvedValue('blob:explicit-audio'),
    });
    const { result, rerender } = renderHook(
      ({ selectedChapter, selectedChapterId }) => {
        const cache = useReaderOfflineCache(options(deps, { selectedChapter, selectedChapterId }));
        useEffect(() => {
          if (
            cache.metadataLoading
            || cache.cachedAudioUrl
            || cache.allowAutomaticAudioCache === false
          ) return;
          void cache.cacheAudio(42, selectedChapterId, '/live');
        }, [
          cache.allowAutomaticAudioCache,
          cache.cacheAudio,
          cache.cachedAudioUrl,
          cache.metadataLoading,
          selectedChapterId,
        ]);
        return cache;
      },
      { initialProps: { selectedChapter: chapters[1], selectedChapterId: 102 } },
    );

    await waitFor(() => expect(result.current.cachedAudioUrl).toBe('blob:initial-audio'));
    await act(async () => result.current.removeCurrentChapter());
    await waitFor(() => expect(result.current.cachedAudioUrl).toBe(''));
    rerender({ selectedChapter: chapters[1], selectedChapterId: 102 });
    await act(async () => Promise.resolve());

    expect(result.current.allowAutomaticAudioCache).toBe(false);
    expect(cacheAudio).not.toHaveBeenCalled();

    await act(async () => result.current.cacheCurrentChapter());
    expect(result.current.allowAutomaticAudioCache).toBe(true);

    rerender({ selectedChapter: chapters[2], selectedChapterId: 103 });
    await waitFor(() => expect(result.current.allowAutomaticAudioCache).toBe(true));
  });

  it('reconciles a late automatic audio write after chapter removal', async () => {
    const pendingAudio = deferred<{ cached: boolean; failed: boolean; sizeBytes: number; url: string }>();
    const cacheAudio = vi.fn().mockReturnValue(pendingAudio.promise);
    const removeChapter = vi.fn().mockResolvedValue(undefined);
    const deps = dependencies({
      cacheAudio,
      getCachedAudioUrl: vi.fn().mockResolvedValue(''),
      removeChapter,
    });
    const { result } = renderHook(() => {
      const cache = useReaderOfflineCache(options(deps));
      useEffect(() => {
        if (
          cache.metadataLoading
          || cache.cachedAudioUrl
          || cache.allowAutomaticAudioCache === false
        ) return;
        void cache.cacheAudio(42, 102, '/live');
      }, [
        cache.allowAutomaticAudioCache,
        cache.cacheAudio,
        cache.cachedAudioUrl,
        cache.metadataLoading,
      ]);
      return cache;
    });

    await waitFor(() => expect(cacheAudio).toHaveBeenCalledTimes(1));
    await act(async () => result.current.removeCurrentChapter());
    expect(removeChapter).toHaveBeenCalledTimes(1);

    await act(async () => pendingAudio.resolve({
      cached: true,
      failed: false,
      sizeBytes: 10,
      url: '/live',
    }));
    await waitFor(() => expect(removeChapter).toHaveBeenCalledTimes(2));

    expect(result.current.cachedAudioUrl).toBe('');
    expect(result.current.allowAutomaticAudioCache).toBe(false);
    expect(deps.removeManifestChapter).toHaveBeenCalledWith(42, 102);
  });

  it('reconciles a late book-suppressed audio write without removing newer explicit chapter cache', async () => {
    const pendingAudio = deferred<{ cached: boolean; failed: boolean; sizeBytes: number; url: string }>();
    const removeBook = vi.fn().mockResolvedValue(undefined);
    const removeChapter = vi.fn().mockResolvedValue(undefined);
    const cacheChapter = vi.fn().mockResolvedValue({
      assetsCached: 0,
      assetsFailed: 0,
      assetsTotal: 0,
      audioCached: 1,
      audioFailed: 0,
      audioTotal: 1,
    });
    const deps = dependencies({
      cacheAudio: vi.fn().mockReturnValue(pendingAudio.promise),
      cacheChapter,
      getCachedAudioUrl: vi.fn().mockResolvedValue(''),
      removeBook,
      removeChapter,
    });
    const { result, rerender } = renderHook(
      ({ selectedChapter, selectedChapterId }) => useReaderOfflineCache(options(deps, {
        audioUrl: `/api/books/42/chapters/${selectedChapterId}/audio`,
        selectedChapter,
        selectedChapterId,
      })),
      { initialProps: { selectedChapter: chapters[1], selectedChapterId: 102 } },
    );
    await waitFor(() => expect(result.current.metadataLoading).toBe(false));

    let automaticCache!: Promise<unknown>;
    act(() => {
      automaticCache = result.current.cacheAudio(42, 102, '/live-audio-102');
    });
    await act(async () => result.current.removeCurrentBook());
    expect(removeBook).toHaveBeenCalledTimes(1);

    rerender({ selectedChapter: chapters[2], selectedChapterId: 103 });
    await act(async () => result.current.cacheCurrentChapter('/live-audio-103'));
    expect(cacheChapter).toHaveBeenCalledWith(expect.objectContaining({
      audioUrl: '/live-audio-103',
      chapter: chapters[2],
    }));

    await act(async () => {
      pendingAudio.resolve({ cached: true, failed: false, sizeBytes: 10, url: '/live-audio-102' });
      await automaticCache;
    });

    expect(removeChapter).toHaveBeenCalledWith(42, 102);
    expect(removeChapter).not.toHaveBeenCalledWith(42, 103);
    expect(removeBook).toHaveBeenCalledTimes(1);
  });

  it('waits for same-chapter late cleanup before writing an explicit cache', async () => {
    const pendingAudio = deferred<{ cached: boolean; failed: boolean; sizeBytes: number; url: string }>();
    const pendingCleanup = deferred<void>();
    const removeChapter = vi.fn()
      .mockResolvedValueOnce(undefined)
      .mockReturnValueOnce(pendingCleanup.promise);
    const cacheChapter = vi.fn().mockResolvedValue({
      assetsCached: 0,
      assetsFailed: 0,
      assetsTotal: 0,
      audioCached: 1,
      audioFailed: 0,
      audioTotal: 1,
    });
    const deps = dependencies({
      cacheAudio: vi.fn().mockReturnValue(pendingAudio.promise),
      cacheChapter,
      getCachedAudioUrl: vi.fn().mockResolvedValue(''),
      removeChapter,
    });
    const { result } = renderHook(() => useReaderOfflineCache(options(deps)));
    await waitFor(() => expect(result.current.metadataLoading).toBe(false));

    let automaticCache!: Promise<unknown>;
    act(() => {
      automaticCache = result.current.cacheAudio(42, 102, '/live-audio');
    });
    await act(async () => result.current.removeCurrentChapter());

    act(() => pendingAudio.resolve({ cached: true, failed: false, sizeBytes: 10, url: '/live-audio' }));
    await waitFor(() => expect(removeChapter).toHaveBeenCalledTimes(2));

    let explicitCache!: Promise<void>;
    act(() => {
      explicitCache = result.current.cacheCurrentChapter('/live-audio');
    });
    await act(async () => Promise.resolve());
    expect(cacheChapter).not.toHaveBeenCalled();

    await act(async () => {
      pendingCleanup.resolve();
      await Promise.all([automaticCache, explicitCache]);
    });

    expect(cacheChapter).toHaveBeenCalledTimes(1);
    expect(removeChapter.mock.invocationCallOrder[1]).toBeLessThan(cacheChapter.mock.invocationCallOrder[0]);
    expect(result.current.allowAutomaticAudioCache).toBe(true);
    expect(deps.removeBook).not.toHaveBeenCalled();
  });

  it('does not clean a late automatic write when explicit caching starts before it completes', async () => {
    const pendingAudio = deferred<{ cached: boolean; failed: boolean; sizeBytes: number; url: string }>();
    const removeChapter = vi.fn().mockResolvedValue(undefined);
    const deps = dependencies({
      cacheAudio: vi.fn().mockReturnValue(pendingAudio.promise),
      getCachedAudioUrl: vi.fn().mockResolvedValue('blob:explicit-audio'),
      removeChapter,
    });
    const { result } = renderHook(() => useReaderOfflineCache(options(deps)));
    await waitFor(() => expect(result.current.metadataLoading).toBe(false));

    let automaticCache!: Promise<unknown>;
    act(() => {
      automaticCache = result.current.cacheAudio(42, 102, '/live-audio');
    });
    await act(async () => result.current.removeCurrentChapter());
    await act(async () => result.current.cacheCurrentChapter('/live-audio'));

    await act(async () => {
      pendingAudio.resolve({ cached: true, failed: false, sizeBytes: 10, url: '/live-audio' });
      await automaticCache;
    });

    expect(removeChapter).toHaveBeenCalledTimes(1);
    expect(deps.removeBook).not.toHaveBeenCalled();
    expect(result.current.allowAutomaticAudioCache).toBe(true);
  });

  it('suppresses every chapter in a removed book until leaving that book or caching explicitly', async () => {
    const deps = dependencies({ getCachedAudioUrl: vi.fn().mockResolvedValue('') });
    const { result, rerender } = renderHook(
      ({ bookId, selectedChapter, selectedChapterId }) => useReaderOfflineCache(options(deps, {
        bookId,
        selectedChapter,
        selectedChapterId,
      })),
      {
        initialProps: {
          bookId: 42,
          selectedChapter: chapters[1],
          selectedChapterId: 102,
        },
      },
    );

    await waitFor(() => expect(result.current.metadataLoading).toBe(false));
    await act(async () => result.current.removeCurrentBook());
    expect(result.current.allowAutomaticAudioCache).toBe(false);

    rerender({ bookId: 42, selectedChapter: chapters[2], selectedChapterId: 103 });
    expect(result.current.allowAutomaticAudioCache).toBe(false);

    await act(async () => result.current.cacheCurrentChapter());
    expect(result.current.allowAutomaticAudioCache).toBe(true);

    rerender({
      bookId: 43,
      selectedChapter: { ...chapters[0], book_id: 43, id: 201 },
      selectedChapterId: 201,
    });
    await waitFor(() => expect(result.current.allowAutomaticAudioCache).toBe(true));
  });

  it('caches and removes the translated book with progress and summary messages', async () => {
    const pendingCache = deferred<ReaderOfflineCacheSummary>();
    const deps = dependencies({ cacheBook: vi.fn().mockReturnValue(pendingCache.promise) });
    const { result } = renderHook(() => useReaderOfflineCache(options(deps)));
    await waitFor(() => expect(result.current.cacheStatus).toEqual(cacheStatus));

    let cachePromise!: Promise<void>;
    act(() => {
      cachePromise = result.current.cacheCurrentBook();
    });
    const cacheBookOptions = vi.mocked(deps.cacheBook).mock.calls[0][0];
    act(() => cacheBookOptions.onProgress?.({
      assetsCached: 0,
      assetsFailed: 0,
      assetsTotal: 0,
      audioCached: 0,
      audioFailed: 0,
      audioTotal: 0,
      chaptersCached: 2,
      chaptersFailed: 0,
      chaptersTotal: 3,
      currentChapterId: 102,
      dictionaryCached: false,
    }));
    expect(result.current.message).toBe('Đang cache offline 2/3 chương...');

    await act(async () => {
      pendingCache.resolve({
        assetsCached: 1,
        assetsFailed: 0,
        assetsTotal: 1,
        audioCached: 1,
        audioFailed: 0,
        audioTotal: 1,
        chaptersCached: 3,
        chaptersFailed: 0,
        chaptersTotal: 3,
        dictionaryCached: true,
      });
      await cachePromise;
    });
    expect(deps.cacheBook).toHaveBeenCalledWith(expect.objectContaining({ bookId: 42, chapters }));
    expect(result.current.message).toBe('Đã cache offline 3/3 chương · 1/1 asset · 1/1 audio · đã cache từ điển');

    await act(async () => result.current.removeCurrentBook());
    expect(deps.removeBook).toHaveBeenCalledWith(42);
    expect(deps.removeManifest).toHaveBeenCalledWith(42);
    expect(result.current.message).toBe('Đã xóa cache offline của truyện này.');
  });

  it('distinguishes offline with cached content from offline without cache', async () => {
    Object.defineProperty(window.navigator, 'onLine', { configurable: true, value: false });
    const withCache = dependencies();
    const first = renderHook(() => useReaderOfflineCache(options(withCache)));
    await waitFor(() => expect(first.result.current.offlineState).toBe('offline-with-cache'));
    first.unmount();

    const withoutCache = dependencies({
      getCachedChapter: vi.fn().mockResolvedValue(null),
      loadManifest: vi.fn().mockReturnValue(null),
      readStatus: vi.fn().mockResolvedValue({ ...cacheStatus, currentCached: false }),
    });
    const second = renderHook(() => useReaderOfflineCache(options(withoutCache)));
    await waitFor(() => expect(second.result.current.offlineState).toBe('offline-without-cache'));

    act(() => window.dispatchEvent(new Event('online')));
    expect(second.result.current.offlineState).toBe('online');
  });

  it('does not treat a failed manifest chapter entry as available offline', async () => {
    Object.defineProperty(window.navigator, 'onLine', { configurable: true, value: false });
    const failedManifest = manifest();
    failedManifest.chapters = [{
      cached: false,
      failed: true,
      htmlCached: false,
      id: 102,
      textCached: false,
    }];
    failedManifest.summary = {
      ...failedManifest.summary,
      chaptersCached: 0,
      chaptersFailed: 1,
    };
    const deps = dependencies({
      getCachedChapter: vi.fn().mockResolvedValue(null),
      loadManifest: vi.fn().mockReturnValue(failedManifest),
      readStatus: vi.fn().mockResolvedValue({ ...cacheStatus, currentCached: false }),
    });
    const { result } = renderHook(() => useReaderOfflineCache(options(deps)));

    await waitFor(() => expect(result.current.metadataLoading).toBe(false));

    expect(result.current.currentAvailable).toBe(false);
    expect(result.current.offlineState).toBe('offline-without-cache');
  });

  it('removes cache and connectivity listeners on unmount', async () => {
    const addSpy = vi.spyOn(window, 'addEventListener');
    const removeSpy = vi.spyOn(window, 'removeEventListener');
    const deps = dependencies();
    const { result, unmount } = renderHook(() => useReaderOfflineCache(options(deps)));
    await waitFor(() => expect(result.current.cacheStatus).toEqual(cacheStatus));

    unmount();

    expect(removeSpy).toHaveBeenCalledWith(READER_CACHE_UPDATED_EVENT, expect.any(Function));
    expect(removeSpy).toHaveBeenCalledWith('online', expect.any(Function));
    expect(removeSpy).toHaveBeenCalledWith('offline', expect.any(Function));
    expect(addSpy).toHaveBeenCalledWith(READER_CACHE_UPDATED_EVENT, expect.any(Function));
  });

  it('suppresses stale async cache state after rapid chapter and book changes', async () => {
    const firstStatus = deferred<ReaderCacheStatus>();
    const firstChapter = deferred<ReaderCachedChapter | null>();
    const firstAudio = deferred<string>();
    const deps = dependencies({
      getCachedAudioUrl: vi.fn()
        .mockReturnValueOnce(firstAudio.promise)
        .mockResolvedValueOnce('blob:book-43-audio'),
      getCachedChapter: vi.fn()
        .mockReturnValueOnce(firstChapter.promise)
        .mockResolvedValueOnce(cachedChapter(43, 201)),
      loadManifest: vi.fn((bookId: number) => manifest(bookId, bookId === 43 ? [201] : [102])),
      readStatus: vi.fn()
        .mockReturnValueOnce(firstStatus.promise)
        .mockResolvedValueOnce({ ...cacheStatus, currentCached: true, sizeLabel: '43 KB' }),
    });
    const nextChapter: Chapter = {
      id: 201,
      book_id: 43,
      chapter_number: 1,
      title: 'Book 43',
      status: 'translated',
      audio_path: '/audio/201.mp3',
      has_translation: true,
    };
    const { result, rerender } = renderHook(
      ({ bookId, chapter }) => useReaderOfflineCache(options(deps, {
        audioUrl: `/api/books/${bookId}/chapters/${chapter.id}/audio`,
        bookId,
        chapters: [chapter],
        coverUrl: '',
        liveCoverUrl: '',
        nextChapterId: null,
        selectedChapter: chapter,
        selectedChapterId: chapter.id,
      })),
      { initialProps: { bookId: 42, chapter: chapters[1] } },
    );

    rerender({ bookId: 43, chapter: nextChapter });
    await waitFor(() => expect(result.current.cachedChapter?.bookId).toBe(43));

    await act(async () => {
      firstStatus.resolve({ ...cacheStatus, sizeLabel: 'stale' });
      firstChapter.resolve(cachedChapter(42, 102));
      firstAudio.resolve('blob:stale-audio');
      await Promise.all([firstStatus.promise, firstChapter.promise, firstAudio.promise]);
    });

    expect(result.current.cacheStatus?.sizeLabel).toBe('43 KB');
    expect(result.current.cachedChapter?.bookId).toBe(43);
    expect(result.current.cachedAudioUrl).toBe('blob:book-43-audio');
    expect(result.current.manifest?.bookId).toBe(43);
  });

  it('clears an in-flight action when the selected chapter changes and ignores its late result', async () => {
    const pendingCache = deferred<ReaderOfflineCacheSummary>();
    const deps = dependencies({ cacheChapter: vi.fn().mockReturnValue(pendingCache.promise) });
    const onError = vi.fn();
    const { result, rerender } = renderHook(
      ({ chapter }) => useReaderOfflineCache(options(deps, {
        audioUrl: `/api/books/42/chapters/${chapter.id}/audio`,
        onError,
        selectedChapter: chapter,
        selectedChapterId: chapter.id,
      })),
      { initialProps: { chapter: chapters[1] } },
    );
    await waitFor(() => expect(result.current.cacheStatus).toEqual(cacheStatus));

    act(() => {
      void result.current.cacheCurrentChapter();
    });
    expect(result.current.loading).toBe(true);
    rerender({ chapter: chapters[2] });

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.message).toBe('');

    await act(async () => {
      pendingCache.resolve({
        assetsCached: 0,
        assetsFailed: 0,
        assetsTotal: 0,
        audioCached: 0,
        audioFailed: 0,
        audioTotal: 0,
        chaptersCached: 1,
        chaptersFailed: 0,
        chaptersTotal: 1,
        dictionaryCached: false,
      });
      await pendingCache.promise;
    });

    expect(result.current.message).toBe('');
    expect(onError).not.toHaveBeenCalled();
  });

  it('contains cache action failures and releases the busy state', async () => {
    const deps = dependencies({ cacheChapter: vi.fn().mockRejectedValue(new Error('cache unavailable')) });
    const onError = vi.fn();
    const { result } = renderHook(() => useReaderOfflineCache(options(deps, { onError })));
    await waitFor(() => expect(result.current.cacheStatus).toEqual(cacheStatus));

    await act(async () => result.current.cacheCurrentChapter());

    expect(result.current.loading).toBe(false);
    expect(result.current.message).toBe('');
    expect(onError).toHaveBeenCalledWith('cache unavailable');
  });
});
