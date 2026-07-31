import type {
  ReaderFontFamily,
  ReaderMode,
  ReaderSettings,
  ReaderTextMode,
  ReaderTheme,
  ReaderWidth,
} from './types';

export const READER_SETTINGS_STORAGE_KEY = 'novel-reader-settings-v1';
export const READER_TEXT_MODE_STORAGE_KEY = 'novel-reader-text-mode-v1';

export const defaultReaderSettings: ReaderSettings = {
  characterSpacing: 0,
  fontFamily: 'serif',
  fontSize: 18,
  fontWeight: 400,
  fullscreen: false,
  instantMode: false,
  lineHeight: 1.9,
  marginScale: 1,
  paragraphSpacing: 1.05,
  readingMode: 'scroll',
  theme: 'light',
  width: 'medium',
};

function getBrowserStorage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function clampNumber(value: unknown, fallback: number, min: number, max: number): number {
  const numberValue = Number(value);
  if (!Number.isFinite(numberValue)) return fallback;
  return Math.min(max, Math.max(min, numberValue));
}

function normalizeReaderTheme(value: unknown): ReaderTheme | null {
  if (value === 'light' || value === 'dark' || value === 'sepia' || value === 'eink') return value;
  if (value === 'paper') return 'light';
  if (value === 'night') return 'dark';
  if (value === 'oled') return 'eink';
  return null;
}

function isReaderWidth(value: unknown): value is ReaderWidth {
  return value === 'narrow' || value === 'medium' || value === 'wide';
}

function isReaderFontFamily(value: unknown): value is ReaderFontFamily {
  return value === 'serif' || value === 'sans';
}

function isReaderMode(value: unknown): value is ReaderMode {
  return value === 'scroll' || value === 'paginated';
}

function isReaderTextMode(value: unknown): value is ReaderTextMode {
  return value === 'translation'
    || value === 'raw'
    || value === 'split'
    || value === 'raw-collapsed'
    || value === 'qa-overlay';
}

export function loadReaderSettings(storage: Storage | null = getBrowserStorage()): ReaderSettings {
  if (!storage) return defaultReaderSettings;
  try {
    const parsed = JSON.parse(storage.getItem(READER_SETTINGS_STORAGE_KEY) ?? '{}') as Partial<ReaderSettings>;
    return {
      characterSpacing: clampNumber(
        parsed.characterSpacing,
        defaultReaderSettings.characterSpacing,
        0,
        1.5,
      ),
      fontFamily: isReaderFontFamily(parsed.fontFamily) ? parsed.fontFamily : defaultReaderSettings.fontFamily,
      fontSize: clampNumber(parsed.fontSize, defaultReaderSettings.fontSize, 16, 24),
      fontWeight: clampNumber(parsed.fontWeight, defaultReaderSettings.fontWeight, 350, 800),
      fullscreen: typeof parsed.fullscreen === 'boolean' ? parsed.fullscreen : defaultReaderSettings.fullscreen,
      instantMode: typeof parsed.instantMode === 'boolean' ? parsed.instantMode : defaultReaderSettings.instantMode,
      lineHeight: clampNumber(parsed.lineHeight, defaultReaderSettings.lineHeight, 1.5, 2.2),
      marginScale: clampNumber(parsed.marginScale, defaultReaderSettings.marginScale, 0.75, 1.5),
      paragraphSpacing: clampNumber(
        parsed.paragraphSpacing,
        defaultReaderSettings.paragraphSpacing,
        0.6,
        2.4,
      ),
      readingMode: isReaderMode(parsed.readingMode) ? parsed.readingMode : defaultReaderSettings.readingMode,
      theme: normalizeReaderTheme(parsed.theme) ?? defaultReaderSettings.theme,
      width: isReaderWidth(parsed.width) ? parsed.width : defaultReaderSettings.width,
    };
  } catch {
    return defaultReaderSettings;
  }
}

export function saveReaderSettings(
  settings: ReaderSettings,
  storage: Storage | null = getBrowserStorage(),
): void {
  if (!storage) return;
  try {
    storage.setItem(READER_SETTINGS_STORAGE_KEY, JSON.stringify(settings));
  } catch {
    // Reading should still work when browser storage is unavailable.
  }
}

export function loadReaderTextMode(storage: Storage | null = getBrowserStorage()): ReaderTextMode {
  if (!storage) return 'translation';
  try {
    const stored = storage.getItem(READER_TEXT_MODE_STORAGE_KEY);
    return isReaderTextMode(stored) ? stored : 'translation';
  } catch {
    return 'translation';
  }
}

export function saveReaderTextMode(
  mode: ReaderTextMode,
  storage: Storage | null = getBrowserStorage(),
): void {
  if (!storage) return;
  try {
    storage.setItem(READER_TEXT_MODE_STORAGE_KEY, mode);
  } catch {
    // Reading should remain usable when storage is unavailable.
  }
}
