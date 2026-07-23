import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ApiClient, ApiError } from '../api/client';
import {
  clearToken,
  loadToken,
  saveToken,
} from './session';
import { formatError } from './types';

async function withBrowserRefreshLock<T>(operation: () => Promise<T>): Promise<T> {
  const locks = typeof navigator === 'undefined' ? undefined : navigator.locks;
  if (!locks) return operation();
  return locks.request('novel-tnn-auth-refresh', { mode: 'exclusive' }, operation);
}

export function useSession(apiBaseUrl: string, authDisabled = false) {
  const [token, setToken] = useState(() => (authDisabled ? '' : loadToken()));
  const [isRestoring, setIsRestoring] = useState(() => !authDisabled && !loadToken());
  const [loginError, setLoginError] = useState('');
  const refreshInFlightRef = useRef<Promise<boolean> | null>(null);

  const client = useMemo(() => {
    const api = new ApiClient(apiBaseUrl);
    api.token = token;
    return api;
  }, [apiBaseUrl, token]);

  const refreshSession = useCallback(async (): Promise<boolean> => {
    if (authDisabled) return true;
    if (refreshInFlightRef.current) return refreshInFlightRef.current;

    const refreshPromise = withBrowserRefreshLock(async () => {
      const refreshClient = new ApiClient(apiBaseUrl);
      try {
        const response = await refreshClient.refresh();
        saveToken(response.access_token);
        setToken(response.access_token);
        setLoginError('');
        return true;
      } catch (error) {
        if (!(error instanceof ApiError)
          && typeof navigator !== 'undefined'
          && navigator.onLine === false
          && loadToken()) {
          setLoginError('');
          return true;
        }
        clearToken();
        setToken('');
        setLoginError('Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.');
        return false;
      } finally {
        setIsRestoring(false);
        refreshInFlightRef.current = null;
      }
    });

    refreshInFlightRef.current = refreshPromise;
    return refreshPromise;
  }, [apiBaseUrl, authDisabled]);

  useEffect(() => {
    if (authDisabled) {
      setIsRestoring(false);
      setLoginError('');
      return;
    }
    if (loadToken()) {
      setIsRestoring(false);
      return;
    }
    setIsRestoring(true);
    void refreshSession();
  }, [authDisabled, refreshSession]);

  const login = useCallback(
    async (username: string, password: string) => {
      setLoginError('');
      if (authDisabled) {
        clearToken();
        setToken('');
        setIsRestoring(false);
        return;
      }
      try {
        const response = await client.login(username, password);
        saveToken(response.access_token);
        setToken(response.access_token);
      } catch (error) {
        setLoginError(formatError(error));
      }
    },
    [authDisabled, client],
  );

  const logout = useCallback(async () => {
    if (authDisabled) {
      clearToken();
      setToken('');
      setIsRestoring(false);
      setLoginError('');
      return;
    }
    try {
      await client.logout();
    } catch {
      // Local logout must work even when backend logout fails.
    } finally {
      clearToken();
      setToken('');
      setIsRestoring(false);
      setLoginError('');
    }
  }, [authDisabled, client]);

  const expireSession = useCallback(() => {
    if (authDisabled) {
      clearToken();
      setToken('');
      setIsRestoring(false);
      setLoginError('');
      return;
    }
    setIsRestoring(true);
    void refreshSession();
  }, [authDisabled, refreshSession]);

  return {
    authDisabled,
    client,
    expireSession,
    isAuthenticated: authDisabled || (Boolean(token) && !isRestoring),
    isRestoring,
    login,
    loginError,
    logout,
    token,
  };
}
