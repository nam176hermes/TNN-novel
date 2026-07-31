import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, type ApiClient } from '../api/client';
import type {
  ChapterTask,
  ImportJob,
  ImportJobAcceptedResponse,
  JobEvent,
  URLFetchRequest,
} from '../api/types';
import {
  IMPORT_JOB_STORAGE_KEY,
  importJobReducer,
  initialImportJobState,
  mapImportJobError,
  useImportJob,
} from './useImportJob';

function snapshot(status: ImportJob['status'], overrides: Partial<ImportJob> = {}): ImportJob {
  return {
    job_id: 'job-1',
    status,
    source: '69shuba',
    book_id: null,
    total: 2,
    queued_count: status === 'queued' ? 2 : 0,
    running_count: status === 'running' ? 1 : 0,
    succeeded_count: status === 'succeeded' ? 2 : 0,
    failed_count: 0,
    cancelled_count: 0,
    waiting_retry_count: 0,
    verification_required_count: 0,
    created_at: '2026-07-15T00:00:00Z',
    started_at: '',
    finished_at: '',
    cancel_requested_at: '',
    error_summary: '',
    tasks: [],
    ...overrides,
  };
}

function event(sequence: number): JobEvent {
  return {
    sequence,
    job_id: 'job-1',
    task_id: null,
    type: 'job_transitioned',
    data: { status: 'running' },
    created_at: '2026-07-15T00:00:00Z',
  };
}

function failedTask(errorCode: string): ChapterTask {
  return {
    id: 1,
    chapter_number: 1,
    title: 'Chương 1',
    status: 'failed',
    stage: 'failed',
    attempts: 1,
    next_attempt_at: '',
    error_code: errorCode,
    error_message: 'provider detail must not be shown',
    retryable: false,
    fetch_method: 'direct_http',
    text_length: 0,
    content_hash: '',
    elapsed_ms: 10,
    started_at: '',
    finished_at: '',
    book_id: null,
    chapter_id: null,
  };
}

function request(): URLFetchRequest {
  return {
    source_url: 'https://www.69shuba.com/book/1',
    title: 'Đại Đạo Triều Thiên',
    author: '',
    source: '69shuba',
    chapters: [
      { url: 'https://www.69shuba.com/book/1/1.html', chapter_number: 1, title: 'Chương 1' },
    ],
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((next, fail) => {
    resolve = next;
    reject = fail;
  });
  return { promise, resolve, reject };
}

function pendingStream() {
  const done = new Promise<void>(() => {});
  return { abort: vi.fn(), done };
}

beforeEach(() => {
  window.localStorage.clear();
});

describe('importJobReducer', () => {
  it('moves through idle, creating, queued, running, and terminal states', () => {
    const accepted: ImportJobAcceptedResponse = { job_id: 'job-1', status: 'queued', total: 2 };
    let state = initialImportJobState;

    state = importJobReducer(state, { type: 'creating' });
    expect(state.phase).toBe('creating');

    state = importJobReducer(state, { type: 'accepted', response: accepted });
    expect(state.phase).toBe('queued');

    state = importJobReducer(state, { type: 'snapshot', snapshot: snapshot('running') });
    expect(state.phase).toBe('running');

    state = importJobReducer(state, { type: 'snapshot', snapshot: snapshot('succeeded') });
    expect(state.phase).toBe('terminal');
  });

  it('ignores duplicate and out-of-order events', () => {
    const current = importJobReducer(
      { ...initialImportJobState, phase: 'running', jobId: 'job-1' },
      { type: 'event', event: event(5) },
    );

    expect(importJobReducer(current, { type: 'event', event: event(5) })).toBe(current);
    expect(importJobReducer(current, { type: 'event', event: event(4) })).toBe(current);
    expect(current.cursor).toBe(5);
  });

  it('represents reconnecting and typed error states explicitly', () => {
    const reconnecting = importJobReducer(
      { ...initialImportJobState, phase: 'running', jobId: 'job-1' },
      { type: 'reconnecting', attempt: 2 },
    );
    expect(reconnecting).toMatchObject({ phase: 'reconnecting', reconnectAttempt: 2 });

    const failed = importJobReducer(reconnecting, {
      type: 'failed',
      error: { code: 'source_unavailable', message: 'Nguồn tạm lỗi', retryable: true },
    });
    expect(failed).toMatchObject({
      phase: 'error',
      error: { code: 'source_unavailable', retryable: true },
    });
  });

  it('maps chapter error_code from an authoritative snapshot into domain state', () => {
    const state = importJobReducer(
      { ...initialImportJobState, phase: 'running', jobId: 'job-1' },
      {
        type: 'snapshot',
        snapshot: snapshot('failed', {
          failed_count: 1,
          tasks: [failedTask('user_verification_required')],
        }),
      },
    );

    expect(state.phase).toBe('terminal');
    expect(state.error).toMatchObject({ code: 'user_verification_required', retryable: false });
    expect(state.error?.message.toLowerCase()).toContain('xác minh');
    expect(state.error?.message).not.toContain('provider detail');
  });
});

describe('mapImportJobError', () => {
  it.each([
    ['user_verification_required', 'xác minh'],
    ['private_network_blocked', 'mạng riêng'],
    ['rate_limited', 'quá nhiều yêu cầu'],
    ['chapter_quota_exceeded', 'giới hạn'],
  ])('maps %s to a safe domain message', (code, expectedText) => {
    const mapped = mapImportJobError(new ApiError('unsafe provider detail', 422, code, false));

    expect(mapped.code).toBe(code);
    expect(mapped.message.toLowerCase()).toContain(expectedText);
    expect(mapped.message).not.toContain('unsafe provider detail');
  });
});

describe('useImportJob', () => {
  it('creates a job, reconciles snapshots, and reaches terminal state from an event', async () => {
    const accepted = deferred<ImportJobAcceptedResponse>();
    let onEvent: ((nextEvent: JobEvent) => void) | undefined;
    const client = {
      createImportJob: vi.fn().mockReturnValue(accepted.promise),
      getImportJob: vi.fn()
        .mockResolvedValueOnce(snapshot('running'))
        .mockResolvedValueOnce(snapshot('succeeded')),
      subscribeJobEvents: vi.fn((_jobId, listener) => {
        onEvent = listener;
        return pendingStream();
      }),
    } as unknown as ApiClient;
    const { result, unmount } = renderHook(() => useImportJob(client));

    let creation!: Promise<ImportJobAcceptedResponse | null>;
    act(() => {
      creation = result.current.createJob(request());
    });
    expect(result.current.state.phase).toBe('creating');

    await act(async () => {
      accepted.resolve({ job_id: 'job-1', status: 'queued', total: 2 });
      await creation;
    });

    await waitFor(() => expect(result.current.state.phase).toBe('running'));
    expect(window.localStorage.getItem(IMPORT_JOB_STORAGE_KEY)).toBe('job-1');

    act(() => onEvent?.(event(1)));

    await waitFor(() => expect(result.current.state.phase).toBe('terminal'));
    expect(result.current.state.snapshot?.status).toBe('succeeded');
    expect(result.current.state.cursor).toBe(1);
    unmount();
  });

  it('reconnects with the latest cursor and reconciles a fresh snapshot', async () => {
    window.localStorage.setItem(IMPORT_JOB_STORAGE_KEY, 'job-1');
    let subscription = 0;
    const client = {
      getImportJob: vi.fn().mockResolvedValue(snapshot('running')),
      subscribeJobEvents: vi.fn((_jobId, listener) => {
        subscription += 1;
        if (subscription === 1) {
          listener(event(7));
          return { abort: vi.fn(), done: Promise.reject(new TypeError('stream unavailable')) };
        }
        return pendingStream();
      }),
    } as unknown as ApiClient;
    const { result, unmount } = renderHook(() => useImportJob(client, {
      reconnectBaseMs: 1,
      reconnectMaxMs: 2,
    }));

    await waitFor(() => expect(client.subscribeJobEvents).toHaveBeenCalledTimes(2));

    expect(client.subscribeJobEvents).toHaveBeenLastCalledWith(
      'job-1',
      expect.any(Function),
      expect.objectContaining({ cursor: 7, lastEventId: 7 }),
    );
    expect(result.current.state.cursor).toBe(7);
    expect(result.current.state.snapshot?.status).toBe('running');
    unmount();
  });

  it('falls back to polling when SSE is unavailable', async () => {
    window.localStorage.setItem(IMPORT_JOB_STORAGE_KEY, 'job-1');
    const client = {
      getImportJob: vi.fn()
        .mockResolvedValueOnce(snapshot('running'))
        .mockResolvedValueOnce(snapshot('succeeded')),
      subscribeJobEvents: vi.fn().mockReturnValue({
        abort: vi.fn(),
        done: Promise.reject(new TypeError('SSE unavailable')),
      }),
    } as unknown as ApiClient;
    const { result } = renderHook(() => useImportJob(client, {
      maxSseReconnectAttempts: 1,
      pollIntervalMs: 1,
    }));

    await waitFor(() => expect(result.current.state.phase).toBe('terminal'));
    expect(client.subscribeJobEvents).toHaveBeenCalledTimes(1);
    expect(client.getImportJob).toHaveBeenCalledTimes(2);
  });

  it('calls cancel and retry APIs and reconciles their snapshots', async () => {
    window.localStorage.setItem(IMPORT_JOB_STORAGE_KEY, 'job-1');
    const client = {
      getImportJob: vi.fn().mockResolvedValue(snapshot('running')),
      subscribeJobEvents: vi.fn().mockReturnValue(pendingStream()),
      cancelImportJob: vi.fn().mockResolvedValue(snapshot('cancelled')),
      retryFailedTasks: vi.fn().mockResolvedValue(snapshot('queued')),
    } as unknown as ApiClient;
    const { result, unmount } = renderHook(() => useImportJob(client));
    await waitFor(() => expect(result.current.state.phase).toBe('running'));

    await act(async () => {
      await result.current.cancelJob();
    });
    expect(client.cancelImportJob).toHaveBeenCalledWith('job-1');
    expect(result.current.state.phase).toBe('terminal');

    await act(async () => {
      await result.current.retryFailedTasks();
    });
    expect(client.retryFailedTasks).toHaveBeenCalledWith('job-1');
    await waitFor(() => expect(result.current.state.phase).toBe('running'));
    expect(client.getImportJob).toHaveBeenCalledWith('job-1');
    unmount();
  });

  it('resumes the last job id from localStorage after refresh', async () => {
    window.localStorage.setItem(IMPORT_JOB_STORAGE_KEY, 'job-resume');
    const resumed = snapshot('running', { job_id: 'job-resume' });
    const client = {
      getImportJob: vi.fn().mockResolvedValue(resumed),
      subscribeJobEvents: vi.fn().mockReturnValue(pendingStream()),
    } as unknown as ApiClient;
    const { result, unmount } = renderHook(() => useImportJob(client));

    await waitFor(() => expect(result.current.state.phase).toBe('running'));
    expect(result.current.state.jobId).toBe('job-resume');
    expect(client.getImportJob).toHaveBeenCalledWith('job-resume');
    unmount();
  });
});
