import { useEffect, useMemo, useState } from 'react';
import type { ApiClient } from '../../api/client';
import type { Chapter, ReaderSearchResult } from '../../api/types';
import type { ReaderChapterMarks } from '../../state/readerMarks';
import { searchCurrentChapter, type ReaderSearchOptions } from '../../state/readerSearch';

const DEFAULT_READER_SEARCH_SCOPES: NonNullable<ReaderSearchOptions['scopes']> = [
  'translation',
  'notes',
  'highlights',
];
export function useReaderSearch({ apiClient, activeBookId, selectedChapter, chapterMarks, progressTextBlocks }: {
  apiClient?: Pick<ApiClient, 'searchBook'>;
  activeBookId: number | null;
  selectedChapter: Chapter | null;
  chapterMarks: ReaderChapterMarks;
  progressTextBlocks: string[];
}) {
  const [readerSearchOpen, setReaderSearchOpen] = useState(false);
  const [readerSearchQuery, setReaderSearchQuery] = useState('');
  const [readerSearchOptions, setReaderSearchOptions] = useState<ReaderSearchOptions>({
    scopes: ['translation', 'notes', 'highlights'],
  });
  const [bookSearchResults, setBookSearchResults] = useState<ReaderSearchResult[]>([]);
  const [bookSearchLoading, setBookSearchLoading] = useState(false);
  const [bookSearchError, setBookSearchError] = useState('');
  const readerSearchScopes = readerSearchOptions.scopes ?? DEFAULT_READER_SEARCH_SCOPES;
  const searchScopesKey = readerSearchScopes.join(',');
  const currentSearchResults = useMemo(
    () => searchCurrentChapter({
      chapter: selectedChapter,
      marks: chapterMarks,
      options: readerSearchOptions,
      paragraphs: progressTextBlocks,
      query: readerSearchQuery,
    }),
    [chapterMarks, progressTextBlocks, readerSearchOptions, readerSearchQuery, selectedChapter],
  );
  useEffect(() => {
    const query = readerSearchQuery.trim();
    if (!readerSearchOpen || !apiClient || !activeBookId || !query) {
      setBookSearchResults([]);
      setBookSearchLoading(false);
      setBookSearchError('');
      return;
    }

    let cancelled = false;
    const controller = new AbortController();
    setBookSearchLoading(true);
    setBookSearchError('');
    const timeout = window.setTimeout(() => {
      void apiClient.searchBook(activeBookId, query, {
        caseSensitive: readerSearchOptions.caseSensitive,
        regex: readerSearchOptions.regex,
        scopes: readerSearchScopes,
        wholeWord: readerSearchOptions.wholeWord,
      }, { signal: controller.signal })
        .then((results) => {
          if (cancelled) return;
          setBookSearchResults(results);
          setBookSearchError('');
        })
        .catch((error: unknown) => {
          if (cancelled) return;
          setBookSearchResults([]);
          setBookSearchError(error instanceof Error ? error.message : 'Failed to search reader book');
        })
        .finally(() => {
          if (!cancelled) setBookSearchLoading(false);
        });
    }, 300);

    return () => {
      cancelled = true;
      controller.abort();
      window.clearTimeout(timeout);
    };
  }, [
    activeBookId,
    apiClient,
    readerSearchOpen,
    readerSearchOptions.caseSensitive,
    readerSearchOptions.regex,
    readerSearchOptions.wholeWord,
    readerSearchQuery,
    searchScopesKey,
  ]);

  return {
    readerSearchOpen, setReaderSearchOpen, readerSearchQuery, setReaderSearchQuery,
    readerSearchOptions, setReaderSearchOptions, bookSearchResults,
    bookSearchLoading, bookSearchError, currentSearchResults,
  };
}
