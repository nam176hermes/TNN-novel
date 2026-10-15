import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ApiClient } from '../../api/client';
import type { ReaderSyncConflict, ReaderSyncProgress, ReaderSyncRequest } from '../../api/types';
import { loadReaderDeviceId } from '../../state/readerDevice';
import {
  acceptReaderAnnotationConflictFromServer,
  annotationToLocalMark,
  loadReaderMarks,
  markReaderAnnotationConflictForLocalResolution,
  mergeLocalAndRemoteMarks,
  readerMarksToSyncAnnotations,
  saveReaderMarks,
  type ReaderMarksStore,
} from '../../state/readerMarks';
import {
  chooseLatestReaderProgressSnapshot,
  loadReaderLastSyncAt,
  loadReaderProgressSnapshot,
  remoteReaderProgressToSnapshot,
  saveReaderLastSyncAt,
  saveReaderProgressSnapshot,
  type ReaderProgressSnapshot,
} from '../../state/readerProgress';
import type { ReaderBootstrap } from '../../state/useReaderChapterData';

type PendingReaderProgressSync = {
  bookId: number;
  client: Pick<ApiClient, 'syncReaderState'>;
  key: string;
  request: ReaderSyncRequest;
  revision: number;
  snapshot: ReaderProgressSnapshot;
};

const READER_PROGRESS_SYNC_DEBOUNCE_MS = 400;

function readerProgressSnapshotToSyncProgress(snapshot: ReaderProgressSnapshot): ReaderSyncProgress {
  const progress: ReaderSyncProgress = {
    chapter_id: snapshot.chapterId,
    absolute_char_offset: snapshot.absoluteCharOffset ?? 0,
    char_offset: snapshot.charOffset ?? 0,
    mode: snapshot.mode ?? 'scroll',
    page_index: snapshot.pageIndex ?? 0,
    paragraph_index: snapshot.paragraphIndex ?? 0,
    percent: snapshot.percent,
    updated_at: snapshot.updatedAt,
  };
  if (snapshot.anchor) progress.anchor = snapshot.anchor;
  return progress;
}

export function useReaderSync({ apiClient, activeBookId, readerBootstrap, onSelectChapter }: {
  apiClient?: Pick<ApiClient, 'getReaderState' | 'syncReaderState'>;
  activeBookId: number | null;
  readerBootstrap?: ReaderBootstrap | null;
  onSelectChapter(chapterId: number): void;
}) {
  const skipInitialProgressSaveRef = useRef('');
  const progressSyncTimerRef = useRef<number | null>(null);
  const pendingProgressSyncRef = useRef<PendingReaderProgressSync | null>(null);
  const progressSyncRevisionRef = useRef(0);
  const progressSyncMountedRef = useRef(true);
  const progressSyncStartedRef = useRef(false);
  const readerDeviceId = useMemo(() => loadReaderDeviceId(), []);
  const [marksError, setMarksError] = useState('');
  const [readerSyncStatus, setReaderSyncStatus] = useState('');
  const [readerAnnotationConflicts, setReaderAnnotationConflicts] = useState<ReaderSyncConflict[]>([]);
  const [readerProgressConflict, setReaderProgressConflict] = useState<{
    local: ReaderProgressSnapshot;
    remote: ReaderProgressSnapshot;
  } | null>(null);
  const [marksStore, setMarksStore] = useState<ReaderMarksStore>(() => loadReaderMarks());

  useEffect(() => {
    if (!apiClient || !activeBookId) return;
    let cancelled = false;

    void (readerBootstrap?.bookId === activeBookId ? readerBootstrap.request : apiClient.getReaderState(activeBookId))
      .then((state) => {
        if (cancelled) return;
        if (state.progress) {
          const localSnapshot = loadReaderProgressSnapshot(activeBookId);
          const remoteSnapshot = remoteReaderProgressToSnapshot(state.progress);
          const resolvedSnapshot = chooseLatestReaderProgressSnapshot(
            localSnapshot,
            remoteSnapshot,
          );
          if (!localSnapshot) {
            setReaderSyncStatus('Sync: tải tiến độ remote');
            setReaderProgressConflict(null);
          } else if (resolvedSnapshot === localSnapshot) {
            setReaderSyncStatus('Sync: giữ tiến độ local mới hơn remote');
            setReaderProgressConflict({ local: localSnapshot, remote: remoteSnapshot });
            skipInitialProgressSaveRef.current = `${activeBookId}:${resolvedSnapshot.chapterId}`;
          } else {
            setReaderSyncStatus('Sync: dùng tiến độ remote mới hơn local');
            setReaderProgressConflict({ local: localSnapshot, remote: remoteSnapshot });
          }
          saveReaderProgressSnapshot(
            activeBookId,
            resolvedSnapshot.chapterId,
            resolvedSnapshot.position,
            resolvedSnapshot.totalChapters,
            undefined,
            {
              absoluteCharOffset: resolvedSnapshot.absoluteCharOffset,
              charOffset: resolvedSnapshot.charOffset,
              mode: resolvedSnapshot.mode,
              pageIndex: resolvedSnapshot.pageIndex,
              percent: resolvedSnapshot.percent,
              paragraphIndex: resolvedSnapshot.paragraphIndex,
              updatedAt: resolvedSnapshot.updatedAt,
            },
          );
        } else {
          setReaderSyncStatus('');
          setReaderProgressConflict(null);
        }
        const mergedMarks = mergeLocalAndRemoteMarks(loadReaderMarks(), state.annotations);
        saveReaderMarks(mergedMarks);
        setMarksStore(mergedMarks);
        const localAnnotations = readerMarksToSyncAnnotations(mergedMarks, activeBookId);
        if (localAnnotations.length > 0) {
          void apiClient.syncReaderState(activeBookId, {
            annotations: localAnnotations,
            device_id: readerDeviceId,
            last_sync_at: loadReaderLastSyncAt(activeBookId),
          })
            .then((syncedState) => {
              if (cancelled) return;
              saveReaderLastSyncAt(activeBookId, syncedState.server_time);
              const next = mergeLocalAndRemoteMarks(loadReaderMarks(), syncedState.annotations);
              saveReaderMarks(next);
              setMarksStore(next);
              const annotationConflicts = syncedState.conflicts.filter((conflict) => conflict.entity === 'annotation');
              setReaderAnnotationConflicts(annotationConflicts);
              setReaderSyncStatus(
                annotationConflicts.length > 0
                  ? `Sync: ${annotationConflicts.length} xung đột dấu đọc`
                  : `Sync: đã đồng bộ ${localAnnotations.length} dấu đọc local`,
              );
            })
            .catch((error: unknown) => {
              if (!cancelled) handleMarksSyncError(error);
            });
        } else {
          setReaderAnnotationConflicts([]);
        }
        setMarksError('');
      })
      .catch((error: unknown) => {
        if (!cancelled) setMarksError(error instanceof Error ? error.message : 'Failed to load reader marks');
      });

    return () => {
      cancelled = true;
    };
  }, [activeBookId, apiClient, readerBootstrap, readerDeviceId]);

  const flushReaderProgressSync = useCallback(() => {
    if (progressSyncTimerRef.current !== null) {
      window.clearTimeout(progressSyncTimerRef.current);
      progressSyncTimerRef.current = null;
    }
    const pending = pendingProgressSyncRef.current;
    pendingProgressSyncRef.current = null;
    if (!pending) return;

    void pending.client.syncReaderState(pending.bookId, pending.request)
      .then((syncedState) => {
        if (!progressSyncMountedRef.current || pending.revision !== progressSyncRevisionRef.current) return;
        saveReaderLastSyncAt(pending.bookId, syncedState.server_time);
        const progressConflict = syncedState.conflicts.find((conflict) => conflict.entity === 'progress');
        if (!progressConflict) return;
        if (progressConflict.resolution === 'client_won') {
          setReaderProgressConflict(null);
        } else if (syncedState.progress) {
          setReaderProgressConflict({
            local: pending.snapshot,
            remote: remoteReaderProgressToSnapshot(syncedState.progress),
          });
        }
        setReaderSyncStatus(
          progressConflict.resolution === 'client_won'
            ? 'Sync: đã resolve tiến độ bằng local'
            : 'Sync: tiến độ server mới hơn local',
        );
      })
      .catch((error: unknown) => {
        if (progressSyncMountedRef.current && pending.revision === progressSyncRevisionRef.current) {
          setMarksError(error instanceof Error ? error.message : 'Failed to sync reader progress');
        }
      });
  }, []);

  const scheduleReaderProgressSync = useCallback((
    bookId: number,
    snapshot: ReaderProgressSnapshot,
  ) => {
    if (!apiClient) return;
    const key = `${bookId}:${snapshot.chapterId}`;
    if (pendingProgressSyncRef.current?.key !== key && pendingProgressSyncRef.current) {
      flushReaderProgressSync();
    }
    const revision = progressSyncRevisionRef.current + 1;
    progressSyncRevisionRef.current = revision;
    pendingProgressSyncRef.current = {
      bookId,
      client: apiClient,
      key,
      request: {
        device_id: readerDeviceId,
        last_sync_at: loadReaderLastSyncAt(bookId),
        progress: readerProgressSnapshotToSyncProgress(snapshot),
      },
      revision,
      snapshot,
    };
    if (!progressSyncStartedRef.current) {
      progressSyncStartedRef.current = true;
      flushReaderProgressSync();
      return;
    }
    if (progressSyncTimerRef.current !== null) {
      window.clearTimeout(progressSyncTimerRef.current);
    }
    progressSyncTimerRef.current = window.setTimeout(
      flushReaderProgressSync,
      READER_PROGRESS_SYNC_DEBOUNCE_MS,
    );
  }, [apiClient, flushReaderProgressSync, readerDeviceId]);

  useEffect(() => {
    progressSyncMountedRef.current = true;
    const handlePageHide = () => flushReaderProgressSync();
    window.addEventListener('pagehide', handlePageHide);
    return () => {
      window.removeEventListener('pagehide', handlePageHide);
      flushReaderProgressSync();
      progressSyncMountedRef.current = false;
    };
  }, [flushReaderProgressSync]);

  function mergeRemoteAnnotation(annotation: Parameters<typeof annotationToLocalMark>[0]): void {
    setMarksStore((currentStore) => {
      const nextStore = mergeLocalAndRemoteMarks(currentStore, [annotation]);
      saveReaderMarks(nextStore);
      return nextStore;
    });
    setMarksError('');
  }

  function handleMarksSyncError(error: unknown): void {
    setMarksError(error instanceof Error ? error.message : 'Failed to sync reader marks');
  }

  function saveResolvedReaderProgressSnapshot(snapshot: ReaderProgressSnapshot): void {
    if (!activeBookId) return;
    saveReaderProgressSnapshot(
      activeBookId,
      snapshot.chapterId,
      snapshot.position,
      snapshot.totalChapters,
      undefined,
      {
        absoluteCharOffset: snapshot.absoluteCharOffset,
        charOffset: snapshot.charOffset,
        mode: snapshot.mode,
        pageIndex: snapshot.pageIndex,
        percent: snapshot.percent,
        paragraphIndex: snapshot.paragraphIndex,
        updatedAt: snapshot.updatedAt,
      },
    );
  }

  function useRemoteReaderProgress(): void {
    if (!readerProgressConflict) return;
    saveResolvedReaderProgressSnapshot(readerProgressConflict.remote);
    setReaderSyncStatus('Sync: đã dùng tiến độ remote');
    setReaderProgressConflict(null);
    onSelectChapter(readerProgressConflict.remote.chapterId);
  }

  function useLocalReaderProgress(): void {
    if (!readerProgressConflict || !apiClient || !activeBookId) return;
    const local = readerProgressConflict.local;
    setReaderSyncStatus('Sync: đang gửi tiến độ local...');
    void apiClient.syncReaderState(activeBookId, {
      device_id: readerDeviceId,
      last_sync_at: loadReaderLastSyncAt(activeBookId),
      progress: readerProgressSnapshotToSyncProgress(local),
    })
      .then((syncedState) => {
        saveReaderLastSyncAt(activeBookId, syncedState.server_time);
        saveResolvedReaderProgressSnapshot(local);
        setReaderSyncStatus('Sync: đã dùng tiến độ local');
        setReaderProgressConflict(null);
      })
      .catch((error: unknown) => {
        setMarksError(error instanceof Error ? error.message : 'Failed to sync local reader progress');
      });
  }

  function useLocalReaderAnnotationConflict(conflict: ReaderSyncConflict): void {
    if (!apiClient || !activeBookId) return;
    const resolvedMarks = markReaderAnnotationConflictForLocalResolution(
      loadReaderMarks(),
      activeBookId,
      conflict,
    );
    const annotations = readerMarksToSyncAnnotations(resolvedMarks, activeBookId);
    if (annotations.length === 0) {
      setReaderSyncStatus('Sync: không tìm thấy dấu đọc local để gửi lại');
      return;
    }

    saveReaderMarks(resolvedMarks);
    setMarksStore(resolvedMarks);
    setReaderSyncStatus('Sync: đang dùng local cho dấu đọc...');
    void apiClient.syncReaderState(activeBookId, {
      annotations,
      device_id: readerDeviceId,
      last_sync_at: loadReaderLastSyncAt(activeBookId),
    })
      .then((syncedState) => {
        saveReaderLastSyncAt(activeBookId, syncedState.server_time);
        const next = mergeLocalAndRemoteMarks(loadReaderMarks(), syncedState.annotations);
        saveReaderMarks(next);
        setMarksStore(next);
        const annotationConflicts = syncedState.conflicts.filter((item) => item.entity === 'annotation');
        setReaderAnnotationConflicts(annotationConflicts);
        setReaderSyncStatus(
          annotationConflicts.length > 0
            ? `Sync: ${annotationConflicts.length} xung đột dấu đọc`
            : 'Sync: đã dùng local cho dấu đọc',
        );
      })
      .catch((error: unknown) => {
        setMarksError(error instanceof Error ? error.message : 'Failed to sync local reader annotation');
      });
  }

  function useServerReaderAnnotationConflict(conflict: ReaderSyncConflict): void {
    if (!activeBookId || !conflict.server_annotation) return;
    const resolvedMarks = acceptReaderAnnotationConflictFromServer(
      loadReaderMarks(),
      activeBookId,
      conflict,
    );
    saveReaderMarks(resolvedMarks);
    setMarksStore(resolvedMarks);
    setReaderAnnotationConflicts((current) => current.filter((item) => (
      item !== conflict
      && !(
        item.entity === conflict.entity
        && item.id === conflict.id
        && item.client_id === conflict.client_id
        && item.reason === conflict.reason
      )
    )));
    setReaderSyncStatus('Sync: đã dùng server cho dấu đọc');
  }

  const persistReaderProgress = useCallback((bookId: number, snapshot: ReaderProgressSnapshot) => {
    saveReaderProgressSnapshot(bookId, snapshot.chapterId, snapshot.position, snapshot.totalChapters,
      undefined, {
        absoluteCharOffset: snapshot.absoluteCharOffset,
        anchor: snapshot.anchor,
        charOffset: snapshot.charOffset,
        mode: snapshot.mode,
        pageIndex: snapshot.pageIndex,
        percent: snapshot.percent,
        paragraphIndex: snapshot.paragraphIndex,
        updatedAt: snapshot.updatedAt,
      });
    scheduleReaderProgressSync(bookId, snapshot);
  }, [scheduleReaderProgressSync]);

  const consumeInitialProgressSave = useCallback((bookId: number, chapterId: number) => {
    if (skipInitialProgressSaveRef.current !== `${bookId}:${chapterId}`) return false;
    skipInitialProgressSaveRef.current = '';
    return true;
  }, []);

  return {
    marksStore, setMarksStore, marksError, setMarksError, readerSyncStatus,
    readerAnnotationConflicts, readerProgressConflict,
    mergeRemoteAnnotation, handleMarksSyncError, consumeInitialProgressSave,
    persistReaderProgress, useRemoteReaderProgress, useLocalReaderProgress,
    useLocalReaderAnnotationConflict, useServerReaderAnnotationConflict,
  };
}
