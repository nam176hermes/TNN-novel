import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
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
});
