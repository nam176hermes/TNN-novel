import { beforeEach, describe, expect, it } from 'vitest';
import { getCachedChapterAsync, putCachedChapterAsync } from './readerCache';
import { clearReaderPrivateData } from './readerPrivateData';

const privateKeys = [
  'novel-reader-resume-v1',
  'novel-reader-offline-manifest-v1',
  'novel-reader-dictionary-cache-v1',
  'novel-reader-progress-v1',
  'novel-reader-sync-v1',
  'novel-reader-marks-v1',
  'novel-reader-audio-position-v1',
];

describe('reader private data boundary', () => {
  beforeEach(() => window.localStorage.clear());

  it('clears private reader payloads while preserving non-content preferences', async () => {
    for (const key of privateKeys) window.localStorage.setItem(key, '{"private":true}');
    window.localStorage.setItem('novel-reader-settings-v1', '{"fontSize":20}');
    window.localStorage.setItem('novel-reader-text-mode-v1', 'split');
    window.localStorage.setItem('novel-reader-audio-playback-rate-v1', '1.25');
    await putCachedChapterAsync({
      bookId: 42,
      chapterId: 4201,
      html: '<p>private</p>',
      sourceText: 'private source',
      text: 'private translation',
    });

    await clearReaderPrivateData(window.localStorage);

    for (const key of privateKeys) expect(window.localStorage.getItem(key)).toBeNull();
    expect(await getCachedChapterAsync(42, 4201)).toBeNull();
    expect(window.localStorage.getItem('novel-reader-settings-v1')).toBe('{"fontSize":20}');
    expect(window.localStorage.getItem('novel-reader-text-mode-v1')).toBe('split');
    expect(window.localStorage.getItem('novel-reader-audio-playback-rate-v1')).toBe('1.25');
  });
});
