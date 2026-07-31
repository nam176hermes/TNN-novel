import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, type ApiClient } from '../api/client';
import type {
  ImportJob,
  ImportJobAcceptedResponse,
  ImportJobCreateRequest,
  ImportJobStatus,
  JobEvent,
  JobEventSubscription,
} from '../api/types';

export const IMPORT_JOB_STORAGE_KEY = 'novel-import-job-id-v1';

const TERMINAL_STATUSES = new Set<ImportJobStatus>([
  'succeeded',
  'partially_succeeded',
  'failed',
  'cancelled',
]);

const ERROR_MESSAGES: Record<string, string> = {
  invalid_url: 'URL nguồn không hợp lệ. Hãy kiểm tra lại địa chỉ chương.',
  source_not_allowed: 'Nguồn này chưa được phép nhập tự động.',
  private_network_blocked: 'URL trỏ tới mạng riêng hoặc địa chỉ bị chặn.',
  connect_timeout: 'Không thể kết nối nguồn đúng thời hạn. Hãy thử lại.',
  read_timeout: 'Nguồn phản hồi quá chậm. Hãy thử lại sau.',
  rate_limited: 'Nguồn nhận quá nhiều yêu cầu. Job sẽ có thể thử lại sau.',
  source_unavailable: 'Nguồn truyện đang tạm thời không khả dụng.',
  user_verification_required: 'Nguồn yêu cầu xác minh người dùng trước khi tiếp tục.',
  content_not_found: 'Không tìm thấy nội dung chương tại nguồn.',
  content_invalid: 'Nội dung chương không hợp lệ hoặc đang trống.',
  parse_failed: 'Không thể phân tích nội dung chương từ nguồn.',
  duplicate: 'Chương này đã tồn tại hoặc bị chọn trùng.',
  import_failed: 'Không thể lưu chương vào thư viện.',
  cancelled: 'Job nhập truyện đã bị hủy.',
  internal_error: 'Import gặp lỗi nội bộ. Hãy thử lại hoặc kiểm tra trạng thái hệ thống.',
  job_not_found: 'Không tìm thấy job nhập truyện hoặc bạn không có quyền truy cập.',
  invalid_job_state: 'Trạng thái hiện tại của job không cho phép thao tác này.',
  invalid_request: 'Yêu cầu nhập truyện chưa đầy đủ hoặc không hợp lệ.',
  chapter_quota_exceeded: 'Số chương đã vượt giới hạn cho phép của một job.',
  invalid_cursor: 'Vị trí tiếp tục theo dõi job không hợp lệ.',
};

export type ImportJobPhase =
  | 'idle'
  | 'creating'
  | 'queued'
  | 'running'
  | 'terminal'
  | 'reconnecting'
  | 'error';

export type ImportJobDomainError = {
  code: string;
  message: string;
  retryable: boolean;
};

export type ImportJobState = {
  phase: ImportJobPhase;
  jobId: string;
  snapshot: ImportJob | null;
  cursor: number;
  error: ImportJobDomainError | null;
  reconnectAttempt: number;
};

export type ImportJobAction =
  | { type: 'reset' }
  | { type: 'creating' }
  | { type: 'accepted'; response: ImportJobAcceptedResponse }
  | { type: 'snapshot'; snapshot: ImportJob }
  | { type: 'event'; event: JobEvent }
  | { type: 'reconnecting'; attempt: number }
  | { type: 'failed'; error: ImportJobDomainError };

export const initialImportJobState: ImportJobState = {
  phase: 'idle',
  jobId: '',
  snapshot: null,
  cursor: 0,
  error: null,
  reconnectAttempt: 0,
};

type StorageLike = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

export type UseImportJobOptions = {
  enabled?: boolean;
  storage?: StorageLike | null;
  storageKey?: string;
  reconnectBaseMs?: number;
  reconnectMaxMs?: number;
  maxSseReconnectAttempts?: number;
  pollIntervalMs?: number;
  maxPollingFailures?: number;
  onAuthError?: () => void;
};

function phaseFromStatus(status: ImportJobStatus): ImportJobPhase {
  if (TERMINAL_STATUSES.has(status)) return 'terminal';
  return status === 'running' ? 'running' : 'queued';
}

export function importJobReducer(state: ImportJobState, action: ImportJobAction): ImportJobState {
  if (action.type === 'reset') return initialImportJobState;
  if (action.type === 'creating') {
    return { ...initialImportJobState, phase: 'creating' };
  }
  if (action.type === 'accepted') {
    return {
      ...initialImportJobState,
      phase: phaseFromStatus(action.response.status),
      jobId: action.response.job_id,
    };
  }
  if (action.type === 'snapshot') {
    const taskFailure = action.snapshot.tasks.find((task) => Boolean(task.error_code));
    return {
      ...state,
      phase: phaseFromStatus(action.snapshot.status),
      jobId: action.snapshot.job_id,
      snapshot: action.snapshot,
      error: taskFailure
        ? mapImportJobErrorCode(taskFailure.error_code, taskFailure.retryable)
        : null,
      reconnectAttempt: 0,
    };
  }
  if (action.type === 'event') {
    if (state.jobId && action.event.job_id !== state.jobId) return state;
    if (action.event.sequence <= state.cursor) return state;
    return { ...state, cursor: action.event.sequence };
  }
  if (action.type === 'reconnecting') {
    if (state.phase === 'terminal') return state;
    return {
      ...state,
      phase: 'reconnecting',
      reconnectAttempt: action.attempt,
    };
  }
  return {
    ...state,
    phase: 'error',
    error: action.error,
  };
}

export function mapImportJobErrorCode(
  code: string,
  retryable = false,
): ImportJobDomainError | null {
  if (!code) return null;
  return {
    code,
    message: ERROR_MESSAGES[code] ?? 'Không thể xử lý chương này. Hãy kiểm tra trạng thái job.',
    retryable,
  };
}

export function mapImportJobError(error: unknown): ImportJobDomainError {
  const code = error instanceof ApiError ? error.code : '';
  const networkFailure = error instanceof TypeError
    || (error instanceof Error && /failed to fetch|networkerror|load failed/i.test(error.message));
  const typed = mapImportJobErrorCode(code, error instanceof ApiError && error.retryable);
  if (typed) return typed;
  return {
    code: networkFailure ? 'network_error' : 'unknown_error',
    message: networkFailure
      ? 'Không kết nối được API. Kiểm tra server, Cloudflare Tunnel hoặc mạng.'
      : 'Không thể cập nhật job nhập truyện. Hãy thử lại.',
    retryable: networkFailure,
  };
}

function defaultStorage(): StorageLike | null {
  if (typeof window === 'undefined') return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function readStoredJobId(storage: StorageLike | null, key: string): string {
  try {
    return storage?.getItem(key)?.trim() ?? '';
  } catch {
    return '';
  }
}

function writeStoredJobId(storage: StorageLike | null, key: string, jobId: string): void {
  try {
    if (jobId) storage?.setItem(key, jobId);
    else storage?.removeItem(key);
  } catch {
    // Storage can be unavailable in private browsing; the active session still works.
  }
}

function waitForDelay(signal: AbortSignal, delayMs: number): Promise<void> {
  if (signal.aborted || delayMs <= 0) return Promise.resolve();
  return new Promise((resolve) => {
    const timeoutId = window.setTimeout(resolve, delayMs);
    signal.addEventListener('abort', () => {
      window.clearTimeout(timeoutId);
      resolve();
    }, { once: true });
  });
}

export function useImportJob(client: ApiClient, options: UseImportJobOptions = {}) {
  const {
    enabled = true,
    storage = defaultStorage(),
    storageKey = IMPORT_JOB_STORAGE_KEY,
    reconnectBaseMs = 500,
    reconnectMaxMs = 8_000,
    maxSseReconnectAttempts = 3,
    pollIntervalMs = 2_000,
    maxPollingFailures = 3,
    onAuthError,
  } = options;
  const initialStateRef = useRef<ImportJobState | null>(null);
  if (initialStateRef.current === null) {
    const storedJobId = readStoredJobId(storage, storageKey);
    initialStateRef.current = storedJobId
      ? { ...initialImportJobState, phase: 'reconnecting', jobId: storedJobId }
      : initialImportJobState;
  }
  const [state, setState] = useState<ImportJobState>(initialStateRef.current);
  const stateRef = useRef(state);
  const streamRef = useRef<JobEventSubscription | null>(null);
  const snapshotRequestRef = useRef(0);
  const [connectionEpoch, setConnectionEpoch] = useState(0);

  const transition = useCallback((action: ImportJobAction): ImportJobState => {
    const next = importJobReducer(stateRef.current, action);
    if (next === stateRef.current) return next;
    stateRef.current = next;
    setState(next);
    return next;
  }, []);

  const persistForSnapshot = useCallback((nextSnapshot: ImportJob) => {
    writeStoredJobId(
      storage,
      storageKey,
      TERMINAL_STATUSES.has(nextSnapshot.status) ? '' : nextSnapshot.job_id,
    );
  }, [storage, storageKey]);

  const applySnapshot = useCallback((nextSnapshot: ImportJob): ImportJob => {
    if (stateRef.current.jobId && stateRef.current.jobId !== nextSnapshot.job_id) return nextSnapshot;
    const next = transition({ type: 'snapshot', snapshot: nextSnapshot });
    persistForSnapshot(nextSnapshot);
    if (next.phase === 'terminal') {
      streamRef.current?.abort();
      streamRef.current = null;
    }
    return nextSnapshot;
  }, [persistForSnapshot, transition]);

  const refreshSnapshot = useCallback(async (jobId = stateRef.current.jobId): Promise<ImportJob | null> => {
    if (!enabled || !jobId) return null;
    const requestId = snapshotRequestRef.current + 1;
    snapshotRequestRef.current = requestId;
    const nextSnapshot = await client.getImportJob(jobId);
    if (requestId !== snapshotRequestRef.current || stateRef.current.jobId !== jobId) return nextSnapshot;
    return applySnapshot(nextSnapshot);
  }, [applySnapshot, client, enabled]);

  const recordFatalError = useCallback((error: unknown) => {
    if (error instanceof ApiError && error.status === 401) onAuthError?.();
    transition({ type: 'failed', error: mapImportJobError(error) });
  }, [onAuthError, transition]);

  useEffect(() => {
    const jobId = state.jobId;
    if (!enabled || !jobId || stateRef.current.phase === 'terminal') return;
    const lifecycle = new AbortController();

    async function pollUntilTerminal(): Promise<void> {
      let failures = 0;
      transition({ type: 'reconnecting', attempt: maxSseReconnectAttempts });
      while (!lifecycle.signal.aborted && stateRef.current.jobId === jobId) {
        try {
          const nextSnapshot = await refreshSnapshot(jobId);
          failures = 0;
          if (!nextSnapshot || TERMINAL_STATUSES.has(nextSnapshot.status)) return;
        } catch (error) {
          if (lifecycle.signal.aborted) return;
          if (error instanceof ApiError && error.status === 401) {
            recordFatalError(error);
            return;
          }
          failures += 1;
          if (failures >= maxPollingFailures) {
            recordFatalError(error);
            return;
          }
        }
        await waitForDelay(lifecycle.signal, pollIntervalMs);
      }
    }

    async function run(): Promise<void> {
      try {
        const firstSnapshot = await refreshSnapshot(jobId);
        if (!firstSnapshot || TERMINAL_STATUSES.has(firstSnapshot.status)) return;
      } catch (error) {
        if (!lifecycle.signal.aborted) recordFatalError(error);
        return;
      }

      let failedStreams = 0;
      while (!lifecycle.signal.aborted && stateRef.current.jobId === jobId) {
        const listener = (nextEvent: JobEvent) => {
          const previousCursor = stateRef.current.cursor;
          const next = transition({ type: 'event', event: nextEvent });
          if (next.cursor === previousCursor) return;
          void refreshSnapshot(jobId).catch((error) => {
            if (!lifecycle.signal.aborted && error instanceof ApiError && error.status === 401) {
              recordFatalError(error);
            }
          });
        };
        const cursor = stateRef.current.cursor;
        const subscription = client.subscribeJobEvents(jobId, listener, {
          cursor,
          lastEventId: cursor,
        });
        streamRef.current = subscription;
        try {
          await subscription.done;
          if (lifecycle.signal.aborted || stateRef.current.phase === 'terminal') return;
          const nextSnapshot = await refreshSnapshot(jobId);
          if (!nextSnapshot || TERMINAL_STATUSES.has(nextSnapshot.status)) return;
          failedStreams += 1;
        } catch (error) {
          if (lifecycle.signal.aborted || stateRef.current.phase === 'terminal') return;
          if (error instanceof ApiError && error.status === 401) {
            recordFatalError(error);
            return;
          }
          failedStreams += 1;
        } finally {
          if (streamRef.current === subscription) streamRef.current = null;
        }

        if (failedStreams >= Math.max(1, maxSseReconnectAttempts)) {
          await pollUntilTerminal();
          return;
        }
        transition({ type: 'reconnecting', attempt: failedStreams });
        const delayMs = Math.min(reconnectMaxMs, reconnectBaseMs * (2 ** (failedStreams - 1)));
        await waitForDelay(lifecycle.signal, delayMs);
        if (lifecycle.signal.aborted) return;
        try {
          const nextSnapshot = await refreshSnapshot(jobId);
          if (!nextSnapshot || TERMINAL_STATUSES.has(nextSnapshot.status)) return;
        } catch (error) {
          if (error instanceof ApiError && error.status === 401) {
            recordFatalError(error);
            return;
          }
        }
      }
    }

    void run();
    return () => {
      lifecycle.abort();
      streamRef.current?.abort();
      streamRef.current = null;
    };
  }, [
    client,
    connectionEpoch,
    enabled,
    maxPollingFailures,
    maxSseReconnectAttempts,
    pollIntervalMs,
    reconnectBaseMs,
    reconnectMaxMs,
    recordFatalError,
    refreshSnapshot,
    state.jobId,
    transition,
  ]);

  const createJob = useCallback(async (
    request: ImportJobCreateRequest,
  ): Promise<ImportJobAcceptedResponse | null> => {
    if (!enabled || stateRef.current.phase === 'creating') return null;
    transition({ type: 'creating' });
    snapshotRequestRef.current += 1;
    streamRef.current?.abort();
    streamRef.current = null;
    try {
      const response = await client.createImportJob(request);
      transition({ type: 'accepted', response });
      writeStoredJobId(storage, storageKey, response.job_id);
      return response;
    } catch (error) {
      recordFatalError(error);
      throw error;
    }
  }, [client, enabled, recordFatalError, storage, storageKey, transition]);

  const cancelJob = useCallback(async (): Promise<ImportJob | null> => {
    const jobId = stateRef.current.jobId;
    if (!enabled || !jobId) return null;
    try {
      return applySnapshot(await client.cancelImportJob(jobId));
    } catch (error) {
      recordFatalError(error);
      throw error;
    }
  }, [applySnapshot, client, enabled, recordFatalError]);

  const retryFailedTasks = useCallback(async (): Promise<ImportJob | null> => {
    const jobId = stateRef.current.jobId;
    if (!enabled || !jobId) return null;
    try {
      const nextSnapshot = applySnapshot(await client.retryFailedTasks(jobId));
      if (!TERMINAL_STATUSES.has(nextSnapshot.status)) {
        writeStoredJobId(storage, storageKey, jobId);
        setConnectionEpoch((current) => current + 1);
      }
      return nextSnapshot;
    } catch (error) {
      recordFatalError(error);
      throw error;
    }
  }, [applySnapshot, client, enabled, recordFatalError, storage, storageKey]);

  const resumeJob = useCallback((jobId: string) => {
    const normalized = jobId.trim();
    if (!normalized) return;
    snapshotRequestRef.current += 1;
    streamRef.current?.abort();
    streamRef.current = null;
    writeStoredJobId(storage, storageKey, normalized);
    stateRef.current = { ...initialImportJobState, phase: 'reconnecting', jobId: normalized };
    setState(stateRef.current);
    setConnectionEpoch((current) => current + 1);
  }, [storage, storageKey]);

  const clearJob = useCallback(() => {
    snapshotRequestRef.current += 1;
    streamRef.current?.abort();
    streamRef.current = null;
    writeStoredJobId(storage, storageKey, '');
    transition({ type: 'reset' });
  }, [storage, storageKey, transition]);

  return {
    state,
    createJob,
    cancelJob,
    retryFailedTasks,
    resumeJob,
    clearJob,
    refreshSnapshot,
  };
}
