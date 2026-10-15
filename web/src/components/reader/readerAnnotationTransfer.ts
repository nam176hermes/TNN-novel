import type { Chapter, ReaderAnnotationExportFormat, ReaderAnnotationImportItem, ReaderAnnotationKind } from '../../api/types';
import type { ReaderMarksStore } from '../../state/readerMarks';
import type { ReaderMarkPanelItem } from './ReaderMarksPanel';

export const readerAnnotationExportScopes: Array<{ kind: ReaderAnnotationKind | null; label: string }> = [
  { kind: null, label: 'All' },
  { kind: 'bookmark', label: 'Bookmarks' },
  { kind: 'highlight', label: 'Highlights' },
  { kind: 'note', label: 'Notes' },
];
function parseReaderMarksKey(key: string): { bookId: number; chapterId: number } | null {
  const [bookIdRaw, chapterIdRaw] = key.split(':');
  const bookId = Number(bookIdRaw);
  const chapterId = Number(chapterIdRaw);
  if (!Number.isInteger(bookId) || !Number.isInteger(chapterId)) return null;
  return { bookId, chapterId };
}

function markChapterLabel(chapters: Chapter[], chapterId: number): { chapterNumber: number; chapterTitle: string } {
  const chapter = chapters.find((item) => item.id === chapterId);
  return {
    chapterNumber: chapter?.chapter_number ?? 0,
    chapterTitle: chapter?.title ?? 'Chương chưa rõ',
  };
}

export function buildReaderMarkPanelItems(
  marksStore: ReaderMarksStore,
  chapters: Chapter[],
  activeBookId: number | null,
): ReaderMarkPanelItem[] {
  const items: ReaderMarkPanelItem[] = [];
  for (const [key, marks] of Object.entries(marksStore)) {
    const ids = parseReaderMarksKey(key);
    if (!ids || (activeBookId !== null && ids.bookId !== activeBookId)) continue;
    const chapterLabel = markChapterLabel(chapters, ids.chapterId);

    if (marks.bookmarked) {
      items.push({
        annotationId: marks.bookmarkAnnotationId,
        bookId: ids.bookId,
        chapterId: ids.chapterId,
        chapterNumber: chapterLabel.chapterNumber,
        chapterTitle: chapterLabel.chapterTitle,
        clientId: marks.bookmarkAnnotationId ? undefined : `bookmark-${ids.bookId}-${ids.chapterId}`,
        id: `bookmark-${ids.bookId}-${ids.chapterId}`,
        kind: 'bookmark',
        paragraphIndex: 0,
        text: 'Đánh dấu chương',
      });
    }

    for (const highlight of marks.highlights) {
      items.push({
        annotationId: highlight.annotationId,
        bookId: highlight.bookId ?? ids.bookId,
        chapterId: highlight.chapterId ?? ids.chapterId,
        chapterNumber: highlight.chapterNumber ?? chapterLabel.chapterNumber,
        chapterTitle: highlight.chapterTitle ?? chapterLabel.chapterTitle,
        charEnd: highlight.charEnd,
        charStart: highlight.charStart,
        clientId: highlight.clientId ?? (highlight.annotationId ? undefined : highlight.id),
        color: highlight.color,
        id: `highlight-${highlight.annotationId ?? highlight.id}`,
        kind: 'highlight',
        paragraphIndex: highlight.paragraphIndex,
        text: highlight.text,
      });
    }

    for (const note of marks.notes) {
      items.push({
        annotationId: note.annotationId,
        bookId: note.bookId ?? ids.bookId,
        chapterId: note.chapterId ?? ids.chapterId,
        chapterNumber: note.chapterNumber ?? chapterLabel.chapterNumber,
        chapterTitle: note.chapterTitle ?? chapterLabel.chapterTitle,
        charEnd: note.charEnd,
        charStart: note.charStart,
        clientId: note.clientId ?? (note.annotationId ? undefined : note.id),
        color: note.color,
        id: `note-${note.annotationId ?? note.id}`,
        kind: 'note',
        note: note.note,
        paragraphIndex: note.paragraphIndex,
        text: note.text,
      });
    }
  }

  return items.sort((left, right) => {
    if (left.chapterNumber !== right.chapterNumber) return left.chapterNumber - right.chapterNumber;
    if (left.paragraphIndex !== right.paragraphIndex) return left.paragraphIndex - right.paragraphIndex;
    return left.id.localeCompare(right.id);
  });
}

function readerExportSlug(value: string): string {
  const slug = value
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/đ/g, 'd')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return slug || 'reader';
}

function readerMarkExportRows(
  items: ReaderMarkPanelItem[],
  kind: ReaderAnnotationKind | null,
): Array<Record<string, string | number | undefined>> {
  return items
    .filter((item) => !kind || item.kind === kind)
    .map((item) => ({
      annotation_id: item.annotationId,
      book_id: item.bookId,
      char_end: item.charEnd,
      char_start: item.charStart,
      chapter_id: item.chapterId,
      chapter_number: item.chapterNumber,
      chapter_title: item.chapterTitle,
      client_id: item.clientId ?? (item.annotationId ? undefined : item.id),
      color: item.color,
      kind: item.kind,
      note: item.note,
      paragraph_index: item.paragraphIndex,
      selected_text: item.text,
      text: item.text,
    }));
}

function emptyReaderMarkKindCounts(): Record<ReaderAnnotationKind, number> {
  return {
    bookmark: 0,
    highlight: 0,
    note: 0,
  };
}

function readerMarkKindCounts(rows: Array<Record<string, string | number | undefined>>): Record<ReaderAnnotationKind, number> {
  const counts = emptyReaderMarkKindCounts();
  for (const row of rows) {
    if (row.kind === 'bookmark' || row.kind === 'highlight' || row.kind === 'note') {
      counts[row.kind] += 1;
    }
  }
  return counts;
}

function readerMarkExportScope(kind: ReaderAnnotationKind | null): { kinds: ReaderAnnotationKind[]; label: string } {
  if (!kind) return { kinds: [], label: 'annotations' };
  if (kind === 'bookmark') return { kinds: [kind], label: 'bookmarks' };
  if (kind === 'highlight') return { kinds: [kind], label: 'highlights' };
  return { kinds: [kind], label: 'notes' };
}

function localReaderMarkChapterGroups(rows: Array<Record<string, string | number | undefined>>) {
  const groups = new Map<string, {
    annotation_count: number;
    annotation_ids: number[];
    chapter_id: number;
    chapter_number: number;
    chapter_title: string;
    client_ids: string[];
    kind_counts: Record<ReaderAnnotationKind, number>;
  }>();

  for (const row of rows) {
    const chapterId = Number(row.chapter_id ?? 0);
    const chapterNumber = Number(row.chapter_number ?? 0);
    const chapterTitle = String(row.chapter_title ?? '');
    const key = `${chapterNumber}:${chapterId}:${chapterTitle}`;
    const group = groups.get(key) ?? {
      annotation_count: 0,
      annotation_ids: [],
      chapter_id: chapterId,
      chapter_number: chapterNumber,
      chapter_title: chapterTitle,
      client_ids: [],
      kind_counts: emptyReaderMarkKindCounts(),
    };
    group.annotation_count += 1;
    if (row.kind === 'bookmark' || row.kind === 'highlight' || row.kind === 'note') {
      group.kind_counts[row.kind] += 1;
    }
    if (typeof row.annotation_id === 'number') group.annotation_ids.push(row.annotation_id);
    if (typeof row.client_id === 'string' && row.client_id.trim()) group.client_ids.push(row.client_id);
    groups.set(key, group);
  }

  return [...groups.values()].sort((left, right) => {
    if (left.chapter_number !== right.chapter_number) return left.chapter_number - right.chapter_number;
    return left.chapter_id - right.chapter_id;
  });
}

function localReaderMarksJson(
  rows: Array<Record<string, string | number | undefined>>,
  bookTitle: string,
  kind: ReaderAnnotationKind | null,
): string {
  const chapters = localReaderMarkChapterGroups(rows);
  const firstRow = rows[0];
  return JSON.stringify({
    format: 'novel_tnn_reader_annotations',
    version: 2,
    exported_at: new Date().toISOString(),
    scope: readerMarkExportScope(kind),
    book: {
      id: Number(firstRow?.book_id ?? 0),
      title: bookTitle,
      author: '',
    },
    annotation_count: rows.length,
    kind_counts: readerMarkKindCounts(rows),
    chapter_count: chapters.length,
    chapters,
    annotations: rows,
  }, null, 2);
}

function csvCell(value: string | number | undefined): string {
  const text = value === undefined ? '' : String(value);
  return `"${text.replace(/"/g, '""')}"`;
}

function localReaderMarksMarkdown(rows: Array<Record<string, string | number | undefined>>): string {
  if (rows.length === 0) return '# Reader Marks\n\n_Chưa có dấu đọc._\n';
  return [
    '# Reader Marks',
    '',
    ...rows.map((row) => [
      `## Ch. ${row.chapter_number ?? ''} · ${row.chapter_title ?? ''}`,
      '',
      `- Loại: ${row.kind}`,
      `- Đoạn: ${Number(row.paragraph_index ?? 0) + 1}`,
      row.client_id ? `- Client ID: ${row.client_id}` : '',
      row.annotation_id ? `- Annotation ID: ${row.annotation_id}` : '',
      row.char_start !== undefined || row.char_end !== undefined
        ? `- Range: ${row.char_start ?? ''}-${row.char_end ?? ''}`
        : '',
      row.text ? `- Nội dung: ${row.text}` : '',
      row.note ? `- Ghi chú: ${row.note}` : '',
    ].filter(Boolean).join('\n')),
    '',
  ].join('\n');
}

function localReaderMarksCsv(rows: Array<Record<string, string | number | undefined>>): string {
  const headers = [
    'kind',
    'chapter_number',
    'chapter_title',
    'paragraph_index',
    'char_start',
    'char_end',
    'selected_text',
    'text',
    'note',
    'color',
    'annotation_id',
    'client_id',
    'book_id',
    'chapter_id',
  ];
  return [
    headers.join(','),
    ...rows.map((row) => headers.map((header) => csvCell(row[header])).join(',')),
  ].join('\n');
}

export function localReaderMarksDownload(
  items: ReaderMarkPanelItem[],
  format: ReaderAnnotationExportFormat,
  bookTitle: string,
  kind: ReaderAnnotationKind | null,
): { blob: Blob; filename: string } {
  const rows = readerMarkExportRows(items, kind);
  const slug = readerExportSlug(bookTitle);
  const filename = `${slug}.reader-marks.${format}`;
  if (format === 'json') {
    return {
      blob: new Blob([localReaderMarksJson(rows, bookTitle, kind)], { type: 'application/json' }),
      filename,
    };
  }
  if (format === 'csv') {
    return {
      blob: new Blob([localReaderMarksCsv(rows)], { type: 'text/csv;charset=utf-8' }),
      filename,
    };
  }
  return {
    blob: new Blob([localReaderMarksMarkdown(rows)], { type: 'text/markdown;charset=utf-8' }),
    filename,
  };
}

function importNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? Math.max(0, Math.round(value)) : undefined;
}

function isReaderAnnotationKind(value: unknown): value is ReaderAnnotationKind {
  return value === 'bookmark' || value === 'highlight' || value === 'note';
}

export function readerAnnotationImportItemsFromPayload(payload: unknown): ReaderAnnotationImportItem[] {
  const source = Array.isArray(payload)
    ? payload
    : payload && typeof payload === 'object' && Array.isArray((payload as { annotations?: unknown }).annotations)
      ? (payload as { annotations: unknown[] }).annotations
      : [];

  return source.flatMap((entry) => {
    if (!entry || typeof entry !== 'object') return [];
    const raw = entry as Record<string, unknown>;
    if (!isReaderAnnotationKind(raw.kind)) return [];
    const item: ReaderAnnotationImportItem = { kind: raw.kind };
    const chapterId = importNumber(raw.chapter_id);
    const chapterNumber = importNumber(raw.chapter_number);
    const paragraphIndex = importNumber(raw.paragraph_index);
    const charStart = importNumber(raw.char_start);
    const charEnd = importNumber(raw.char_end);
    if (chapterId !== undefined) item.chapter_id = chapterId;
    if (chapterNumber !== undefined) item.chapter_number = chapterNumber;
    if (paragraphIndex !== undefined) item.paragraph_index = paragraphIndex;
    if (charStart !== undefined) item.char_start = charStart;
    if (charEnd !== undefined) item.char_end = charEnd;
    if (typeof raw.client_id === 'string') item.client_id = raw.client_id;
    if (typeof raw.selected_text === 'string') item.selected_text = raw.selected_text;
    if (typeof raw.text === 'string' && item.selected_text === undefined) item.selected_text = raw.text;
    if (typeof raw.note === 'string') item.note = raw.note;
    if (typeof raw.color === 'string') item.color = raw.color;
    return [item];
  });
}

