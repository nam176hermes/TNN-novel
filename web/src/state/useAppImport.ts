import type { Dispatch, SetStateAction } from 'react';
import { useCallback, useEffect, useState } from 'react';
import type {
  EbookImportHistoryRun, EbookImportRequest,
  EbookInboxFile,
  EbookPreview, EbookSplitMode,
  ImportFileRequest, ImportPasteRequest, ImportResponse, ImportUrlRequest, JobStartResponse,
  SourcePreview, WizardTextImportRequest, WizardTextImportResult
} from '../api/types';
import type { WorkflowView } from '../components/WorkflowShell';
import { isAuthError, type AppWorkflowOptions } from './appWorkflow';
import { translationPresets } from './translationPresets';
import { formatError } from './types';
import type { useAppJobs } from './useAppJobs';
import type { useLibrary } from './useLibrary';
import type { useLibraryCatalog } from './useLibraryCatalog';

export function useAppImport({ session, expireSession, setBackendError, setBackendSuccess,
  setBackendLoading, handleJobError, activeView, setActiveView, setWorkbenchChapterId, library,
  rawBacklogChapters, translatedBooks, loadRawBacklog, loadTranslatedBooks, jobState,
  selectedPresetId, selectedStyleProfileId }: AppWorkflowOptions & ReturnType<typeof useLibraryCatalog> & {
    activeView: WorkflowView;
    setActiveView(view: WorkflowView): void;
    setWorkbenchChapterId: Dispatch<SetStateAction<number | null>>;
    library: ReturnType<typeof useLibrary>;
    jobState: ReturnType<typeof useAppJobs>['jobState'];
    selectedPresetId: string;
    selectedStyleProfileId: string;
  }) {
  const [ebookImportHistory, setEbookImportHistory] = useState<EbookImportHistoryRun[]>([]);
  const [ebookInboxDirectory, setEbookInboxDirectory] = useState('inbox/ebooks');
  const [ebookInboxFiles, setEbookInboxFiles] = useState<EbookInboxFile[]>([]);
  const [ebookInboxError, setEbookInboxError] = useState('');
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
        selectedStyleProfileId || undefined,
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

  return {
    ebookImportHistory, ebookInboxDirectory, ebookInboxFiles, ebookInboxError, loadEbookInbox,
    handleImportPaste, handleImportFile, handleImportWizardText, handleWizardTranslationJob,
    handleWizardTtsJob, handleImportUrlPreview, handleStartImportUrl,
    handlePreviewTranslatedEbook, handlePreviewInboxEbook, handleImportTranslatedEbook,
  };
}
