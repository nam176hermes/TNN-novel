import { describe, expect, it } from 'vitest';
import type { Book, BookSummary, Chapter, ChapterApi } from '../api/types';
import {
  estimateSourceChars,
  hasUnsavedTranslationChange,
  mapBookSummary,
  mapChapter,
  mergeChapterSummary,
} from './translator';

const book: Book = {
  id: 7,
  title: 'Backend Novel',
  author: '',
  source: 'paste',
  source_url: '',
  created_at: '2026-06-20T00:00:00Z',
  updated_at: '2026-06-20T00:00:00Z',
};

function chapter(overrides: Partial<ChapterApi> = {}): ChapterApi {
  return {
    id: 100,
    book_id: 7,
    chapter_number: 1,
    title: 'Chapter One',
    status: 'cleaned',
    source_url: '',
    raw_text_path: '/raw/1.txt',
    cleaned_text_path: '/clean/1.txt',
    translated_text_path: null,
    audio_path: null,
    translated_at: null,
    audio_created_at: null,
    ...overrides,
  };
}

describe('translator state helpers', () => {
  it('excludes stale audio from the library count while retaining unverified legacy audio', () => {
    const summary = mapBookSummary(book, [
      chapter({ audio_path: 'available', audio_status: 'stale' }),
      chapter({ audio_path: 'available', audio_status: 'legacy_unverified' }),
    ]);
    expect(summary.audio).toBe(1);
  });
  it('maps a backend book with no chapters into a usable summary', () => {
    expect(mapBookSummary(book)).toEqual({
      id: 7,
      title: 'Backend Novel',
      translated: 0,
      audio: 0,
      failed: 0,
      total: 0,
      qa_low: 0,
      last_activity: 'Loaded from backend',
      next_action: 'Review library',
    });
  });

  it('merges chapter rows into translated, failed, QA-low, and audio counts', () => {
    const summary: BookSummary = {
      id: 7,
      title: 'Backend Novel',
      translated: 0,
      audio: 0,
      failed: 0,
      total: 0,
      qa_low: 0,
    };

    const merged = mergeChapterSummary(summary, [
      chapter({ id: 101, status: 'translated', translated_text_path: '/translated/101.txt' }),
      chapter({ id: 102, status: 'failed' }),
      chapter({ id: 103, status: 'qa_low', translated_text_path: '/translated/103.txt' }),
      chapter({
        id: 104,
        status: 'audio_done',
        translated_text_path: '/translated/104.txt',
        audio_path: '/audio/104.mp3',
      }),
    ]);

    expect(merged).toMatchObject({
      translated: 3,
      failed: 1,
      qa_low: 1,
      audio: 1,
      total: 4,
      last_activity: '4 chapters loaded',
      next_action: 'Retry failed chapters',
    });
  });

  it('maps a chapter while preserving identifiers and backend-derived status fields', () => {
    const mapped = mapChapter(
      chapter({
        id: 222,
        book_id: 9,
        chapter_number: 12,
        title: 'Storm Gate',
        status: 'qa_low',
        translated_text_path: '/translated/222.txt',
        translated_at: '2026-06-20T10:00:00Z',
      }),
      'Mapped Book',
    );

    expect(mapped).toMatchObject({
      id: 222,
      book_id: 9,
      book_title: 'Mapped Book',
      chapter_number: 12,
      title: 'Storm Gate',
      status: 'qa_low',
      qa_verdict: 'Cần xem lại',
      source_preview: 'Có bản nguồn đã làm sạch',
      latest_job_status: 'qa low',
      last_action: 'Đã dịch từ backend',
    });
    expect(mapped.qa_score).toBeUndefined();
    expect(mapped.qa_issue_count).toBeUndefined();
    expect(mapped.translation_preview).toBeUndefined();
  });

  it('maps chapter API data without inventing QA scores or translation previews', () => {
    const mapped = mapChapter(
      {
        id: 1,
        book_id: 2,
        chapter_number: 3,
        title: '入门',
        status: 'qa_low',
        source_url: '',
        raw_text_path: null,
        cleaned_text_path: '/tmp/source.txt',
        translated_text_path: '/tmp/translation.txt',
        audio_path: null,
        translated_at: null,
        audio_created_at: null,
      },
      'Test Book',
    );

    expect(mapped.qa_score).toBeUndefined();
    expect(mapped.qa_issue_count).toBeUndefined();
    expect(mapped.translation_preview).toBeUndefined();
    expect(mapped.source_preview).toBe('Có bản nguồn đã làm sạch');
  });

  it('falls back to the per-chapter heuristic when mapped chapters only carry readiness labels', () => {
    const mapped = mapChapter(
      {
        id: 1,
        book_id: 2,
        chapter_number: 3,
        title: '入门',
        status: 'cleaned',
        source_url: '',
        raw_text_path: null,
        cleaned_text_path: '/tmp/source.txt',
        translated_text_path: null,
        audio_path: null,
        translated_at: null,
        audio_created_at: null,
      },
      'Test Book',
    );

    expect(estimateSourceChars([mapped])).toBe(0);
  });

  it('estimates source characters from real previews only', () => {
    const chaptersWithPreviews: Chapter[] = [
      {
        id: 1,
        book_id: 7,
        chapter_number: 1,
        title: 'A',
        status: 'translated',
        audio_path: '',
        source_preview: 'source',
        translation_preview: 'translated',
      },
      {
        id: 2,
        book_id: 7,
        chapter_number: 2,
        title: 'B',
        status: 'cleaned',
        audio_path: '',
        source_preview: 'raw',
      },
    ];

    const chaptersWithoutPreviews: Chapter[] = chaptersWithPreviews.map((item) => ({
      ...item,
      source_preview: '',
      translation_preview: '',
    }));

    expect(estimateSourceChars(chaptersWithPreviews)).toBe('sourcetranslatedraw'.length);
    expect(estimateSourceChars(chaptersWithoutPreviews)).toBe(0);
  });

  it('detects unsaved translation editor changes', () => {
    expect(hasUnsavedTranslationChange(null, '')).toBe(false);
    expect(hasUnsavedTranslationChange(null, 'draft')).toBe(true);
    expect(hasUnsavedTranslationChange('saved', 'saved')).toBe(false);
    expect(hasUnsavedTranslationChange('saved', 'changed')).toBe(true);
  });
});
