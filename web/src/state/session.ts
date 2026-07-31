const TOKEN_KEY = 'novel-operator-token';
const REFRESH_TOKEN_KEY = 'novel-operator-refresh-token';

function getStorage(): Storage | undefined {
  try {
    return globalThis.sessionStorage ?? undefined;
  } catch {
    return undefined;
  }
}

function clearLegacyPersistentTokens(): void {
  try {
    globalThis.localStorage?.removeItem(TOKEN_KEY);
    globalThis.localStorage?.removeItem(REFRESH_TOKEN_KEY);
  } catch {
    // Storage can be unavailable in privacy-focused browser modes.
  }
}

export function loadToken(): string {
  try {
    clearLegacyPersistentTokens();
    return getStorage()?.getItem(TOKEN_KEY) ?? '';
  } catch {
    return '';
  }
}

export function saveToken(token: string): void {
  try {
    clearLegacyPersistentTokens();
    getStorage()?.setItem(TOKEN_KEY, token);
  } catch {
    // Ignore storage failures so non-browser environments can still render.
  }
}

export function loadRefreshToken(): string {
  clearLegacyPersistentTokens();
  return '';
}

export function saveRefreshToken(_token: string): void {
  clearLegacyPersistentTokens();
}

export function saveSessionTokens(accessToken: string, _refreshToken = ''): void {
  saveToken(accessToken);
}

export function clearToken(): void {
  try {
    const storage = getStorage();
    storage?.removeItem(TOKEN_KEY);
    storage?.removeItem(REFRESH_TOKEN_KEY);
    clearLegacyPersistentTokens();
  } catch {
    // Ignore storage failures so non-browser environments can still render.
  }
}
