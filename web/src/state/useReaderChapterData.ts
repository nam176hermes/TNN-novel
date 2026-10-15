import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ApiClient } from '../api/client';
import type { Chapter, ReaderStateResponse } from '../api/types';
import {
  useChapterText,
  type ChapterTextPrefetchTarget,
  type UseChapterTextOptions,
} from './useChapterText';
import { useQa } from './useQa';

export function readerChapterKey(chapter: Pick<Chapter, 'book_id' | 'id'> | null): string {
  return chapter ? `${chapter.book_id}:${chapter.id}` : '';
}

export type ReaderBootstrap = {bookId: number; request: Promise<ReaderStateResponse>};

export function useReaderBootstrap(client: ApiClient, enabled: boolean) {
  const currentRef = useRef<ReaderBootstrap | null>(null);
  const [current, setCurrent] = useState<ReaderBootstrap | null>(null);
  useEffect(() => { currentRef.current = null; setCurrent(null); }, [client, enabled]);
  const load = useCallback((bookId: number) => {
    if (currentRef.current?.bookId === bookId) return currentRef.current.request;
    const request = client.getReaderState(bookId);
    const entry = {bookId, request};
    currentRef.current = entry;
    setCurrent(entry);
    void request.catch(() => {
      if (currentRef.current === entry) currentRef.current = null;
    });
    return request;
  }, [client]);
  return {current, load};
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
