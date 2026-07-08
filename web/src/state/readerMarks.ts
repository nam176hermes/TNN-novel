import type { ReaderAnnotation, ReaderAnnotationKind, ReaderSyncAnnotation, ReaderSyncConflict } from '../api/types';

export const READER_MARKS_STORAGE_KEY = 'novel-reader-marks-v1';

export type ReaderHighlight = {
  id: string;
  annotationId?: number;
  bookId?: number;
  charEnd?: number;
  charStart?: number;
  chapterId?: number;
  chapterNumber?: number;
  chapterTitle?: string;
  clientId?: string;
  paragraphIndex: number;
  text: string;
  color?: string;
  createdAt?: string;
  syncPending?: boolean;
  updatedAt?: string;
};

export type ReaderNote = ReaderHighlight & {
  note: string;
};

export type ReaderChapterMarks = {
  bookmarked: boolean;
  bookmarkAnnotationId?: number;
  deletedAnnotations?: ReaderDeletedAnnotation[];
  highlights: ReaderHighlight[];
  notes: ReaderNote[];
};

export type ReaderMarksStore = Record<string, ReaderChapterMarks>;

export type ReaderDeletedAnnotation = {
  annotationId?: number;
  chapterId: number;
  charEnd?: number;
  charStart?: number;
  clientId?: string;
  color?: string;
  deletedAt: string;
  kind: ReaderAnnotationKind;
  note?: string;
  paragraphIndex: number;
  selectedText?: string;
  updatedAt?: string;
};

function getBrowserStorage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export function chapterMarksKey(bookId: number, chapterId: number): string {
  return `${bookId}:${chapterId}`;
}

export function createEmptyChapterMarks(): ReaderChapterMarks {
  return {
    bookmarked: false,
    deletedAnnotations: [],
    highlights: [],
    notes: [],
  };
}

function normalizeParagraphIndex(value: unknown): number {
  const paragraphIndex = Number(value);
  return Number.isInteger(paragraphIndex) && paragraphIndex >= 0 ? paragraphIndex : 0;
}

function normalizeOptionalInteger(value: unknown): number | undefined {
  const numberValue = Number(value);
  return Number.isInteger(numberValue) && numberValue >= 0 ? numberValue : undefined;
}

function normalizeOptionalString(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value : undefined;
}

function sanitizeHighlight(value: unknown): ReaderHighlight | null {
  if (!value || typeof value !== 'object') return null;
  const candidate = value as Partial<ReaderHighlight>;
  if (typeof candidate.text !== 'string') return null;
  const charStart = normalizeOptionalInteger(candidate.charStart);
  const charEnd = normalizeOptionalInteger(candidate.charEnd);
  return {
    annotationId: Number.isInteger(candidate.annotationId) ? candidate.annotationId : undefined,
    bookId: Number.isInteger(candidate.bookId) ? candidate.bookId : undefined,
    charEnd: charEnd !== undefined && charStart !== undefined && charEnd >= charStart ? charEnd : undefined,
    charStart,
    chapterId: Number.isInteger(candidate.chapterId) ? candidate.chapterId : undefined,
    chapterNumber: Number.isInteger(candidate.chapterNumber) ? candidate.chapterNumber : undefined,
    chapterTitle: typeof candidate.chapterTitle === 'string' ? candidate.chapterTitle : undefined,
    clientId: normalizeOptionalString(candidate.clientId),
    color: typeof candidate.color === 'string' ? candidate.color : undefined,
    createdAt: normalizeOptionalString(candidate.createdAt),
    id: typeof candidate.id === 'string' ? candidate.id : `highlight-${normalizeParagraphIndex(candidate.paragraphIndex)}`,
    paragraphIndex: normalizeParagraphIndex(candidate.paragraphIndex),
    syncPending: candidate.syncPending === true,
    text: candidate.text,
    updatedAt: normalizeOptionalString(candidate.updatedAt),
  };
}

function sanitizeNote(value: unknown): ReaderNote | null {
  if (!value || typeof value !== 'object') return null;
  const candidate = value as Partial<ReaderNote>;
  if (typeof candidate.note !== 'string') return null;
  const highlight = sanitizeHighlight(value);
  if (!highlight) return null;
  return {
    ...highlight,
    id: typeof candidate.id === 'string' ? candidate.id : `note-${highlight.paragraphIndex}`,
    note: candidate.note,
  };
}

function isReaderAnnotationKind(value: unknown): value is ReaderAnnotationKind {
  return value === 'bookmark' || value === 'highlight' || value === 'note';
}

function sanitizeDeletedAnnotation(value: unknown): ReaderDeletedAnnotation | null {
  if (!value || typeof value !== 'object') return null;
  const candidate = value as Partial<ReaderDeletedAnnotation>;
  const annotationId = normalizeOptionalInteger(candidate.annotationId);
  const chapterId = Number(candidate.chapterId);
  const deletedAt = normalizeOptionalString(candidate.deletedAt);
  if (!Number.isInteger(chapterId) || chapterId <= 0 || !deletedAt || !isReaderAnnotationKind(candidate.kind)) {
    return null;
  }
  const charStart = normalizeOptionalInteger(candidate.charStart);
  const charEnd = normalizeOptionalInteger(candidate.charEnd);
  return {
    annotationId,
    chapterId,
    charEnd: charEnd !== undefined && charStart !== undefined && charEnd >= charStart ? charEnd : undefined,
    charStart,
    clientId: normalizeOptionalString(candidate.clientId),
    color: normalizeOptionalString(candidate.color),
    deletedAt,
    kind: candidate.kind,
    note: normalizeOptionalString(candidate.note),
    paragraphIndex: normalizeParagraphIndex(candidate.paragraphIndex),
    selectedText: normalizeOptionalString(candidate.selectedText),
    updatedAt: normalizeOptionalString(candidate.updatedAt),
  };
}

export function sanitizeChapterMarks(value: unknown): ReaderChapterMarks {
  if (!value || typeof value !== 'object') return createEmptyChapterMarks();
  const candidate = value as Partial<ReaderChapterMarks>;
  return {
    bookmarked: candidate.bookmarked === true,
    bookmarkAnnotationId: Number.isInteger(candidate.bookmarkAnnotationId) ? candidate.bookmarkAnnotationId : undefined,
    deletedAnnotations: Array.isArray(candidate.deletedAnnotations)
      ? candidate.deletedAnnotations
        .map(sanitizeDeletedAnnotation)
        .filter((annotation): annotation is ReaderDeletedAnnotation => Boolean(annotation))
      : [],
    highlights: Array.isArray(candidate.highlights)
      ? candidate.highlights.map(sanitizeHighlight).filter((mark): mark is ReaderHighlight => Boolean(mark))
      : [],
    notes: Array.isArray(candidate.notes)
      ? candidate.notes.map(sanitizeNote).filter((mark): mark is ReaderNote => Boolean(mark))
      : [],
  };
}

export function loadReaderMarks(storage: Storage | null = getBrowserStorage()): ReaderMarksStore {
  if (!storage) return {};
  try {
    const parsed = JSON.parse(storage.getItem(READER_MARKS_STORAGE_KEY) ?? '{}') as Record<string, unknown>;
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    return Object.fromEntries(
      Object.entries(parsed).map(([key, value]) => [key, sanitizeChapterMarks(value)]),
    );
  } catch {
    return {};
  }
}

export function saveReaderMarks(marks: ReaderMarksStore, storage: Storage | null = getBrowserStorage()): void {
  if (!storage) return;
  try {
    storage.setItem(READER_MARKS_STORAGE_KEY, JSON.stringify(marks));
  } catch {
    // Reading should still work when browser storage is unavailable.
  }
}

export function annotationToLocalMark(annotation: ReaderAnnotation): ReaderHighlight | ReaderNote {
  const base: ReaderHighlight = {
    annotationId: annotation.id,
    bookId: annotation.book_id,
    chapterId: annotation.chapter_id,
    chapterNumber: annotation.chapter_number,
    chapterTitle: annotation.chapter_title,
    charEnd: annotation.char_end,
    charStart: annotation.char_start,
    clientId: annotation.client_id,
    color: annotation.color,
    createdAt: annotation.created_at,
    id: `annotation-${annotation.id}`,
    paragraphIndex: annotation.paragraph_index,
    text: annotation.selected_text || annotation.chapter_title || `Đoạn ${annotation.paragraph_index + 1}`,
    updatedAt: annotation.updated_at,
  };

  if (annotation.kind === 'note') {
    return {
      ...base,
      note: annotation.note,
    };
  }
  return base;
}

function timestampMs(value: string | null | undefined): number {
  if (!value) return 0;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function hasNewerPendingLocalMark(marks: ReaderChapterMarks, annotation: ReaderAnnotation): boolean {
  if (annotation.kind === 'highlight') {
    return marks.highlights.some((item) => (
      item.annotationId === annotation.id
      && item.syncPending === true
      && timestampMs(item.updatedAt) > timestampMs(annotation.updated_at)
    ));
  }
  if (annotation.kind === 'note') {
    return marks.notes.some((item) => (
      item.annotationId === annotation.id
      && item.syncPending === true
      && timestampMs(item.updatedAt) > timestampMs(annotation.updated_at)
    ));
  }
  return false;
}

function hasNewerDeletionTombstone(marks: ReaderChapterMarks, annotation: ReaderAnnotation): boolean {
  return (marks.deletedAnnotations ?? []).some((item) => (
    item.annotationId === annotation.id
    && timestampMs(item.deletedAt) > timestampMs(annotation.updated_at)
  ));
}

function removeSyncedAnnotationFromMarks(marks: ReaderChapterMarks, annotation: ReaderAnnotation): ReaderChapterMarks {
  return sanitizeChapterMarks({
    ...marks,
    bookmarked: marks.bookmarkAnnotationId === annotation.id ? false : marks.bookmarked,
    bookmarkAnnotationId: marks.bookmarkAnnotationId === annotation.id ? undefined : marks.bookmarkAnnotationId,
    deletedAnnotations: (marks.deletedAnnotations ?? []).filter((item) => item.annotationId !== annotation.id),
    highlights: marks.highlights.filter((item) => item.annotationId !== annotation.id),
    notes: marks.notes.filter((item) => item.annotationId !== annotation.id),
  });
}

export function mergeLocalAndRemoteMarks(
  local: ReaderMarksStore,
  remote: ReaderAnnotation[],
): ReaderMarksStore {
  const merged: ReaderMarksStore = Object.fromEntries(
    Object.entries(local).map(([key, value]) => [key, sanitizeChapterMarks(value)]),
  );

  for (const annotation of remote) {
    const key = chapterMarksKey(annotation.book_id, annotation.chapter_id);
    const current = sanitizeChapterMarks(merged[key] ?? createEmptyChapterMarks());

    if (annotation.deleted_at) {
      merged[key] = removeSyncedAnnotationFromMarks(current, annotation);
      continue;
    }

    if (hasNewerDeletionTombstone(current, annotation) || hasNewerPendingLocalMark(current, annotation)) {
      continue;
    }

  if (annotation.kind === 'bookmark') {
    merged[key] = {
      ...current,
      bookmarked: true,
      bookmarkAnnotationId: annotation.id,
        deletedAnnotations: (current.deletedAnnotations ?? []).filter((item) => item.annotationId !== annotation.id),
      };
      continue;
    }

    const mark = annotationToLocalMark(annotation);
    if ('note' in mark) {
      const notes = current.notes.filter((item) => (
        item.annotationId !== annotation.id
        && !(item.annotationId === undefined && item.paragraphIndex === annotation.paragraph_index)
      ));
      merged[key] = {
        ...current,
        deletedAnnotations: (current.deletedAnnotations ?? []).filter((item) => item.annotationId !== annotation.id),
        notes: [...notes, mark],
      };
      continue;
    }

    const highlights = current.highlights.filter((item) => (
      item.annotationId !== annotation.id
      && !(item.annotationId === undefined && item.paragraphIndex === annotation.paragraph_index)
    ));
    merged[key] = {
      ...current,
      deletedAnnotations: (current.deletedAnnotations ?? []).filter((item) => item.annotationId !== annotation.id),
      highlights: [...highlights, mark],
    };
  }

  return merged;
}

function parseChapterMarksKey(key: string): { bookId: number; chapterId: number } | null {
  const [rawBookId, rawChapterId] = key.split(':');
  const bookId = Number(rawBookId);
  const chapterId = Number(rawChapterId);
  if (!Number.isInteger(bookId) || !Number.isInteger(chapterId) || bookId <= 0 || chapterId <= 0) return null;
  return { bookId, chapterId };
}

function markRange(mark: ReaderHighlight): Pick<ReaderSyncAnnotation, 'char_end' | 'char_start'> {
  return {
    char_end: mark.charEnd ?? 0,
    char_start: mark.charStart ?? 0,
  };
}

function markSyncBase(mark: ReaderHighlight): Pick<
  ReaderSyncAnnotation,
  'client_id' | 'created_at' | 'id' | 'updated_at'
> {
  const base: Pick<ReaderSyncAnnotation, 'client_id' | 'created_at' | 'id' | 'updated_at'> = {
    client_id: mark.clientId ?? mark.id,
  };
  if (mark.annotationId) base.id = mark.annotationId;
  if (mark.createdAt) base.created_at = mark.createdAt;
  if (mark.updatedAt) base.updated_at = mark.updatedAt;
  return base;
}

function shouldSyncActiveMark(mark: ReaderHighlight): boolean {
  return !mark.annotationId || mark.syncPending === true;
}

export function readerMarksToSyncAnnotations(
  marks: ReaderMarksStore,
  bookId: number,
): ReaderSyncAnnotation[] {
  const annotations: ReaderSyncAnnotation[] = [];

  for (const [key, rawChapterMarks] of Object.entries(marks)) {
    const parsedKey = parseChapterMarksKey(key);
    if (!parsedKey || parsedKey.bookId !== bookId) continue;

    const chapterMarks = sanitizeChapterMarks(rawChapterMarks);
    const chapterId = parsedKey.chapterId;

    if (chapterMarks.bookmarked && !chapterMarks.bookmarkAnnotationId) {
      annotations.push({
        chapter_id: chapterId,
        client_id: `bookmark-${bookId}-${chapterId}`,
        kind: 'bookmark',
        paragraph_index: 0,
        selected_text: '',
      });
    }

    for (const highlight of chapterMarks.highlights) {
      if (!shouldSyncActiveMark(highlight)) continue;
      annotations.push({
        chapter_id: highlight.chapterId ?? chapterId,
        color: highlight.color ?? 'yellow',
        kind: 'highlight',
        paragraph_index: highlight.paragraphIndex,
        selected_text: highlight.text,
        ...markRange(highlight),
        ...markSyncBase(highlight),
      });
    }

    for (const note of chapterMarks.notes) {
      if (!shouldSyncActiveMark(note)) continue;
      annotations.push({
        chapter_id: note.chapterId ?? chapterId,
        color: note.color ?? 'yellow',
        kind: 'note',
        note: note.note,
        paragraph_index: note.paragraphIndex,
        selected_text: note.text,
        ...markRange(note),
        ...markSyncBase(note),
      });
    }

    for (const deleted of chapterMarks.deletedAnnotations ?? []) {
      annotations.push({
        chapter_id: deleted.chapterId || chapterId,
        client_id: deleted.clientId ?? null,
        kind: deleted.kind,
        paragraph_index: deleted.paragraphIndex,
        selected_text: deleted.selectedText ?? '',
        ...(deleted.annotationId ? { id: deleted.annotationId } : {}),
        ...(deleted.charStart !== undefined ? { char_start: deleted.charStart } : {}),
        ...(deleted.charEnd !== undefined ? { char_end: deleted.charEnd } : {}),
        ...(deleted.color ? { color: deleted.color } : {}),
        ...(deleted.note ? { note: deleted.note } : {}),
        deleted_at: deleted.deletedAt,
        updated_at: deleted.updatedAt ?? deleted.deletedAt,
      });
    }
  }

  return annotations;
}

function conflictMatchesMark(conflict: ReaderSyncConflict, mark: ReaderHighlight): boolean {
  const conflictClientId = conflict.client_id?.trim();
  return (
    (Number.isInteger(conflict.id) && mark.annotationId === conflict.id)
    || (Boolean(conflictClientId) && (mark.clientId === conflictClientId || mark.id === conflictClientId))
  );
}

function markForLocalResolution<T extends ReaderHighlight>(mark: T, updatedAt: string): T {
  return {
    ...mark,
    syncPending: true,
    updatedAt,
  };
}

export function markReaderAnnotationConflictForLocalResolution(
  marks: ReaderMarksStore,
  bookId: number,
  conflict: ReaderSyncConflict,
  updatedAt: string = new Date().toISOString(),
): ReaderMarksStore {
  if (conflict.entity !== 'annotation') return marks;
  const next: ReaderMarksStore = {};
  let changed = false;

  for (const [key, rawChapterMarks] of Object.entries(marks)) {
    const parsedKey = parseChapterMarksKey(key);
    const chapterMarks = sanitizeChapterMarks(rawChapterMarks);
    if (!parsedKey || parsedKey.bookId !== bookId) {
      next[key] = chapterMarks;
      continue;
    }

    const highlights = chapterMarks.highlights.map((highlight) => {
      if (!conflictMatchesMark(conflict, highlight)) return highlight;
      changed = true;
      return markForLocalResolution(highlight, updatedAt);
    });
    const notes = chapterMarks.notes.map((note) => {
      if (!conflictMatchesMark(conflict, note)) return note;
      changed = true;
      return markForLocalResolution(note, updatedAt);
    });

    next[key] = {
      ...chapterMarks,
      highlights,
      notes,
    };
  }

  return changed ? next : marks;
}

function removeConflictingLocalAnnotation(
  marks: ReaderChapterMarks,
  conflict: ReaderSyncConflict,
  annotation: ReaderAnnotation,
): ReaderChapterMarks {
  const matches = (mark: ReaderHighlight) => (
    conflictMatchesMark(conflict, mark)
    || mark.annotationId === annotation.id
    || (Boolean(annotation.client_id) && mark.clientId === annotation.client_id)
  );
  return sanitizeChapterMarks({
    ...marks,
    bookmarked: (
      marks.bookmarkAnnotationId === annotation.id
      || (conflict.entity === 'annotation' && conflict.id === marks.bookmarkAnnotationId)
    ) ? false : marks.bookmarked,
    bookmarkAnnotationId: (
      marks.bookmarkAnnotationId === annotation.id
      || (conflict.entity === 'annotation' && conflict.id === marks.bookmarkAnnotationId)
    ) ? undefined : marks.bookmarkAnnotationId,
    deletedAnnotations: (marks.deletedAnnotations ?? []).filter((item) => (
      item.annotationId !== annotation.id
      && item.clientId !== conflict.client_id
      && item.clientId !== annotation.client_id
    )),
    highlights: marks.highlights.filter((item) => !matches(item)),
    notes: marks.notes.filter((item) => !matches(item)),
  });
}

export function acceptReaderAnnotationConflictFromServer(
  marks: ReaderMarksStore,
  bookId: number,
  conflict: ReaderSyncConflict,
): ReaderMarksStore {
  if (conflict.entity !== 'annotation' || !conflict.server_annotation) return marks;
  const annotation = conflict.server_annotation;
  if (annotation.book_id !== bookId) return marks;

  const next: ReaderMarksStore = Object.fromEntries(
    Object.entries(marks).map(([key, value]) => [key, sanitizeChapterMarks(value)]),
  );
  const key = chapterMarksKey(annotation.book_id, annotation.chapter_id);
  const current = sanitizeChapterMarks(next[key] ?? createEmptyChapterMarks());
  const cleaned = removeConflictingLocalAnnotation(current, conflict, annotation);

  if (annotation.deleted_at) {
    next[key] = cleaned;
    return next;
  }

  if (annotation.kind === 'bookmark') {
    next[key] = {
      ...cleaned,
      bookmarked: true,
      bookmarkAnnotationId: annotation.id,
    };
    return next;
  }

  const mark = annotationToLocalMark(annotation);
  if ('note' in mark) {
    next[key] = {
      ...cleaned,
      notes: [...cleaned.notes, mark],
    };
    return next;
  }

  next[key] = {
    ...cleaned,
    highlights: [...cleaned.highlights, mark],
  };
  return next;
}
