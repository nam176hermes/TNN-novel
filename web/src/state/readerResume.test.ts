import { describe, expect, it } from 'vitest';
import {
  READER_RESUME_STORAGE_KEY,
  clearReaderResume,
  loadReaderResume,
  saveReaderResume,
} from './readerResume';

const resume = {
  bookId: 42,
  bookTitle: 'Live Book',
  chapterId: 4201,
  chapterNumber: 1,
  chapterTitle: 'Chapter 1',
  contentRevision: '/book-assets/42/4201/rev-a/content.html',
};

describe('reader resume state', () => {
  it('round-trips bounded current-reader metadata without private chapter content', () => {
    saveReaderResume(resume, window.localStorage);

    expect(loadReaderResume(window.localStorage)).toEqual({ ...resume, version: 1 });
    expect(window.localStorage.getItem(READER_RESUME_STORAGE_KEY)).not.toContain('sourceText');
  });

  it('rejects malformed, unsupported, and incomplete state', () => {
    window.localStorage.setItem(READER_RESUME_STORAGE_KEY, '{broken');
    expect(loadReaderResume(window.localStorage)).toBeNull();

    window.localStorage.setItem(READER_RESUME_STORAGE_KEY, JSON.stringify({ ...resume, version: 2 }));
    expect(loadReaderResume(window.localStorage)).toBeNull();

    window.localStorage.setItem(READER_RESUME_STORAGE_KEY, JSON.stringify({ ...resume, version: 1, chapterId: -1 }));
    expect(loadReaderResume(window.localStorage)).toBeNull();
  });

  it('clears resume metadata at the session boundary', () => {
    saveReaderResume(resume, window.localStorage);
    clearReaderResume(window.localStorage);

    expect(loadReaderResume(window.localStorage)).toBeNull();
  });
});
