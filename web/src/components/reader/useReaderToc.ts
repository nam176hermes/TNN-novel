import { useMemo, useState } from 'react';
import type { Chapter } from '../../api/types';

export type ReaderTocOrder = 'asc' | 'desc';

export type UseReaderTocOptions = {
  chapters: Chapter[];
  currentChapterId: number | null;
};

function normalizeVietnameseQuery(value: string): string {
  return value
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .replace(/đ/gi, 'd')
    .toLowerCase();
}

function sortChapters(chapters: Chapter[]): Chapter[] {
  return [...chapters].sort((left, right) => {
    if (left.chapter_number !== right.chapter_number) return left.chapter_number - right.chapter_number;
    return left.id - right.id;
  });
}

export function useReaderToc({ chapters, currentChapterId }: UseReaderTocOptions) {
  const [order, setOrder] = useState<ReaderTocOrder>('asc');
  const [query, setQuery] = useState('');
  const translatedChapters = useMemo(
    () => sortChapters(chapters.filter((chapter) => chapter.has_translation)),
    [chapters],
  );
  const translatedChapterDatasetKey = useMemo(
    () => translatedChapters.map((chapter) => chapter.id).join(':'),
    [translatedChapters],
  );
  const normalizedQuery = normalizeVietnameseQuery(query.trim());
  const visibleChapters = useMemo(() => {
    const filtered = normalizedQuery
      ? translatedChapters.filter((chapter) => (
        String(chapter.chapter_number).includes(normalizedQuery)
        || normalizeVietnameseQuery(chapter.title).includes(normalizedQuery)
      ))
      : translatedChapters;
    return order === 'desc' ? [...filtered].reverse() : filtered;
  }, [normalizedQuery, order, translatedChapters]);

  return {
    currentChapterId,
    firstChapter: translatedChapters[0] ?? null,
    latestChapter: translatedChapters[translatedChapters.length - 1] ?? null,
    order,
    query,
    setOrder,
    setQuery,
    translatedChapterDatasetKey,
    translatedChapters,
    visibleChapters,
  };
}
