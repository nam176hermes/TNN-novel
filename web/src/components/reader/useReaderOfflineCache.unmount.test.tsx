import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { Chapter } from '../../api/types';
import type { ReaderCacheStatus } from '../../state/readerCache';
import {
  useReaderOfflineCache,
  type ReaderOfflineCacheDependencies,
} from './useReaderOfflineCache';

const stateUpdates = vi.hoisted(() => ({ enabled: false, total: 0 }));

vi.mock('react', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react')>();
  return {
    ...actual,
    useState: <T,>(initialState: T | (() => T)) => {
      const [value, setValue] = actual.useState(initialState);
      const trackedSetValue: typeof setValue = (nextValue) => {
        if (stateUpdates.enabled) stateUpdates.total += 1;
        setValue(nextValue);
      };
      return [value, trackedSetValue] as const;
    },
  };
});

const chapter: Chapter = {
  id: 102,
  book_id: 42,
  chapter_number: 2,
  title: 'Thanh Ngưu trấn',
  status: 'translated',
  audio_path: '/audio/chapter-102.mp3',
  has_translation: true,
};

const emptyStatus: ReaderCacheStatus = {
  audioCount: 0,
  audioSizeBytes: 0,
  audioSizeLabel: '0 B',
  assetCount: 0,
  assetSizeBytes: 0,
  assetSizeLabel: '0 B',
  currentCached: false,
  nextCached: null,
  sizeBytes: 0,
  sizeLabel: '0 B',
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

afterEach(() => {
  stateUpdates.enabled = false;
  stateUpdates.total = 0;
  vi.restoreAllMocks();
});

it('finishes a deferred privacy cleanup after unmount without refreshing hook state', async () => {
  const pendingAudio = deferred<{ cached: boolean; failed: boolean; sizeBytes: number; url: string }>();
  const pendingCleanup = deferred<void>();
  const removeChapter = vi.fn()
    .mockResolvedValueOnce(undefined)
    .mockReturnValueOnce(pendingCleanup.promise);
  const readStatus = vi.fn().mockResolvedValue(emptyStatus);
  const getCachedChapter = vi.fn().mockResolvedValue(null);
  const getCachedAudioUrl = vi.fn().mockResolvedValue('');
  const dependencies: ReaderOfflineCacheDependencies = {
    cacheAudio: vi.fn().mockReturnValue(pendingAudio.promise),
    cacheBook: vi.fn(),
    cacheChapter: vi.fn(),
    getCachedAudioUrl,
    getCachedChapter,
    getCachedCoverUrl: vi.fn().mockResolvedValue(''),
    hydrateCachedChapterHtml: vi.fn(async (_bookId, _chapterId, html) => html),
    loadManifest: vi.fn().mockReturnValue(null),
    readStatus,
    removeBook: vi.fn(),
    removeChapter,
    removeManifest: vi.fn(),
    removeManifestChapter: vi.fn(),
  };
  const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
  const { result, unmount } = renderHook(() => useReaderOfflineCache({
    apiClient: {
      chapterAudioUrl: vi.fn(),
      getChapterContent: vi.fn(),
      getChapterTranslation: vi.fn(),
      getReaderDictionaryPack: vi.fn(),
    },
    audioUrl: '/api/books/42/chapters/102/audio',
    bookId: 42,
    chapters: [chapter],
    dependencies,
    onError: vi.fn(),
    selectedChapter: chapter,
    selectedChapterId: 102,
  }));
  await waitFor(() => expect(result.current.metadataLoading).toBe(false));

  let automaticCache!: Promise<unknown>;
  act(() => {
    automaticCache = result.current.cacheAudio(42, 102, '/live-audio');
  });
  await act(async () => result.current.removeCurrentChapter());
  act(() => pendingAudio.resolve({ cached: true, failed: false, sizeBytes: 10, url: '/live-audio' }));
  await waitFor(() => expect(removeChapter).toHaveBeenCalledTimes(2));

  const statusReadsBeforeUnmount = readStatus.mock.calls.length;
  const chapterReadsBeforeUnmount = getCachedChapter.mock.calls.length;
  const audioReadsBeforeUnmount = getCachedAudioUrl.mock.calls.length;
  unmount();
  stateUpdates.enabled = true;

  await act(async () => {
    pendingCleanup.resolve();
    await automaticCache;
  });

  expect(removeChapter).toHaveBeenCalledTimes(2);
  expect(readStatus).toHaveBeenCalledTimes(statusReadsBeforeUnmount);
  expect(getCachedChapter).toHaveBeenCalledTimes(chapterReadsBeforeUnmount);
  expect(getCachedAudioUrl).toHaveBeenCalledTimes(audioReadsBeforeUnmount);
  expect(stateUpdates.total).toBe(0);
  expect(consoleError).not.toHaveBeenCalled();
});
