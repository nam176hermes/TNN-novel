import type { Dispatch, SetStateAction } from 'react';
import { ApiError } from '../api/client';
import type { useSession } from './useSession';

export function isAuthError(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}

export type AppWorkflowOptions = {
  session: Pick<ReturnType<typeof useSession>, 'client' | 'isAuthenticated'>;
  expireSession(): void;
  setBackendError: Dispatch<SetStateAction<string>>;
  setBackendSuccess(message: string): void;
  setBackendLoading(loading: boolean): void;
  handleJobError(error: unknown, label: string): void;
};
