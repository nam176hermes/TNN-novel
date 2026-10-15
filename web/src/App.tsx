import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { resolveApiBaseUrl } from './api/baseUrl';
import type { Chapter } from './api/types';
import LoginPanel from './components/LoginPanel';
import PwaInstallPrompt from './components/PwaInstallPrompt';
import PwaNetworkStatus from './components/PwaNetworkStatus';
import ReviewModeApp from './components/ReviewModeApp';
import type { WorkbenchDashboardData } from './components/WorkbenchView';
import WorkflowShell, { type WorkflowView } from './components/WorkflowShell';
import { isAuthError } from './state/appWorkflow';
import { readerChapterRevision } from './state/readerCache';
import { clearReaderPrivateData } from './state/readerPrivateData';
import {
  chooseLatestReaderProgressSnapshot,
  loadReaderProgressSnapshot,
  remoteReaderProgressToSnapshot,
  resolveReaderChapterId,
  saveReaderProgress,
  saveReaderProgressSnapshot,
} from './state/readerProgress';
import { loadReaderResume, saveReaderResume } from './state/readerResume';
import { translationPresets } from './state/translationPresets';
import { formatError } from './state/types';
import { useAppImport } from './state/useAppImport';
import { useAppJobs } from './state/useAppJobs';
import { useAppOperations } from './state/useAppOperations';
import { useGlossary } from './state/useGlossary';
import { useLibrary } from './state/useLibrary';
import { useLibraryCatalog } from './state/useLibraryCatalog';
import { useLibraryMutations, type DeleteConfirmation } from './state/useLibraryMutations';
import { useProviders } from './state/useProviders';
import { useReaderBootstrap, useReaderChapterData } from './state/useReaderChapterData';
import { useSession } from './state/useSession';
import { useSourceManagement } from './state/useSourceManagement';
import { useStyleProfiles } from './state/useStyleProfiles';
import { useWorkbenchActions } from './state/useWorkbenchActions';
import './styles.css';

const API_BASE_URL = resolveApiBaseUrl(import.meta.env.VITE_API_BASE_URL);
const AUTH_DISABLED = ['1', 'true', 'yes', 'on'].includes(
  String(import.meta.env.VITE_DISABLE_AUTH ?? '').trim().toLowerCase(),
);
const PUBLIC_REVIEW_MODE = ['1', 'true', 'yes', 'on'].includes(
  String(import.meta.env.VITE_PUBLIC_REVIEW_MODE ?? '').trim().toLowerCase(),
);
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
  const [activeView, setActiveView] = useState<WorkflowView>(restoreOfflineReader ? 'reader' : 'library');
  const readerBootstrap = useReaderBootstrap(session.client, session.isAuthenticated);
  const bookOpenGenerationRef = useRef(0);
  const [workbenchChapterId, setWorkbenchChapterId] = useState<number | null>(null);
  const [backendLoading, setBackendLoading] = useState(false);
  const [workbenchMode, setWorkbenchMode] = useState<'edit' | 'reader'>('edit');
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
      content_html_path: resume.contentRevision.startsWith('revision:') ? null : resume.contentRevision || null,
      content_revision: resume.contentRevision.startsWith('revision:') ? Number(resume.contentRevision.slice(9)) : undefined,
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
      contentRevision: readerChapterRevision(selectedChapter),
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
    { cacheOwnership: activeView === 'reader' ? 'external' : 'internal', sourceEnabled: activeView === 'workbench' },
  );
  const chapterText = readerChapterData.text;
  const catalog = useLibraryCatalog({ session, expireSession, activeView, library });
  const { translatedBooks, rawBacklogChapters, rawBacklogInfo, rawPage, setRawPage, loadTranslatedBooks, loadRawBacklog } = catalog;
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
  );
  const activeBookId = library.selectedBookId;
  const textLoading = chapterText.state === 'loading';
  const workbenchChapter = workbenchChapterSelected ? selectedChapter : null;

  const workflowOptions = { session, expireSession, setBackendError, setBackendSuccess,
    setBackendLoading, handleJobError };
  const {
    selectedPresetId, setSelectedPresetId, jobState, jobAttemptsState, jobLogsState, jobsHistoryState,
    ttsJobStatus, ttsRetrying, handleEstimateSelectedChapter, handleTranslateSelectedChapter,
    handleBatchTranslateBook, rawBatchLoading, handleCreateAudioBatch, handleRunQa, handleCancelJob, handleRetryTtsChunks,
  } = useAppJobs({ ...workflowOptions, ...catalog, activeView, setActiveView, library,
    chapterText, qaState, providersState, styleState, selectedChapter, workbenchChapter });
  const {
    exportLoading, exportError, lastExport, backupError, backupListError, backupListLoading,
    backups, backupJob, backupBusy, systemStatus, statusRefreshSeconds, setStatusRefreshSeconds,
    retryLoadingJobId, loadSystemStatus, handleRetryFailedJob,
    handleExportBook, handleCreateBackup, handleCreateEncryptedBackup, handleDownloadBackup,
  } = useAppOperations({ ...workflowOptions, activeView, library, jobState });
  const {
    ebookImportHistory, ebookInboxDirectory, ebookInboxFiles, ebookInboxError, loadEbookInbox,
    handleImportPaste, handleImportFile, handleImportWizardText, handleWizardTranslationJob,
    handleWizardTtsJob, handleImportUrlPreview, handleStartImportUrl,
    handlePreviewTranslatedEbook, handlePreviewInboxEbook, handleImportTranslatedEbook,
  } = useAppImport({ ...workflowOptions, ...catalog, activeView, setActiveView, setWorkbenchChapterId,
    library, jobState, selectedPresetId, selectedStyleProfileId: styleState.selectedStyleProfileId });
  const {
    sourceCapabilities, sourceCapabilitiesState, sourceCapabilitiesError, loadSourceCapabilities,
    loadSourceCatalog, checkSourceCatalogEntry, loadSourceAdapterCandidates, createSourceAdapterCandidate,
    importManagedSources, testManagedSource, verifyManagedSource, setManagedSourceStatus,
  } = useSourceManagement({ session, expireSession, activeView });

  const {
    handleApplyQaFix, handleSearchTm, handleStyleProfileChange, handleGlossaryTermUpdate,
    handleGlossaryLockToggle, handleGlossaryApprove, handleGlossaryReject,
    handleGlossarySaveAndApprove, handleTestProvider, handleSaveProviderKey, handleSaveTranslation,
  } = useWorkbenchActions({ ...workflowOptions, chapterText, selectedChapter, library,
    providersState, styleState, glossaryState, rawBacklogChapters, loadRawBacklog });
  const {
    deleteConfirmation, requestDeleteTranslation, requestDeleteChapter, requestDeleteBook,
    handleUpdateBookCover, handleConfirmDelete, dismissDeleteConfirmation,
  } = useLibraryMutations({ ...workflowOptions, ...catalog, library, selectedChapter,
    workbenchChapterId, setWorkbenchChapterId, chapterText, providersState });

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
    const generation = ++bookOpenGenerationRef.current;
    const readerStateRequest = readerBootstrap.load(bookId);
    const loadedChapters = await library.refreshChapters(bookId);
    if (generation !== bookOpenGenerationRef.current) return null;
    let preferredChapterId = chapterId;
    if (preferredChapterId === null || preferredChapterId === undefined) {
      try {
        const readerState = await readerStateRequest;
        if (generation !== bookOpenGenerationRef.current) return null;
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
      rawBookCount: rawBacklogInfo.total_books,
      rawChapterCount: rawBacklogInfo.total_chapters,
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
    rawBacklogInfo,
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
          onTranslatedTitleChange={chapterText.setTranslatedTitle}
          onViewModeChange={setWorkbenchMode}
          selectedPresetId={selectedPresetId}
          selectedStyleProfileId={styleState.selectedStyleProfileId}
          sourceState={workbenchChapter ? chapterText.state : 'idle'}
          sourceText={workbenchChapter ? chapterText.sourceText : ''}
          styleProfiles={styleState.profiles.data}
          translationPresets={translationPresets}
          translateDisabledReason={translateDisabledReason}
          translationText={workbenchChapter ? chapterText.translationText : ''}
          translatedTitle={chapterText.translatedTitle}
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
              batchBusy={jobBusy || rawBatchLoading}
              books={books}
              chapters={rawBacklogChapters}
              backlog={rawBacklogInfo}
              page={rawPage}
              onPageChange={setRawPage}
              onBatchTranslateBook={(bookId) => { void handleBatchTranslateBook(bookId); }}
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
              readerBootstrap={readerBootstrap.current}
              books={translatedBooks.data}
              chapters={chapters}
              contentHtml={chapterText.contentHtml}
              qaError={qaState.error}
              qaReport={qaState.report}
              qaState={qaState.state}
              selectedChapter={selectedChapter}
              selectedChapterId={selectedChapterId}
              sourceText={chapterText.sourceText}
              sourceError={chapterText.sourceError}
              onLoadSource={chapterText.loadSource}
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
              glossaryTerms={glossaryState.terms.data}
              onApproveTerm={handleGlossaryApprove}
              onLockToggle={handleGlossaryLockToggle}
              onProfileChange={handleStyleProfileChange}
              onRejectTerm={handleGlossaryReject}
              onSaveAndApproveTerm={handleGlossarySaveAndApprove}
              onUpdateTerm={handleGlossaryTermUpdate}
              profiles={styleState.profiles.data}
              selectedProfileId={styleState.selectedStyleProfileId}
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
          onCancel={dismissDeleteConfirmation}
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
