import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, type ApiClient } from '../api/client';
import type {
  Chapter,
  ImportJob,
  JobEventSubscription,
  JobStartResponse,
  JobStatus,
} from '../api/types';
import { formatError } from './types';

function startedJob(jobId: string, status: string, message: string, total = 1): JobStatus {
  return { job_id: jobId, status, progress: 0, total, message };
}

function isTerminalJobStatus(status: string): boolean {
  return ['completed', 'failed', 'cancelled', 'canceled', 'interrupted', 'stale_interrupted'].includes(status.toLowerCase());
}

type JobDomain = 'legacy' | 'durable-import';

function durableImportJobStatus(job: ImportJob): JobStatus {
  const status = job.status === 'succeeded' || job.status === 'partially_succeeded'
    ? 'completed'
    : job.status;
  const progress = job.succeeded_count + job.failed_count + job.cancelled_count;
  return {
    job_id: job.job_id,
    job_type: 'import_url',
    status,
    progress,
    total: job.total,
    message: job.error_summary || `URL import ${status}`,
    created_at: job.created_at,
    started_at: job.started_at,
    finished_at: job.finished_at || null,
    cancel_requested: Boolean(job.cancel_requested_at),
  };
}

const STREAM_FALLBACK_POLL_INTERVAL_MS = 1000;
const STREAM_FALLBACK_POLL_MAX_INTERVAL_MS = 5000;
const STREAM_FALLBACK_VISIBLE_ERROR_AFTER_FAILURES = 3;

function waitForFallbackPoll(signal: AbortSignal, delayMs = STREAM_FALLBACK_POLL_INTERVAL_MS): Promise<void> {
  if (signal.aborted) return Promise.resolve();

  return new Promise((resolve) => {
    const timeoutId = window.setTimeout(resolve, delayMs);
    signal.addEventListener(
      'abort',
      () => {
        window.clearTimeout(timeoutId);
        resolve();
      },
      { once: true },
    );
  });
}

export function useTranslationJob(
  client: ApiClient,
  enabled: boolean,
  onCompleted?: (job: JobStatus) => void | Promise<void>,
  onAuthError?: () => void,
) {
  const [activeJobId, setActiveJobIdState] = useState('');
  const [activeJob, setActiveJobState] = useState<JobStatus | null>(null);
  const [activeJobDomain, setActiveJobDomainState] = useState<JobDomain>('legacy');
  const [error, setError] = useState('');
  const [handledJobId, setHandledJobId] = useState('');
  const [starting, setStarting] = useState(false);
  const terminalHandledRef = useRef('');
  const activeJobIdRef = useRef('');
  const activeJobRef = useRef<JobStatus | null>(null);
  const activeJobDomainRef = useRef<JobDomain>('legacy');
  const startingRef = useRef(false);
  const startRequestIdRef = useRef(0);

  const setActiveJobId = useCallback((jobId: string) => {
    activeJobIdRef.current = jobId;
    setActiveJobIdState(jobId);
  }, []);

  const setActiveJob = useCallback((job: JobStatus | null) => {
    activeJobRef.current = job;
    setActiveJobState(job);
    setActiveJobId(job?.job_id ?? '');
    if (!job) {
      terminalHandledRef.current = '';
    }
  }, [setActiveJobId]);

  const applyStartedJob = useCallback((response: JobStartResponse, total = 1, domain: JobDomain = 'legacy') => {
    startingRef.current = false;
    setStarting(false);
    setHandledJobId('');
    terminalHandledRef.current = '';
    setError('');
    activeJobDomainRef.current = domain;
    setActiveJobDomainState(domain);
    setActiveJob(startedJob(response.job_id, response.status, response.message, total));
  }, [setActiveJob]);

  const setStartedJob = useCallback((response: JobStartResponse, total = 1) => {
    startRequestIdRef.current += 1;
    applyStartedJob(response, total, 'legacy');
  }, [applyStartedJob]);

  const startJob = useCallback(
    async (start: () => Promise<JobStartResponse | null>, total = 1, domain: JobDomain = 'legacy') => {
      if (!enabled) return null;
      if (startingRef.current || (activeJobRef.current && !isTerminalJobStatus(activeJobRef.current.status))) {
        return null;
      }

      const requestId = startRequestIdRef.current + 1;
      startRequestIdRef.current = requestId;
      startingRef.current = true;
      setStarting(true);
      setError('');

      try {
        const response = await start();
        if (!response) return null;
        if (requestId !== startRequestIdRef.current) return null;

        applyStartedJob(response, total, domain);
        return response;
      } catch (nextError) {
        if (requestId !== startRequestIdRef.current) return null;
        if (nextError instanceof ApiError && nextError.status === 401) {
          onAuthError?.();
        }
        setError(formatError(nextError));
        throw nextError;
      } finally {
        if (requestId === startRequestIdRef.current) {
          startingRef.current = false;
          setStarting(false);
        }
      }
    },
    [applyStartedJob, enabled, onAuthError],
  );

  const startTranslate = useCallback(
    async (chapter: Chapter | null, presetId: string, styleProfileId: string, chunkSize?: number | null) => {
      if (!enabled || !chapter || !presetId) return null;
      return startJob(
        () => client.startTranslateJob(
          chapter.book_id,
          [chapter.id],
          presetId,
          styleProfileId || undefined,
          chunkSize,
        ),
      );
    },
    [client, enabled, startJob],
  );

  const cancelActiveJob = useCallback(async () => {
    const job = activeJobRef.current;
    if (!enabled || !job || isTerminalJobStatus(job.status)) return;

    try {
      if (activeJobDomainRef.current === 'durable-import') {
        setActiveJob(durableImportJobStatus(await client.cancelImportJob(job.job_id)));
        return;
      }
      await client.cancelJob(job.job_id);
      setActiveJob({
        ...job,
        status: 'cancelled',
        message: 'Job cancelled by user',
      });
    } catch (nextError) {
      if (nextError instanceof ApiError && nextError.status === 401) {
        onAuthError?.();
        return;
      }
      setError(formatError(nextError));
      throw nextError;
    }
  }, [client, enabled, onAuthError, setActiveJob]);

  useEffect(() => {
    if (!enabled || !activeJobId) return;

    const controller = new AbortController();
    const streamJobId = activeJobId;

    if (activeJobDomain === 'durable-import') {
      let durableSubscription: JobEventSubscription | null = null;

      async function refreshDurableJob(): Promise<ImportJob | null> {
        try {
          const snapshot = await client.getImportJob(streamJobId);
          if (controller.signal.aborted || activeJobIdRef.current !== streamJobId) return snapshot;
          setError('');
          setActiveJob(durableImportJobStatus(snapshot));
          return snapshot;
        } catch (nextError) {
          if (controller.signal.aborted || activeJobIdRef.current !== streamJobId) return null;
          if (nextError instanceof ApiError && nextError.status === 401) {
            onAuthError?.();
            return null;
          }
          setError(formatError(nextError));
          const current = activeJobRef.current;
          if (current?.job_id === streamJobId) {
            setActiveJob({ ...current, status: 'failed', message: 'Unable to track durable import job' });
          }
          return null;
        }
      }

      async function trackDurableJob(): Promise<void> {
        const first = await refreshDurableJob();
        if (
          !first
          || controller.signal.aborted
          || activeJobIdRef.current !== streamJobId
          || isTerminalJobStatus(durableImportJobStatus(first).status)
        ) return;
        durableSubscription = client.subscribeJobEvents(streamJobId, () => {
          void refreshDurableJob();
        });
        try {
          await durableSubscription.done;
        } catch (nextError) {
          if (!controller.signal.aborted) {
            setError(formatError(nextError));
          }
        }

        let snapshot = controller.signal.aborted ? null : await refreshDurableJob();
        while (
          snapshot
          && !isTerminalJobStatus(durableImportJobStatus(snapshot).status)
          && !controller.signal.aborted
          && activeJobIdRef.current === streamJobId
        ) {
          await waitForFallbackPoll(controller.signal);
          if (controller.signal.aborted || activeJobIdRef.current !== streamJobId) return;
          snapshot = await refreshDurableJob();
        }
      }

      void trackDurableJob();
      return () => {
        controller.abort();
        durableSubscription?.abort();
      };
    }

    async function pollJobStatusAfterStreamDrop(): Promise<void> {
      let consecutiveFailures = 0;
      while (!controller.signal.aborted && activeJobIdRef.current === streamJobId) {
        try {
          const job = await client.getJobStatus(streamJobId);
          if (controller.signal.aborted || activeJobIdRef.current !== streamJobId) return;
          consecutiveFailures = 0;
          setError('');
          setActiveJob(job);
          if (isTerminalJobStatus(job.status)) return;
          await waitForFallbackPoll(controller.signal);
        } catch (pollError) {
          if (controller.signal.aborted || activeJobIdRef.current !== streamJobId) return;
          if (pollError instanceof ApiError && pollError.status === 401) {
            throw pollError;
          }
          consecutiveFailures += 1;
          if (consecutiveFailures >= STREAM_FALLBACK_VISIBLE_ERROR_AFTER_FAILURES) {
            setError(formatError(pollError));
          }
          await waitForFallbackPoll(
            controller.signal,
            Math.min(STREAM_FALLBACK_POLL_MAX_INTERVAL_MS, STREAM_FALLBACK_POLL_INTERVAL_MS * consecutiveFailures),
          );
        }
      }
    }

    client.streamJob(
      streamJobId,
      (job) => {
        if (activeJobIdRef.current !== streamJobId) return;
        setActiveJob(job);
      },
      controller.signal,
    ).catch((nextError) => {
      if (controller.signal.aborted) return;
      if (activeJobIdRef.current !== streamJobId) return;
      if (nextError instanceof ApiError && nextError.status === 401) {
        onAuthError?.();
        return;
      }
      pollJobStatusAfterStreamDrop().catch((pollError) => {
        if (controller.signal.aborted) return;
        if (activeJobIdRef.current !== streamJobId) return;
        if (pollError instanceof ApiError && pollError.status === 401) {
          onAuthError?.();
          return;
        }
        setError(formatError(pollError));
      });
    });

    return () => {
      controller.abort();
    };
  }, [activeJobDomain, activeJobId, client, enabled, onAuthError, setActiveJob]);

  useEffect(() => {
    if (!activeJob || !isTerminalJobStatus(activeJob.status)) return;
    if (terminalHandledRef.current === activeJob.job_id) return;

    terminalHandledRef.current = activeJob.job_id;
    setHandledJobId(activeJob.job_id);
    if (activeJob.status !== 'completed') return;

    void Promise.resolve(onCompleted?.(activeJob)).catch((nextError) => {
      setError(formatError(nextError));
    });
  }, [activeJob, onCompleted]);

  useEffect(() => {
    if (enabled) return;
    setActiveJobId('');
    activeJobDomainRef.current = 'legacy';
    setActiveJobDomainState('legacy');
    activeJobRef.current = null;
    startingRef.current = false;
    setActiveJobState(null);
    setError('');
    setHandledJobId('');
    setStarting(false);
    terminalHandledRef.current = '';
  }, [enabled]);

  const activeJobBusy = Boolean(activeJob && !isTerminalJobStatus(activeJob.status));

  return {
    activeJob,
    activeJobBusy,
    activeJobId,
    error,
    handledJobId,
    setActiveJob,
    setActiveJobId,
    setHandledJobId,
    setStartedJob,
    starting,
    cancelActiveJob,
    startJob,
    startTranslate,
  };
}
