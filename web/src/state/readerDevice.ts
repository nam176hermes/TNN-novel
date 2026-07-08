export const READER_DEVICE_STORAGE_KEY = 'novel-reader-device-id-v1';

function getBrowserStorage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function isValidReaderDeviceId(value: unknown): value is string {
  return typeof value === 'string' && /^reader-web-[a-zA-Z0-9._:-]{4,160}$/.test(value);
}

function generateReaderDeviceId(): string {
  const randomId = globalThis.crypto?.randomUUID?.()
    ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
  return `reader-web-${randomId}`;
}

export function loadReaderDeviceId(storage: Storage | null = getBrowserStorage()): string {
  if (!storage) return generateReaderDeviceId();
  try {
    const stored = storage.getItem(READER_DEVICE_STORAGE_KEY);
    if (isValidReaderDeviceId(stored)) return stored;
    const next = generateReaderDeviceId();
    storage.setItem(READER_DEVICE_STORAGE_KEY, next);
    return next;
  } catch {
    return generateReaderDeviceId();
  }
}
