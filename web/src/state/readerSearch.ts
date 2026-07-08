import type { Chapter, ReaderSearchResult, ReaderSearchScope, ReaderSearchSource } from '../api/types';
import type { ReaderChapterMarks } from './readerMarks';

export type ReaderSearchOptions = {
  caseSensitive?: boolean;
  regex?: boolean;
  scopes?: ReaderSearchScope[];
  wholeWord?: boolean;
};

export type SearchCurrentChapterInput = {
  chapter: Chapter | null;
  marks: ReaderChapterMarks;
  options?: ReaderSearchOptions;
  paragraphs: string[];
  query: string;
};

const defaultScopes: ReaderSearchScope[] = ['translation', 'notes', 'highlights'];

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function activeScopes(options: ReaderSearchOptions = {}): Set<ReaderSearchScope> {
  return new Set(options.scopes && options.scopes.length > 0 ? options.scopes : defaultScopes);
}

export function createReaderSearchMatcher(
  query: string,
  options: ReaderSearchOptions = {},
): RegExp | null {
  const trimmed = query.trim();
  if (!trimmed) return null;

  const pattern = options.regex ? trimmed : escapeRegExp(trimmed);
  const boundedPattern = options.wholeWord
    ? `(?<![\\p{L}\\p{N}_])${pattern}(?![\\p{L}\\p{N}_])`
    : pattern;
  const flags = `u${options.caseSensitive ? '' : 'i'}`;

  try {
    return new RegExp(boundedPattern, flags);
  } catch {
    return null;
  }
}

function snippetFor(text: string, index: number, matchLength: number): string {
  const start = Math.max(0, index - 42);
  const end = Math.min(text.length, index + Math.max(matchLength, 1) + 42);
  const prefix = start > 0 ? '...' : '';
  const suffix = end < text.length ? '...' : '';
  return `${prefix}${text.slice(start, end)}${suffix}`;
}

function resultForMatch(
  chapter: Chapter,
  source: ReaderSearchSource,
  paragraphIndex: number,
  text: string,
  matcher: RegExp,
  rangeForMatch?: (match: RegExpExecArray) => { char_end: number; char_start: number },
): ReaderSearchResult | null {
  const match = matcher.exec(text);
  matcher.lastIndex = 0;
  if (!match || match.index === undefined) return null;

  const matchLength = match[0]?.length ?? 0;
  const range = rangeForMatch?.(match) ?? {
    char_end: match.index + matchLength,
    char_start: match.index,
  };
  const sourceScore = source === 'translation' ? 100 : source === 'highlight' ? 90 : 85;
  return {
    chapter_id: chapter.id,
    chapter_number: chapter.chapter_number,
    chapter_title: chapter.title,
    char_end: range.char_end,
    char_start: range.char_start,
    paragraph_index: paragraphIndex,
    score: Math.max(1, sourceScore - paragraphIndex),
    snippet: snippetFor(text, match.index, matchLength),
    source,
  };
}

export function searchTextParagraphs(
  paragraphs: string[],
  chapter: Chapter | null,
  query: string,
  options: ReaderSearchOptions = {},
): ReaderSearchResult[] {
  if (!chapter || !activeScopes(options).has('translation')) return [];
  const matcher = createReaderSearchMatcher(query, options);
  if (!matcher) return [];

  return paragraphs
    .map((paragraph, index) => resultForMatch(chapter, 'translation', index, paragraph, matcher))
    .filter((result): result is ReaderSearchResult => Boolean(result));
}

export function searchReaderMarks(
  marks: ReaderChapterMarks,
  chapter: Chapter | null,
  query: string,
  options: ReaderSearchOptions = {},
): ReaderSearchResult[] {
  if (!chapter) return [];
  const matcher = createReaderSearchMatcher(query, options);
  if (!matcher) return [];
  const scopes = activeScopes(options);
  const results: ReaderSearchResult[] = [];

  if (scopes.has('highlights')) {
    for (const highlight of marks.highlights) {
      const base = highlight.charStart ?? 0;
      const result = resultForMatch(
        chapter,
        'highlight',
        highlight.paragraphIndex,
        highlight.text,
        matcher,
        (match) => ({
          char_end: base + match.index + (match[0]?.length ?? 0),
          char_start: base + match.index,
        }),
      );
      if (result) results.push(result);
    }
  }

  if (scopes.has('notes')) {
    for (const note of marks.notes) {
      const noteText = [note.note, note.text].filter(Boolean).join('\n');
      const noteLength = note.note.length;
      const selectedTextOffset = note.note && note.text ? noteLength + 1 : note.note ? noteLength : 0;
      const base = note.charStart ?? 0;
      const fallbackEnd = note.charEnd ?? base + note.text.length;
      const result = resultForMatch(
        chapter,
        'note',
        note.paragraphIndex,
        noteText,
        matcher,
        (match) => {
          if (note.note && match.index < noteLength) {
            return { char_end: fallbackEnd, char_start: base };
          }
          const selectedOffset = Math.max(0, match.index - selectedTextOffset);
          return {
            char_end: base + selectedOffset + (match[0]?.length ?? 0),
            char_start: base + selectedOffset,
          };
        },
      );
      if (result) results.push(result);
    }
  }

  return results;
}

export function searchCurrentChapter({
  chapter,
  marks,
  options = {},
  paragraphs,
  query,
}: SearchCurrentChapterInput): ReaderSearchResult[] {
  return [
    ...searchTextParagraphs(paragraphs, chapter, query, options),
    ...searchReaderMarks(marks, chapter, query, options),
  ].sort((left, right) => {
    if (left.chapter_number !== right.chapter_number) return left.chapter_number - right.chapter_number;
    if (left.paragraph_index !== right.paragraph_index) return left.paragraph_index - right.paragraph_index;
    return right.score - left.score;
  });
}
