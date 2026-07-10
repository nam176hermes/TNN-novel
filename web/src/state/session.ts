const TOKEN_KEY = 'novel-operator-token';
const REFRESH_TOKEN_KEY = 'novel-operator-refresh-token';

function getStorage(): Storage | undefined {
  try {
    return globalThis.localStorage ?? undefined;
  } catch {
    return undefined;
  }
}

export function loadToken(): string {
  try {
    return getStorage()?.getItem(TOKEN_KEY) ?? '';
  } catch {
    return '';
  }
}

export function saveToken(token: string): void {
  try {
    getStorage()?.setItem(TOKEN_KEY, token);
  } catch {
    // Ignore storage failures so non-browser environments can still render.
  }
}

export function loadRefreshToken(): string {
  try {
    return getStorage()?.getItem(REFRESH_TOKEN_KEY) ?? '';
  } catch {
    return '';
  }
}

export function saveRefreshToken(token: string): void {
  try {
    getStorage()?.setItem(REFRESH_TOKEN_KEY, token);
  } catch {
    // Ignore storage failures so non-browser environments can still render.
  }
}

export function saveSessionTokens(accessToken: string, refreshToken: string): void {
  saveToken(accessToken);
  saveRefreshToken(refreshToken);
}

export function clearToken(): void {
  try {
    const storage = getStorage();
    storage?.removeItem(TOKEN_KEY);
    storage?.removeItem(REFRESH_TOKEN_KEY);
  } catch {
    // Ignore storage failures so non-browser environments can still render.
  }
}
