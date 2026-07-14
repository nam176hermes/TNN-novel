import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ApiClient } from '../../api/client';
import type {
  BookAudioPlaylistItem,
  Chapter,
  JobStatus,
  QaReport,
  TtsJobStatus,
} from '../../api/types';

const FAILED_TTS_STATUSES = new Set(['failed', 'error', 'qa_failed']);
const COMPLETE_TTS_STATUSES = new Set(['completed', 'done', 'success']);
const TERMINAL_JOB_STATUSES = new Set(['completed', 'done', 'success', 'failed', 'error', 'canceled', 'cancelled', 'interrupted']);
const CANCELABLE_JOB_STATUSES = new Set([
  'queued', 'pending', 'claimed', 'running', 'retrying', 'generating_tts',
  'loading_source', 'cleaning_text', 'splitting_chunks', 'translating',
  'qa_checking', 'exporting',
]);
const AUDIO_JOB_POLL_INTERVAL_MS = 3_000;
const AUDIO_JOB_REFRESH_TIMEOUT_MS = 10_000;

export type ReaderAudioApiClient = Pick<
  ApiClient,
  | 'cancelJob'
  | 'chapterAudioDownloadUrl'
  | 'chapterAudioUrl'
  | 'downloadAudiobookExport'
  | 'getBookAudioPlaylist'
  | 'getJobStatus'
  | 'getTtsJob'
  | 'retryTtsJob'
  | 'startBookTtsJob'
  | 'startTtsJob'
>;

type CacheAudioResult = { cached: boolean; failed: boolean; sizeBytes: number; url: string };
type ReaderAudioJobKind = 'audio' | 'audiobook';
type ReaderAudioRefreshOutcome =
  | {
    kind: 'results';
    jobResult: PromiseSettledResult<JobStatus>;
    ttsResult: PromiseSettledResult<TtsJobStatus>;
  }
  | { kind: 'cancelled' | 'timeout' };

export type UseReaderAudioOptions = {
  activeBookId: number | null;
  apiClient?: ReaderAudioApiClient;
  cacheAudio(bookId: number, chapterId: number, url: string): Promise<CacheAudioResult>;
  chapters: Chapter[];
  getCachedAudioUrl(bookId: number, chapterId: number, url: string): Promise<string>;
  onDownload(blob: Blob, filename: string): void;
  onError(message: string): void;
  onSelectChapter(chapterId: number): void;
  qaReport: QaReport | null;
  selectedChapter: Chapter | null;
  selectedChapterId: number | null;
  translationText: string;
};

function shortJobId(jobId: string): string {
  return jobId.trim().slice(0, 8);
}

function sanitizeAudioErrorText(value: string): string {
  return value
    .replace(/sk-[A-Za-z0-9_-]{6,}/gi, '[redacted]')
    .replace(/\b[A-Z][A-Z0-9_]*(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*\b/g, '[redacted]')
    .replace(/\/(?:home|Users|mnt|tmp|var|srv|app|root)\/[^\s'",)<]+/gi, '[path]')
    .replace(/[A-Za-z]:\\[^\s'",)<]+/g, '[path]');
}

export function friendlyAudioError(
  message: string,
  fallback = 'TTS thất bại. Kiểm tra cấu hình audio và log server.',
): string {
  const cleaned = sanitizeAudioErrorText(message).toLowerCase();
  if (!cleaned.trim()) return fallback;
  if (cleaned.includes('ffmpeg')) return 'Thiếu ffmpeg hoặc ffmpeg không chạy được. Cài ffmpeg rồi chạy lại audio.';
  if (
    cleaned.includes('checkpoint') || cleaned.includes('ckpt') || cleaned.includes('vocab')
    || cleaned.includes('model') || cleaned.includes('hugging face')
  ) return 'Thiếu model TTS hoặc file cấu hình. Kiểm tra TTS_CKPT_FILE/TTS_VOCAB_FILE trên server.';
  if (cleaned.includes('cuda') || cleaned.includes('gpu') || cleaned.includes('out of memory')) {
    return 'Thiết bị TTS không sẵn sàng. Kiểm tra CUDA/GPU hoặc chuyển TTS_DEVICE=cpu.';
  }
  if (cleaned.includes('already running') || cleaned.includes('job already')) {
    return 'Đã có job audio đang chạy. Đợi job hiện tại xong hoặc mở trang Tác vụ để kiểm tra.';
  }
  if (cleaned.includes('artifact') || cleaned.includes('not found') || cleaned.includes('no audio')) {
    return 'Chưa có file audio để nghe hoặc tải. Hãy tạo audio trước.';
  }
  if (cleaned.includes('provider') || cleaned.includes('unauthorized') || cleaned.includes('forbidden')) {
    return 'Provider TTS không sẵn sàng. Kiểm tra cấu hình provider trên server.';
  }
  if (cleaned.includes('chunk')) return 'Một hoặc nhiều đoạn audio bị lỗi. Có thể chạy lại các chunk lỗi.';
  return fallback;
}

function audioErrorFromUnknown(error: unknown, fallback: string): string {
  if (error instanceof Error) return friendlyAudioError(error.message, fallback);
  if (typeof error === 'string') return friendlyAudioError(error, fallback);
  return fallback;
}

function failedTtsChunkCount(ttsJob: TtsJobStatus | null): number {
  return (ttsJob?.chunks ?? []).filter((chunk) => (
    FAILED_TTS_STATUSES.has(chunk.status.toLowerCase())
    || (chunk.qa_status ? FAILED_TTS_STATUSES.has(chunk.qa_status.toLowerCase()) : false)
  )).length;
}

function completedTtsChunkCount(ttsJob: TtsJobStatus | null): number {
  return (ttsJob?.chunks ?? []).filter((chunk) => COMPLETE_TTS_STATUSES.has(chunk.status.toLowerCase())).length;
}

function audioJobProgressPercent(job: JobStatus | null, ttsJob: TtsJobStatus | null): number | null {
  if (typeof ttsJob?.progress === 'number' && Number.isFinite(ttsJob.progress)) {
    return Math.max(0, Math.min(100, Math.round(ttsJob.progress)));
  }
  if (job && Number.isFinite(job.progress) && Number.isFinite(job.total) && job.total > 0) {
    return Math.max(0, Math.min(100, Math.round((job.progress / job.total) * 100)));
  }
  return null;
}

function audioJobFailureReason(job: JobStatus | null, ttsJob: TtsJobStatus | null): string {
  if (ttsJob?.error_message) return ttsJob.error_message;
  const failedChunk = (ttsJob?.chunks ?? []).find((chunk) => (
    FAILED_TTS_STATUSES.has(chunk.status.toLowerCase()) && Boolean(chunk.error_message)
  ));
  if (failedChunk?.error_message) return failedChunk.error_message;
  if (job?.error) return job.error;
  if (job?.status.toLowerCase() === 'failed') return job.message;
  return '';
}

export function useReaderAudio({
  activeBookId,
  apiClient,
  cacheAudio,
  chapters,
  getCachedAudioUrl,
  onDownload,
  onError,
  onSelectChapter,
  qaReport,
  selectedChapter,
  selectedChapterId,
  translationText,
}: UseReaderAudioOptions) {
  const [open, setOpen] = useState(false);
  const [autoNext, setAutoNext] = useState(false);
  const [jobLoading, setJobLoading] = useState(false);
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');
  const [jobId, setJobId] = useState('');
  const [jobKind, setJobKind] = useState<ReaderAudioJobKind>('audio');
  const [bulkConfirmOpen, setBulkConfirmOpen] = useState(false);
  const [jobSnapshot, setJobSnapshot] = useState<JobStatus | null>(null);
  const [ttsSnapshot, setTtsSnapshot] = useState<TtsJobStatus | null>(null);
  const [jobRefreshing, setJobRefreshing] = useState(false);
  const [playlist, setPlaylist] = useState<BookAudioPlaylistItem[]>([]);
  const [playlistError, setPlaylistError] = useState('');
  const [cachedUrl, setCachedUrl] = useState('');
  const activeJobGenerationRef = useRef(0);
  const activeJobIdRef = useRef('');
  const playlistRequestRef = useRef(0);
  const playlistRefreshJobRef = useRef('');
  const refreshDeadlineRef = useRef(new Map<number, () => void>());
  const refreshEpochRef = useRef(0);
  const refreshInFlightRef = useRef(new Map<number, Promise<void>>());
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      for (const cancelDeadline of refreshDeadlineRef.current.values()) cancelDeadline();
      refreshDeadlineRef.current.clear();
    };
  }, []);

  const translatedChapters = useMemo(
    () => chapters.filter((chapter) => chapter.has_translation).sort((a, b) => a.chapter_number - b.chapter_number),
    [chapters],
  );
  const playlistByChapterId = useMemo(
    () => new Map(playlist.map((item) => [item.chapter_id, item])),
    [playlist],
  );
  const selectedIndex = translatedChapters.findIndex((chapter) => chapter.id === selectedChapterId);
  const nextChapter = selectedIndex >= 0
    ? translatedChapters.slice(selectedIndex + 1)
      .find((chapter) => Boolean(chapter.audio_path) || playlistByChapterId.has(chapter.id)) ?? null
    : null;
  const playlistItem = selectedChapterId ? playlistByChapterId.get(selectedChapterId) ?? null : null;
  const canPlay = Boolean(apiClient && activeBookId && selectedChapterId && (selectedChapter?.audio_path || playlistItem));
  const streamUrl = canPlay && apiClient && activeBookId && selectedChapterId
    ? selectedChapter?.audio_path
      ? apiClient.chapterAudioUrl(activeBookId, selectedChapterId)
      : playlistItem?.stream_url || apiClient.chapterAudioUrl(activeBookId, selectedChapterId)
    : '';
  const downloadUrl = canPlay && apiClient && activeBookId && selectedChapterId
    ? selectedChapter?.audio_path
      ? apiClient.chapterAudioDownloadUrl(activeBookId, selectedChapterId)
      : playlistItem?.download_url || apiClient.chapterAudioDownloadUrl(activeBookId, selectedChapterId)
    : '';

  const loadPlaylist = useCallback(async () => {
    const requestId = playlistRequestRef.current + 1;
    playlistRequestRef.current = requestId;
    if (!apiClient || !activeBookId) {
      setPlaylist([]);
      setPlaylistError('');
      return;
    }
    try {
      const response = await apiClient.getBookAudioPlaylist(activeBookId);
      if (!mountedRef.current || playlistRequestRef.current !== requestId) return;
      setPlaylist(response.chapters);
      setPlaylistError('');
    } catch (loadError) {
      if (!mountedRef.current || playlistRequestRef.current !== requestId) return;
      setPlaylist([]);
      setPlaylistError(audioErrorFromUnknown(loadError, 'Không tải được danh sách audio của truyện.'));
    }
  }, [activeBookId, apiClient]);

  useEffect(() => {
    let cancelled = false;
    void loadPlaylist().catch(() => {
      if (!cancelled) setPlaylistError('Không tải được danh sách audio của truyện.');
    });
    return () => { cancelled = true; };
  }, [loadPlaylist]);

  useEffect(() => {
    if (!canPlay || !activeBookId || !selectedChapterId || !streamUrl) {
      setCachedUrl('');
      return;
    }
    let cancelled = false;
    setCachedUrl('');
    void getCachedAudioUrl(activeBookId, selectedChapterId, streamUrl)
      .then(async (url) => {
        if (cancelled) return;
        if (url) {
          setCachedUrl(url);
          return;
        }
        const result = await cacheAudio(activeBookId, selectedChapterId, streamUrl);
        if (!result.cached || cancelled) return;
        const nextUrl = await getCachedAudioUrl(activeBookId, selectedChapterId, streamUrl);
        if (!cancelled) setCachedUrl(nextUrl);
      })
      .catch(() => { if (!cancelled) setCachedUrl(''); });
    return () => { cancelled = true; };
  }, [activeBookId, cacheAudio, canPlay, getCachedAudioUrl, selectedChapterId, streamUrl]);

  const activateJob = useCallback((nextJobId: string) => {
    activeJobGenerationRef.current += 1;
    activeJobIdRef.current = nextJobId;
    setJobId(nextJobId);
  }, []);

  const refreshJob = useCallback((requestedJobId = activeJobIdRef.current): Promise<void> => {
    if (!apiClient || !requestedJobId || requestedJobId !== activeJobIdRef.current) return Promise.resolve();
    const generation = activeJobGenerationRef.current;
    const existingRefresh = refreshInFlightRef.current.get(generation);
    if (existingRefresh) return existingRefresh;
    const refreshEpoch = refreshEpochRef.current + 1;
    refreshEpochRef.current = refreshEpoch;
    setJobRefreshing(true);
    let deadlineSettled = false;
    let deadlineTimer = 0;
    let resolveDeadline!: (outcome: ReaderAudioRefreshOutcome) => void;
    const deadlinePromise = new Promise<ReaderAudioRefreshOutcome>((resolve) => {
      resolveDeadline = resolve;
    });
    const finishDeadline = (kind: 'cancelled' | 'timeout') => {
      if (deadlineSettled) return;
      deadlineSettled = true;
      window.clearTimeout(deadlineTimer);
      refreshDeadlineRef.current.delete(refreshEpoch);
      resolveDeadline({ kind });
    };
    deadlineTimer = window.setTimeout(() => finishDeadline('timeout'), AUDIO_JOB_REFRESH_TIMEOUT_MS);
    refreshDeadlineRef.current.set(refreshEpoch, () => finishDeadline('cancelled'));
    const requestPromise = Promise.allSettled([
      apiClient.getJobStatus(requestedJobId),
      apiClient.getTtsJob(requestedJobId),
    ]).then(([jobResult, ttsResult]): ReaderAudioRefreshOutcome => ({
      jobResult,
      kind: 'results',
      ttsResult,
    }));
    const refreshPromise = Promise.race([requestPromise, deadlinePromise]).then((outcome) => {
      if (outcome.kind === 'results') finishDeadline('cancelled');
      if (
        !mountedRef.current
        || activeJobGenerationRef.current !== generation
        || activeJobIdRef.current !== requestedJobId
        || refreshEpochRef.current !== refreshEpoch
      ) return;
      if (outcome.kind === 'timeout') {
        setError('Không đọc được trạng thái job audio: yêu cầu đã hết thời gian chờ. Hãy thử làm mới lại.');
        return;
      }
      if (outcome.kind !== 'results') return;
      const { jobResult, ttsResult } = outcome;
      setJobSnapshot(jobResult.status === 'fulfilled' ? jobResult.value : null);
      setTtsSnapshot(ttsResult.status === 'fulfilled' ? ttsResult.value : null);
      if (jobResult.status === 'rejected' && ttsResult.status === 'rejected') {
        setError(audioErrorFromUnknown(jobResult.reason, 'Không đọc được trạng thái job audio. Mở trang Tác vụ để kiểm tra.'));
      } else {
        setError('');
      }
    }).finally(() => {
      if (refreshInFlightRef.current.get(generation) === refreshPromise) {
        refreshInFlightRef.current.delete(generation);
      }
      if (
        mountedRef.current
        && activeJobGenerationRef.current === generation
        && activeJobIdRef.current === requestedJobId
        && refreshEpochRef.current === refreshEpoch
      ) setJobRefreshing(false);
    });
    refreshInFlightRef.current.set(generation, refreshPromise);
    return refreshPromise;
  }, [apiClient]);

  const statusValue = ttsSnapshot?.status || jobSnapshot?.status || (jobId ? 'queued' : '');

  useEffect(() => {
    if (!jobId || TERMINAL_JOB_STATUSES.has(statusValue.toLowerCase())) return undefined;
    const interval = window.setInterval(() => { void refreshJob(jobId); }, AUDIO_JOB_POLL_INTERVAL_MS);
    return () => window.clearInterval(interval);
  }, [jobId, refreshJob, statusValue]);

  useEffect(() => {
    if (!jobId || !COMPLETE_TTS_STATUSES.has(statusValue.toLowerCase())) return;
    if (playlistRefreshJobRef.current === jobId) return;
    playlistRefreshJobRef.current = jobId;
    void loadPlaylist();
  }, [jobId, loadPlaylist, statusValue]);

  const reportError = useCallback((nextError: string) => {
    setError(nextError);
    onError(nextError);
  }, [onError]);

  const startChapterJob = useCallback(async () => {
    if (!apiClient || !activeBookId || !selectedChapterId) {
      setStatus('Không thể tạo audio: thiếu kết nối API hoặc chương đang đọc.');
      return;
    }
    if (!(selectedChapter?.has_translation && translationText.trim())) {
      setStatus('');
      reportError('Chưa có bản dịch tiếng Việt để tạo audio.');
      return;
    }
    setJobLoading(true);
    setError('');
    setJobSnapshot(null);
    setTtsSnapshot(null);
    setStatus('Đang gửi job tạo audio...');
    try {
      const job = await apiClient.startTtsJob(activeBookId, [selectedChapterId]);
      activateJob(job.job_id);
      setJobKind('audio');
      setStatus(`Đã tạo job audio ${shortJobId(job.job_id)}. Mở Jobs để theo dõi.`);
      onError('');
      await refreshJob(job.job_id);
    } catch (startError) {
      setStatus('');
      reportError(audioErrorFromUnknown(startError, 'Không thể tạo audio chương. Kiểm tra cấu hình TTS.'));
    } finally {
      setJobLoading(false);
    }
  }, [activateJob, activeBookId, apiClient, onError, refreshJob, reportError, selectedChapter, selectedChapterId, translationText]);

  const confirmBookJob = useCallback(async () => {
    setBulkConfirmOpen(false);
    if (!apiClient || !activeBookId) {
      setStatus('Không thể tạo audiobook: thiếu kết nối API hoặc truyện đang đọc.');
      return;
    }
    setJobLoading(true);
    setError('');
    setJobSnapshot(null);
    setTtsSnapshot(null);
    setStatus('Đang gửi job tạo audiobook...');
    try {
      const job = await apiClient.startBookTtsJob(activeBookId, { limit: 200 });
      activateJob(job.job_id);
      setJobKind('audiobook');
      setStatus(`Đã tạo job audiobook ${shortJobId(job.job_id)}. Mở Jobs để theo dõi.`);
      onError('');
      await refreshJob(job.job_id);
    } catch (startError) {
      setStatus('');
      reportError(audioErrorFromUnknown(startError, 'Không thể tạo audiobook. Kiểm tra cấu hình TTS.'));
    } finally {
      setJobLoading(false);
    }
  }, [activateJob, activeBookId, apiClient, onError, refreshJob, reportError]);

  const cancelJob = useCallback(async () => {
    if (!apiClient || !jobId) {
      reportError('Không thể hủy: chưa có job audio đang chạy.');
      return;
    }
    setJobLoading(true);
    setError('');
    setStatus('Đang yêu cầu hủy job audio...');
    try {
      await apiClient.cancelJob(jobId);
      setStatus(`Đã yêu cầu hủy job audio ${shortJobId(jobId)}.`);
      onError('');
      await refreshJob(jobId);
    } catch (cancelError) {
      setStatus('');
      reportError(audioErrorFromUnknown(cancelError, 'Không thể hủy job audio. Mở trang Tác vụ để kiểm tra.'));
    } finally {
      setJobLoading(false);
    }
  }, [apiClient, jobId, onError, refreshJob, reportError]);

  const retryChunks = useCallback(async () => {
    if (!apiClient || !jobId) {
      reportError('Không thể retry: chưa có job audio để chạy lại.');
      return;
    }
    setJobLoading(true);
    setError('');
    setStatus('Đang gửi retry TTS...');
    try {
      const job = await apiClient.retryTtsJob(jobId);
      activateJob(job.job_id);
      setJobKind('audio');
      setStatus(`Đã gửi retry TTS ${shortJobId(job.job_id)}. Mở Jobs để theo dõi.`);
      setJobSnapshot(null);
      setTtsSnapshot(null);
      onError('');
      await refreshJob(job.job_id);
    } catch (retryError) {
      setStatus('');
      reportError(audioErrorFromUnknown(retryError, 'Không thể retry chunk lỗi. Mở trang Tác vụ để kiểm tra.'));
    } finally {
      setJobLoading(false);
    }
  }, [activateJob, apiClient, jobId, onError, refreshJob, reportError]);

  const downloadAudiobook = useCallback(async () => {
    if (!apiClient || !activeBookId) {
      setStatus('Không thể tải audiobook: thiếu kết nối API hoặc truyện đang đọc.');
      return;
    }
    setJobLoading(true);
    setStatus('Đang xuất audiobook M4B...');
    try {
      const download = await apiClient.downloadAudiobookExport(activeBookId, 'm4b');
      onDownload(download.blob, download.filename);
      setStatus(`Đã tải ${download.filename}`);
      onError('');
    } catch (downloadError) {
      setStatus('');
      reportError(audioErrorFromUnknown(downloadError, 'Không thể tải audiobook M4B. Hãy tạo audiobook trước.'));
    } finally {
      setJobLoading(false);
    }
  }, [activeBookId, apiClient, onDownload, onError, reportError]);

  const failedChunks = failedTtsChunkCount(ttsSnapshot);
  const completedChunks = completedTtsChunkCount(ttsSnapshot);
  const totalChunks = ttsSnapshot?.chunks.length ?? 0;
  const operationalWarnings = Array.from(new Set(
    (ttsSnapshot?.audio_summary?.warnings ?? []).filter(
      (warning): warning is string => typeof warning === 'string' && warning.trim().length > 0,
    ),
  ));
  const translatedAudioChapterCount = translatedChapters.filter(
    (chapter) => Boolean(chapter.audio_path) || playlistByChapterId.has(chapter.id),
  ).length;
  const generationBlocked = !(selectedChapter?.has_translation && translationText.trim());
  const canStartChapterJob = Boolean(
    apiClient && activeBookId && selectedChapterId && !jobLoading && !generationBlocked,
  );
  const canStartBookJob = Boolean(
    apiClient && activeBookId && translatedChapters.length > 0 && !jobLoading,
  );
  const qaOverallStatus = String(qaReport?.overall_status ?? '').toUpperCase();
  const chineseLeakageCount = Math.max(0, Math.round(qaReport?.chinese_leakage_count ?? 0));
  const readinessWarnings = [
    generationBlocked ? 'Chưa có bản dịch tiếng Việt để tạo audio.' : '',
    qaOverallStatus === 'FAIL' ? 'QA đang FAIL. Nên xem lại trước khi tạo audio.' : '',
    chineseLeakageCount > 0 ? `Còn ${chineseLeakageCount.toLocaleString('vi-VN')} dấu hiệu rò chữ Trung trong bản dịch.` : '',
  ].filter(Boolean);
  const failureMessage = error || friendlyAudioError(audioJobFailureReason(jobSnapshot, ttsSnapshot), '');

  return {
    state: {
      autoNext,
      bulkConfirmOpen,
      canCancelJob: Boolean(apiClient && jobId && CANCELABLE_JOB_STATUSES.has(statusValue.toLowerCase())),
      canPlay,
      canRetryChunks: Boolean(apiClient && jobId && (failedChunks > 0 || statusValue.toLowerCase() === 'failed')),
      canStartBookJob,
      canStartChapterJob,
      completedChunks,
      error,
      failedChunks,
      failureMessage,
      generationBlocked,
      jobId,
      jobKind,
      jobLoading,
      jobRefreshing,
      jobSnapshot,
      missingAudioTranslatedChapterCount: Math.max(0, translatedChapters.length - translatedAudioChapterCount),
      missingTranslationChapterCount: chapters.filter((chapter) => !chapter.has_translation).length,
      open,
      operationalWarnings,
      playlistError,
      progressPercent: audioJobProgressPercent(jobSnapshot, ttsSnapshot),
      readinessWarnings,
      status,
      statusValue,
      totalChunks,
      translatedAudioChapterCount,
      translatedChapterCount: translatedChapters.length,
      ttsSnapshot,
    },
    actions: {
      cancelJob,
      close: () => setOpen(false),
      closeBulkConfirm: () => setBulkConfirmOpen(false),
      confirmBookJob,
      downloadAudiobook,
      open: () => setOpen(true),
      playNextChapter: () => {
        if (!nextChapter) return;
        setOpen(true);
        onSelectChapter(nextChapter.id);
      },
      refreshJob,
      requestBookJob: () => setBulkConfirmOpen(true),
      retryChunks,
      setAutoNext,
      startChapterJob,
    },
    playback: {
      chapterTitle: selectedChapter
        ? `Chương ${selectedChapter.chapter_number} · ${selectedChapter.title}`
        : 'Chưa chọn chương',
      downloadUrl,
      hasNextChapter: Boolean(nextChapter),
      nextChapterId: nextChapter?.id ?? null,
      resumeOnSourceChange: autoNext,
      streamUrl,
      url: cachedUrl || streamUrl,
    },
  };
}
