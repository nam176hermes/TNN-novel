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
    sessionStorage.clear();
  });

  it('keeps the short-lived access token in sessionStorage only', () => {
    saveToken('access');
    saveRefreshToken('refresh');

    expect(loadToken()).toBe('access');
    expect(loadRefreshToken()).toBe('');
    expect(sessionStorage.getItem('novel-operator-token')).toBe('access');
    expect(localStorage.getItem('novel-operator-token')).toBeNull();
    expect(localStorage.getItem('novel-operator-refresh-token')).toBeNull();

    clearToken();

    expect(loadToken()).toBe('');
    expect(loadRefreshToken()).toBe('');
  });

  it('never persists a refresh token supplied by an older caller', () => {
    saveSessionTokens('new-access', 'new-refresh');

    expect(loadToken()).toBe('new-access');
    expect(loadRefreshToken()).toBe('');
    expect(JSON.stringify({
      local: Object.fromEntries(Object.entries(localStorage)),
      session: Object.fromEntries(Object.entries(sessionStorage)),
    })).not.toContain('new-refresh');
  });

  it('removes legacy persistent auth tokens during migration', () => {
    localStorage.setItem('novel-operator-token', 'legacy-access');
    localStorage.setItem('novel-operator-refresh-token', 'legacy-refresh');

    expect(loadToken()).toBe('');
    expect(localStorage.getItem('novel-operator-token')).toBeNull();
    expect(localStorage.getItem('novel-operator-refresh-token')).toBeNull();
  });

  it('falls back safely when browser storage is unavailable', () => {
    vi.stubGlobal('sessionStorage', undefined);
    vi.stubGlobal('localStorage', undefined);

    expect(loadToken()).toBe('');
    expect(loadRefreshToken()).toBe('');
    expect(() => saveToken('access')).not.toThrow();
    expect(() => saveRefreshToken('refresh')).not.toThrow();
    expect(() => saveSessionTokens('access', 'refresh')).not.toThrow();
    expect(() => clearToken()).not.toThrow();
  });
});
