import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { ApiClient } from '../api/client';
import type { ImportJob, JobStartResponse, JobStatus } from '../api/types';
import { fixtureChapter } from '../test/fixtures';
import { useTranslationJob } from './useTranslationJob';

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((next, fail) => {
    resolve = next;
    reject = fail;
  });

  return { promise, resolve, reject };
}

function jobStart(jobId: string): JobStartResponse {
  return { job_id: jobId, status: 'queued', message: `${jobId} queued` };
}

function jobStatus(jobId: string, status = 'running'): JobStatus {
  return { job_id: jobId, status, progress: 1, total: 2, message: `${jobId} ${status}` };
}

function importJobStatus(status: ImportJob['status'], overrides: Partial<ImportJob> = {}): ImportJob {
  return {
    job_id: 'durable-url-1',
    status,
    source: '69shuba',
    book_id: null,
    total: 1,
    queued_count: status === 'queued' ? 1 : 0,
    running_count: status === 'running' ? 1 : 0,
    succeeded_count: status === 'succeeded' ? 1 : 0,
    failed_count: status === 'failed' ? 1 : 0,
    cancelled_count: status === 'cancelled' ? 1 : 0,
    waiting_retry_count: 0,
    verification_required_count: 0,
    created_at: '2026-08-12T00:00:00Z',
    started_at: '',
    finished_at: '',
    cancel_requested_at: '',
    error_summary: '',
    tasks: [],
    ...overrides,
  };
}

describe('useTranslationJob', () => {
  it('blocks duplicate job starts while a start request is in flight', async () => {
    const slowStart = deferred<JobStartResponse>();
    const client = {
      startTranslateJob: vi.fn().mockReturnValueOnce(slowStart.promise),
      streamJob: vi.fn().mockResolvedValue(undefined),
    } as unknown as ApiClient;
    const { result } = renderHook(() => useTranslationJob(client, true));

    let firstStart!: Promise<JobStartResponse | null>;
    let secondStart!: Promise<JobStartResponse | null>;
    act(() => {
      firstStart = result.current.startTranslate(fixtureChapter, 'gemini', 'tien_hiep');
      secondStart = result.current.startTranslate(fixtureChapter, 'deepseek', 'tien_hiep');
    });

    await act(async () => {
      await expect(secondStart).resolves.toBeNull();
    });

    expect(client.startTranslateJob).toHaveBeenCalledTimes(1);
    expect(result.current.starting).toBe(true);

    await act(async () => {
      slowStart.resolve(jobStart('job-new'));
      await expect(firstStart).resolves.toMatchObject({ job_id: 'job-new' });
    });

    expect(result.current.activeJobId).toBe('job-new');
    expect(result.current.activeJob?.job_id).toBe('job-new');
    expect(result.current.starting).toBe(false);
  });

  it('ignores stale stream events after a newer active job starts', async () => {
    const streamCalls: Array<{
      jobId: string;
      onEvent: (job: JobStatus) => void;
      signal: AbortSignal;
    }> = [];
    const client = {
      streamJob: vi.fn((jobId: string, onEvent: (job: JobStatus) => void, signal: AbortSignal) => {
        streamCalls.push({ jobId, onEvent, signal });
        return new Promise<void>(() => {});
      }),
    } as unknown as ApiClient;
    const { result } = renderHook(() => useTranslationJob(client, true));

    act(() => {
      result.current.setStartedJob(jobStart('job-old'));
    });
    await waitFor(() => expect(streamCalls).toHaveLength(1));

    act(() => {
      result.current.setStartedJob(jobStart('job-new'));
    });
    await waitFor(() => expect(streamCalls).toHaveLength(2));

    act(() => {
      streamCalls[0].onEvent(jobStatus('job-old'));
    });

    expect(result.current.activeJobId).toBe('job-new');
    expect(result.current.activeJob?.job_id).toBe('job-new');

    act(() => {
      streamCalls[1].onEvent(jobStatus('job-new'));
    });

    expect(result.current.activeJobId).toBe('job-new');
    expect(result.current.activeJob?.message).toBe('job-new running');
    expect(streamCalls[0].signal.aborted).toBe(true);
  });

  it('marks failed terminal jobs as handled without running completed-job refresh', async () => {
    const onCompleted = vi.fn();
    const streamCalls: Array<{
      jobId: string;
      onEvent: (job: JobStatus) => void;
      signal: AbortSignal;
    }> = [];
    const client = {
      streamJob: vi.fn((jobId: string, onEvent: (job: JobStatus) => void, signal: AbortSignal) => {
        streamCalls.push({ jobId, onEvent, signal });
        return Promise.resolve();
      }),
    } as unknown as ApiClient;
    const { result } = renderHook(() => useTranslationJob(client, true, onCompleted));

    act(() => {
      result.current.setStartedJob(jobStart('job-failed'));
    });
    await waitFor(() => expect(streamCalls).toHaveLength(1));

    act(() => {
      streamCalls[0].onEvent(jobStatus('job-failed', 'failed'));
    });

    await waitFor(() => expect(result.current.handledJobId).toBe('job-failed'));
    expect(result.current.activeJobBusy).toBe(false);
    expect(onCompleted).not.toHaveBeenCalled();
  });

  it('polls job status when the event stream drops before a terminal status', async () => {
    vi.useFakeTimers();
    try {
      const onCompleted = vi.fn();
      const client = {
        streamJob: vi.fn().mockRejectedValue(new TypeError('Failed to fetch')),
        getJobStatus: vi.fn()
          .mockResolvedValueOnce(jobStatus('job-long', 'running'))
          .mockResolvedValueOnce(jobStatus('job-long', 'completed')),
      } as unknown as ApiClient;
      const { result } = renderHook(() => useTranslationJob(client, true, onCompleted));

      act(() => {
        result.current.setStartedJob(jobStart('job-long'));
      });
      await act(async () => {
        await Promise.resolve();
      });

      expect(client.getJobStatus).toHaveBeenCalledTimes(1);
      expect(result.current.error).toBe('');

      await act(async () => {
        await vi.advanceTimersByTimeAsync(1000);
      });

      expect(result.current.activeJob?.status).toBe('completed');
      expect(result.current.error).toBe('');
      expect(onCompleted).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it('keeps fallback polling through transient network errors', async () => {
    vi.useFakeTimers();
    try {
      const onCompleted = vi.fn();
      const client = {
        streamJob: vi.fn().mockRejectedValue(new TypeError('Failed to fetch')),
        getJobStatus: vi.fn()
          .mockRejectedValueOnce(new TypeError('Failed to fetch'))
          .mockResolvedValueOnce(jobStatus('job-flaky', 'running'))
          .mockResolvedValueOnce(jobStatus('job-flaky', 'completed')),
      } as unknown as ApiClient;
      const { result } = renderHook(() => useTranslationJob(client, true, onCompleted));

      act(() => {
        result.current.setStartedJob(jobStart('job-flaky'));
      });
      await act(async () => {
        await Promise.resolve();
      });

      expect(client.getJobStatus).toHaveBeenCalledTimes(1);
      expect(result.current.error).toBe('');

      await act(async () => {
        await vi.advanceTimersByTimeAsync(1000);
      });

      expect(result.current.activeJob?.status).toBe('running');
      expect(result.current.error).toBe('');

      await act(async () => {
        await vi.advanceTimersByTimeAsync(1000);
      });

      expect(result.current.activeJob?.status).toBe('completed');
      expect(result.current.error).toBe('');
      expect(onCompleted).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it('cancels the active job through the API client', async () => {
    const client = {
      cancelJob: vi.fn().mockResolvedValue(undefined),
      streamJob: vi.fn().mockResolvedValue(undefined),
    } as unknown as ApiClient;
    const { result } = renderHook(() => useTranslationJob(client, true));

    act(() => {
      result.current.setStartedJob(jobStart('job-cancel'));
    });

    await act(async () => {
      await result.current.cancelActiveJob();
    });

    expect(client.cancelJob).toHaveBeenCalledWith('job-cancel');
    expect(result.current.activeJob?.status).toBe('cancelled');
    expect(result.current.activeJobBusy).toBe(false);
  });

  it('tracks a durable URL import to success without calling legacy job endpoints', async () => {
    const client = {
      getImportJob: vi.fn().mockResolvedValue(importJobStatus('succeeded')),
      streamJob: vi.fn().mockRejectedValue(new Error('legacy endpoint must not run')),
      getJobStatus: vi.fn().mockRejectedValue(new Error('legacy endpoint must not run')),
    } as unknown as ApiClient;
    const { result } = renderHook(() => useTranslationJob(client, true));

    await act(async () => {
      await result.current.startJob(
        async () => ({ job_id: 'durable-url-1', status: 'pending', message: 'URL import queued' }),
        1,
        'durable-import',
      );
    });

    await waitFor(() => expect(result.current.activeJob?.status).toBe('completed'));
    expect(result.current.activeJobBusy).toBe(false);
    expect(client.getImportJob).toHaveBeenCalledWith('durable-url-1');
    expect(client.streamJob).not.toHaveBeenCalled();
    expect(client.getJobStatus).not.toHaveBeenCalled();
  });

  it('maps a terminal durable URL import failure without leaving the UI busy', async () => {
    const client = {
      getImportJob: vi.fn().mockResolvedValue(importJobStatus('failed', {
        error_summary: 'Source unavailable',
      })),
      streamJob: vi.fn().mockRejectedValue(new Error('legacy endpoint must not run')),
      getJobStatus: vi.fn().mockRejectedValue(new Error('legacy endpoint must not run')),
    } as unknown as ApiClient;
    const { result } = renderHook(() => useTranslationJob(client, true));

    await act(async () => {
      await result.current.startJob(
        async () => ({ job_id: 'durable-url-1', status: 'pending', message: 'URL import queued' }),
        1,
        'durable-import',
      );
    });

    await waitFor(() => expect(result.current.activeJob?.status).toBe('failed'));
    expect(result.current.activeJobBusy).toBe(false);
    expect(client.streamJob).not.toHaveBeenCalled();
    expect(client.getJobStatus).not.toHaveBeenCalled();
  });

  it('cancels a durable URL import through /api/import/jobs and applies its snapshot', async () => {
    const client = {
      getImportJob: vi.fn().mockResolvedValue(importJobStatus('running')),
      cancelImportJob: vi.fn().mockResolvedValue(importJobStatus('cancelled')),
      cancelJob: vi.fn().mockRejectedValue(new Error('legacy cancel must not run')),
      subscribeJobEvents: vi.fn().mockReturnValue({
        abort: vi.fn(),
        done: new Promise<void>(() => {}),
      }),
    } as unknown as ApiClient;
    const { result } = renderHook(() => useTranslationJob(client, true));

    await act(async () => {
      await result.current.startJob(
        async () => ({ job_id: 'durable-url-1', status: 'pending', message: 'URL import queued' }),
        1,
        'durable-import',
      );
    });
    await waitFor(() => expect(result.current.activeJob?.status).toBe('running'));

    await act(async () => {
      await result.current.cancelActiveJob();
    });

    expect(client.cancelImportJob).toHaveBeenCalledWith('durable-url-1');
    expect(client.cancelJob).not.toHaveBeenCalled();
    expect(result.current.activeJob?.status).toBe('cancelled');
    expect(result.current.activeJobBusy).toBe(false);
  });

  it('terminalizes an unrecoverable durable status lookup instead of staying pending', async () => {
    const client = {
      getImportJob: vi.fn().mockRejectedValue(new Error('durable job not found')),
      streamJob: vi.fn().mockRejectedValue(new Error('legacy endpoint must not run')),
      getJobStatus: vi.fn().mockRejectedValue(new Error('legacy endpoint must not run')),
    } as unknown as ApiClient;
    const { result } = renderHook(() => useTranslationJob(client, true));

    await act(async () => {
      await result.current.startJob(
        async () => ({ job_id: 'durable-url-1', status: 'pending', message: 'URL import queued' }),
        1,
        'durable-import',
      );
    });

    await waitFor(() => expect(result.current.activeJob?.status).toBe('failed'));
    expect(result.current.activeJobBusy).toBe(false);
    expect(result.current.error).toContain('durable job not found');
    expect(client.streamJob).not.toHaveBeenCalled();
    expect(client.getJobStatus).not.toHaveBeenCalled();
  });

  it('falls back to durable snapshot polling when the import event stream ends early', async () => {
    vi.useFakeTimers();
    try {
      const client = {
        getImportJob: vi.fn()
          .mockResolvedValueOnce(importJobStatus('running'))
          .mockResolvedValueOnce(importJobStatus('running'))
          .mockResolvedValueOnce(importJobStatus('succeeded')),
        subscribeJobEvents: vi.fn().mockReturnValue({
          abort: vi.fn(),
          done: Promise.resolve(),
        }),
        streamJob: vi.fn().mockRejectedValue(new Error('legacy endpoint must not run')),
        getJobStatus: vi.fn().mockRejectedValue(new Error('legacy endpoint must not run')),
      } as unknown as ApiClient;
      const { result } = renderHook(() => useTranslationJob(client, true));

      await act(async () => {
        await result.current.startJob(
          async () => ({ job_id: 'durable-url-1', status: 'pending', message: 'URL import queued' }),
          1,
          'durable-import',
        );
      });
      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
      });

      expect(client.getImportJob).toHaveBeenCalledTimes(2);
      expect(result.current.activeJob?.status).toBe('running');

      await act(async () => {
        await vi.advanceTimersByTimeAsync(1000);
      });

      expect(client.getImportJob).toHaveBeenCalledTimes(3);
      expect(result.current.activeJob?.status).toBe('completed');
      expect(result.current.activeJobBusy).toBe(false);
      expect(client.streamJob).not.toHaveBeenCalled();
      expect(client.getJobStatus).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it('aborts a durable import event subscription when tracking is cleaned up', async () => {
    const abort = vi.fn();
    const client = {
      getImportJob: vi.fn().mockResolvedValue(importJobStatus('running')),
      subscribeJobEvents: vi.fn().mockReturnValue({
        abort,
        done: new Promise<void>(() => {}),
      }),
    } as unknown as ApiClient;
    const { result, unmount } = renderHook(() => useTranslationJob(client, true));

    await act(async () => {
      await result.current.startJob(
        async () => ({ job_id: 'durable-url-1', status: 'pending', message: 'URL import queued' }),
        1,
        'durable-import',
      );
    });
    await waitFor(() => expect(client.subscribeJobEvents).toHaveBeenCalledWith('durable-url-1', expect.any(Function)));

    unmount();

    expect(abort).toHaveBeenCalledTimes(1);
  });
});
