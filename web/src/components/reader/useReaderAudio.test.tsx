import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Chapter, JobStatus, TtsJobStatus } from '../../api/types';
import { useReaderAudio, type ReaderAudioApiClient } from './useReaderAudio';

const chapters: Chapter[] = [
  { id: 101, book_id: 42, chapter_number: 1, title: 'Sơn biên tiểu thôn', status: 'translated', audio_path: null, has_translation: true },
  { id: 102, book_id: 42, chapter_number: 2, title: 'Thanh Ngưu trấn', status: 'translated', audio_path: '/audio/chapter-102.mp3', has_translation: true },
  { id: 103, book_id: 42, chapter_number: 3, title: 'Thất Huyền Môn', status: 'translated', audio_path: '/audio/chapter-103.mp3', has_translation: true },
  { id: 104, book_id: 42, chapter_number: 4, title: 'Chưa dịch', status: 'cleaned', audio_path: null, has_translation: false },
];

function api(overrides: Partial<ReaderAudioApiClient> = {}): ReaderAudioApiClient {
  return {
    cancelJob: vi.fn().mockResolvedValue(undefined),
    chapterAudioDownloadUrl: vi.fn((bookId, chapterId) => `/api/books/${bookId}/chapters/${chapterId}/audio/download`),
    chapterAudioUrl: vi.fn((bookId, chapterId) => `/api/books/${bookId}/chapters/${chapterId}/audio`),
    downloadAudiobookExport: vi.fn().mockResolvedValue({
      blob: new Blob(['m4b'], { type: 'audio/mp4' }),
      filename: 'pham-nhan.m4b',
      mediaType: 'audio/mp4',
    }),
    getBookAudioPlaylist: vi.fn().mockResolvedValue({ book_id: 42, chapters: [] }),
    getJobStatus: vi.fn().mockResolvedValue({
      job_id: 'tts-job-123456', job_type: 'tts', status: 'running', progress: 1, total: 4, message: 'running',
    }),
    getTtsJob: vi.fn().mockResolvedValue({ job_id: 'tts-job-123456', status: 'running', progress: 25, chunks: [] }),
    retryTtsJob: vi.fn().mockResolvedValue({ job_id: 'tts-retry-123456', status: 'queued', message: 'queued' }),
    startBookTtsJob: vi.fn().mockResolvedValue({ job_id: 'tts-book-123456', status: 'queued', message: 'queued' }),
    startTtsJob: vi.fn().mockResolvedValue({ job_id: 'tts-job-123456', status: 'queued', message: 'queued' }),
    ...overrides,
  };
}

function options(overrides: Record<string, unknown> = {}) {
  return {
    activeBookId: 42,
    apiClient: api(),
    cacheAudio: vi.fn().mockResolvedValue({ cached: true, failed: false, sizeBytes: 10, url: '/live' }),
    cachedAudioLoading: false,
    cachedAudioUrl: 'blob:cached-audio',
    chapters,
    onDownload: vi.fn(),
    onError: vi.fn(),
    onSelectChapter: vi.fn(),
    qaReport: null,
    selectedChapter: chapters[1],
    selectedChapterId: 102,
    translationText: 'Bản dịch tiếng Việt.',
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

describe('useReaderAudio', () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('loads the playlist and consumes the cached audio URL supplied by the offline controller', async () => {
    const cacheAudio = vi.fn().mockResolvedValue({ cached: true, failed: false, sizeBytes: 10, url: '/live' });
    const hookOptions = options({ cacheAudio, cachedAudioUrl: 'blob:offline-controller' });
    const { result } = renderHook(() => useReaderAudio(hookOptions));

    await waitFor(() => expect(result.current.playback.url).toBe('blob:offline-controller'));

    expect(result.current.playback.streamUrl).toBe('/api/books/42/chapters/102/audio');
    expect(result.current.playback.downloadUrl).toBe('/api/books/42/chapters/102/audio/download');
    expect(cacheAudio).not.toHaveBeenCalled();
  });

  it('asks the offline controller to cache live audio when no cached URL is supplied', async () => {
    const cacheAudio = vi.fn().mockResolvedValue({ cached: true, failed: false, sizeBytes: 10, url: '/live' });
    const hookOptions = options({ cacheAudio, cachedAudioUrl: '' });
    const { result } = renderHook(() => useReaderAudio(hookOptions));

    await waitFor(() => expect(cacheAudio).toHaveBeenCalledWith(42, 102, '/api/books/42/chapters/102/audio'));
    expect(result.current.playback.url).toBe('/api/books/42/chapters/102/audio');
  });

  it('waits for the offline controller metadata lookup before caching live audio', async () => {
    const cacheAudio = vi.fn().mockResolvedValue({ cached: true, failed: false, sizeBytes: 10, url: '/live' });
    const hookOptions = options({ cacheAudio, cachedAudioLoading: true, cachedAudioUrl: '' });
    renderHook(() => useReaderAudio(hookOptions));

    await waitFor(() => expect(hookOptions.apiClient.getBookAudioPlaylist).toHaveBeenCalledTimes(1));
    expect(cacheAudio).not.toHaveBeenCalled();
  });

  it('ignores a stale playlist response after the active book changes', async () => {
    let resolveFirst!: (value: Awaited<ReturnType<ReaderAudioApiClient['getBookAudioPlaylist']>>) => void;
    let resolveSecond!: (value: Awaited<ReturnType<ReaderAudioApiClient['getBookAudioPlaylist']>>) => void;
    const firstPlaylist = new Promise<Awaited<ReturnType<ReaderAudioApiClient['getBookAudioPlaylist']>>>((resolve) => {
      resolveFirst = resolve;
    });
    const secondPlaylist = new Promise<Awaited<ReturnType<ReaderAudioApiClient['getBookAudioPlaylist']>>>((resolve) => {
      resolveSecond = resolve;
    });
    const client = api({
      getBookAudioPlaylist: vi.fn()
        .mockReturnValueOnce(firstPlaylist)
        .mockReturnValueOnce(secondPlaylist),
    });
    const selectedChapter = chapters[0];
    const { result, rerender } = renderHook(
      ({ bookId }) => useReaderAudio(options({
        activeBookId: bookId,
        apiClient: client,
        cachedAudioUrl: '',
        selectedChapter,
        selectedChapterId: selectedChapter.id,
      })),
      { initialProps: { bookId: 42 } },
    );

    expect(client.getBookAudioPlaylist).toHaveBeenCalledTimes(1);
    rerender({ bookId: 43 });
    expect(client.getBookAudioPlaylist).toHaveBeenCalledTimes(2);

    await act(async () => {
      resolveSecond({ book_id: 43, chapters: [] });
      resolveFirst({
        book_id: 42,
        chapters: [{
          chapter_id: selectedChapter.id,
          chapter_number: selectedChapter.chapter_number,
          title: selectedChapter.title,
          duration_seconds: 60,
          download_url: '/api/books/42/chapters/101/audio/download',
          filename: 'chapter_0001.mp3',
          order: 0,
          size_bytes: 1024,
          stream_url: '/api/books/42/chapters/101/audio',
        }],
      });
      await Promise.all([secondPlaylist, firstPlaylist]);
      await Promise.resolve();
    });

    expect(result.current.state.canPlay).toBe(false);
  });

  it('submits, refreshes and polls a chapter job, then refreshes the playlist on completion', async () => {
    vi.useFakeTimers();
    const completedJob: JobStatus = {
      job_id: 'tts-job-123456', job_type: 'tts', status: 'completed', progress: 1, total: 1, message: 'done',
    };
    const completedTts: TtsJobStatus = {
      job_id: 'tts-job-123456', status: 'completed', progress: 100, chunks: [],
    };
    const client = api({
      getJobStatus: vi.fn()
        .mockResolvedValueOnce({ ...completedJob, status: 'running' })
        .mockResolvedValue(completedJob),
      getTtsJob: vi.fn()
        .mockResolvedValueOnce({ ...completedTts, status: 'running', progress: 25 })
        .mockResolvedValue(completedTts),
    });
    const hookOptions = options({ apiClient: client });
    const { result } = renderHook(() => useReaderAudio(hookOptions));

    await act(async () => result.current.actions.startChapterJob());
    expect(client.startTtsJob).toHaveBeenCalledWith(42, [102]);
    expect(result.current.state.jobSnapshot?.status).toBe('running');

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3_000);
    });
    await act(async () => Promise.resolve());

    expect(result.current.state.jobSnapshot?.status).toBe('completed');
    expect(client.getBookAudioPlaylist).toHaveBeenCalledTimes(2);
  });

  it('serializes overlapping refreshes for the same audio job', async () => {
    const pendingJob = deferred<JobStatus>();
    const pendingTts = deferred<TtsJobStatus>();
    const runningJob: JobStatus = {
      job_id: 'tts-job-123456', job_type: 'tts', status: 'running', progress: 1, total: 4, message: 'running',
    };
    const runningTts: TtsJobStatus = {
      job_id: 'tts-job-123456', status: 'running', progress: 25, chunks: [],
    };
    const client = api({
      getJobStatus: vi.fn()
        .mockResolvedValueOnce(runningJob)
        .mockReturnValueOnce(pendingJob.promise)
        .mockResolvedValue(runningJob),
      getTtsJob: vi.fn()
        .mockResolvedValueOnce(runningTts)
        .mockReturnValueOnce(pendingTts.promise)
        .mockResolvedValue(runningTts),
    });
    const hookOptions = options({ apiClient: client });
    const { result } = renderHook(() => useReaderAudio(hookOptions));

    await act(async () => result.current.actions.startChapterJob());
    let firstRefresh!: Promise<void>;
    let overlappingRefresh!: Promise<void>;
    act(() => {
      firstRefresh = result.current.actions.refreshJob();
      overlappingRefresh = result.current.actions.refreshJob();
    });

    expect(client.getJobStatus).toHaveBeenCalledTimes(2);
    expect(client.getTtsJob).toHaveBeenCalledTimes(2);

    pendingJob.resolve(runningJob);
    pendingTts.resolve(runningTts);
    await act(async () => Promise.all([firstRefresh, overlappingRefresh]));
  });

  it('times out a stuck refresh, unlocks the next refresh, and ignores late results', async () => {
    vi.useFakeTimers();
    const stuckJob = deferred<JobStatus>();
    const stuckTts = deferred<TtsJobStatus>();
    const runningJob: JobStatus = {
      job_id: 'tts-job-123456', job_type: 'tts', status: 'running', progress: 1, total: 2, message: 'running',
    };
    const runningTts: TtsJobStatus = {
      job_id: 'tts-job-123456', status: 'running', progress: 50, chunks: [],
    };
    const completedJob: JobStatus = {
      ...runningJob, status: 'completed', progress: 2, message: 'done',
    };
    const completedTts: TtsJobStatus = {
      ...runningTts, status: 'completed', progress: 100,
    };
    const client = api({
      getJobStatus: vi.fn()
        .mockResolvedValueOnce(runningJob)
        .mockReturnValueOnce(stuckJob.promise)
        .mockResolvedValueOnce(completedJob),
      getTtsJob: vi.fn()
        .mockResolvedValueOnce(runningTts)
        .mockReturnValueOnce(stuckTts.promise)
        .mockResolvedValueOnce(completedTts),
    });
    const hookOptions = options({ apiClient: client });
    const { result } = renderHook(() => useReaderAudio(hookOptions));

    await act(async () => result.current.actions.startChapterJob());
    let timedOutRefresh!: Promise<void>;
    act(() => { timedOutRefresh = result.current.actions.refreshJob(); });
    expect(result.current.state.jobRefreshing).toBe(true);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
      await timedOutRefresh;
    });
    expect(result.current.state.jobRefreshing).toBe(false);
    expect(result.current.state.error).toMatch(/hết thời gian chờ/i);

    await act(async () => result.current.actions.refreshJob());
    expect(client.getJobStatus).toHaveBeenCalledTimes(3);
    expect(result.current.state.jobSnapshot?.status).toBe('completed');
    expect(result.current.state.ttsSnapshot?.status).toBe('completed');
    expect(result.current.state.error).toBe('');

    stuckJob.resolve({ ...runningJob, status: 'failed', message: 'late failure' });
    stuckTts.resolve({ ...runningTts, status: 'failed', error_message: 'late failure' });
    await act(async () => {
      await Promise.all([stuckJob.promise, stuckTts.promise]);
      await Promise.resolve();
    });

    expect(result.current.state.jobSnapshot?.status).toBe('completed');
    expect(result.current.state.ttsSnapshot?.status).toBe('completed');
    expect(result.current.state.error).toBe('');
  });

  it('ignores a completed refresh from the previous job after a new job starts', async () => {
    const oldJob = deferred<JobStatus>();
    const oldTts = deferred<TtsJobStatus>();
    const newJob: JobStatus = {
      job_id: 'tts-new-123456', job_type: 'tts', status: 'running', progress: 1, total: 2, message: 'new',
    };
    const newTts: TtsJobStatus = {
      job_id: 'tts-new-123456', status: 'running', progress: 50, chunks: [],
    };
    const client = api({
      startTtsJob: vi.fn()
        .mockResolvedValueOnce({ job_id: 'tts-old-123456', status: 'queued', message: 'old' })
        .mockResolvedValueOnce({ job_id: 'tts-new-123456', status: 'queued', message: 'new' }),
      getJobStatus: vi.fn((requestedJobId: string) => (
        requestedJobId === 'tts-old-123456' ? oldJob.promise : Promise.resolve(newJob)
      )),
      getTtsJob: vi.fn((requestedJobId: string) => (
        requestedJobId === 'tts-old-123456' ? oldTts.promise : Promise.resolve(newTts)
      )),
    });
    const hookOptions = options({ apiClient: client });
    const { result } = renderHook(() => useReaderAudio(hookOptions));

    let oldStart!: Promise<void>;
    act(() => { oldStart = result.current.actions.startChapterJob(); });
    await waitFor(() => expect(result.current.state.jobId).toBe('tts-old-123456'));

    await act(async () => result.current.actions.startChapterJob());
    expect(result.current.state.jobId).toBe('tts-new-123456');
    expect(result.current.state.jobSnapshot?.job_id).toBe('tts-new-123456');
    expect(result.current.state.ttsSnapshot?.job_id).toBe('tts-new-123456');

    oldJob.resolve({
      job_id: 'tts-old-123456', job_type: 'tts', status: 'completed', progress: 1, total: 1, message: 'old done',
    });
    oldTts.resolve({ job_id: 'tts-old-123456', status: 'completed', progress: 100, chunks: [] });
    await act(async () => oldStart);

    expect(result.current.state.jobId).toBe('tts-new-123456');
    expect(result.current.state.jobSnapshot?.job_id).toBe('tts-new-123456');
    expect(result.current.state.ttsSnapshot?.job_id).toBe('tts-new-123456');
  });

  it('clears a rejected TTS snapshot so current job completion stops polling and refreshes the playlist', async () => {
    vi.useFakeTimers();
    const runningJob: JobStatus = {
      job_id: 'tts-job-123456', job_type: 'tts', status: 'running', progress: 1, total: 2, message: 'running',
    };
    const completedJob: JobStatus = {
      ...runningJob, status: 'completed', progress: 2, message: 'done',
    };
    const runningTts: TtsJobStatus = {
      job_id: 'tts-job-123456', status: 'running', progress: 50, chunks: [],
    };
    const client = api({
      getJobStatus: vi.fn()
        .mockResolvedValueOnce(runningJob)
        .mockResolvedValueOnce(completedJob)
        .mockResolvedValue(runningJob),
      getTtsJob: vi.fn()
        .mockResolvedValueOnce(runningTts)
        .mockRejectedValueOnce(new Error('TTS detail endpoint unavailable'))
        .mockResolvedValue(runningTts),
    });
    const hookOptions = options({ apiClient: client });
    const { result } = renderHook(() => useReaderAudio(hookOptions));

    await act(async () => result.current.actions.startChapterJob());
    expect(result.current.state.ttsSnapshot?.status).toBe('running');

    await act(async () => result.current.actions.refreshJob());
    expect(result.current.state.jobSnapshot?.status).toBe('completed');
    expect(result.current.state.ttsSnapshot).toBeNull();
    expect(result.current.state.statusValue).toBe('completed');
    await act(async () => Promise.resolve());
    expect(client.getBookAudioPlaylist).toHaveBeenCalledTimes(2);

    await act(async () => { await vi.advanceTimersByTimeAsync(3_000); });
    expect(client.getJobStatus).toHaveBeenCalledTimes(2);
  });

  it('exposes explicit chapter and book start guards for missing runtime prerequisites', () => {
    const valid = options();
    const noApi = renderHook(() => useReaderAudio({ ...valid, apiClient: undefined }));
    const noBook = renderHook(() => useReaderAudio({ ...valid, activeBookId: null }));
    const noChapter = renderHook(() => useReaderAudio({
      ...valid,
      selectedChapter: null,
      selectedChapterId: null,
    }));
    const ready = renderHook(() => useReaderAudio(valid));

    expect(noApi.result.current.state.canStartChapterJob).toBe(false);
    expect(noApi.result.current.state.canStartBookJob).toBe(false);
    expect(noBook.result.current.state.canStartChapterJob).toBe(false);
    expect(noBook.result.current.state.canStartBookJob).toBe(false);
    expect(noChapter.result.current.state.canStartChapterJob).toBe(false);
    expect(ready.result.current.state.canStartChapterJob).toBe(true);
    expect(ready.result.current.state.canStartBookJob).toBe(true);
  });

  it('sanitizes job errors and never exposes secrets or absolute paths', async () => {
    const client = api({
      startTtsJob: vi.fn().mockRejectedValue(new Error(
        'ffmpeg failed with sk-live-secret GEMINI_API_KEY at /home/operator/private/file',
      )),
    });
    const onError = vi.fn();
    const hookOptions = options({ apiClient: client, onError });
    const { result } = renderHook(() => useReaderAudio(hookOptions));

    await act(async () => result.current.actions.startChapterJob());

    expect(result.current.state.error).toMatch(/Thiếu ffmpeg/);
    expect(result.current.state.error).not.toMatch(/sk-live-secret|GEMINI_API_KEY|\/home\/operator/);
    expect(onError).toHaveBeenCalledWith(result.current.state.error);
  });

  it('cancels and retries the current job through the existing APIs', async () => {
    const client = api();
    const hookOptions = options({ apiClient: client });
    const { result } = renderHook(() => useReaderAudio(hookOptions));

    await act(async () => result.current.actions.startChapterJob());
    await act(async () => result.current.actions.cancelJob());
    expect(client.cancelJob).toHaveBeenCalledWith('tts-job-123456');

    await act(async () => result.current.actions.retryChunks());
    expect(client.retryTtsJob).toHaveBeenCalledWith('tts-job-123456');
    expect(result.current.state.jobId).toBe('tts-retry-123456');
  });

  it('keeps bulk creation behind confirmation and exports M4B through an injected download', async () => {
    const client = api();
    const onDownload = vi.fn();
    const hookOptions = options({ apiClient: client, onDownload });
    const { result } = renderHook(() => useReaderAudio(hookOptions));

    act(() => result.current.actions.requestBookJob());
    expect(result.current.state.bulkConfirmOpen).toBe(true);
    expect(client.startBookTtsJob).not.toHaveBeenCalled();

    await act(async () => result.current.actions.confirmBookJob());
    expect(client.startBookTtsJob).toHaveBeenCalledWith(42, { limit: 200 });
    expect(result.current.state.bulkConfirmOpen).toBe(false);

    await act(async () => result.current.actions.downloadAudiobook());
    expect(onDownload).toHaveBeenCalledWith(expect.any(Blob), 'pham-nhan.m4b');
  });

  it('selects the next chapter with audio for auto-next playback', async () => {
    const onSelectChapter = vi.fn();
    const hookOptions = options({ onSelectChapter });
    const { result } = renderHook(() => useReaderAudio(hookOptions));

    await waitFor(() => expect(result.current.playback.nextChapterId).toBe(103));
    act(() => result.current.actions.setAutoNext(true));
    act(() => result.current.actions.playNextChapter());

    expect(onSelectChapter).toHaveBeenCalledWith(103);
    expect(result.current.state.open).toBe(true);
  });

  it('clears its polling timer on unmount', async () => {
    vi.useFakeTimers();
    const clearIntervalSpy = vi.spyOn(window, 'clearInterval');
    const hookOptions = options();
    const { result, unmount } = renderHook(() => useReaderAudio(hookOptions));

    await act(async () => result.current.actions.startChapterJob());
    unmount();

    expect(clearIntervalSpy).toHaveBeenCalled();
  });
});
