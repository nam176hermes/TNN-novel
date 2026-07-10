import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, type ApiClient } from '../api/client';
import type { JobStatus } from '../api/types';
import { formatError, type AsyncState } from './types';

const emptyJobsHistory: AsyncState<JobStatus[]> = { data: [], error: '', state: 'idle' };

export function useJobsHistory(client: ApiClient, enabled: boolean, onAuthError?: () => void, limit = 30) {
  const [jobs, setJobs] = useState<AsyncState<JobStatus[]>>(emptyJobsHistory);
  const requestIdRef = useRef(0);

  const reset = useCallback(() => {
    requestIdRef.current += 1;
    setJobs(emptyJobsHistory);
  }, []);

  const refresh = useCallback(async () => {
    if (!enabled) {
      reset();
      return [];
    }

    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    setJobs((current) => ({ data: current.data, error: '', state: 'loading' }));

    try {
      const nextJobs = await client.listJobs(limit);
      if (requestId !== requestIdRef.current) return nextJobs;
      setJobs({
        data: nextJobs,
        error: '',
        state: nextJobs.length > 0 ? 'ready' : 'empty',
      });
      return nextJobs;
    } catch (error) {
      if (requestId !== requestIdRef.current) throw error;
      if (error instanceof ApiError && error.status === 401) {
        onAuthError?.();
      }
      setJobs((current) => ({ data: current.data, error: formatError(error), state: 'error' }));
      throw error;
    }
  }, [client, enabled, limit, onAuthError, reset]);

  useEffect(() => {
    if (!enabled) {
      reset();
      return;
    }

    void refresh().catch(() => {});
  }, [enabled, refresh, reset]);

  return {
    jobs,
    refresh,
  };
}
