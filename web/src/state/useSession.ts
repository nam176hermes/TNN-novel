import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ApiClient } from '../api/client';
import {
  clearToken,
  loadRefreshToken,
  loadToken,
  saveSessionTokens,
} from './session';
import { formatError } from './types';

export function useSession(apiBaseUrl: string, authDisabled = false) {
  const [token, setToken] = useState(() => (authDisabled ? '' : loadToken()));
  const [isRestoring, setIsRestoring] = useState(() => !authDisabled && Boolean(loadRefreshToken()));
  const [loginError, setLoginError] = useState('');
  const refreshInFlightRef = useRef<Promise<boolean> | null>(null);

  const client = useMemo(() => {
    const api = new ApiClient(apiBaseUrl);
    api.token = token;
    return api;
  }, [apiBaseUrl, token]);

  const refreshSession = useCallback(async (): Promise<boolean> => {
    if (authDisabled) return true;
    const refreshToken = loadRefreshToken();
    if (!refreshToken) return false;
    if (refreshInFlightRef.current) return refreshInFlightRef.current;

    const refreshPromise = (async () => {
      const refreshClient = new ApiClient(apiBaseUrl);
      try {
        const response = await refreshClient.refresh(refreshToken);
        saveSessionTokens(response.access_token, response.refresh_token);
        setToken(response.access_token);
        setLoginError('');
        return true;
      } catch (error) {
        clearToken();
        setToken('');
        setLoginError('Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.');
        return false;
      } finally {
        setIsRestoring(false);
        refreshInFlightRef.current = null;
      }
    })();

    refreshInFlightRef.current = refreshPromise;
    return refreshPromise;
  }, [apiBaseUrl, authDisabled]);

  useEffect(() => {
    if (authDisabled) {
      setIsRestoring(false);
      setLoginError('');
      return;
    }
    if (!loadRefreshToken()) {
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
        saveSessionTokens(response.access_token, response.refresh_token);
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
    if (loadRefreshToken()) {
      setIsRestoring(true);
      void refreshSession();
      return;
    }
    clearToken();
    setToken('');
    setIsRestoring(false);
    setLoginError('Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.');
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
