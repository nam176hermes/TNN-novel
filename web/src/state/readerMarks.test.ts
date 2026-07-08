import { describe, expect, it } from 'vitest';
import type { ReaderAnnotation } from '../api/types';
import {
  acceptReaderAnnotationConflictFromServer,
  annotationToLocalMark,
  chapterMarksKey,
  markReaderAnnotationConflictForLocalResolution,
  mergeLocalAndRemoteMarks,
  readerMarksToSyncAnnotations,
  sanitizeChapterMarks,
  type ReaderMarksStore,
} from './readerMarks';

const highlight: ReaderAnnotation = {
  id: 7,
  book_id: 42,
  chapter_id: 102,
  chapter_number: 2,
  chapter_title: 'Thanh Ngưu trấn',
  kind: 'highlight',
  paragraph_index: 3,
  char_start: 0,
  char_end: 12,
  selected_text: 'Hàn Lập khẽ gật đầu.',
  note: '',
  color: 'yellow',
  created_at: '2026-06-28T10:00:00Z',
  updated_at: '2026-06-28T10:00:00Z',
  deleted_at: null,
};

describe('readerMarks', () => {
  it('builds stable chapter marks keys', () => {
    expect(chapterMarksKey(42, 102)).toBe('42:102');
  });

  it('converts remote annotations to local highlight or note marks', () => {
    expect(annotationToLocalMark(highlight)).toMatchObject({
      annotationId: 7,
      bookId: 42,
      charEnd: 12,
      charStart: 0,
      chapterId: 102,
      chapterNumber: 2,
      chapterTitle: 'Thanh Ngưu trấn',
      id: 'annotation-7',
      paragraphIndex: 3,
      text: 'Hàn Lập khẽ gật đầu.',
    });

    expect(annotationToLocalMark({ ...highlight, kind: 'note', note: 'Giữ xưng hô cổ trang.' })).toMatchObject({
      annotationId: 7,
      charEnd: 12,
      charStart: 0,
      note: 'Giữ xưng hô cổ trang.',
    });
  });

  it('preserves local character ranges when sanitizing persisted marks', () => {
    expect(sanitizeChapterMarks({
      bookmarked: false,
      highlights: [{
        charEnd: 16,
        charStart: 4,
        id: 'local-selection',
        paragraphIndex: 2,
        text: 'Lập khẽ',
      }],
      notes: [{
        charEnd: 18,
        charStart: 9,
        id: 'local-note',
        note: 'Tên riêng.',
        paragraphIndex: 3,
        text: 'Hàn Lập',
      }],
    })).toMatchObject({
      highlights: [{ charEnd: 16, charStart: 4 }],
      notes: [{ charEnd: 18, charStart: 9 }],
    });
  });

  it('merges local marks with active remote annotations without duplicating remote ids', () => {
    const local: ReaderMarksStore = {
      [chapterMarksKey(42, 102)]: {
        bookmarked: false,
        highlights: [{ id: 'local-1', paragraphIndex: 1, text: 'Local highlight' }],
        notes: [],
      },
    };

    const merged = mergeLocalAndRemoteMarks(local, [
      { ...highlight, kind: 'bookmark', id: 6, paragraph_index: 0, selected_text: 'Chương 2' },
      highlight,
      highlight,
      { ...highlight, kind: 'note', id: 8, paragraph_index: 4, note: 'Một ghi chú' },
      { ...highlight, id: 9, deleted_at: '2026-06-28T11:00:00Z' },
    ]);

    expect(merged[chapterMarksKey(42, 102)]).toMatchObject({
      bookmarked: true,
      bookmarkAnnotationId: 6,
      highlights: [
        { id: 'local-1', paragraphIndex: 1, text: 'Local highlight' },
        { annotationId: 7, charEnd: 12, charStart: 0, paragraphIndex: 3, text: 'Hàn Lập khẽ gật đầu.' },
      ],
      notes: [{ annotationId: 8, charEnd: 12, charStart: 0, paragraphIndex: 4, note: 'Một ghi chú' }],
    });
  });

  it('converts local-only marks into sync annotations without resending remote-backed marks', () => {
    const local: ReaderMarksStore = {
      [chapterMarksKey(42, 102)]: {
        bookmarked: true,
        bookmarkAnnotationId: 6,
        highlights: [
          { annotationId: 7, id: 'remote-highlight', paragraphIndex: 1, text: 'Remote highlight' },
          {
            charEnd: 12,
            charStart: 4,
            color: 'green',
            id: 'local-highlight',
            paragraphIndex: 2,
            text: 'Local highlight',
          },
        ],
        notes: [
          {
            charEnd: 18,
            charStart: 5,
            id: 'local-note',
            note: 'Ghi chú offline',
            paragraphIndex: 3,
            text: 'Local note',
          },
        ],
      },
      [chapterMarksKey(99, 201)]: {
        bookmarked: true,
        highlights: [{ id: 'other-book', paragraphIndex: 0, text: 'Other' }],
        notes: [],
      },
    };

    expect(readerMarksToSyncAnnotations(local, 42)).toEqual([
      {
        chapter_id: 102,
        char_end: 12,
        char_start: 4,
        client_id: 'local-highlight',
        color: 'green',
        kind: 'highlight',
        paragraph_index: 2,
        selected_text: 'Local highlight',
      },
      {
        chapter_id: 102,
        char_end: 18,
        char_start: 5,
        client_id: 'local-note',
        color: 'yellow',
        kind: 'note',
        note: 'Ghi chú offline',
        paragraph_index: 3,
        selected_text: 'Local note',
      },
    ]);
  });

  it('syncs dirty remote-backed marks and deletion tombstones for offline conflict resolution', () => {
    const local = {
      [chapterMarksKey(42, 102)]: {
        bookmarked: true,
        bookmarkAnnotationId: 6,
        highlights: [
          {
            annotationId: 7,
            id: 'annotation-7',
            paragraphIndex: 1,
            text: 'Clean remote highlight',
            updatedAt: '2026-06-28T10:00:00Z',
          },
          {
            annotationId: 8,
            charEnd: 22,
            charStart: 4,
            color: 'green',
            id: 'annotation-8',
            paragraphIndex: 2,
            syncPending: true,
            text: 'Edited offline highlight',
            updatedAt: '2026-06-28T10:12:00Z',
          },
        ],
        notes: [
          {
            annotationId: 9,
            charEnd: 18,
            charStart: 5,
            id: 'annotation-9',
            note: 'Ghi chú đã sửa khi offline',
            paragraphIndex: 3,
            syncPending: true,
            text: 'Edited offline note',
            updatedAt: '2026-06-28T10:13:00Z',
          },
        ],
        deletedAnnotations: [
          {
            annotationId: 10,
            chapterId: 102,
            kind: 'highlight',
            paragraphIndex: 4,
            selectedText: 'Deleted offline highlight',
            deletedAt: '2026-06-28T10:14:00Z',
            updatedAt: '2026-06-28T10:14:00Z',
          },
        ],
      },
    } as unknown as ReaderMarksStore;

    expect(readerMarksToSyncAnnotations(local, 42)).toEqual([
      {
        id: 8,
        chapter_id: 102,
        char_end: 22,
        char_start: 4,
        client_id: 'annotation-8',
        color: 'green',
        kind: 'highlight',
        paragraph_index: 2,
        selected_text: 'Edited offline highlight',
        updated_at: '2026-06-28T10:12:00Z',
      },
      {
        id: 9,
        chapter_id: 102,
        char_end: 18,
        char_start: 5,
        client_id: 'annotation-9',
        color: 'yellow',
        kind: 'note',
        note: 'Ghi chú đã sửa khi offline',
        paragraph_index: 3,
        selected_text: 'Edited offline note',
        updated_at: '2026-06-28T10:13:00Z',
      },
      {
        id: 10,
        chapter_id: 102,
        client_id: null,
        kind: 'highlight',
        paragraph_index: 4,
        selected_text: 'Deleted offline highlight',
        deleted_at: '2026-06-28T10:14:00Z',
        updated_at: '2026-06-28T10:14:00Z',
      },
    ]);
  });

  it('marks a conflicted remote-backed annotation as dirty when resolving with local', () => {
    const local: ReaderMarksStore = {
      [chapterMarksKey(42, 102)]: {
        bookmarked: false,
        highlights: [
          {
            annotationId: 7,
            clientId: 'reader-highlight-7',
            id: 'annotation-7',
            paragraphIndex: 1,
            syncPending: false,
            text: 'Local highlight',
            updatedAt: '2026-06-28T10:00:00Z',
          },
        ],
        notes: [],
      },
    };

    const resolved = markReaderAnnotationConflictForLocalResolution(
      local,
      42,
      {
        entity: 'annotation',
        id: 7,
        client_id: 'reader-highlight-7',
        reason: 'server_newer',
        resolution: 'server_won',
      },
      '2026-06-29T10:00:00Z',
    );

    expect(resolved[chapterMarksKey(42, 102)]?.highlights[0]).toMatchObject({
      annotationId: 7,
      syncPending: true,
      updatedAt: '2026-06-29T10:00:00Z',
    });
    expect(readerMarksToSyncAnnotations(resolved, 42)).toEqual([
      expect.objectContaining({
        id: 7,
        client_id: 'reader-highlight-7',
        kind: 'highlight',
        selected_text: 'Local highlight',
        updated_at: '2026-06-29T10:00:00Z',
      }),
    ]);
  });

  it('accepts the server annotation when resolving a sync conflict with server', () => {
    const local: ReaderMarksStore = {
      [chapterMarksKey(42, 102)]: {
        bookmarked: false,
        highlights: [
          {
            annotationId: 7,
            charEnd: 22,
            charStart: 0,
            clientId: 'reader-highlight-7',
            color: 'yellow',
            id: 'reader-highlight-7',
            paragraphIndex: 1,
            syncPending: true,
            text: 'Local highlight',
            updatedAt: '2026-06-28T10:00:00Z',
          },
        ],
        notes: [],
      },
    };

    const resolved = acceptReaderAnnotationConflictFromServer(
      local,
      42,
      {
        entity: 'annotation',
        id: 7,
        client_id: 'reader-highlight-7',
        reason: 'server_newer',
        resolution: 'server_won',
        server_annotation: {
          id: 7,
          book_id: 42,
          chapter_id: 102,
          chapter_number: 2,
          chapter_title: 'Thanh Ngưu trấn',
          kind: 'highlight',
          paragraph_index: 1,
          char_start: 0,
          char_end: 24,
          selected_text: 'Server newer highlight',
          note: '',
          color: 'green',
          created_at: '2026-06-29T10:00:00Z',
          updated_at: '2026-06-29T10:11:00Z',
          deleted_at: null,
        },
      },
    );

    expect(resolved[chapterMarksKey(42, 102)]?.highlights).toEqual([
      expect.objectContaining({
        annotationId: 7,
        charEnd: 24,
        charStart: 0,
        color: 'green',
        text: 'Server newer highlight',
        updatedAt: '2026-06-29T10:11:00Z',
      }),
    ]);
    expect(readerMarksToSyncAnnotations(resolved, 42)).toEqual([]);
  });
});
