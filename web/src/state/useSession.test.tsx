import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { clearToken, loadRefreshToken, loadToken, saveSessionTokens } from './session';
import { useSession } from './useSession';

describe('useSession', () => {
  it('treats no-login mode as authenticated without bearer tokens', async () => {
    saveSessionTokens('stale-access', 'stale-refresh');

    const { result } = renderHook(() => useSession('http://127.0.0.1:7860', true));

    expect(result.current.authDisabled).toBe(true);
    expect(result.current.isAuthenticated).toBe(true);
    expect(result.current.isRestoring).toBe(false);
    expect(result.current.client.token).toBe('');

    await act(async () => {
      await result.current.logout();
    });

    expect(result.current.isAuthenticated).toBe(true);
    expect(loadToken()).toBe('');
    expect(loadRefreshToken()).toBe('');
  });

  it('keeps normal login behavior when no-login mode is off', () => {
    clearToken();

    const { result } = renderHook(() => useSession('http://127.0.0.1:7860', false));

    expect(result.current.authDisabled).toBe(false);
    expect(result.current.isAuthenticated).toBe(false);
  });

  it('retains the local access token when refresh fails while the browser is offline', async () => {
    saveSessionTokens('offline-access', 'offline-refresh');
    const originalOnline = Object.getOwnPropertyDescriptor(window.navigator, 'onLine');
    Object.defineProperty(window.navigator, 'onLine', { configurable: true, value: false });
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));

    try {
      const { result } = renderHook(() => useSession('http://127.0.0.1:7860', false));

      await waitFor(() => expect(result.current.isRestoring).toBe(false));
      expect(result.current.isAuthenticated).toBe(true);
      expect(result.current.client.token).toBe('offline-access');
      expect(loadToken()).toBe('offline-access');
      expect(loadRefreshToken()).toBe('offline-refresh');
      expect(result.current.loginError).toBe('');
    } finally {
      vi.unstubAllGlobals();
      if (originalOnline) Object.defineProperty(window.navigator, 'onLine', originalOnline);
    }
  });

  it('clears an invalid session when refresh returns 401 even if navigator reports offline', async () => {
    saveSessionTokens('expired-access', 'expired-refresh');
    const originalOnline = Object.getOwnPropertyDescriptor(window.navigator, 'onLine');
    Object.defineProperty(window.navigator, 'onLine', { configurable: true, value: false });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ detail: 'expired' }),
      { headers: { 'content-type': 'application/json' }, status: 401 },
    )));

    try {
      const { result } = renderHook(() => useSession('http://127.0.0.1:7860', false));

      await waitFor(() => expect(result.current.isRestoring).toBe(false));
      expect(result.current.isAuthenticated).toBe(false);
      expect(loadToken()).toBe('');
      expect(loadRefreshToken()).toBe('');
    } finally {
      vi.unstubAllGlobals();
      if (originalOnline) Object.defineProperty(window.navigator, 'onLine', originalOnline);
    }
  });
});
