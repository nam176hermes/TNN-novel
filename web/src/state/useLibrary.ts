import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ApiError, type ApiClient } from '../api/client';
import type { Book, BookSummary, Chapter } from '../api/types';
import { mapBookSummary, mapChapter, mergeChapterSummary } from './translator';
import { formatError, type AsyncState } from './types';

const emptyBooks: AsyncState<BookSummary[]> = { data: [], error: '', state: 'idle' };
const emptyChapters: AsyncState<Chapter[]> = { data: [], error: '', state: 'idle' };

export function useLibrary(client: ApiClient, enabled: boolean, onAuthError?: () => void) {
  const [books, setBooks] = useState<AsyncState<BookSummary[]>>(emptyBooks);
  const [chapters, setChapters] = useState<AsyncState<Chapter[]>>(emptyChapters);
  const [selectedBookId, setSelectedBookId] = useState<number | null>(null);
  const [selectedChapterId, setSelectedChapterId] = useState<number | null>(null);
  const booksRef = useRef<BookSummary[]>([]);
  const booksRequestIdRef = useRef(0);
  const chaptersRequestIdRef = useRef(0);

  useEffect(() => {
    booksRef.current = books.data;
  }, [books.data]);

  const reset = useCallback(() => {
    booksRequestIdRef.current += 1;
    chaptersRequestIdRef.current += 1;
    setBooks(emptyBooks);
    setChapters(emptyChapters);
    setSelectedBookId(null);
    setSelectedChapterId(null);
  }, []);

  const refreshBooks = useCallback(async () => {
    if (!enabled) {
      reset();
      return [];
    }

    const requestId = booksRequestIdRef.current + 1;
    booksRequestIdRef.current = requestId;
    setBooks((current) => ({ ...current, error: '', state: 'loading' }));

    try {
      const liveBooks = await client.getBooks();
      const mappedBooks = liveBooks.map((book) => mapBookSummary(book));
      if (requestId !== booksRequestIdRef.current) return mappedBooks;

      if (mappedBooks.length === 0) {
        chaptersRequestIdRef.current += 1;
        setBooks({ data: [], error: '', state: 'empty' });
        setChapters({ data: [], error: '', state: 'idle' });
        setSelectedBookId(null);
        setSelectedChapterId(null);
        return [];
      }

      setBooks((current) => {
        const summariesById = new Map(current.data.map((book) => [book.id, book]));
        return {
          data: mappedBooks.map((book) => summariesById.get(book.id) ?? book),
          error: '',
          state: 'ready',
        };
      });
      setSelectedBookId((current) => {
        if (current !== null && mappedBooks.some((book) => book.id === current)) return current;
        return mappedBooks[0]?.id ?? null;
      });

      return mappedBooks;
    } catch (error) {
      if (requestId !== booksRequestIdRef.current) throw error;
      if (error instanceof ApiError && error.status === 401) {
        onAuthError?.();
      }
      const message = formatError(error);
      setBooks((current) => ({ data: current.data, error: message, state: 'error' }));
      throw error;
    }
  }, [client, enabled, onAuthError, reset]);

  const refreshChapters = useCallback(
    async (bookId = selectedBookId) => {
      if (!enabled || bookId === null) {
        chaptersRequestIdRef.current += 1;
        setChapters({ data: [], error: '', state: 'idle' });
        setSelectedChapterId(null);
        return [];
      }

      const requestId = chaptersRequestIdRef.current + 1;
      chaptersRequestIdRef.current = requestId;
      setChapters((current) => ({ data: current.data, error: '', state: 'loading' }));

      try {
        const liveChapters = await client.getChapters(bookId);
        if (requestId !== chaptersRequestIdRef.current) return liveChapters.map((chapter) => mapChapter(chapter, ''));
        const bookTitle = booksRef.current.find((book) => book.id === bookId)?.title ?? '';
        const mappedChapters = liveChapters.map((chapter) => mapChapter(chapter, bookTitle));

        setChapters({
          data: mappedChapters,
          error: '',
          state: mappedChapters.length > 0 ? 'ready' : 'empty',
        });
        setBooks((current) => ({
          ...current,
          data: current.data.map((book) => (book.id === bookId ? mergeChapterSummary(book, liveChapters) : book)),
        }));
        setSelectedChapterId((current) => {
          if (current !== null && mappedChapters.some((chapter) => chapter.id === current)) return current;
          return mappedChapters[0]?.id ?? null;
        });

        return mappedChapters;
      } catch (error) {
        if (requestId !== chaptersRequestIdRef.current) throw error;
        if (error instanceof ApiError && error.status === 401) {
          onAuthError?.();
        }
        const message = formatError(error);
        setChapters((current) => ({ data: current.data, error: message, state: 'error' }));
        throw error;
      }
    },
    [client, enabled, onAuthError, selectedBookId],
  );

  const renameBook = useCallback(
    async (bookId: number, title: string): Promise<Book> => {
      const normalizedTitle = title.trim();
      if (!normalizedTitle) {
        throw new Error('Book title is required');
      }

      try {
        const updatedBook = await client.updateBook(bookId, { title: normalizedTitle });
        if (updatedBook.id !== bookId) {
          const refreshedBooks = await refreshBooks();
          if (refreshedBooks.some((book) => book.id === updatedBook.id)) {
            setSelectedBookId(updatedBook.id);
            await refreshChapters(updatedBook.id);
          }
          return updatedBook;
        }

        setBooks((current) => ({
          ...current,
          data: current.data.map((book) =>
            book.id === bookId
              ? {
                  ...book,
                  title: updatedBook.title,
                  last_activity: updatedBook.author ? `Author: ${updatedBook.author}` : book.last_activity,
                }
              : book,
          ),
        }));
        setChapters((current) => ({
          ...current,
          data: current.data.map((chapter) =>
            chapter.book_id === bookId ? { ...chapter, book_title: updatedBook.title } : chapter,
          ),
        }));

        return updatedBook;
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          onAuthError?.();
        }
        const message = formatError(error);
        setBooks((current) => ({ ...current, error: message, state: 'error' }));
        throw error;
      }
    },
    [client, onAuthError, refreshBooks, refreshChapters],
  );

  useEffect(() => {
    if (!enabled) {
      reset();
      return;
    }

    void refreshBooks().catch(() => {});
  }, [enabled, refreshBooks, reset]);

  useEffect(() => {
    if (!enabled) {
      setChapters(emptyChapters);
      setSelectedChapterId(null);
      return;
    }

    if (selectedBookId === null) {
      setChapters({ data: [], error: '', state: books.state === 'empty' ? 'empty' : 'idle' });
      setSelectedChapterId(null);
      return;
    }

    void refreshChapters(selectedBookId).catch(() => {});
  }, [books.state, enabled, refreshChapters, selectedBookId]);

  const activeChapters = useMemo(
    () => chapters.data.filter((chapter) => chapter.book_id === selectedBookId),
    [chapters.data, selectedBookId],
  );
  const selectedChapter =
    selectedChapterId === null ? null : (activeChapters.find((chapter) => chapter.id === selectedChapterId) ?? null);
  const handleSetSelectedBookId = useCallback((bookId: number | null) => {
    chaptersRequestIdRef.current += 1;
    setSelectedBookId(bookId);
  }, []);

  return {
    activeChapters,
    books,
    chapters,
    refreshBooks,
    refreshChapters,
    renameBook,
    selectedBookId,
    selectedChapter,
    selectedChapterId,
    setSelectedBookId: handleSetSelectedBookId,
    setSelectedChapterId,
  };
}
