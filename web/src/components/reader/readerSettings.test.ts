import { afterEach, describe, expect, it } from 'vitest';
import {
  READER_SETTINGS_STORAGE_KEY,
  READER_TEXT_MODE_STORAGE_KEY,
  defaultReaderSettings,
  loadReaderSettings,
  loadReaderTextMode,
  saveReaderSettings,
  saveReaderTextMode,
} from './readerSettings';
import type { ReaderSettings, ReaderTextMode } from './types';

describe('reader settings persistence', () => {
  afterEach(() => {
    window.localStorage.clear();
  });

  it('normalizes invalid settings and legacy themes to the current defaults', () => {
    window.localStorage.setItem(READER_SETTINGS_STORAGE_KEY, JSON.stringify({
      characterSpacing: -2,
      fontFamily: 'display',
      fontSize: 99,
      fontWeight: 'heavy',
      fullscreen: 'yes',
      instantMode: 1,
      lineHeight: 0,
      marginScale: 9,
      paragraphSpacing: 20,
      readingMode: 'page',
      theme: 'night',
      width: 'full',
    }));

    expect(loadReaderSettings(window.localStorage)).toEqual({
      ...defaultReaderSettings,
      characterSpacing: 0,
      fontSize: 24,
      lineHeight: 1.5,
      marginScale: 1.5,
      paragraphSpacing: 2.4,
      theme: 'dark',
    });

    window.localStorage.setItem(READER_TEXT_MODE_STORAGE_KEY, 'source');
    expect(loadReaderTextMode(window.localStorage)).toBe('translation');
  });

  it('persists current reader settings and text modes without changing their values', () => {
    const settings: ReaderSettings = {
      characterSpacing: 0.35,
      fontFamily: 'sans',
      fontSize: 20,
      fontWeight: 550,
      fullscreen: true,
      instantMode: true,
      lineHeight: 2,
      marginScale: 1.2,
      paragraphSpacing: 1.4,
      readingMode: 'paginated',
      theme: 'eink',
      width: 'wide',
    };

    saveReaderSettings(settings, window.localStorage);
    saveReaderTextMode('raw-collapsed', window.localStorage);

    expect(loadReaderSettings(window.localStorage)).toEqual(settings);
    expect(loadReaderTextMode(window.localStorage)).toBe('raw-collapsed');
  });

  it.each<ReaderTextMode>([
    'translation',
    'raw',
    'split',
    'raw-collapsed',
    'qa-overlay',
  ])('round-trips the %s reader text mode', (mode) => {
    saveReaderTextMode(mode, window.localStorage);

    expect(loadReaderTextMode(window.localStorage)).toBe(mode);
  });

  it('keeps the existing storage keys byte-for-byte unchanged', () => {
    saveReaderSettings(defaultReaderSettings, window.localStorage);
    saveReaderTextMode('raw', window.localStorage);

    expect(READER_SETTINGS_STORAGE_KEY).toBe('novel-reader-settings-v1');
    expect(READER_TEXT_MODE_STORAGE_KEY).toBe('novel-reader-text-mode-v1');
    expect(window.localStorage.getItem('novel-reader-settings-v1')).toBe(JSON.stringify(defaultReaderSettings));
    expect(window.localStorage.getItem('novel-reader-text-mode-v1')).toBe('raw');
  });
});
