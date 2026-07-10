import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  clearToken,
  loadRefreshToken,
  loadToken,
  saveRefreshToken,
  saveSessionTokens,
  saveToken,
} from './session';

describe('session token storage', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it('saves, loads, and clears the token from localStorage', () => {
    saveToken('access');
    saveRefreshToken('refresh');

    expect(loadToken()).toBe('access');
    expect(loadRefreshToken()).toBe('refresh');

    clearToken();

    expect(loadToken()).toBe('');
    expect(loadRefreshToken()).toBe('');
  });

  it('saves an access and refresh token pair for persistent sessions', () => {
    saveSessionTokens('new-access', 'new-refresh');

    expect(loadToken()).toBe('new-access');
    expect(loadRefreshToken()).toBe('new-refresh');
  });

  it('falls back safely when localStorage is unavailable', () => {
    vi.stubGlobal('localStorage', undefined);

    expect(loadToken()).toBe('');
    expect(loadRefreshToken()).toBe('');
    expect(() => saveToken('access')).not.toThrow();
    expect(() => saveRefreshToken('refresh')).not.toThrow();
    expect(() => saveSessionTokens('access', 'refresh')).not.toThrow();
    expect(() => clearToken()).not.toThrow();
  });
});
