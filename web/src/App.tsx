import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ApiError } from './api/client';
import type {
  ExportFormat,
  ExportResponse,
  GlossaryTermUpdate,
  Chapter,
  EbookInboxFile,
  EbookImportRequest,
  EbookImportHistoryRun,
  EbookPreview,
  EbookSplitMode,
  ImportFileRequest,
  ImportPasteRequest,
  ImportUrlRequest,
  ImportResponse,
  JobStartResponse,
  SourceAdapterCandidate,
  SourceAdapterCandidateList,
  SourceCapability,
  SourceCatalogHealthResult,
  SourceCatalogQuery,
  SourcePreview,
  SystemBackupItem,
  SystemStatus,
  TranslatedBookSummary,
  TtsJobStatus,
  WizardTextImportRequest,
  WizardTextImportResult,
} from './api/types';
import LoginPanel from './components/LoginPanel';
import PwaInstallPrompt from './components/PwaInstallPrompt';
import PwaNetworkStatus from './components/PwaNetworkStatus';
import ReviewModeApp from './components/ReviewModeApp';
import WorkflowShell, { type WorkflowView } from './components/WorkflowShell';
import type { WorkbenchDashboardData } from './components/WorkbenchView';
import { resolveApiBaseUrl } from './api/baseUrl';
import { formatError, type AsyncState, type LoadState } from './state/types';
import { useReaderChapterData } from './state/useReaderChapterData';
import { useGlossary } from './state/useGlossary';
import { useJobAttempts } from './state/useJobAttempts';
import { useJobLogs } from './state/useJobLogs';
import { useJobsHistory } from './state/useJobsHistory';
import { useLibrary } from './state/useLibrary';
import { useProviders } from './state/useProviders';
import type { NormalizedQaIssue } from './state/useQa';
import { removeCachedBookAsync, removeCachedChapterAsync } from './state/readerCache';
import { clearReaderPrivateData } from './state/readerPrivateData';
import { loadReaderResume, saveReaderResume } from './state/readerResume';
import {
  chooseLatestReaderProgressSnapshot,
  loadReaderProgressSnapshot,
  remoteReaderProgressToSnapshot,
  resolveReaderChapterId,
  saveReaderProgress,
  saveReaderProgressSnapshot,
} from './state/readerProgress';
import { useSession } from './state/useSession';
import { useStyleProfiles } from './state/useStyleProfiles';
import { mapChapter } from './state/translator';
import { defaultTranslationPresetId, translationPresets } from './state/translationPresets';
import { useTranslationJob } from './state/useTranslationJob';
import './styles.css';

const API_BASE_URL = resolveApiBaseUrl(import.meta.env.VITE_API_BASE_URL);
const AUTH_DISABLED = ['1', 'true', 'yes', 'on'].includes(
  String(import.meta.env.VITE_DISABLE_AUTH ?? '').trim().toLowerCase(),
);
const PUBLIC_REVIEW_MODE = ['1', 'true', 'yes', 'on'].includes(
  String(import.meta.env.VITE_PUBLIC_REVIEW_MODE ?? '').trim().toLowerCase(),
);

export async function runGlossaryPhase4Mutation(
  call: () => Promise<unknown>,
  onError: (error: unknown, label: string) => void,
  label: string,
): Promise<void> {
  try {
    await call();
  } catch (error) {
    onError(error, label);
    throw error;
  }
}
const MAX_JOB_REFRESH_RETRIES = 3;
const JOB_REFRESH_RETRY_DELAY_MS = 100;
const emptyTranslatedBooks: AsyncState<TranslatedBookSummary[]> = { data: [], error: '', state: 'idle' };
const emptyRawBacklogChapters: AsyncState<Chapter[]> = { data: [], error: '', state: 'idle' };
const emptySystemStatus: AsyncState<SystemStatus | null> = { data: null, error: '', state: 'idle' };
const emptyTtsJobStatus: AsyncState<TtsJobStatus | null> = { data: null, error: '', state: 'idle' };

const AssistPanel = lazy(() => import('./components/AssistPanel'));
const ExportView = lazy(() => import('./components/ExportView'));
const GlossaryStyleView = lazy(() => import('./components/GlossaryStyleView'));
const ImportPanel = lazy(() => import('./components/ImportPanel'));
const JobsView = lazy(() => import('./components/JobsView'));
const LibraryBooksView = lazy(() => import('./components/LibraryBooksView'));
const ProvidersView = lazy(() => import('./components/ProvidersView'));
const RawBacklogView = lazy(() => import('./components/RawBacklogView'));
const ReaderView = lazy(() => import('./components/ReaderView'));
const SourcesView = lazy(() => import('./components/SourcesView'));
const StatusSettingsView = lazy(() => import('./components/StatusSettingsView'));
const WorkbenchView = lazy(() => import('./components/WorkbenchView'));

type DeleteConfirmation = {
  kind: 'translation' | 'chapter' | 'book';
  bookId: number;
  chapterId?: number;
  title: string;
  message: string;
  confirmLabel: string;
};

function isAuthError(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}

function relativeTimeLabel(value?: string | null): string {
  if (!value) return 'Vừa cập nhật';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return 'Vừa cập nhật';
  const elapsedMs = Date.now() - parsed.getTime();
  if (!Number.isFinite(elapsedMs) || elapsedMs < 0) return 'Vừa cập nhật';
  const minutes = Math.floor(elapsedMs / 60_000);
  if (minutes < 1) return 'Vừa cập nhật';
  if (minutes < 60) return `${minutes.toLocaleString('vi-VN')} phút trước`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours.toLocaleString('vi-VN')} giờ trước`;
  const days = Math.floor(hours / 24);
  return `${days.toLocaleString('vi-VN')} ngày trước`;
}

function DeleteConfirmDialog({
  confirmation,
  loading,
  onCancel,
  onConfirm,
}: {
  confirmation: DeleteConfirmation;
  loading: boolean;
  onCancel(): void;
  onConfirm(): void;
}) {
  const titleId = `delete-confirm-title-${confirmation.kind}`;

  return (
    <div className="modal-backdrop">
      <section aria-labelledby={titleId} aria-modal="true" className="dialog confirm-dialog" role="dialog">
        <div className="dialog-header">
          <div>
            <p className="section-label">Xác nhận xóa</p>
            <h2 id={titleId}>{confirmation.title}</h2>
          </div>
        </div>
        <p>{confirmation.message}</p>
        <div className="dialog-actions">
          <button className="secondary-action" disabled={loading} onClick={onCancel} type="button">
            Hủy
          </button>
          <button
            className={confirmation.kind === 'translation' ? 'secondary-action' : 'danger-action'}
            disabled={loading}
            onClick={onConfirm}
            type="button"
          >
            {confirmation.confirmLabel}
          </button>
        </div>
      </section>
    </div>
  );
}

function reviewModeRequested(): boolean {
  if (typeof window === 'undefined') return false;
  const params = new URLSearchParams(window.location.search);
  return window.location.pathname === '/review' || params.get('review') === '1';
}

function AuthenticatedApp() {
  const session = useSession(API_BASE_URL, AUTH_DISABLED);
  const initialReaderResumeRef = useRef(loadReaderResume());
  const restoreOfflineReader = initialReaderResumeRef.current !== null
    && typeof navigator !== 'undefined'
    && navigator.onLine === false;
  const readerResumeRestoredRef = useRef(false);
  const [backendError, setBackendError] = useState('');
  const [backendSuccess, setBackendSuccess] = useState('');
  const [activeView, setActiveView] = useState<WorkflowView>(restoreOfflineReader ? 'reader' : 'workbench');
  const [workbenchChapterId, setWorkbenchChapterId] = useState<number | null>(null);
  const [backendLoading, setBackendLoading] = useState(false);
  const [deleteConfirmation, setDeleteConfirmation] = useState<DeleteConfirmation | null>(null);
  const [exportLoading, setExportLoading] = useState(false);
  const [exportError, setExportError] = useState('');
  const [lastExport, setLastExport] = useState<ExportResponse | null>(null);
  const [backupJobId, setBackupJobId] = useState('');
  const [backupError, setBackupError] = useState('');
  const [backupListError, setBackupListError] = useState('');
  const [backupListLoading, setBackupListLoading] = useState(false);
  const [backups, setBackups] = useState<SystemBackupItem[]>([]);
  const handledBackupJobIdRef = useRef('');
  const [selectedPresetId, setSelectedPresetId] = useState(defaultTranslationPresetId);
  const [workbenchMode, setWorkbenchMode] = useState<'edit' | 'reader'>('edit');
  const [translatedBooks, setTranslatedBooks] = useState<AsyncState<TranslatedBookSummary[]>>(emptyTranslatedBooks);
  const [rawBacklogChapters, setRawBacklogChapters] =
    useState<AsyncState<Chapter[]>>(emptyRawBacklogChapters);
  const [ebookImportHistory, setEbookImportHistory] = useState<EbookImportHistoryRun[]>([]);
  const [ebookInboxDirectory, setEbookInboxDirectory] = useState('inbox/ebooks');
  const [ebookInboxFiles, setEbookInboxFiles] = useState<EbookInboxFile[]>([]);
  const [ebookInboxError, setEbookInboxError] = useState('');
  const [sourceCapabilities, setSourceCapabilities] = useState<SourceCapability[]>([]);
  const [sourceCapabilitiesState, setSourceCapabilitiesState] = useState<LoadState>('idle');
  const [sourceCapabilitiesError, setSourceCapabilitiesError] = useState('');
  const [systemStatus, setSystemStatus] = useState<AsyncState<SystemStatus | null>>(emptySystemStatus);
  const [statusRefreshSeconds, setStatusRefreshSeconds] = useState(10);
  const [retryLoadingJobId, setRetryLoadingJobId] = useState('');
  const refreshRetryCounts = useRef<Record<string, number>>({});

  const expireSession = useCallback((): void => {
    session.expireSession();
    setBackendError('');
    setBackendSuccess('');
    setBackendLoading(false);
  }, [session.expireSession]);

  const library = useLibrary(session.client, session.isAuthenticated, expireSession);
  const books = library.books.data;
  const chapters = library.chapters.data;
  const selectedChapter = library.selectedChapter;
  const selectedChapterId = library.selectedChapterId;
  useEffect(() => {
    const resume = initialReaderResumeRef.current;
    if (!restoreOfflineReader || !session.isAuthenticated || !resume || readerResumeRestoredRef.current) return;
    readerResumeRestoredRef.current = true;
    library.restoreReaderSelection({
      audio_path: null,
      book_id: resume.bookId,
      book_title: resume.bookTitle,
      chapter_number: resume.chapterNumber,
      content_html_path: resume.contentRevision || null,
      has_translation: true,
      id: resume.chapterId,
      status: 'translated',
      title: resume.chapterTitle,
    });
  }, [library.restoreReaderSelection, restoreOfflineReader, session.isAuthenticated]);

  useEffect(() => {
    if (activeView !== 'reader' || !selectedChapter) return;
    saveReaderResume({
      bookId: selectedChapter.book_id,
      bookTitle: selectedChapter.book_title ?? '',
      chapterId: selectedChapter.id,
      chapterNumber: selectedChapter.chapter_number,
      chapterTitle: selectedChapter.title,
      contentRevision: selectedChapter.content_html_path ?? '',
    });
  }, [activeView, selectedChapter]);
  const chapterTextPrefetchTargets = useMemo(() => {
    if (!selectedChapterId) return [];
    const translatedChapters = chapters
      .filter((chapter) => chapter.book_id === selectedChapter?.book_id && chapter.has_translation)
      .sort((left, right) => {
        if (left.chapter_number !== right.chapter_number) return left.chapter_number - right.chapter_number;
        return left.id - right.id;
      });
    const selectedIndex = translatedChapters.findIndex((chapter) => chapter.id === selectedChapterId);
    if (selectedIndex < 0) return [];

    return [
      translatedChapters[selectedIndex + 1],
      translatedChapters[selectedIndex - 1],
    ].filter((target): target is Chapter => Boolean(target));
  }, [chapters, selectedChapter?.book_id, selectedChapterId]);
  const workbenchChapterSelected = selectedChapter?.id === workbenchChapterId;
  const chapterTextEnabled = session.isAuthenticated && Boolean(
    selectedChapter && (activeView === 'reader' || (activeView === 'workbench' && workbenchChapterSelected)),
  );
  const glossaryEnabled = session.isAuthenticated && Boolean(
    activeView === 'glossary' || (activeView === 'workbench' && workbenchChapterSelected),
  );
  const readerPrefetchTargets = activeView === 'reader' ? chapterTextPrefetchTargets : [];
  const readerChapterData = useReaderChapterData(
    session.client,
    chapterTextEnabled,
    selectedChapter,
    expireSession,
    readerPrefetchTargets,
    { cacheOwnership: activeView === 'reader' ? 'external' : 'internal' },
  );
  const chapterText = readerChapterData.text;
  const providersState = useProviders(session.client, session.isAuthenticated, expireSession);
  const styleState = useStyleProfiles(session.client, session.isAuthenticated, expireSession);
  const assistBookId = selectedChapter?.book_id ?? library.selectedBookId;
  const qaState = readerChapterData.qa;
  const glossaryState = useGlossary(
    session.client,
    glossaryEnabled,
    assistBookId,
    chapterText.sourceText,
    expireSession,
    activeView === 'glossary',
  );
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

  const loadEbookImportHistory = useCallback(async (): Promise<void> => {
    if (!session.isAuthenticated) {
      setEbookImportHistory([]);
      return;
    }

    try {
      setEbookImportHistory(await session.client.getEbookImportHistory());
    } catch (error) {
      if (isAuthError(error)) {
        expireSession();
      }
    }
  }, [expireSession, session.client, session.isAuthenticated]);

  useEffect(() => {
    if (activeView !== 'import') return;
    void loadEbookImportHistory();
  }, [activeView, loadEbookImportHistory]);

  const loadEbookInbox = useCallback(async (): Promise<void> => {
    if (!session.isAuthenticated) {
      setEbookInboxFiles([]);
      return;
    }

    setEbookInboxError('');
    try {
      const inbox = await session.client.getEbookInboxFiles();
      setEbookInboxDirectory(inbox.directory);
      setEbookInboxFiles(inbox.files);
    } catch (error) {
      if (isAuthError(error)) {
        expireSession();
        return;
      }
      setEbookInboxError(formatError(error));
    }
  }, [expireSession, session.client, session.isAuthenticated]);

  useEffect(() => {
    if (activeView !== 'import') return;
    void loadEbookInbox();
  }, [activeView, loadEbookInbox]);

  const activeBookId = library.selectedBookId;
  const textLoading = chapterText.state === 'loading';
  const workbenchChapter = workbenchChapterSelected ? selectedChapter : null;

  const loadRawBacklog = useCallback(async (): Promise<Chapter[]> => {
    if (!session.isAuthenticated) {
      setRawBacklogChapters(emptyRawBacklogChapters);
      return [];
    }

    if (library.books.state === 'loading') {
      setRawBacklogChapters((current) => ({ ...current, error: '', state: 'loading' }));
      return [];
    }

    if (books.length === 0) {
      setRawBacklogChapters({ data: [], error: '', state: 'empty' });
      return [];
    }

    setRawBacklogChapters((current) => ({ ...current, error: '', state: 'loading' }));
    try {
      const chapterGroups = await Promise.all(
        books.map(async (book) => {
          const liveChapters = await session.client.getChapters(book.id);
          return liveChapters.map((chapter) => mapChapter(chapter, book.title));
        }),
      );
      const nextChapters = chapterGroups.flat();
      const hasRawBacklog = nextChapters.some((chapter) => chapter.has_translation !== true);
      setRawBacklogChapters({
        data: nextChapters,
        error: '',
        state: hasRawBacklog ? 'ready' : 'empty',
      });
      return nextChapters;
    } catch (error) {
      if (isAuthError(error)) {
        expireSession();
      }
      const message = formatError(error);
      setRawBacklogChapters((current) => ({ data: current.data, error: message, state: 'error' }));
      throw error;
    }
  }, [
    books,
    expireSession,
    library.books.state,
    session.client,
    session.isAuthenticated,
  ]);

  const loadSystemStatus = useCallback(async (): Promise<void> => {
    if (!session.isAuthenticated) {
      setSystemStatus(emptySystemStatus);
      return;
    }

    setSystemStatus((current) => ({ ...current, error: '', state: 'loading' }));
    try {
      const nextStatus = await session.client.getSystemStatus();
      setSystemStatus({ data: nextStatus, error: '', state: 'ready' });
    } catch (error) {
      if (isAuthError(error)) {
        expireSession();
        return;
      }
      setSystemStatus((current) => ({ data: current.data, error: formatError(error), state: 'error' }));
    }
  }, [expireSession, session.client, session.isAuthenticated]);

  const loadBackups = useCallback(async (): Promise<void> => {
    if (!session.isAuthenticated) {
      setBackups([]);
      return;
    }
    setBackupListError('');
    setBackupListLoading(true);
    try {
      const response = await session.client.listSystemBackups();
      setBackups(response.items);
    } catch (error) {
      if (isAuthError(error)) {
        expireSession();
        return;
      }
      setBackupListError(formatError(error));
    } finally {
      setBackupListLoading(false);
    }
  }, [expireSession, session.client, session.isAuthenticated]);

  const refreshAfterCompletedJob = useCallback(
    async (job: { job_id: string; job_type?: string }) => {
      if (job.job_type === 'backup') return;
      const refreshBookId = library.selectedChapter?.book_id ?? library.selectedBookId;

      const attemptRefresh = async () => {
        await library.refreshBooks();

        if (refreshBookId !== null) {
          await library.refreshChapters(refreshBookId);
        }

        await chapterText.load();
        await providersState.refresh();
        if (translatedBooks.state !== 'idle') {
          await loadTranslatedBooks();
        }
        if (rawBacklogChapters.state !== 'idle') {
          await loadRawBacklog();
        }
        try {
          await qaState.refresh();
        } catch (error) {
          if (isAuthError(error)) {
            throw error;
          }
        }
      };

      for (let attempt = 0; attempt <= MAX_JOB_REFRESH_RETRIES; attempt += 1) {
        try {
          await attemptRefresh();
          refreshRetryCounts.current[job.job_id] = 0;
          setBackendError((current) => (current.startsWith('Job refresh failed:') ? '' : current));
          return;
        } catch (error) {
          if (isAuthError(error)) {
            expireSession();
            return;
          }

          refreshRetryCounts.current[job.job_id] = attempt + 1;
          if (attempt === MAX_JOB_REFRESH_RETRIES) {
            setBackendError(`Job refresh failed: ${formatError(error)}`);
            return;
          }

          await new Promise<void>((resolve) => {
            window.setTimeout(resolve, JOB_REFRESH_RETRY_DELAY_MS * (attempt + 1));
          });
        }
      }
    },
    [
      chapterText.load,
      expireSession,
      library.refreshBooks,
      library.refreshChapters,
      library.selectedBookId,
      library.selectedChapter,
      loadTranslatedBooks,
      loadRawBacklog,
      providersState.refresh,
      qaState.refresh,
      rawBacklogChapters.state,
      translatedBooks.state,
    ],
  );
  const jobState = useTranslationJob(
    session.client,
    session.isAuthenticated,
    refreshAfterCompletedJob,
    expireSession,
  );
  const backupJob = backupJobId && jobState.activeJob?.job_id === backupJobId
    ? jobState.activeJob
    : null;
  const backupBusy = Boolean(
    backupJob && ['queued', 'running'].includes(backupJob.status.toLowerCase()),
  );
  const jobAttemptsState = useJobAttempts(
    session.client,
    session.isAuthenticated,
    jobState.activeJob?.job_id ?? '',
    expireSession,
  );
  const jobLogsState = useJobLogs(
    session.client,
    session.isAuthenticated,
    jobState.activeJob?.job_id ?? '',
    expireSession,
  );
  const jobsHistoryState = useJobsHistory(session.client, session.isAuthenticated, expireSession);
  const [ttsJobStatus, setTtsJobStatus] = useState<AsyncState<TtsJobStatus | null>>(emptyTtsJobStatus);
  const [ttsRetrying, setTtsRetrying] = useState(false);
  const activeTtsJobId = jobState.activeJob?.job_type === 'tts' ? jobState.activeJob.job_id : '';

  const loadTtsJobStatus = useCallback(async () => {
    if (!session.isAuthenticated || !activeTtsJobId) {
      setTtsJobStatus(emptyTtsJobStatus);
      return null;
    }
    setTtsJobStatus((current) => ({ data: current.data, error: '', state: 'loading' }));
    try {
      const status = await session.client.getTtsJob(activeTtsJobId);
      setTtsJobStatus({ data: status, error: '', state: 'ready' });
      return status;
    } catch (error) {
      if (isAuthError(error)) {
        expireSession();
      }
      setTtsJobStatus((current) => ({ data: current.data, error: formatError(error), state: 'error' }));
      return null;
    }
  }, [activeTtsJobId, expireSession, session.client, session.isAuthenticated]);

  useEffect(() => {
    if (!session.isAuthenticated || !activeTtsJobId) {
      setTtsJobStatus(emptyTtsJobStatus);
      return;
    }
    void loadTtsJobStatus();
  }, [activeTtsJobId, loadTtsJobStatus, session.isAuthenticated]);

  useEffect(() => {
    const messages = [
      providersState.providers.error ? `Providers unavailable: ${providersState.providers.error}` : '',
      styleState.profiles.error ? `Style profiles unavailable: ${styleState.profiles.error}` : '',
      providersState.estimateError ? `Cost estimate unavailable: ${providersState.estimateError}` : '',
      jobState.error ? `Job stream unavailable: ${jobState.error}` : '',
      jobAttemptsState.attempts.error ? `Job attempts unavailable: ${jobAttemptsState.attempts.error}` : '',
      glossaryState.terms.error ? `Glossary unavailable: ${glossaryState.terms.error}` : '',
      glossaryState.tmError ? `TM search unavailable: ${glossaryState.tmError}` : '',
      qaState.error ? `QA unavailable: ${qaState.error}` : '',
    ].filter(Boolean);

    setBackendError((current) => (current.startsWith('Job refresh failed:') ? current : messages[0] ?? ''));
  }, [
    jobState.error,
    jobAttemptsState.attempts.error,
    glossaryState.terms.error,
    glossaryState.tmError,
    providersState.estimateError,
    providersState.providers.error,
    qaState.error,
    styleState.profiles.error,
  ]);

  useEffect(() => {
    if (!session.isAuthenticated || !jobState.handledJobId) return;
    void Promise.all([jobAttemptsState.refresh(), jobsHistoryState.refresh()]).catch((error) => {
      if (isAuthError(error)) {
        expireSession();
      }
    });
  }, [
    expireSession,
    jobAttemptsState.refresh,
    jobsHistoryState.refresh,
    jobState.handledJobId,
    session.isAuthenticated,
  ]);

  useEffect(() => {
    if (!session.isAuthenticated) {
      setTranslatedBooks(emptyTranslatedBooks);
      setRawBacklogChapters(emptyRawBacklogChapters);
      return;
    }

    if ((activeView === 'workbench' || activeView === 'library' || activeView === 'reader') && translatedBooks.state === 'idle') {
      void loadTranslatedBooks().catch(() => {});
    }
  }, [activeView, loadTranslatedBooks, session.isAuthenticated, translatedBooks.state]);

  useEffect(() => {
    if (activeView !== 'raw') return;
    void loadRawBacklog().catch(() => {});
  }, [activeView, loadRawBacklog]);

  useEffect(() => {
    if (activeView !== 'workbench' && activeView !== 'status') return;
    void loadSystemStatus();
  }, [activeView, loadSystemStatus]);

  useEffect(() => {
    if (activeView !== 'status') return;
    void loadBackups();
  }, [activeView, loadBackups]);

  useEffect(() => {
    if (!backupJob) return;
    const terminal = ['completed', 'failed', 'cancelled', 'canceled', 'interrupted', 'stale_interrupted']
      .includes(backupJob.status.toLowerCase());
    if (!terminal || handledBackupJobIdRef.current === backupJob.job_id) return;

    handledBackupJobIdRef.current = backupJob.job_id;
    if (backupJob.status.toLowerCase() === 'completed') {
      setBackupError('');
      setBackendSuccess(backupJob.message || 'System backup completed.');
      void loadBackups();
      return;
    }
    setBackupError(
      backupJob.last_safe_error
      || backupJob.error
      || backupJob.message
      || 'Backup job did not complete. Check server logs.',
    );
  }, [backupJob, loadBackups]);

  useEffect(() => {
    if (!session.isAuthenticated || activeView !== 'status') return undefined;
    const interval = window.setInterval(() => {
      void loadSystemStatus();
    }, statusRefreshSeconds * 1000);
    return () => window.clearInterval(interval);
  }, [activeView, loadSystemStatus, session.isAuthenticated, statusRefreshSeconds]);

  useEffect(() => {
    if (
      activeView !== 'workbench'
      || !session.isAuthenticated
      || !workbenchChapter
      || !chapterText.sourceText
      || !providersState.selectedProviderId
    ) {
      void providersState.estimateForSource(0, 0).catch(() => {});
      return;
    }

    void providersState
      .estimateForSource(chapterText.sourceText.length, 1)
      .catch(() => {});
  }, [
    activeView,
    chapterText.sourceText,
    providersState.estimateForSource,
    providersState.selectedProviderId,
    session.isAuthenticated,
    workbenchChapter,
  ]);

  function handleJobError(error: unknown, label: string): void {
    if (isAuthError(error)) {
      expireSession();
      return;
    }

    setBackendError(`${label}: ${formatError(error)}`);
  }

  function canLeaveCurrentChapter(): boolean {
    if (!chapterText.isDirty) return true;
    return window.confirm('You have unsaved translation edits. Switch chapter anyway?');
  }

  function handleSelectBook(bookId: number): void {
    if (bookId !== activeBookId && !canLeaveCurrentChapter()) return;
    library.setSelectedBookId(bookId);
    library.setSelectedChapterId(null);
  }

  function handleSelectChapter(chapterId: number): void {
    if (chapterId !== selectedChapterId && !canLeaveCurrentChapter()) return;
    library.setSelectedChapterId(chapterId);
    if (activeBookId !== null) {
      saveReaderProgress(activeBookId, chapterId);
    }
  }

  async function selectBookChapter(bookId: number, chapterId?: number | null): Promise<Chapter[] | null> {
    if (bookId !== activeBookId && !canLeaveCurrentChapter()) return null;

    library.setSelectedBookId(bookId);
    const loadedChapters = await library.refreshChapters(bookId);
    let preferredChapterId = chapterId;
    if (preferredChapterId === null || preferredChapterId === undefined) {
      try {
        const readerState = await session.client.getReaderState(bookId);
        if (readerState.progress) {
          const remoteSnapshot = remoteReaderProgressToSnapshot(readerState.progress);
          const resolvedSnapshot = chooseLatestReaderProgressSnapshot(
            loadReaderProgressSnapshot(bookId),
            remoteSnapshot,
          );
          preferredChapterId = resolvedSnapshot.chapterId;
          saveReaderProgressSnapshot(
            bookId,
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
        }
      } catch {
        // Reader state should not block opening the book; local progress remains the fallback.
      }
    }
    const nextChapterId = resolveReaderChapterId(loadedChapters, preferredChapterId, bookId);
    library.setSelectedChapterId(nextChapterId);
    if (nextChapterId !== null) {
      saveReaderProgress(bookId, nextChapterId);
    }
    return loadedChapters;
  }

  function resolveWorkbenchChapterId(chapters: Chapter[], preferredChapterId?: number | null): number | null {
    const sortedChapters = [...chapters].sort((left, right) => {
      if (left.chapter_number !== right.chapter_number) return left.chapter_number - right.chapter_number;
      return left.id - right.id;
    });

    if (
      preferredChapterId !== null &&
      preferredChapterId !== undefined &&
      sortedChapters.some((chapter) => chapter.id === preferredChapterId)
    ) {
      return preferredChapterId;
    }

    return sortedChapters[0]?.id ?? null;
  }

  async function handleOpenReader(bookId: number, chapterId?: number | null): Promise<void> {
    setBackendError('');
    setBackendLoading(true);
    try {
      const loadedChapters = await selectBookChapter(bookId, chapterId);
      if (loadedChapters) setActiveView('reader');
    } catch (error) {
      handleJobError(error, 'Open reader failed');
    } finally {
      setBackendLoading(false);
    }
  }

  async function handleOpenWorkbenchBook(bookId: number, chapterId?: number | null): Promise<void> {
    setBackendError('');
    setBackendLoading(true);
    try {
      const willSwitchBook = bookId !== activeBookId;
      if (willSwitchBook && !canLeaveCurrentChapter()) return;

      library.setSelectedBookId(bookId);
      const loadedChapters = await library.refreshChapters(bookId);
      const nextChapterId = resolveWorkbenchChapterId(loadedChapters, chapterId);
      if (!willSwitchBook && nextChapterId !== selectedChapterId && !canLeaveCurrentChapter()) return;

      library.setSelectedChapterId(nextChapterId);
      setWorkbenchChapterId(nextChapterId);
      setWorkbenchMode('edit');
      setActiveView('workbench');
    } catch (error) {
      handleJobError(error, 'Open workbench failed');
    } finally {
      setBackendLoading(false);
    }
  }

  function handleOpenSelectedWorkbench(): void {
    setWorkbenchChapterId(selectedChapterId);
    setWorkbenchMode('edit');
    setActiveView('workbench');
  }

  async function handleRenameBook(bookId: number, title: string): Promise<void> {
    setBackendError('');
    setBackendLoading(true);
    try {
      await library.renameBook(bookId, title);
    } catch (error) {
      handleJobError(error, 'Rename book failed');
      throw error;
    } finally {
      setBackendLoading(false);
    }
  }

  async function handleEstimateSelectedChapter(): Promise<void> {
    if (!selectedChapter || !providersState.selectedProviderId) return;

    setBackendError('');
    try {
      await providersState.estimateForSource(
        chapterText.sourceText.length,
        1,
      );
    } catch (error) {
      handleJobError(error, 'Cost estimate unavailable');
    }
  }

  async function handleTranslateSelectedChapter(): Promise<void> {
    if (!selectedChapter || !selectedPresetId) return;
    const selectedPreset = translationPresets.find((preset) => preset.id === selectedPresetId);

    setBackendError('');
    try {
      await jobState.startTranslate(
        selectedChapter,
        selectedPresetId,
        styleState.selectedStyleProfileId,
        selectedPreset?.chunk_size,
      );
    } catch (error) {
      handleJobError(error, 'Translate job failed');
    }
  }

  async function handleBatchTranslateBook(bookId: number, rawChapterIds: number[]): Promise<void> {
    const rawChapterCount = rawChapterIds.length;
    if (!selectedPresetId || rawChapterCount <= 0) return;
    const selectedPreset = translationPresets.find((preset) => preset.id === selectedPresetId);

    setBackendError('');
    setBackendSuccess('');
    try {
      const response = await jobState.startJob(
        () => session.client.startBookTranslateJob(
          bookId,
          selectedPresetId,
          styleState.selectedStyleProfileId || undefined,
          selectedPreset?.chunk_size,
          { chapterIds: rawChapterIds, limit: rawChapterCount },
        ),
        rawChapterCount,
      );
      if (response) {
        setBackendSuccess(`Đã bắt đầu dịch hàng loạt: ${response.job_id}`);
        setActiveView('jobs');
      }
    } catch (error) {
      handleJobError(error, 'Batch translate job failed');
    }
  }

  async function handleCreateAudioBatch(bookId: number, missingAudioCount: number): Promise<void> {
    if (missingAudioCount <= 0) return;

    setBackendError('');
    setBackendSuccess('');
    try {
      const response = await jobState.startJob(
        () => session.client.startBookTtsJob(bookId, { limit: missingAudioCount }),
        missingAudioCount,
      );
      if (response) {
        setBackendSuccess(`Đã bắt đầu tạo audio hàng loạt: ${response.job_id}`);
        setActiveView('jobs');
      }
    } catch (error) {
      handleJobError(error, 'Batch audio job failed');
    }
  }

  async function handleRunQa(): Promise<void> {
    if (!selectedChapter) return;

    setBackendError('');
    try {
      await jobState.startJob(() => qaState.startQa());
    } catch (error) {
      handleJobError(error, 'QA job failed');
    }
  }

  async function handleCancelJob(): Promise<void> {
    setBackendError('');
    try {
      await jobState.cancelActiveJob();
    } catch (error) {
      handleJobError(error, 'Cancel job failed');
    }
  }

  async function handleRetryFailedJob(jobId: string): Promise<void> {
    const failedJob = systemStatus.data?.last_failed_job?.job_id === jobId
      ? systemStatus.data.last_failed_job
      : null;

    setBackendError('');
    setBackendSuccess('');
    setRetryLoadingJobId(jobId);
    try {
      const response = await session.client.retryFailedJob(jobId);
      jobState.setStartedJob(response, failedJob?.total || 1);
      setBackendSuccess(`Chạy lại job đã bắt đầu: ${response.job_id}`);
      await loadSystemStatus();
    } catch (error) {
      if (isAuthError(error)) {
        expireSession();
        return;
      }
      setBackendError(`Retry job failed: ${formatError(error)}`);
    } finally {
      setRetryLoadingJobId('');
    }
  }

  async function handleRetryTtsChunks(jobId: string): Promise<void> {
    setBackendError('');
    setBackendSuccess('');
    setTtsRetrying(true);
    try {
      const response = await session.client.retryTtsJob(jobId);
      setBackendSuccess(response.message || 'Đã bắt đầu retry TTS chunks.');
      await loadTtsJobStatus();
    } catch (error) {
      if (isAuthError(error)) {
        expireSession();
        return;
      }
      setBackendError(`Retry TTS failed: ${formatError(error)}`);
    } finally {
      setTtsRetrying(false);
    }
  }

  function handleApplyQaFix(issue: NormalizedQaIssue): void {
    const suggestedFix = issue.suggestedFix?.trim();
    if (!suggestedFix) return;

    const segment = issue.segment?.trim();
    chapterText.setTranslationText((current) => {
      if (segment && current.includes(segment)) {
        return current.replace(segment, suggestedFix);
      }

      return current ? `${current}\n\n${suggestedFix}` : suggestedFix;
    });
  }

  async function handleSearchTm(query: string): Promise<void> {
    setBackendError('');
    try {
      await glossaryState.searchTranslationMemory(query);
    } catch (error) {
      handleJobError(error, 'TM search failed');
    }
  }

  async function handleStyleProfileChange(styleProfileId: string): Promise<void> {
    styleState.setSelectedStyleProfileId(styleProfileId);
    setBackendError('');

    try {
      await styleState.setDefaultProfile(styleProfileId);
    } catch (error) {
      if (isAuthError(error)) {
        expireSession();
      } else {
        setBackendError(`Style profile update failed: ${formatError(error)}`);
      }
    }
  }

  async function handleGlossaryTermUpdate(termId: number, updates: GlossaryTermUpdate): Promise<void> {
    setBackendError('');

    try {
      await glossaryState.updateTerm(termId, updates);
    } catch (error) {
      handleJobError(error, 'Glossary update failed');
    }
  }

  async function handleGlossaryLockToggle(termId: number, locked: boolean): Promise<void> {
    setBackendError('');

    try {
      await glossaryState.toggleLock(termId, locked);
    } catch (error) {
      handleJobError(error, 'Glossary lock update failed');
    }
  }

  async function handleGlossaryApprove(termId: number): Promise<void> {
    setBackendError('');

    try {
      await glossaryState.approveTerm(termId);
    } catch (error) {
      handleJobError(error, 'Glossary approve failed');
    }
  }

  async function handleGlossaryReject(termId: number): Promise<void> {
    setBackendError('');

    try {
      await glossaryState.rejectTerm(termId);
    } catch (error) {
      handleJobError(error, 'Glossary reject failed');
    }
  }

  async function handleGlossarySaveAndApprove(
    termId: number,
    updates: GlossaryTermUpdate,
    locked: boolean,
  ): Promise<void> {
    setBackendError('');

    try {
      await glossaryState.saveAndApproveTerm(termId, updates, locked);
    } catch (error) {
      handleJobError(error, 'Glossary review failed');
    }
  }

  async function handleGlossaryPhase4(call: () => Promise<unknown>, label: string): Promise<void> {
    setBackendError('');
    return runGlossaryPhase4Mutation(call, handleJobError, label);
  }

  async function handleTestProvider(providerId: string): Promise<void> {
    setBackendError('');

    try {
      await providersState.testProvider(providerId);
    } catch (error) {
      handleJobError(error, 'Provider test failed');
    }
  }

  async function handleSaveProviderKey(providerId: string, apiKey: string): Promise<void> {
    setBackendError('');

    try {
      await providersState.saveProviderKey(providerId, apiKey);
    } catch (error) {
      handleJobError(error, 'Provider key save failed');
      throw error;
    }
  }

  async function handleSaveTranslation(text: string): Promise<void> {
    if (!selectedChapter) return;

    setBackendError('');
    try {
      await chapterText.save(text);
      await library.refreshChapters(selectedChapter.book_id);
      if (rawBacklogChapters.state !== 'idle') {
        await loadRawBacklog();
      }
    } catch (error) {
      handleJobError(error, 'Save translation failed');
    }
  }

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

  async function selectImportedChapter(response: ImportResponse): Promise<void> {
    await library.refreshBooks();
    library.setSelectedBookId(response.book_id);
    await library.refreshChapters(response.book_id);
    library.setSelectedChapterId(response.chapter_id);
    setWorkbenchChapterId(response.chapter_id);
    if (rawBacklogChapters.state !== 'idle') {
      await loadRawBacklog();
    }
    setActiveView('workbench');
  }

  async function handleImportPaste(request: ImportPasteRequest): Promise<void> {
    setBackendError('');
    setBackendSuccess('');
    setBackendLoading(true);

    try {
      const response = await session.client.importPaste(request);
      await selectImportedChapter(response);
    } catch (error) {
      handleJobError(error, 'Import failed');
    } finally {
      setBackendLoading(false);
    }
  }

  async function handleImportFile(request: ImportFileRequest): Promise<void> {
    setBackendError('');
    setBackendSuccess('');
    setBackendLoading(true);

    try {
      const response = await session.client.importFile(request);
      await selectImportedChapter(response);
    } catch (error) {
      handleJobError(error, 'Import failed');
    } finally {
      setBackendLoading(false);
    }
  }

  async function handleImportWizardText(
    request: WizardTextImportRequest,
    options?: { finalAction?: 'save' | 'open' | 'translate' | 'tts' },
  ): Promise<WizardTextImportResult> {
    setBackendError('');
    setBackendSuccess('');
    setBackendLoading(true);

    try {
      const result = await session.client.importWizardText(request);
      await library.refreshBooks();
      await library.refreshChapters(result.book_id);
      library.setSelectedBookId(result.book_id);
      if (result.chapter_ids.length > 0) {
        library.setSelectedChapterId(result.chapter_ids[0]);
        setWorkbenchChapterId(result.chapter_ids[0]);
        if (options?.finalAction === 'open') {
          setActiveView('workbench');
        }
      }
      if (rawBacklogChapters.state !== 'idle') {
        await loadRawBacklog();
      }
      if (translatedBooks.state !== 'idle') {
        await loadTranslatedBooks();
      }
      setBackendSuccess(
        `Đã import ${result.imported_chapters} chương, bỏ qua ${result.skipped_chapters}, ghi đè ${result.overwritten_chapters}.`,
      );
      return result;
    } catch (error) {
      handleJobError(error, 'Import wizard failed');
      throw error;
    } finally {
      setBackendLoading(false);
    }
  }

  async function handleWizardTranslationJob(bookId: number, chapterIds: number[]): Promise<JobStartResponse | void> {
    if (!selectedPresetId) {
      throw new Error('Chưa chọn preset dịch.');
    }
    const selectedPreset = translationPresets.find((preset) => preset.id === selectedPresetId);
    const response = await jobState.startJob(
      () => session.client.startTranslateJob(
        bookId,
        chapterIds,
        selectedPresetId,
        styleState.selectedStyleProfileId || undefined,
        selectedPreset?.chunk_size,
      ),
      chapterIds.length,
    );
    if (response) {
      setBackendSuccess(`Đã tạo job dịch từ import: ${response.job_id}`);
    }
    return response ?? undefined;
  }

  async function handleWizardTtsJob(bookId: number, chapterIds: number[]): Promise<JobStartResponse | void> {
    const response = await jobState.startJob(
      () => session.client.startTtsJob(bookId, chapterIds),
      chapterIds.length,
    );
    if (response) {
      setBackendSuccess(`Đã tạo job audio từ import: ${response.job_id}`);
    }
    return response ?? undefined;
  }

  async function handleImportUrlPreview(url: string): Promise<SourcePreview> {
    try {
      return await session.client.previewImportUrl(url);
    } catch (error) {
      if (isAuthError(error)) {
        expireSession();
      }
      throw error;
    }
  }

  async function handleStartImportUrl(request: ImportUrlRequest): Promise<JobStartResponse | void> {
    setBackendError('');
    setBackendSuccess('');
    try {
      const response = await jobState.startJob(
        () => session.client.startImportUrlJob(request),
        request.chapters.length || 1,
      );
      if (response) {
        setBackendSuccess(`Đã tạo job import URL: ${response.job_id}`);
      }
      return response ?? undefined;
    } catch (error) {
      handleJobError(error, 'URL import failed');
      throw error;
    }
  }

  async function handlePreviewTranslatedEbook(
    file: File,
    splitMode: EbookSplitMode,
    options?: { duplicateStrategy?: EbookImportRequest['duplicateStrategy']; targetBookId?: number | null },
  ): Promise<EbookPreview> {
    try {
      return await session.client.previewTranslatedEbook(file, splitMode, options);
    } catch (error) {
      if (isAuthError(error)) {
        expireSession();
      }
      throw error;
    }
  }

  async function handlePreviewInboxEbook(
    filename: string,
    splitMode: EbookSplitMode,
    options?: { duplicateStrategy?: EbookImportRequest['duplicateStrategy']; targetBookId?: number | null },
  ): Promise<EbookPreview> {
    try {
      return await session.client.previewInboxTranslatedEbook(filename, splitMode, options);
    } catch (error) {
      if (isAuthError(error)) {
        expireSession();
      }
      throw error;
    }
  }

  async function handleImportTranslatedEbook(request: EbookImportRequest): Promise<void> {
    setBackendError('');
    setBackendSuccess('');
    setBackendLoading(true);

    try {
      const response = await session.client.startTranslatedEbookImportJob(request);
      jobState.setStartedJob(response, 1);
      await loadEbookImportHistory();
      setBackendSuccess(`Đã bắt đầu import ebook. Theo dõi tác vụ ${response.job_id.slice(0, 8)}.`);
      setActiveView('jobs');
    } catch (error) {
      handleJobError(error, 'Import ebook failed');
      throw error;
    } finally {
      setBackendLoading(false);
    }
  }

  const loadSourceCapabilities = useCallback(async (): Promise<void> => {
    if (!session.isAuthenticated || sourceCapabilitiesState === 'loading') return;

    setSourceCapabilitiesError('');
    setSourceCapabilitiesState('loading');
    try {
      const sources = await session.client.getImportSources();
      setSourceCapabilities(sources);
      setSourceCapabilitiesState(sources.length > 0 ? 'ready' : 'empty');
    } catch (error) {
      if (isAuthError(error)) {
        expireSession();
        return;
      }
      setSourceCapabilitiesError(formatError(error));
      setSourceCapabilitiesState('error');
    }
  }, [expireSession, session.client, session.isAuthenticated, sourceCapabilitiesState]);

  const loadSourceCatalog = useCallback(
    (params: SourceCatalogQuery) => session.client.getSourceCatalog(params),
    [session.client],
  );

  const checkSourceCatalogEntry = useCallback(
    (entryId: string): Promise<SourceCatalogHealthResult> => session.client.checkSourceCatalogEntry(entryId),
    [session.client],
  );

  const loadSourceAdapterCandidates = useCallback(
    (): Promise<SourceAdapterCandidateList> => session.client.getSourceAdapterCandidates(),
    [session.client],
  );

  const createSourceAdapterCandidate = useCallback(
    (entryId: string): Promise<SourceAdapterCandidate> => session.client.createSourceAdapterCandidate(entryId),
    [session.client],
  );

  const importManagedSources = useCallback(
    (entryIds: string[]) => session.client.importManagedSources(entryIds),
    [session.client],
  );

  const testManagedSource = useCallback(
    (sourceId: string) => session.client.testManagedSource(sourceId),
    [session.client],
  );

  const verifyManagedSource = useCallback(
    (sourceId: string) => session.client.verifyManagedSource(sourceId),
    [session.client],
  );

  const setManagedSourceStatus = useCallback(
    (sourceId: string, status: 'BROKEN' | 'BLOCKED' | 'NEEDS_REVIEW') => session.client.setManagedSourceStatus(sourceId, status),
    [session.client],
  );

  useEffect(() => {
    if (activeView !== 'sources' || sourceCapabilitiesState !== 'idle') return;
    void loadSourceCapabilities();
  }, [activeView, loadSourceCapabilities, sourceCapabilitiesState]);

  function triggerBrowserDownload(blob: Blob, filename: string): void {
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
  }

  async function handleExportBook(format: ExportFormat): Promise<void> {
    const bookId = library.selectedBookId;
    if (bookId === null) return;

    setBackendError('');
    setExportError('');
    setExportLoading(true);

    try {
      const metadata = await session.client.exportBook(bookId, format);
      const download = await session.client.downloadBookExport(bookId, format);
      triggerBrowserDownload(download.blob, download.filename || metadata.filename);
      setLastExport(metadata);
    } catch (error) {
      if (isAuthError(error)) {
        expireSession();
      } else {
        setExportError(formatError(error));
      }
    } finally {
      setExportLoading(false);
    }
  }

  async function handleCreateBackup(options: {
    includeSecrets?: boolean;
    passphrase?: string;
  } = {}): Promise<void> {
    setBackupError('');
    setBackendSuccess('');
    try {
      const response = await jobState.startJob(
        () => session.client.createSystemBackup({
          include_audio: true,
          include_exports: false,
          include_job_logs: false,
          include_secrets: options.includeSecrets ?? false,
          passphrase: options.passphrase ?? '',
        }),
        6,
      );
      if (response) {
        handledBackupJobIdRef.current = '';
        setBackupJobId(response.job_id);
        setBackendSuccess(response.message || 'Backup queued.');
      }
    } catch (error) {
      if (isAuthError(error)) {
        expireSession();
      } else {
        setBackupError(formatError(error));
      }
    }
  }

  async function handleCreateEncryptedBackup(): Promise<void> {
    const passphrase = window.prompt('Nhập passphrase để tạo backup mã hóa (kèm secrets nếu cần):', '') ?? '';
    if (!passphrase.trim()) {
      setBackupError('Backup mã hóa cần passphrase.');
      return;
    }
    await handleCreateBackup({ includeSecrets: true, passphrase });
  }

  async function handleDownloadBackup(filename: string): Promise<void> {
    setBackupError('');
    try {
      const download = await session.client.downloadSystemBackup(filename);
      triggerBrowserDownload(download.blob, download.filename || filename);
    } catch (error) {
      if (isAuthError(error)) {
        expireSession();
      } else {
        setBackupError(formatError(error));
      }
    }
  }

  async function handleLogout(): Promise<void> {
    await Promise.all([
      clearReaderPrivateData().catch(() => undefined),
      session.logout(),
    ]);
    setBackendError('');
    setBackendSuccess('');
  }

  async function handleRefreshJobsView(): Promise<void> {
    setBackendError('');
    try {
      await Promise.all([
        jobAttemptsState.refresh(),
        jobLogsState.refresh(),
        jobsHistoryState.refresh(),
        loadSystemStatus(),
      ]);
      setBackendSuccess('Đã làm mới tác vụ.');
    } catch (error) {
      if (isAuthError(error)) {
        expireSession();
        return;
      }
      setBackendError(`Không làm mới được tác vụ: ${formatError(error)}`);
    }
  }

  const workbenchDashboard = useMemo<WorkbenchDashboardData>(() => {
    const rawPendingChapters = rawBacklogChapters.data.filter((chapter) => chapter.has_translation !== true);
    const rawBookIds = new Set(rawPendingChapters.map((chapter) => chapter.book_id));
    const translatedChapterCount = translatedBooks.data.reduce(
      (total, book) => total + Math.max(0, book.translated_chapters),
      0,
    );
    const totalTranslatedChapters = translatedBooks.data.reduce(
      (total, book) => total + Math.max(0, book.total_chapters),
      0,
    );
    const progressPercent = totalTranslatedChapters > 0
      ? Math.min(100, Math.max(0, Math.round((translatedChapterCount / totalTranslatedChapters) * 100)))
      : 0;
    const status = systemStatus.data;
    const activeJobCount = status
      ? Math.max(status.running_jobs, status.active_jobs)
      : (jobState.activeJobBusy || jobState.activeJob ? 1 : 0);
    const activities: WorkbenchDashboardData['activities'] = [];

    if (jobState.activeJob) {
      activities.push({
        id: `active-${jobState.activeJob.job_id}`,
        label: `Job ${jobState.activeJob.job_type || 'dịch'} đang ${jobState.activeJob.status}`,
        timestampLabel: relativeTimeLabel(jobState.activeJob.created_at),
      });
    }
    if (status?.last_failed_job) {
      activities.push({
        id: `failed-${status.last_failed_job.job_id}`,
        label: `Job ${status.last_failed_job.job_id} thất bại`,
        timestampLabel: relativeTimeLabel(status.last_failed_job.finished_at || status.last_failed_job.created_at),
      });
    }
    for (const event of status?.recent_operational_errors ?? []) {
      activities.push({
        id: `op-${event.id}`,
        label: event.message || event.event_type,
        timestampLabel: relativeTimeLabel(event.created_at),
      });
    }
    for (const event of status?.recent_backup_events ?? []) {
      activities.push({
        id: `backup-${event.id}`,
        label: event.message || event.event_type,
        timestampLabel: relativeTimeLabel(event.created_at),
      });
    }
    if (systemStatus.error) {
      activities.push({
        id: 'system-status-error',
        label: 'Không tải được trạng thái hệ thống',
        timestampLabel: 'Vừa cập nhật',
      });
    }

    return {
      activeJobCount,
      activities: activities.slice(0, 4),
      loading: rawBacklogChapters.state === 'loading'
        || translatedBooks.state === 'loading'
        || systemStatus.state === 'loading',
      progressPercent,
      rawBookCount: rawBookIds.size,
      rawChapterCount: rawPendingChapters.length,
      systemItems: status ? [
        {
          label: 'API Server',
          ok: status.api_ready,
          statusLabel: status.api_ready ? 'Hoạt động' : 'Không sẵn sàng',
        },
        {
          label: 'Dịch vụ dịch',
          ok: Boolean(status.active_provider),
          statusLabel: status.active_provider || 'Chưa chọn',
        },
        {
          label: 'Cơ sở dữ liệu',
          ok: status.api_ready,
          statusLabel: status.api_ready ? 'Sẵn sàng' : 'Cần kiểm tra',
        },
        {
          label: 'Lưu trữ',
          ok: status.asset_protection_enabled,
          statusLabel: status.asset_protection_enabled ? 'Được bảo vệ' : 'Cần kiểm tra',
        },
      ] : [],
      translatedChapterCount,
    };
  }, [
    jobState.activeJob,
    jobState.activeJobBusy,
    rawBacklogChapters.data,
    rawBacklogChapters.state,
    systemStatus.data,
    systemStatus.error,
    systemStatus.state,
    translatedBooks.data,
    translatedBooks.state,
  ]);

  if (session.isRestoring) {
    return (
      <>
        <PwaInstallPrompt />
        <PwaNetworkStatus />
        <main className="login-screen">
          <section aria-label="Khôi phục phiên đăng nhập" className="login-panel">
            <div className="login-heading">
              <p>Welcome back</p>
              <h1>Novel-TNN Translator</h1>
              <span>Đang khôi phục phiên đăng nhập...</span>
            </div>
          </section>
        </main>
      </>
    );
  }

  if (!session.isAuthenticated) {
    return (
      <>
        <PwaInstallPrompt />
        <PwaNetworkStatus />
        <LoginPanel error={session.loginError} onLogin={session.login} />
      </>
    );
  }

  const statusMessages = (
    <>
      {backendLoading || textLoading ? <p className="status-chip workflow-status">Đang tải backend</p> : null}
      {backendError ? (
        <p className="status-error workflow-status" role="alert">
          {backendError}
        </p>
      ) : null}
      {backendSuccess ? (
        <p className="status-success workflow-status" role="status">
          {backendSuccess}
        </p>
      ) : null}
    </>
  );

  const chapterActionDisabledReason = !selectedChapter
    ? 'Chưa chọn chương'
    : !chapterText.sourceText
      ? 'Chưa tải bản gốc'
      : '';
  const estimateDisabledReason = chapterActionDisabledReason
    || (!providersState.selectedProviderId ? 'Chưa chọn model' : '');
  const jobBusy = jobState.starting || jobState.activeJobBusy;
  const translateDisabledReason = chapterActionDisabledReason
    || (!selectedPresetId ? 'Chưa chọn preset' : '')
    || (jobBusy ? 'Đang có tác vụ dịch' : '');

  const workbench = (
    <>
      {statusMessages}
      <section className="workflow-workbench-layout workbench-editor-only" data-workbench-mode={workbenchMode}>
        <WorkbenchView
          activeJob={jobState.activeJob}
          assistPanel={
            workbenchChapter ? (
              <AssistPanel
                activeJob={jobState.activeJob}
                glossaryError={glossaryState.terms.error}
                pendingGlossaryCount={glossaryState.pendingCount}
                qaIssues={qaState.issues}
                qaReport={qaState.report}
                qaState={qaState.state}
                relevantTerms={glossaryState.relevantTerms}
                tmError={glossaryState.tmError}
                tmResults={glossaryState.tmResults}
                tmState={glossaryState.tmState}
                onRunQa={handleRunQa}
                onApplyQaFix={handleApplyQaFix}
                onSearchTm={handleSearchTm}
              />
            ) : null
          }
          chapter={workbenchChapter}
          contentHtml={workbenchChapter ? chapterText.contentHtml : ''}
          dashboard={workbenchDashboard}
          estimate={workbenchChapter ? providersState.estimate : null}
          estimateDisabledReason={estimateDisabledReason}
          isDirty={chapterText.isDirty}
          onDeleteChapter={requestDeleteChapter}
          onDeleteTranslation={requestDeleteTranslation}
          onEstimate={handleEstimateSelectedChapter}
          onOpenGlossary={() => setActiveView('glossary')}
          onOpenImport={() => setActiveView('import')}
          onOpenJobs={() => setActiveView('jobs')}
          onOpenLibrary={() => setActiveView('library')}
          onOpenStatus={() => setActiveView('status')}
          onPresetChange={setSelectedPresetId}
          onSave={() => handleSaveTranslation(chapterText.translationText)}
          onStyleProfileChange={handleStyleProfileChange}
          onTranslate={handleTranslateSelectedChapter}
          onTranslationChange={chapterText.setTranslationText}
          onViewModeChange={setWorkbenchMode}
          selectedPresetId={selectedPresetId}
          selectedStyleProfileId={styleState.selectedStyleProfileId}
          sourceState={workbenchChapter ? chapterText.state : 'idle'}
          sourceText={workbenchChapter ? chapterText.sourceText : ''}
          styleProfiles={styleState.profiles.data}
          translationPresets={translationPresets}
          translateDisabledReason={translateDisabledReason}
          translationText={workbenchChapter ? chapterText.translationText : ''}
          viewMode={workbenchMode}
        />
      </section>
    </>
  );

  function renderWorkflowViewContent(view: WorkflowView) {
    switch (view) {
      case 'raw':
        return (
          <>
            {statusMessages}
            <RawBacklogView
              batchBusy={jobBusy}
              books={books}
              chapters={rawBacklogChapters}
              onBatchTranslate={(bookId, rawChapterIds) => {
                void handleBatchTranslateBook(bookId, rawChapterIds);
              }}
              onOpenImport={() => setActiveView('import')}
              onOpenWorkbench={(bookId, chapterId) => {
                void handleOpenWorkbenchBook(bookId, chapterId);
              }}
              onRefresh={() => {
                void loadRawBacklog().catch((error) => handleJobError(error, 'Load raw backlog failed'));
              }}
            />
          </>
        );
      case 'library':
        return (
          <>
            {statusMessages}
            <LibraryBooksView
              books={translatedBooks}
              onDeleteBook={requestDeleteBook}
              onOpenImport={() => setActiveView('import')}
              onUpdateCover={(book, cover) => {
                void handleUpdateBookCover(book, cover);
              }}
              onOpenReader={(bookId, chapterId) => {
                void handleOpenReader(bookId, chapterId);
              }}
              onOpenWorkbench={(bookId, chapterId) => {
                void handleOpenWorkbenchBook(bookId, chapterId);
              }}
              onRefresh={() => {
                void loadTranslatedBooks().catch((error) => handleJobError(error, 'Load translated books failed'));
              }}
            />
          </>
        );
      case 'reader':
        return (
          <>
            <ReaderView
              activeBookId={activeBookId}
              apiClient={session.client}
              books={translatedBooks.data}
              chapters={chapters}
              contentHtml={chapterText.contentHtml}
              qaError={qaState.error}
              qaReport={qaState.report}
              qaState={qaState.state}
              selectedChapter={selectedChapter}
              selectedChapterId={selectedChapterId}
              sourceText={chapterText.sourceText}
              textError={chapterText.error}
              textState={chapterText.state}
              translationText={chapterText.translationText}
              onBackToLibrary={() => setActiveView('library')}
              onOpenWorkbench={handleOpenSelectedWorkbench}
              onSelectBook={(bookId) => {
                void handleOpenReader(bookId);
              }}
              onSelectChapter={handleSelectChapter}
            />
          </>
        );
      case 'import':
        return (
          <>
            {statusMessages}
            <ImportPanel
              books={books}
              chapters={chapters}
              importJobClient={session.client}
              ebookInboxDirectory={ebookInboxDirectory}
              ebookInboxError={ebookInboxError}
              ebookInboxFiles={ebookInboxFiles}
              ebookImportHistory={ebookImportHistory}
              loading={backendLoading}
              onCancel={() => setActiveView('workbench')}
              loadSourceCatalog={loadSourceCatalog}
              onCreateTranslationJob={handleWizardTranslationJob}
              onCreateTtsJob={handleWizardTtsJob}
              onImportFile={handleImportFile}
              onImportPaste={handleImportPaste}
              onImportTranslatedEbook={handleImportTranslatedEbook}
              onImportWizardText={handleImportWizardText}
              onOpenImportedBook={(result) => {
                void handleOpenReader(result.book_id, result.chapter_ids[0] ?? null);
              }}
              onOpenJob={() => setActiveView('jobs')}
              onReturnToLibrary={() => setActiveView('library')}
              onPreviewInboxEbook={handlePreviewInboxEbook}
              onPreviewImportUrl={handleImportUrlPreview}
              onPreviewTranslatedEbook={handlePreviewTranslatedEbook}
              onRefreshEbookInbox={loadEbookInbox}
              onStartImportUrlJob={handleStartImportUrl}
            />
          </>
        );
      case 'sources':
        return (
          <>
            {statusMessages}
            <SourcesView
              checkCatalogSource={checkSourceCatalogEntry}
              createParserCandidate={createSourceAdapterCandidate}
              error={sourceCapabilitiesError}
              importCatalogSources={importManagedSources}
              loadCatalog={loadSourceCatalog}
              loadParserCandidates={loadSourceAdapterCandidates}
              markManagedSourceStatus={setManagedSourceStatus}
              onRefresh={loadSourceCapabilities}
              sources={sourceCapabilities}
              state={sourceCapabilitiesState}
              testManagedSource={testManagedSource}
              verifyManagedSource={verifyManagedSource}
            />
          </>
        );
      case 'glossary':
        return (
          <>
            {statusMessages}
            <GlossaryStyleView
              bookId={assistBookId ?? undefined}
              chapterId={selectedChapter?.book_id === assistBookId ? selectedChapter.id : undefined}
              error={glossaryState.terms.error}
              facets={glossaryState.facets}
              glossaryTerms={glossaryState.terms.data}
              loadState={glossaryState.terms.state}
              onApplyImport={(items, digest, policy) => handleGlossaryPhase4(
                () => glossaryState.applyImport(items, digest, policy), 'Glossary import failed',
              )}
              onApplyMerge={(canonicalId, duplicateIds, digest) => handleGlossaryPhase4(
                () => glossaryState.applyMerge(canonicalId, duplicateIds, digest), 'Glossary merge failed',
              )}
              onApproveTerm={handleGlossaryApprove}
              onArchiveTerm={(termId) => handleGlossaryPhase4(
                () => glossaryState.archiveTerm(termId), 'Glossary archive failed',
              )}
              onBulkAction={(action, terms) => handleGlossaryPhase4(
                () => glossaryState.bulkTerms(action, terms), 'Glossary bulk update failed',
              )}
              onCreateTerm={(term) => handleGlossaryPhase4(
                () => glossaryState.createTerm(term), 'Glossary create failed',
              )}
              onCreateBookOverride={glossaryState.createBookOverride}
              onExport={(format) => handleGlossaryPhase4(async () => {
                const download = await session.client.downloadGlossaryExport(assistBookId ?? undefined, format);
                triggerBrowserDownload(download.blob, download.filename);
              }, 'Glossary export failed')}
              onLoadConflicts={glossaryState.loadConflicts}
              onLoadExtractionSettings={(bookId) => session.client.getBookGlossarySettings(bookId)}
              onLoadTermDetail={glossaryState.loadTermDetail}
              onLockToggle={handleGlossaryLockToggle}
              onPageChange={(page) => glossaryState.setQuery({ page })}
              onProfileChange={handleStyleProfileChange}
              onPreviewImport={glossaryState.previewImport}
              onPreviewMerge={glossaryState.previewMerge}
              onQueryChange={glossaryState.setQuery}
              onRejectTerm={handleGlossaryReject}
              onReextractChapter={async (bookId, chapterId) => {
                const result = await session.client.reextractChapterGlossary(bookId, chapterId);
                await glossaryState.refresh();
                return result;
              }}
              onRestoreTerm={(termId) => handleGlossaryPhase4(
                () => glossaryState.restoreTerm(termId), 'Glossary restore failed',
              )}
              onSaveAndApproveTerm={handleGlossarySaveAndApprove}
              onSaveExtractionSettings={(bookId, settings) => (
                session.client.updateBookGlossarySettings(bookId, settings)
              )}
              onUpdateTerm={handleGlossaryTermUpdate}
              page={glossaryState.page}
              pages={glossaryState.pages}
              perPage={glossaryState.perPage}
              profiles={styleState.profiles.data}
              providers={providersState.providers.data}
              query={glossaryState.query}
              selectedProfileId={styleState.selectedStyleProfileId}
              total={glossaryState.total}
            />
          </>
        );
      case 'providers':
        return (
          <>
            {statusMessages}
            <ProvidersView
              keySaveError={providersState.keySaveError}
              keySaveMessage={providersState.keySaveMessage}
              keySaveState={providersState.keySaveState}
              onSaveProviderKey={handleSaveProviderKey}
              onTestProvider={handleTestProvider}
              providers={providersState.providers.data}
              testError={providersState.testError}
              testResult={providersState.testResult}
              testState={providersState.testState}
              usage={providersState.usage}
            />
          </>
        );
      case 'jobs':
        return (
          <>
            {statusMessages}
            <JobsView
              activeJob={jobState.activeJob}
              attempts={jobAttemptsState.attempts}
              logs={jobLogsState.logs}
              jobs={jobsHistoryState.jobs}
              onCancelJob={handleCancelJob}
              onOpenProviders={() => setActiveView('providers')}
              onRefresh={handleRefreshJobsView}
              onRetryTtsChunks={handleRetryTtsChunks}
              ttsJob={ttsJobStatus}
              ttsRetrying={ttsRetrying}
            />
          </>
        );
      case 'status':
        return (
          <>
            {statusMessages}
            <StatusSettingsView
              backupBusy={backupBusy}
              backupError={backupError || backupListError}
              backupItems={backups}
              backupJob={backupJob}
              backupListLoading={backupListLoading}
              error={systemStatus.error}
              loading={systemStatus.state === 'loading'}
              onCreateBackup={() => {
                void handleCreateBackup();
              }}
              onCreateEncryptedBackup={() => {
                void handleCreateEncryptedBackup();
              }}
              onCancelBackup={() => {
                void handleCancelJob();
              }}
              onDownloadBackup={(filename) => {
                void handleDownloadBackup(filename);
              }}
              onRefresh={loadSystemStatus}
              onRefreshIntervalChange={setStatusRefreshSeconds}
              onRetryJob={handleRetryFailedJob}
              refreshIntervalSeconds={statusRefreshSeconds}
              retryLoading={Boolean(
                retryLoadingJobId
                && retryLoadingJobId === systemStatus.data?.last_failed_job?.job_id,
              )}
              status={systemStatus.data}
            />
            <PwaInstallPrompt />
          </>
        );
      case 'export':
        return (
          <>
            {statusMessages}
            <ExportView
              activeBookId={activeBookId}
              audioBatchBusy={jobBusy}
              books={books}
              error={exportError}
              lastExport={lastExport}
              loading={exportLoading}
              onBookChange={handleSelectBook}
              onCreateAudioBatch={(bookId, missingAudioCount) => {
                void handleCreateAudioBatch(bookId, missingAudioCount);
              }}
              onExport={handleExportBook}
            />
          </>
        );
      case 'workbench':
      default:
        return workbench;
    }
  }

  function renderWorkflowView(view: WorkflowView) {
    return (
      <Suspense fallback={<p className="status-chip workflow-status">Đang tải giao diện</p>}>
        {renderWorkflowViewContent(view)}
      </Suspense>
    );
  }

  return (
    <>
      <PwaNetworkStatus />
      <WorkflowShell
        activeView={activeView}
        apiBaseUrl={API_BASE_URL}
        apiStatus={
          systemStatus.state === 'loading'
            ? 'checking'
            : systemStatus.data?.api_ready
              ? 'ready'
              : systemStatus.state === 'error'
                ? 'offline'
                : 'checking'
        }
        onLogout={handleLogout}
        onOpenImport={() => setActiveView('import')}
        onViewChange={setActiveView}
        renderView={renderWorkflowView}
      />
      {deleteConfirmation ? (
        <DeleteConfirmDialog
          confirmation={deleteConfirmation}
          loading={backendLoading}
          onCancel={() => setDeleteConfirmation(null)}
          onConfirm={handleConfirmDelete}
        />
      ) : null}
    </>
  );
}

export default function App() {
  if (PUBLIC_REVIEW_MODE && reviewModeRequested()) {
    return (
      <>
        <PwaInstallPrompt />
        <PwaNetworkStatus />
        <ReviewModeApp apiBaseUrl={API_BASE_URL} />
      </>
    );
  }

  return <AuthenticatedApp />;
}
