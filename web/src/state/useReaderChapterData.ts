import { useMemo } from 'react';
import type { ApiClient } from '../api/client';
import type { Chapter } from '../api/types';
import {
  useChapterText,
  type ChapterTextPrefetchTarget,
  type UseChapterTextOptions,
} from './useChapterText';
import { useQa } from './useQa';

export function readerChapterKey(chapter: Pick<Chapter, 'book_id' | 'id'> | null): string {
  return chapter ? `${chapter.book_id}:${chapter.id}` : '';
}

export function useReaderChapterData(
  client: ApiClient,
  enabled: boolean,
  chapter: Chapter | null,
  onAuthError?: () => void,
  prefetchTargets: ChapterTextPrefetchTarget[] = [],
  textOptions: UseChapterTextOptions = {},
) {
  const chapterKey = useMemo(() => readerChapterKey(chapter), [chapter?.book_id, chapter?.id]);
  const text = useChapterText(client, enabled, chapter, onAuthError, prefetchTargets, textOptions);
  const qa = useQa(client, enabled, chapter, onAuthError);

  return { chapterKey, qa, text };
}
