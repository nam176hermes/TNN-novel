import type { Book, BookSummary, Chapter, ChapterApi, Provider } from '../api/types';

const FALLBACK_PROVIDER_ID = 'gemini';
const SOURCE_READY_LABEL = 'Có bản nguồn đã làm sạch';
const TRANSLATED_CHAPTER_STATUSES = new Set(['translated', 'qa_low', 'audio_done']);

export function isEnabled(value: boolean | number): boolean {
  return value === true || value === 1;
}

export function chapterStats(
  chapterRows: ChapterApi[],
): Pick<BookSummary, 'audio' | 'failed' | 'qa_low' | 'total' | 'translated'> {
  return {
    audio: chapterRows.filter((chapter) => Boolean(chapter.audio_path)).length,
    failed: chapterRows.filter((chapter) => chapter.status === 'failed').length,
    qa_low: chapterRows.filter((chapter) => chapter.status === 'qa_low').length,
    total: chapterRows.length,
    translated: chapterRows.filter((chapter) => chapterHasTranslation(chapter)).length,
  };
}

export function chapterHasTranslation(chapter: ChapterApi): boolean {
  return Boolean(chapter.translated_text_path) || TRANSLATED_CHAPTER_STATUSES.has(chapter.status);
}

export function nextAction(stats: Pick<BookSummary, 'audio' | 'failed' | 'total' | 'translated'>): string {
  if (stats.failed > 0) return 'Retry failed chapters';
  if (stats.translated < stats.total) return 'Translate queued chapters';
  if (stats.audio < stats.translated) return 'Generate audio';
  return 'Review library';
}

export function mapBookSummary(book: Book, chapterRows: ChapterApi[] = []): BookSummary {
  const stats = chapterStats(chapterRows);

  return {
    id: book.id,
    title: book.title,
    ...stats,
    last_activity: book.author ? `Author: ${book.author}` : 'Loaded from backend',
    next_action: nextAction(stats),
  };
}

export function mergeChapterSummary(book: BookSummary, chapterRows: ChapterApi[]): BookSummary {
  const stats = chapterStats(chapterRows);

  return {
    ...book,
    ...stats,
    last_activity: `${chapterRows.length} chapters loaded`,
    next_action: nextAction(stats),
  };
}

export function qaVerdict(status: string): string | undefined {
  if (status === 'qa_low') return 'Cần xem lại';
  if (status === 'translated' || status === 'audio_done') return 'Đã dịch';
  return undefined;
}

export function mapChapter(chapter: ChapterApi, bookTitle: string): Chapter {
  return {
    id: chapter.id,
    book_id: chapter.book_id,
    book_title: bookTitle,
    chapter_number: chapter.chapter_number,
    title: chapter.title,
    status: chapter.status,
    qa_verdict: qaVerdict(chapter.status),
    audio_path: chapter.audio_path ?? '',
    has_translation: chapterHasTranslation(chapter),
    source_preview: chapter.cleaned_text_path ? SOURCE_READY_LABEL : undefined,
    latest_job_status: chapter.status.replace(/_/g, ' '),
    last_action: chapter.translated_at ? 'Đã dịch từ backend' : 'Đã tải từ backend',
  };
}

export function defaultProviderId(providers: Provider[]): string {
  return providers.find((provider) => isEnabled(provider.enabled))?.id ?? providers[0]?.id ?? FALLBACK_PROVIDER_ID;
}

export function estimateSourceChars(chapters: Chapter[]): number {
  const previewChars = chapters.reduce(
    (total, chapter) =>
      total +
      (chapter.source_preview && chapter.source_preview !== SOURCE_READY_LABEL ? chapter.source_preview.length : 0) +
      (chapter.translation_preview?.length ?? 0),
    0,
  );

  return previewChars;
}

export function hasUnsavedTranslationChange(savedText: string | null, editorText: string): boolean {
  return (savedText === null ? '' : savedText) !== editorText;
}
