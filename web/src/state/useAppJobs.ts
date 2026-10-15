import { useCallback, useEffect, useRef, useState } from 'react';
import type { Chapter, TtsJobStatus } from '../api/types';
import type { WorkflowView } from '../components/WorkflowShell';
import { isAuthError, type AppWorkflowOptions } from './appWorkflow';
import { defaultTranslationPresetId, translationPresets } from './translationPresets';
import { formatError, type AsyncState } from './types';
import { useJobAttempts } from './useJobAttempts';
import { useJobLogs } from './useJobLogs';
import { useJobsHistory } from './useJobsHistory';
import type { useLibrary } from './useLibrary';
import type { useLibraryCatalog } from './useLibraryCatalog';
import type { useProviders } from './useProviders';
import type { useReaderChapterData } from './useReaderChapterData';
import type { useStyleProfiles } from './useStyleProfiles';
import { useTranslationJob } from './useTranslationJob';

const MAX_JOB_REFRESH_RETRIES = 3;
const JOB_REFRESH_RETRY_DELAY_MS = 100;
const emptyTtsJobStatus: AsyncState<TtsJobStatus | null> = { data: null, error: '', state: 'idle' };

export function useAppJobs({ session, expireSession, setBackendError, setBackendSuccess, handleJobError,
  activeView, setActiveView, library, chapterText, qaState, providersState, styleState,
  translatedBooks, rawBacklogChapters, loadTranslatedBooks, loadRawBacklog, selectedChapter, workbenchChapter }:
  Omit<AppWorkflowOptions, 'setBackendLoading'> & ReturnType<typeof useLibraryCatalog> & {
    activeView: WorkflowView;
    setActiveView(view: WorkflowView): void;
    library: ReturnType<typeof useLibrary>;
    chapterText: ReturnType<typeof useReaderChapterData>['text'];
    qaState: ReturnType<typeof useReaderChapterData>['qa'];
    providersState: ReturnType<typeof useProviders>;
    styleState: ReturnType<typeof useStyleProfiles>;
    selectedChapter: Chapter | null;
    workbenchChapter: Chapter | null;
  }) {
  const [selectedPresetId, setSelectedPresetId] = useState(defaultTranslationPresetId);
  const refreshRetryCounts = useRef<Record<string, number>>({});
  const batchPending = useRef(false);
  const [rawBatchLoading, setRawBatchLoading] = useState(false);

  const refreshAfterCompletedJob = useCallback(
    async (job: { job_id: string; job_type?: string }) => {
      if (job.job_type === 'backup') return;
      const refreshBookId = library.selectedChapter?.book_id ?? library.selectedBookId;

      const attemptRefresh = async () => {
        await library.refreshBooks();

        if (refreshBookId !== null) {
          await library.refreshChapters(refreshBookId);
        }

        await chapterText.load();
        await providersState.refresh();
        if (translatedBooks.state !== 'idle') {
          await loadTranslatedBooks();
        }
        if (rawBacklogChapters.state !== 'idle') {
          await loadRawBacklog();
        }
        try {
          await qaState.refresh();
        } catch (error) {
          if (isAuthError(error)) {
            throw error;
          }
        }
      };

      for (let attempt = 0; attempt <= MAX_JOB_REFRESH_RETRIES; attempt += 1) {
        try {
          await attemptRefresh();
          refreshRetryCounts.current[job.job_id] = 0;
          setBackendError((current) => (current.startsWith('Job refresh failed:') ? '' : current));
          return;
        } catch (error) {
          if (isAuthError(error)) {
            expireSession();
            return;
          }

          refreshRetryCounts.current[job.job_id] = attempt + 1;
          if (attempt === MAX_JOB_REFRESH_RETRIES) {
            setBackendError(`Job refresh failed: ${formatError(error)}`);
            return;
          }

          await new Promise<void>((resolve) => {
            window.setTimeout(resolve, JOB_REFRESH_RETRY_DELAY_MS * (attempt + 1));
          });
        }
      }
    },
    [
      chapterText.load,
      expireSession,
      library.refreshBooks,
      library.refreshChapters,
      library.selectedBookId,
      library.selectedChapter,
      loadTranslatedBooks,
      loadRawBacklog,
      providersState.refresh,
      qaState.refresh,
      rawBacklogChapters.state,
      translatedBooks.state,
    ],
  );
  const jobState = useTranslationJob(
    session.client,
    session.isAuthenticated,
    refreshAfterCompletedJob,
    expireSession,
  );
  const jobAttemptsState = useJobAttempts(
    session.client,
    session.isAuthenticated,
    jobState.activeJob?.job_id ?? '',
    expireSession,
  );
  const jobLogsState = useJobLogs(
    session.client,
    session.isAuthenticated,
    jobState.activeJob?.job_id ?? '',
    expireSession,
  );
  const jobsHistoryState = useJobsHistory(session.client, session.isAuthenticated, expireSession);
  const [ttsJobStatus, setTtsJobStatus] = useState<AsyncState<TtsJobStatus | null>>(emptyTtsJobStatus);
  const [ttsRetrying, setTtsRetrying] = useState(false);
  const activeTtsJobId = jobState.activeJob?.job_type === 'tts' ? jobState.activeJob.job_id : '';

  const loadTtsJobStatus = useCallback(async () => {
    if (!session.isAuthenticated || !activeTtsJobId) {
      setTtsJobStatus(emptyTtsJobStatus);
      return null;
    }
    setTtsJobStatus((current) => ({ data: current.data, error: '', state: 'loading' }));
    try {
      const status = await session.client.getTtsJob(activeTtsJobId);
      setTtsJobStatus({ data: status, error: '', state: 'ready' });
      return status;
    } catch (error) {
      if (isAuthError(error)) {
        expireSession();
      }
      setTtsJobStatus((current) => ({ data: current.data, error: formatError(error), state: 'error' }));
      return null;
    }
  }, [activeTtsJobId, expireSession, session.client, session.isAuthenticated]);

  useEffect(() => {
    if (!session.isAuthenticated || !activeTtsJobId) {
      setTtsJobStatus(emptyTtsJobStatus);
      return;
    }
    void loadTtsJobStatus();
  }, [activeTtsJobId, loadTtsJobStatus, session.isAuthenticated]);

  useEffect(() => {
    if (!session.isAuthenticated || !jobState.handledJobId) return;
    void Promise.all([jobAttemptsState.refresh(), jobsHistoryState.refresh()]).catch((error) => {
      if (isAuthError(error)) {
        expireSession();
      }
    });
  }, [
    expireSession,
    jobAttemptsState.refresh,
    jobsHistoryState.refresh,
    jobState.handledJobId,
    session.isAuthenticated,
  ]);

  useEffect(() => {
    if (
      activeView !== 'workbench'
      || !session.isAuthenticated
      || !workbenchChapter
      || !chapterText.sourceText
      || !providersState.selectedProviderId
    ) {
      void providersState.estimateForSource(0, 0).catch(() => {});
      return;
    }

    void providersState
      .estimateForSource(chapterText.sourceText.length, 1)
      .catch(() => {});
  }, [
    activeView,
    chapterText.sourceText,
    providersState.estimateForSource,
    providersState.selectedProviderId,
    session.isAuthenticated,
    workbenchChapter,
  ]);

  async function handleEstimateSelectedChapter(): Promise<void> {
    if (!selectedChapter || !providersState.selectedProviderId) return;

    setBackendError('');
    try {
      await providersState.estimateForSource(
        chapterText.sourceText.length,
        1,
      );
    } catch (error) {
      handleJobError(error, 'Cost estimate unavailable');
    }
  }

  async function handleTranslateSelectedChapter(): Promise<void> {
    if (!selectedChapter || !selectedPresetId) return;
    const selectedPreset = translationPresets.find((preset) => preset.id === selectedPresetId);

    setBackendError('');
    try {
      await jobState.startTranslate(
        selectedChapter,
        selectedPresetId,
        styleState.selectedStyleProfileId,
        selectedPreset?.chunk_size,
      );
    } catch (error) {
      handleJobError(error, 'Translate job failed');
    }
  }

  async function handleBatchTranslateBook(bookId: number, rawChapterIds?: number[]): Promise<void> {
    if (!selectedPresetId || rawChapterIds?.length === 0 || batchPending.current) return;
    const selectedPreset = translationPresets.find((preset) => preset.id === selectedPresetId);
    batchPending.current = true;
    setRawBatchLoading(true);
    setBackendError('');
    setBackendSuccess('');
    try {
      const chapterIds = rawChapterIds ?? await session.client.getRawChapterIds(bookId);
      const rawChapterCount = chapterIds.length;
      if (rawChapterCount === 0) {
        setBackendSuccess('Không còn chương raw cần dịch.');
        await loadRawBacklog();
        return;
      }
      const response = await jobState.startJob(
        () => session.client.startBookTranslateJob(
          bookId,
          selectedPresetId,
          styleState.selectedStyleProfileId || undefined,
          selectedPreset?.chunk_size,
          { chapterIds, limit: rawChapterCount },
        ),
        rawChapterCount,
      );
      if (response) {
        setBackendSuccess(`Đã bắt đầu dịch hàng loạt: ${response.job_id}`);
        setActiveView('jobs');
      }
    } catch (error) {
      handleJobError(error, 'Batch translate job failed');
    } finally {
      batchPending.current = false;
      setRawBatchLoading(false);
    }
  }

  async function handleCreateAudioBatch(bookId: number, missingAudioCount: number): Promise<void> {
    if (missingAudioCount <= 0) return;

    setBackendError('');
    setBackendSuccess('');
    try {
      const response = await jobState.startJob(
        () => session.client.startBookTtsJob(bookId, { limit: missingAudioCount }),
        missingAudioCount,
      );
      if (response) {
        setBackendSuccess(`Đã bắt đầu tạo audio hàng loạt: ${response.job_id}`);
        setActiveView('jobs');
      }
    } catch (error) {
      handleJobError(error, 'Batch audio job failed');
    }
  }

  async function handleRunQa(): Promise<void> {
    if (!selectedChapter) return;

    setBackendError('');
    try {
      await jobState.startJob(() => qaState.startQa());
    } catch (error) {
      handleJobError(error, 'QA job failed');
    }
  }

  async function handleCancelJob(): Promise<void> {
    setBackendError('');
    try {
      await jobState.cancelActiveJob();
    } catch (error) {
      handleJobError(error, 'Cancel job failed');
    }
  }

  async function handleRetryTtsChunks(jobId: string): Promise<void> {
    setBackendError('');
    setBackendSuccess('');
    setTtsRetrying(true);
    try {
      const response = await session.client.retryTtsJob(jobId);
      setBackendSuccess(response.message || 'Đã bắt đầu retry TTS chunks.');
      await loadTtsJobStatus();
    } catch (error) {
      if (isAuthError(error)) {
        expireSession();
        return;
      }
      setBackendError(`Retry TTS failed: ${formatError(error)}`);
    } finally {
      setTtsRetrying(false);
    }
  }

  return {
    selectedPresetId, setSelectedPresetId, jobState, jobAttemptsState, jobLogsState, jobsHistoryState,
    ttsJobStatus, ttsRetrying, handleEstimateSelectedChapter, handleTranslateSelectedChapter,
    handleBatchTranslateBook, rawBatchLoading, handleCreateAudioBatch, handleRunQa, handleCancelJob, handleRetryTtsChunks,
  };
}
