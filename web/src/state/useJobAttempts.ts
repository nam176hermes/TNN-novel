import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, type ApiClient } from '../api/client';
import type { JobAttempt } from '../api/types';
import { formatError, type AsyncState } from './types';

const emptyAttempts: AsyncState<JobAttempt[]> = { data: [], error: '', state: 'idle' };

export function useJobAttempts(client: ApiClient, enabled: boolean, jobId: string, onAuthError?: () => void) {
  const [attempts, setAttempts] = useState<AsyncState<JobAttempt[]>>(emptyAttempts);
  const requestIdRef = useRef(0);

  const reset = useCallback(() => {
    requestIdRef.current += 1;
    setAttempts(emptyAttempts);
  }, []);

  const refresh = useCallback(async () => {
    if (!enabled || !jobId) {
      reset();
      return [];
    }

    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    setAttempts((current) => ({ data: current.data, error: '', state: 'loading' }));

    try {
      const nextAttempts = await client.getJobAttempts(jobId);
      if (requestId !== requestIdRef.current) return nextAttempts;
      setAttempts({
        data: nextAttempts,
        error: '',
        state: nextAttempts.length > 0 ? 'ready' : 'empty',
      });
      return nextAttempts;
    } catch (error) {
      if (requestId !== requestIdRef.current) throw error;
      if (error instanceof ApiError && error.status === 401) {
        onAuthError?.();
      }
      setAttempts((current) => ({ data: current.data, error: formatError(error), state: 'error' }));
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

  return {
    attempts,
    refresh,
  };
}
