import { useState, type Dispatch, type SetStateAction } from 'react';
import type { Chapter, TranslatedBookSummary } from '../api/types';
import type { AppWorkflowOptions } from './appWorkflow';
import { removeCachedBookAsync, removeCachedChapterAsync } from './readerCache';
import type { useLibrary } from './useLibrary';
import type { useLibraryCatalog } from './useLibraryCatalog';
import type { useProviders } from './useProviders';
import type { useReaderChapterData } from './useReaderChapterData';

export type DeleteConfirmation = {
  kind: 'translation' | 'chapter' | 'book';
  bookId: number;
  chapterId?: number;
  title: string;
  message: string;
  confirmLabel: string;
};

export function useLibraryMutations({ session, setBackendError, setBackendSuccess, setBackendLoading, handleJobError,
  library, selectedChapter, workbenchChapterId, setWorkbenchChapterId, chapterText,
  providersState, translatedBooks, rawBacklogChapters, loadTranslatedBooks, loadRawBacklog }:
  Omit<AppWorkflowOptions, 'expireSession'> & ReturnType<typeof useLibraryCatalog> & {
    library: ReturnType<typeof useLibrary>;
    selectedChapter: Chapter | null;
    workbenchChapterId: number | null;
    setWorkbenchChapterId: Dispatch<SetStateAction<number | null>>;
    chapterText: ReturnType<typeof useReaderChapterData>['text'];
    providersState: ReturnType<typeof useProviders>;
  }) {
  const [deleteConfirmation, setDeleteConfirmation] = useState<DeleteConfirmation | null>(null);
  function requestDeleteTranslation(): void {
    if (!selectedChapter) return;
    setDeleteConfirmation({
      kind: 'translation',
      bookId: selectedChapter.book_id,
      chapterId: selectedChapter.id,
      title: 'Xóa bản dịch?',
      message: 'Bản gốc tiếng Trung sẽ được giữ lại. Bản dịch, audio, QA và job liên quan của chương này sẽ bị dọn.',
      confirmLabel: 'Xóa bản dịch',
    });
  }

  async function executeDeleteTranslation(target: DeleteConfirmation): Promise<void> {
    if (target.chapterId === undefined) return;
    setBackendError('');
    setBackendLoading(true);
    setDeleteConfirmation(null);
    try {
      await session.client.deleteChapterTranslation(target.bookId, target.chapterId);
      await removeCachedChapterAsync(target.bookId, target.chapterId);
      await library.refreshChapters(target.bookId);
      await chapterText.load({ book_id: target.bookId, id: target.chapterId });
      if (translatedBooks.state !== 'idle') {
        await loadTranslatedBooks();
      }
      if (rawBacklogChapters.state !== 'idle') {
        await loadRawBacklog();
      }
      await providersState.refresh();
    } catch (error) {
      handleJobError(error, 'Delete translation failed');
    } finally {
      setBackendLoading(false);
    }
  }

  function requestDeleteChapter(): void {
    if (!selectedChapter) return;
    setDeleteConfirmation({
      kind: 'chapter',
      bookId: selectedChapter.book_id,
      chapterId: selectedChapter.id,
      title: 'Xóa chương?',
      message: 'Bản gốc, bản dịch, audio, QA và job liên quan sẽ bị dọn. Chương được đánh dấu deleted mềm trước, chưa hard delete.',
      confirmLabel: 'Xóa chương',
    });
  }

  async function executeDeleteChapter(target: DeleteConfirmation): Promise<void> {
    if (target.chapterId === undefined) return;
    setBackendError('');
    setBackendLoading(true);
    setDeleteConfirmation(null);
    try {
      await session.client.deleteChapter(target.bookId, target.chapterId);
      await removeCachedChapterAsync(target.bookId, target.chapterId);
      const remainingChapters = await library.refreshChapters(target.bookId);
      if (workbenchChapterId === target.chapterId) {
        setWorkbenchChapterId(null);
      }
      library.setSelectedChapterId(remainingChapters[0]?.id ?? null);
      await library.refreshBooks();
      if (translatedBooks.state !== 'idle') {
        await loadTranslatedBooks();
      }
      if (rawBacklogChapters.state !== 'idle') {
        await loadRawBacklog();
      }
    } catch (error) {
      handleJobError(error, 'Delete chapter failed');
    } finally {
      setBackendLoading(false);
    }
  }

  function requestDeleteBook(book: TranslatedBookSummary): void {
    setBackendError('');
    setBackendSuccess('');
    setDeleteConfirmation({
      kind: 'book',
      bookId: book.id,
      title: 'Xóa sách?',
      message: `Toàn bộ chương, bản dịch, audio, QA và dữ liệu liên quan của “${book.title}” sẽ bị xóa khỏi thư viện.`,
      confirmLabel: 'Xóa sách',
    });
  }

  async function executeDeleteBook(target: DeleteConfirmation): Promise<void> {
    setBackendError('');
    setBackendSuccess('');
    setBackendLoading(true);
    setDeleteConfirmation(null);
    try {
      await session.client.deleteBook(target.bookId);
      await removeCachedBookAsync(target.bookId);
      await library.refreshBooks();
      if (library.selectedBookId === target.bookId) {
        library.setSelectedBookId(null);
        library.setSelectedChapterId(null);
      }
      setWorkbenchChapterId((current) => {
        if (current === null) return current;
        return library.chapters.data.some((chapter) => chapter.book_id === target.bookId && chapter.id === current)
          ? null
          : current;
      });
      if (translatedBooks.state !== 'idle') {
        await loadTranslatedBooks();
      }
      setBackendSuccess('Đã xóa sách khỏi thư viện.');
    } catch (error) {
      handleJobError(error, 'Delete book failed');
    } finally {
      setBackendLoading(false);
    }
  }

  async function handleUpdateBookCover(book: TranslatedBookSummary, cover: File): Promise<void> {
    setBackendError('');
    setBackendSuccess('');
    setBackendLoading(true);
    try {
      await session.client.updateBookCover(book.id, cover);
      await library.refreshBooks();
      if (translatedBooks.state !== 'idle') {
        await loadTranslatedBooks();
      }
      setBackendSuccess('Đã cập nhật bìa sách.');
    } catch (error) {
      handleJobError(error, 'Update book cover failed');
    } finally {
      setBackendLoading(false);
    }
  }

  function handleConfirmDelete(): void {
    if (!deleteConfirmation) return;
    if (deleteConfirmation.kind === 'translation') {
      void executeDeleteTranslation(deleteConfirmation);
      return;
    }
    if (deleteConfirmation.kind === 'book') {
      void executeDeleteBook(deleteConfirmation);
      return;
    }
    void executeDeleteChapter(deleteConfirmation);
  }

  return {
    deleteConfirmation, requestDeleteTranslation, requestDeleteChapter, requestDeleteBook,
    handleUpdateBookCover, handleConfirmDelete,
    dismissDeleteConfirmation: () => setDeleteConfirmation(null),
  };
}
