import { clearReaderCacheAsync } from './readerCache';

const READER_PRIVATE_STORAGE_PREFIX = 'novel-reader-';
const PRESERVED_READER_PREFERENCE_KEYS = new Set([
  'novel-reader-settings-v1',
  'novel-reader-text-mode-v1',
  'novel-reader-audio-playback-rate-v1',
]);

function browserStorage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export async function clearReaderPrivateData(
  storage: Storage | null = browserStorage(),
): Promise<void> {
  await clearReaderCacheAsync(storage);
  if (!storage) return;

  const privateKeys: string[] = [];
  try {
    for (let index = 0; index < storage.length; index += 1) {
      const key = storage.key(index);
      if (
        key?.startsWith(READER_PRIVATE_STORAGE_PREFIX)
        && !PRESERVED_READER_PREFERENCE_KEYS.has(key)
      ) privateKeys.push(key);
    }
    privateKeys.forEach((key) => storage.removeItem(key));
  } catch {
    // Local logout must continue when browser storage is unavailable.
  }
}
