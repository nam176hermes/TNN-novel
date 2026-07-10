import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, type ApiClient } from '../api/client';
import type { JobLogEntry } from '../api/types';
import { formatError, type AsyncState } from './types';

const emptyLogs: AsyncState<JobLogEntry[]> = { data: [], error: '', state: 'idle' };

export function useJobLogs(client: ApiClient, enabled: boolean, jobId: string, onAuthError?: () => void) {
  const [logs, setLogs] = useState<AsyncState<JobLogEntry[]>>(emptyLogs);
  const requestIdRef = useRef(0);

  const reset = useCallback(() => {
    requestIdRef.current += 1;
    setLogs(emptyLogs);
  }, []);

  const refresh = useCallback(async () => {
    if (!enabled || !jobId) {
      reset();
      return [];
    }

    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    setLogs((current) => ({ data: current.data, error: '', state: 'loading' }));

    try {
      const nextLogs = await client.getJobLogs(jobId);
      if (requestId !== requestIdRef.current) return nextLogs;
      setLogs({
        data: nextLogs,
        error: '',
        state: nextLogs.length > 0 ? 'ready' : 'empty',
      });
      return nextLogs;
    } catch (error) {
      if (requestId !== requestIdRef.current) throw error;
      if (error instanceof ApiError && error.status === 401) {
        onAuthError?.();
      }
      setLogs((current) => ({ data: current.data, error: formatError(error), state: 'error' }));
      throw error;
    }
  }, [client, enabled, jobId, onAuthError, reset]);

  useEffect(() => {
    if (!enabled || !jobId) {
      reset();
      return;
    }

    void refresh().catch(() => {});
  }, [enabled, jobId, refresh, reset]);

  return { logs, refresh };
}
