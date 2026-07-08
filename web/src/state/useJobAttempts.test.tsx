import { renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { ApiClient } from '../api/client';
import { useJobAttempts } from './useJobAttempts';

describe('useJobAttempts', () => {
  it('loads attempts for an active job id', async () => {
    const attempts = [
      {
        id: 1,
        job_id: 'job-1',
        provider_id: 'gemini',
        model: 'gemini-live',
        status: 'success',
      },
    ];
    const client = {
      getJobAttempts: vi.fn().mockResolvedValue(attempts),
    } as unknown as ApiClient;

    const { result } = renderHook(() => useJobAttempts(client, true, 'job-1'));

    await waitFor(() => expect(result.current.attempts.state).toBe('ready'));
    expect(result.current.attempts.data).toEqual(attempts);
    expect(client.getJobAttempts).toHaveBeenCalledWith('job-1');
  });

  it('resets when there is no active job id', () => {
    const client = {
      getJobAttempts: vi.fn(),
    } as unknown as ApiClient;

    const { result } = renderHook(() => useJobAttempts(client, true, ''));

    expect(result.current.attempts.state).toBe('idle');
    expect(result.current.attempts.data).toEqual([]);
    expect(client.getJobAttempts).not.toHaveBeenCalled();
  });
});
