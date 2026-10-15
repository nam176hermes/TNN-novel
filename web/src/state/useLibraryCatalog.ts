import { useCallback, useEffect, useRef, useState } from 'react';
import type { Chapter, RawBacklogPage, TranslatedBookSummary } from '../api/types';
import type { WorkflowView } from '../components/WorkflowShell';
import { isAuthError, type AppWorkflowOptions } from './appWorkflow';
import { mapChapter } from './translator';
import { formatError, type AsyncState } from './types';
import type { useLibrary } from './useLibrary';

const emptyTranslatedBooks: AsyncState<TranslatedBookSummary[]> = { data: [], error: '', state: 'idle' };
const emptyRawBacklogChapters: AsyncState<Chapter[]> = { data: [], error: '', state: 'idle' };
const emptyRawInfo: Omit<RawBacklogPage, 'chapters'> = {
  total_chapters: 0, total_books: 0, book_counts: {}, offset: 0, limit: 50,
};
export function useLibraryCatalog({ session, expireSession, activeView }:
  Pick<AppWorkflowOptions, 'session' | 'expireSession'> & {
    activeView: WorkflowView;
    library: ReturnType<typeof useLibrary>;
  }) {
  const [translatedBooks, setTranslatedBooks] = useState<AsyncState<TranslatedBookSummary[]>>(emptyTranslatedBooks);
  const [rawBacklogChapters, setRawBacklogChapters] =
    useState<AsyncState<Chapter[]>>(emptyRawBacklogChapters);
  const [rawBacklogInfo, setRawBacklogInfo] = useState(emptyRawInfo);
  const [rawPage, setRawPage] = useState(0);
  const rawRequest = useRef<AbortController | null>(null);
  useEffect(() => () => rawRequest.current?.abort(), [session.client, session.isAuthenticated]);
  const loadTranslatedBooks = useCallback(async (): Promise<TranslatedBookSummary[]> => {
    if (!session.isAuthenticated) {
      setTranslatedBooks(emptyTranslatedBooks);
      return [];
    }

    setTranslatedBooks((current) => ({ ...current, error: '', state: 'loading' }));
    try {
      const nextBooks = await session.client.getTranslatedBooks();
      setTranslatedBooks({ data: nextBooks, error: '', state: nextBooks.length > 0 ? 'ready' : 'empty' });
      return nextBooks;
    } catch (error) {
      if (isAuthError(error)) {
        expireSession();
      }
      const message = formatError(error);
      setTranslatedBooks((current) => ({ data: current.data, error: message, state: 'error' }));
      throw error;
    }
  }, [expireSession, session.client, session.isAuthenticated]);

  const loadRawBacklog = useCallback(async (): Promise<Chapter[]> => {
    rawRequest.current?.abort();
    const controller = new AbortController();
    rawRequest.current = controller;
    if (!session.isAuthenticated) {
      setRawBacklogChapters(emptyRawBacklogChapters);
      setRawBacklogInfo(emptyRawInfo);
      return [];
    }
    setRawBacklogChapters((current) => ({ ...current, error: '', state: 'loading' }));
    try {
      const { chapters, ...info } = await session.client.getRawBacklog(rawPage * 50, 50, { signal: controller.signal });
      if (controller.signal.aborted) return [];
      if (rawPage > 0 && info.offset >= info.total_chapters) {
        setRawPage(Math.max(0, Math.ceil(info.total_chapters / 50) - 1));
        return [];
      }
      const nextChapters = chapters.map((chapter) => mapChapter(chapter, chapter.book_title || `Book ${chapter.book_id}`));
      setRawBacklogInfo(info);
      setRawBacklogChapters({
        data: nextChapters,
        error: '',
        state: info.total_chapters > 0 ? 'ready' : 'empty',
      });
      return nextChapters;
    } catch (error) {
      if (controller.signal.aborted) return [];
      if (isAuthError(error)) {
        expireSession();
      }
      const message = formatError(error);
      setRawBacklogChapters((current) => ({ data: current.data, error: message, state: 'error' }));
      throw error;
    }
  }, [
    expireSession,
    rawPage,
    session.client,
    session.isAuthenticated,
  ]);

  useEffect(() => {
    if (!session.isAuthenticated) {
      setTranslatedBooks(emptyTranslatedBooks);
      setRawBacklogChapters(emptyRawBacklogChapters);
      setRawBacklogInfo(emptyRawInfo);
      setRawPage(0);
      return;
    }

    if ((activeView === 'workbench' || activeView === 'library' || activeView === 'reader') && translatedBooks.state === 'idle') {
      void loadTranslatedBooks().catch(() => {});
    }
  }, [activeView, loadTranslatedBooks, session.isAuthenticated, translatedBooks.state]);

  useEffect(() => {
    if (activeView !== 'raw') return;
    void loadRawBacklog().catch(() => {});
    return () => rawRequest.current?.abort();
  }, [activeView, loadRawBacklog]);

  return { translatedBooks, rawBacklogChapters, rawBacklogInfo, rawPage, setRawPage, loadTranslatedBooks, loadRawBacklog };
}
