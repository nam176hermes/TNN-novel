import { useState } from 'react';
import type { ApiClient } from '../../api/client';
import type { Chapter, ReaderAnnotationExportFormat, ReaderAnnotationKind } from '../../api/types';
import {
  chapterMarksKey, createEmptyChapterMarks, loadReaderMarks, mergeLocalAndRemoteMarks,
  sanitizeChapterMarks,
  saveReaderMarks,
  type ReaderChapterMarks, type ReaderDeletedAnnotation, type ReaderHighlight
} from '../../state/readerMarks';
import type { ReaderBootstrap } from '../../state/useReaderChapterData';
import {
  buildReaderMarkPanelItems, localReaderMarksDownload, readerAnnotationExportScopes,
  readerAnnotationImportItemsFromPayload
} from './readerAnnotationTransfer';
import type { ReaderSelectionState } from './types';
import { useReaderSync } from './useReaderSync';

function getReaderMarksKey(bookId: number | null, chapterId: number | null): string | null {
  if (!bookId || !chapterId) return null;
  return chapterMarksKey(bookId, chapterId);
}

function readerHighlightRangeId(paragraphIndex: number, charStart: number, charEnd: number): string {
  return `highlight-${paragraphIndex}-${charStart}-${charEnd}`;
}

function upsertDeletedReaderAnnotation(
  deletedAnnotations: ReaderDeletedAnnotation[],
  deleted: ReaderDeletedAnnotation,
): ReaderDeletedAnnotation[] {
  return [
    ...deletedAnnotations.filter((item) => {
      if (deleted.annotationId && item.annotationId === deleted.annotationId) return false;
      if (deleted.clientId && item.clientId === deleted.clientId) return false;
      return true;
    }),
    deleted,
  ];
}

function readerHighlightRangeEnd(highlight: ReaderHighlight): number {
  return Number.isInteger(highlight.charEnd) ? highlight.charEnd ?? 0 : highlight.text.length;
}

function sameReaderHighlightRange(
  highlight: ReaderHighlight,
  paragraphIndex: number,
  charStart: number,
  charEnd: number,
): boolean {
  return highlight.paragraphIndex === paragraphIndex
    && (highlight.charStart ?? 0) === charStart
    && readerHighlightRangeEnd(highlight) === charEnd;
}

export function useReaderMarks({ apiClient, activeBookId, selectedChapterId, selectedChapter,
  chapters, bookTitle, readerBootstrap, onSelectChapter, onDownload }: {
  apiClient?: Pick<ApiClient, 'getReaderState' | 'syncReaderState' | 'createReaderAnnotation' | 'updateReaderAnnotation'
    | 'deleteReaderAnnotation' | 'downloadReaderAnnotations' | 'importReaderAnnotations'>;
  activeBookId: number | null;
  selectedChapterId: number | null;
  selectedChapter: Chapter | null;
  chapters: Chapter[];
  bookTitle: string;
  readerBootstrap?: ReaderBootstrap | null;
  onSelectChapter(chapterId: number): void;
  onDownload(blob: Blob, filename: string): void;
}) {
  const sync = useReaderSync({ apiClient, activeBookId, readerBootstrap, onSelectChapter });
  const { marksStore, setMarksStore, setMarksError, mergeRemoteAnnotation, handleMarksSyncError } = sync;
  const [noteDraft, setNoteDraft] = useState<{
    charEnd: number;
    charStart: number;
    paragraphIndex: number;
    text: string;
    value: string;
  } | null>(null);
  const [annotationExportStatus, setAnnotationExportStatus] = useState('');
  const [annotationImportLoading, setAnnotationImportLoading] = useState(false);
  const [annotationExportKind, setAnnotationExportKind] = useState<ReaderAnnotationKind | null>(null);

  const activeMarksKey = getReaderMarksKey(activeBookId, selectedChapterId);
  const chapterMarks = activeMarksKey ? marksStore[activeMarksKey] ?? createEmptyChapterMarks() : createEmptyChapterMarks();
  const bookmarked = chapterMarks.bookmarked;
  const highlightedParagraphs = new Set(chapterMarks.highlights.map((highlight) => highlight.paragraphIndex));
  const notesByParagraph = new Map(chapterMarks.notes.map((note) => [note.paragraphIndex, note]));
  const markPanelItems = buildReaderMarkPanelItems(marksStore, chapters, activeBookId);
  const activeChapterTitle = selectedChapter
    ? `Chương ${selectedChapter.chapter_number} · ${selectedChapter.title}`
    : 'Chưa chọn chương';

  function updateChapterMarks(updater: (current: ReaderChapterMarks) => ReaderChapterMarks): void {
    if (!activeMarksKey) return;
    setMarksStore((currentStore) => {
      const currentMarks = currentStore[activeMarksKey] ?? createEmptyChapterMarks();
      const nextMarks = sanitizeChapterMarks(updater(currentMarks));
      const nextStore = {
        ...currentStore,
        [activeMarksKey]: nextMarks,
      };
      saveReaderMarks(nextStore);
      return nextStore;
    });
  }

  function saveSelectionHighlight(selection: ReaderSelectionState): void {
    const existingHighlight = chapterMarks.highlights.find((highlight) => (
      sameReaderHighlightRange(
        highlight,
        selection.paragraphIndex,
        selection.charStart,
        selection.charEnd,
      )
    ));
    const updatedAt = new Date().toISOString();
    updateChapterMarks((current) => ({
      ...current,
      highlights: [
        ...current.highlights.filter((highlight) => !sameReaderHighlightRange(
          highlight,
          selection.paragraphIndex,
          selection.charStart,
          selection.charEnd,
        )),
        {
          annotationId: existingHighlight?.annotationId,
          bookId: activeBookId ?? undefined,
          charEnd: selection.charEnd,
          charStart: selection.charStart,
          chapterId: selectedChapterId ?? undefined,
          chapterNumber: selectedChapter?.chapter_number,
          chapterTitle: selectedChapter?.title,
          clientId: existingHighlight?.clientId,
          createdAt: existingHighlight?.createdAt,
          id: existingHighlight?.id ?? readerHighlightRangeId(
            selection.paragraphIndex,
            selection.charStart,
            selection.charEnd,
          ),
          paragraphIndex: selection.paragraphIndex,
          syncPending: Boolean(existingHighlight?.annotationId),
          text: selection.text,
          updatedAt: existingHighlight?.annotationId ? updatedAt : existingHighlight?.updatedAt,
        },
      ],
    }));

    if (!apiClient || !activeBookId || !selectedChapterId) return;
    const payload = {
      char_end: selection.charEnd,
      char_start: selection.charStart,
      kind: 'highlight' as const,
      paragraph_index: selection.paragraphIndex,
      selected_text: selection.text,
    };
    if (existingHighlight?.annotationId) {
      void apiClient.updateReaderAnnotation(activeBookId, existingHighlight.annotationId, payload)
        .then(mergeRemoteAnnotation)
        .catch(handleMarksSyncError);
      return;
    }
    void apiClient.createReaderAnnotation(activeBookId, selectedChapterId, payload)
      .then(mergeRemoteAnnotation)
      .catch(handleMarksSyncError);
  }

  function toggleBookmark(): void {
    const wasBookmarked = bookmarked;
    const annotationId = chapterMarks.bookmarkAnnotationId;
    const deletedAt = new Date().toISOString();
    updateChapterMarks((current) => ({
      ...current,
      bookmarked: !current.bookmarked,
      bookmarkAnnotationId: current.bookmarked ? undefined : current.bookmarkAnnotationId,
      deletedAnnotations: current.bookmarked && annotationId && selectedChapterId
        ? upsertDeletedReaderAnnotation(current.deletedAnnotations ?? [], {
          annotationId,
          chapterId: selectedChapterId,
          deletedAt,
          kind: 'bookmark',
          paragraphIndex: 0,
          selectedText: activeChapterTitle,
          updatedAt: deletedAt,
        })
        : current.deletedAnnotations ?? [],
    }));

    if (!apiClient || !activeBookId || !selectedChapterId) return;
    if (wasBookmarked) {
      if (annotationId) {
        void apiClient.deleteReaderAnnotation(activeBookId, annotationId).catch(handleMarksSyncError);
      }
      return;
    }

    void apiClient.createReaderAnnotation(activeBookId, selectedChapterId, {
      kind: 'bookmark',
      paragraph_index: 0,
      selected_text: activeChapterTitle,
    })
      .then(mergeRemoteAnnotation)
      .catch(handleMarksSyncError);
  }

  function toggleHighlight(paragraphIndex: number, text: string, range?: { charEnd: number; charStart: number }): void {
    const charStart = range?.charStart ?? 0;
    const charEnd = range?.charEnd ?? text.length;
    const existingHighlight = chapterMarks.highlights.find((highlight) => (
      sameReaderHighlightRange(highlight, paragraphIndex, charStart, charEnd)
    ));
    const mutationTime = new Date().toISOString();
    updateChapterMarks((current) => {
      const exists = current.highlights.some((highlight) => (
        sameReaderHighlightRange(highlight, paragraphIndex, charStart, charEnd)
      ));
      const deletedChapterId = existingHighlight?.chapterId ?? selectedChapterId ?? 0;
      return {
        ...current,
        deletedAnnotations: exists && existingHighlight?.annotationId && deletedChapterId > 0
          ? upsertDeletedReaderAnnotation(current.deletedAnnotations ?? [], {
            annotationId: existingHighlight.annotationId,
            chapterId: deletedChapterId,
            charEnd: existingHighlight.charEnd,
            charStart: existingHighlight.charStart,
            clientId: existingHighlight.clientId,
            color: existingHighlight.color,
            deletedAt: mutationTime,
            kind: 'highlight',
            paragraphIndex: existingHighlight.paragraphIndex,
            selectedText: existingHighlight.text,
            updatedAt: mutationTime,
          })
          : current.deletedAnnotations ?? [],
        highlights: exists
          ? current.highlights.filter((highlight) => !sameReaderHighlightRange(
            highlight,
            paragraphIndex,
            charStart,
            charEnd,
          ))
          : [
            ...current.highlights,
            {
              id: readerHighlightRangeId(paragraphIndex, charStart, charEnd),
              charEnd,
              charStart,
              paragraphIndex,
              text,
              updatedAt: mutationTime,
            },
          ],
      };
    });

    if (!apiClient || !activeBookId || !selectedChapterId) return;
    if (existingHighlight?.annotationId) {
      void apiClient.deleteReaderAnnotation(activeBookId, existingHighlight.annotationId).catch(handleMarksSyncError);
      return;
    }
    if (existingHighlight) return;

    void apiClient.createReaderAnnotation(activeBookId, selectedChapterId, {
      char_end: charEnd,
      char_start: charStart,
      kind: 'highlight',
      paragraph_index: paragraphIndex,
      selected_text: text,
    })
      .then(mergeRemoteAnnotation)
      .catch(handleMarksSyncError);
  }

  function openNoteEditor(paragraphIndex: number, text: string, range?: { charEnd: number; charStart: number }): void {
    const existingNote = notesByParagraph.get(paragraphIndex);
    setNoteDraft({
      charEnd: range?.charEnd ?? existingNote?.charEnd ?? text.length,
      charStart: range?.charStart ?? existingNote?.charStart ?? 0,
      paragraphIndex,
      text,
      value: existingNote?.note ?? '',
    });
  }

  function saveNoteDraft(): void {
    if (!noteDraft) return;
    const note = noteDraft.value.trim();
    const existingNote = notesByParagraph.get(noteDraft.paragraphIndex);
    const mutationTime = new Date().toISOString();
    updateChapterMarks((current) => ({
      ...current,
      deletedAnnotations: !note && existingNote?.annotationId
        ? upsertDeletedReaderAnnotation(current.deletedAnnotations ?? [], {
          annotationId: existingNote.annotationId,
          chapterId: existingNote.chapterId ?? selectedChapterId ?? 0,
          charEnd: existingNote.charEnd,
          charStart: existingNote.charStart,
          clientId: existingNote.clientId,
          color: existingNote.color,
          deletedAt: mutationTime,
          kind: 'note',
          note: existingNote.note,
          paragraphIndex: existingNote.paragraphIndex,
          selectedText: existingNote.text,
          updatedAt: mutationTime,
        })
        : current.deletedAnnotations ?? [],
      notes: note
        ? [
          ...current.notes.filter((item) => item.paragraphIndex !== noteDraft.paragraphIndex),
          {
            annotationId: existingNote?.annotationId,
            bookId: existingNote?.bookId,
            chapterId: existingNote?.chapterId,
            chapterNumber: existingNote?.chapterNumber,
            chapterTitle: existingNote?.chapterTitle,
            charEnd: noteDraft.charEnd,
            charStart: noteDraft.charStart,
            clientId: existingNote?.clientId,
            color: existingNote?.color,
            createdAt: existingNote?.createdAt,
            id: existingNote?.id ?? `note-${noteDraft.paragraphIndex}`,
            note,
            paragraphIndex: noteDraft.paragraphIndex,
            syncPending: Boolean(existingNote?.annotationId),
            text: noteDraft.text,
            updatedAt: existingNote?.annotationId ? mutationTime : existingNote?.updatedAt,
          },
        ]
        : current.notes.filter((item) => item.paragraphIndex !== noteDraft.paragraphIndex),
    }));
    setNoteDraft(null);

    if (!apiClient || !activeBookId || !selectedChapterId) return;
    if (!note) {
      if (existingNote?.annotationId) {
        void apiClient.deleteReaderAnnotation(activeBookId, existingNote.annotationId).catch(handleMarksSyncError);
      }
      return;
    }

    if (existingNote?.annotationId) {
      void apiClient.updateReaderAnnotation(activeBookId, existingNote.annotationId, {
        char_end: noteDraft.charEnd,
        char_start: noteDraft.charStart,
        kind: 'note',
        note,
        paragraph_index: noteDraft.paragraphIndex,
        selected_text: noteDraft.text,
      })
        .then(mergeRemoteAnnotation)
        .catch(handleMarksSyncError);
      return;
    }

    void apiClient.createReaderAnnotation(activeBookId, selectedChapterId, {
      char_end: noteDraft.charEnd,
      char_start: noteDraft.charStart,
      kind: 'note',
      note,
      paragraph_index: noteDraft.paragraphIndex,
      selected_text: noteDraft.text,
    })
      .then(mergeRemoteAnnotation)
      .catch(handleMarksSyncError);
  }

  function exportReaderAnnotations(format: ReaderAnnotationExportFormat, kindOverride?: ReaderAnnotationKind | null): void {
    if (!activeBookId) {
      setMarksError('Không thể xuất dấu đọc: chưa chọn truyện.');
      return;
    }

    const selectedKind = kindOverride !== undefined ? kindOverride : annotationExportKind;
    const scopeLabel = readerAnnotationExportScopes.find((scope) => scope.kind === selectedKind)?.label ?? 'All';
    const exportLocalMarks = (): void => {
      const download = localReaderMarksDownload(
        markPanelItems,
        format,
        bookTitle,
        selectedKind,
      );
      onDownload(download.blob, download.filename);
      setAnnotationExportStatus(`Đã xuất local ${download.filename}`);
      setMarksError('');
    };

    if (!apiClient) {
      exportLocalMarks();
      return;
    }

    const request = selectedKind
      ? apiClient.downloadReaderAnnotations(activeBookId, format, { kind: selectedKind })
      : apiClient.downloadReaderAnnotations(activeBookId, format);

    setAnnotationExportStatus(`Đang xuất ${scopeLabel} ${format.toUpperCase()}...`);
    void request
      .then((download) => {
        onDownload(download.blob, download.filename);
        setAnnotationExportStatus(`Đã xuất ${download.filename}`);
        setMarksError('');
      })
      .catch((error: unknown) => {
        if (markPanelItems.length > 0) {
          exportLocalMarks();
          setMarksError(error instanceof Error ? `Backend export lỗi, đã dùng local: ${error.message}` : 'Backend export lỗi, đã dùng local.');
        } else {
          setAnnotationExportStatus('');
          setMarksError(error instanceof Error ? error.message : 'Failed to export reader annotations');
        }
      });
  }

  function importReaderAnnotationsFile(file: File | null): void {
    if (!file) return;
    if (!apiClient || !activeBookId) {
      setMarksError('Không thể nhập dấu đọc: thiếu kết nối API hoặc chưa chọn truyện.');
      return;
    }

    setAnnotationImportLoading(true);
    setAnnotationExportStatus(`Đang nhập ${file.name}...`);
    void file.text()
      .then((text) => {
        const parsed = JSON.parse(text) as unknown;
        const annotations = readerAnnotationImportItemsFromPayload(parsed);
        if (annotations.length === 0) {
          throw new Error('File JSON không có dấu đọc hợp lệ.');
        }
        return apiClient.importReaderAnnotations(activeBookId, annotations);
      })
      .then((response) => {
        if (response.annotations.length > 0) {
          const nextStore = mergeLocalAndRemoteMarks(loadReaderMarks(), response.annotations);
          saveReaderMarks(nextStore);
          setMarksStore(nextStore);
        }
        setAnnotationExportStatus(
          `Đã nhập ${response.summary.imported} dấu đọc · bỏ qua ${response.summary.skipped}`,
        );
        setMarksError('');
      })
      .catch((error: unknown) => {
        setAnnotationExportStatus('');
        setMarksError(error instanceof Error ? error.message : 'Failed to import reader annotations');
      })
      .finally(() => setAnnotationImportLoading(false));
  }

  return {
    chapterMarks, bookmarked, highlightedParagraphs, notesByParagraph, markPanelItems,
    noteDraft, annotationExportStatus, annotationImportLoading, annotationExportKind,
    toggleBookmark, toggleHighlight, saveSelectionHighlight, openNoteEditor, saveNoteDraft,
    exportReaderAnnotations, importReaderAnnotationsFile,
    setAnnotationExportKind,
    closeNoteEditor: () => setNoteDraft(null),
    updateNoteDraftValue: (value: string) => setNoteDraft((current) => current ? { ...current, value } : current),
    marksError: sync.marksError, setMarksError,
    readerSyncStatus: sync.readerSyncStatus,
    readerAnnotationConflicts: sync.readerAnnotationConflicts,
    readerProgressConflict: sync.readerProgressConflict,
    consumeInitialProgressSave: sync.consumeInitialProgressSave,
    persistReaderProgress: sync.persistReaderProgress,
    useRemoteReaderProgress: sync.useRemoteReaderProgress,
    useLocalReaderProgress: sync.useLocalReaderProgress,
    useLocalReaderAnnotationConflict: sync.useLocalReaderAnnotationConflict,
    useServerReaderAnnotationConflict: sync.useServerReaderAnnotationConflict,
  };
}
