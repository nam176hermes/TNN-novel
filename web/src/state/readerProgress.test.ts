import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Chapter } from '../api/types';
import {
  chooseLatestReaderProgressSnapshot,
  loadReaderProgress,
  loadReaderProgressSnapshot,
  remoteReaderProgressToSnapshot,
  resolveReaderChapterId,
  saveReaderProgress,
  saveReaderProgressSnapshot,
} from './readerProgress';

function storage(): Storage {
  const values = new Map<string, string>();
  return {
    get length() {
      return values.size;
    },
    clear: () => values.clear(),
    getItem: (key: string) => values.get(key) ?? null,
    key: (index: number) => Array.from(values.keys())[index] ?? null,
    removeItem: (key: string) => {
      values.delete(key);
    },
    setItem: (key: string, value: string) => {
      values.set(key, value);
    },
  };
}

const chapters: Chapter[] = [
  { id: 101, book_id: 42, chapter_number: 1, title: 'Lý Thị!', status: 'translated', audio_path: null, has_translation: true },
  { id: 102, book_id: 42, chapter_number: 2, title: 'Năm Loại Đồng Tham!', status: 'translated', audio_path: null, has_translation: true },
  { id: 103, book_id: 42, chapter_number: 3, title: 'Chưa dịch', status: 'cleaned', audio_path: null, has_translation: false },
];

describe('readerProgress', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('saves and loads the last read chapter by book id', () => {
    const target = storage();

    saveReaderProgress(42, 102, target);

    expect(loadReaderProgress(42, target)).toBe(102);
    expect(loadReaderProgress(7, target)).toBeNull();
  });

  it('resolves preferred, saved, then first readable chapter in order', () => {
    const target = storage();
    saveReaderProgress(42, 102, target);

    expect(resolveReaderChapterId(chapters, 101, 42, target)).toBe(101);
    expect(resolveReaderChapterId(chapters, null, 42, target)).toBe(102);

    saveReaderProgress(42, 999, target);
    expect(resolveReaderChapterId(chapters, null, 42, target)).toBe(101);
  });

  it('saves rich reader progress while keeping legacy chapter id loading compatible', () => {
    const target = storage();

    saveReaderProgressSnapshot(42, 102, 2, 5, target);

    expect(loadReaderProgress(42, target)).toBe(102);
    expect(loadReaderProgressSnapshot(42, target)).toMatchObject({
      chapterId: 102,
      percent: 40,
      position: 2,
      totalChapters: 5,
    });
  });

  it('preserves exact character percent separately from pixel position', () => {
    const target = storage();

    saveReaderProgressSnapshot(42, 102, 300, 600, target, {
      percent: 21,
      absoluteCharOffset: 3,
      charOffset: 3,
      mode: 'scroll',
      paragraphIndex: 0,
    });

    expect(loadReaderProgressSnapshot(42, target)).toMatchObject({
      absoluteCharOffset: 3,
      chapterId: 102,
      charOffset: 3,
      paragraphIndex: 0,
      percent: 21,
      position: 300,
      totalChapters: 600,
    });
  });

  it('timestamps newly saved local progress for cross-device conflict resolution', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-06-29T10:12:00Z'));
    const target = storage();

    saveReaderProgressSnapshot(42, 102, 2, 5, target);

    expect(loadReaderProgressSnapshot(42, target)).toMatchObject({
      chapterId: 102,
      updatedAt: '2026-06-29T10:12:00.000Z',
    });
  });

  it('saves exact reader location metadata for page and paragraph restore', () => {
    const target = storage();

    saveReaderProgressSnapshot(42, 102, 2, 5, target, {
      charOffset: 3,
      mode: 'paginated',
      pageIndex: 1,
      paragraphIndex: 4,
      updatedAt: '2026-06-28T10:00:00.000Z',
    });

    expect(loadReaderProgressSnapshot(42, target)).toEqual({
      chapterId: 102,
      charOffset: 3,
      mode: 'paginated',
      pageIndex: 1,
      paragraphIndex: 4,
      percent: 40,
      position: 2,
      totalChapters: 5,
      updatedAt: '2026-06-28T10:00:00.000Z',
    });
  });

  it('does not erase exact location metadata when reselecting the same chapter', () => {
    const target = storage();

    saveReaderProgressSnapshot(42, 102, 2, 5, target, {
      charOffset: 7,
      mode: 'scroll',
      pageIndex: 0,
      paragraphIndex: 3,
    });
    saveReaderProgress(42, 102, target);

    expect(loadReaderProgressSnapshot(42, target)).toMatchObject({
      chapterId: 102,
      charOffset: 7,
      mode: 'scroll',
      pageIndex: 0,
      paragraphIndex: 3,
    });
  });

  it('normalizes invalid exact reader location metadata defensively', () => {
    const target = storage();
    target.setItem('novel-reader-progress-v1', JSON.stringify({
      42: {
        chapterId: 102,
        charOffset: -1,
        mode: 'unknown',
        pageIndex: Number.NaN,
        paragraphIndex: 'bad',
        position: 2,
        totalChapters: 5,
        updatedAt: 123,
      },
    }));

    expect(loadReaderProgressSnapshot(42, target)).toEqual({
      chapterId: 102,
      percent: 40,
      position: 2,
      totalChapters: 5,
    });
  });

  it('keeps newer local progress when remote progress is stale', () => {
    const local = {
      chapterId: 102,
      charOffset: 24,
      mode: 'scroll' as const,
      paragraphIndex: 3,
      percent: 52,
      position: 52,
      totalChapters: 100,
      updatedAt: '2026-06-29T10:10:00Z',
    };
    const remote = {
      chapterId: 101,
      charOffset: 4,
      mode: 'scroll' as const,
      paragraphIndex: 1,
      percent: 20,
      position: 20,
      totalChapters: 100,
      updatedAt: '2026-06-29T10:00:00Z',
    };

    expect(chooseLatestReaderProgressSnapshot(local, remote)).toBe(local);
  });

  it('uses newer remote progress when another device is ahead', () => {
    const local = {
      chapterId: 101,
      charOffset: 4,
      mode: 'scroll' as const,
      paragraphIndex: 1,
      percent: 20,
      position: 20,
      totalChapters: 100,
      updatedAt: '2026-06-29T10:00:00Z',
    };
    const remote = {
      chapterId: 102,
      charOffset: 24,
      mode: 'scroll' as const,
      paragraphIndex: 3,
      percent: 52,
      position: 52,
      totalChapters: 100,
      updatedAt: '2026-06-29T10:10:00Z',
    };

    expect(chooseLatestReaderProgressSnapshot(local, remote)).toBe(remote);
  });

  it('converts API reader progress into a local snapshot for conflict resolution', () => {
    expect(remoteReaderProgressToSnapshot({
      book_id: 42,
      chapter_id: 102,
      chapter_number: 2,
      chapter_title: 'Năm Loại Đồng Tham!',
      char_offset: 24,
      absolute_char_offset: 824,
      mode: 'scroll',
      page_index: 0,
      paragraph_index: 3,
      percent: 52,
      updated_at: '2026-06-29T10:10:00Z',
    })).toEqual({
      chapterId: 102,
      absoluteCharOffset: 824,
      charOffset: 24,
      mode: 'scroll',
      pageIndex: 0,
      paragraphIndex: 3,
      percent: 52,
      position: 52,
      totalChapters: 100,
      updatedAt: '2026-06-29T10:10:00Z',
    });
  });

  it('preserves remote text anchors for cross-device exact restore', () => {
    const anchor = {
      version: 1,
      text: 'Hàn Lập khẽ gật đầu.',
      offset: 7,
      prefix: 'Sơn đạo',
      suffix: 'Lục ca',
    };

    expect(remoteReaderProgressToSnapshot({
      book_id: 42,
      chapter_id: 102,
      chapter_number: 2,
      chapter_title: 'Thanh Ngưu trấn',
      char_offset: 7,
      absolute_char_offset: 7,
      mode: 'scroll',
      page_index: 0,
      paragraph_index: 0,
      percent: 21,
      anchor,
      updated_at: '2026-06-29T10:10:00Z',
    } as never)).toMatchObject({
      anchor,
      chapterId: 102,
      charOffset: 7,
      paragraphIndex: 0,
    });
  });

  it('ignores a backend default absolute offset when paragraph progress is later in the chapter', () => {
    const snapshot = remoteReaderProgressToSnapshot({
      book_id: 42,
      chapter_id: 102,
      chapter_number: 2,
      chapter_title: 'Năm Loại Đồng Tham!',
      char_offset: 24,
      absolute_char_offset: 0,
      mode: 'scroll',
      page_index: 0,
      paragraph_index: 3,
      percent: 52,
      updated_at: '2026-06-29T10:10:00Z',
    });

    expect(snapshot).toMatchObject({
      chapterId: 102,
      charOffset: 24,
      paragraphIndex: 3,
      percent: 52,
    });
    expect(snapshot.absoluteCharOffset).toBeUndefined();
  });
});
