import { useRef, useState, type ChangeEvent, type DragEvent } from 'react';
import { ApiError } from '../../api/client';
import type { EbookDuplicateStrategy, EbookImportResult, EbookPreview, EbookSplitMode } from '../../api/types';
import { errorMessage, formatBytes } from './importLabels';
import type { EbookPreviewFile, EbookPreviewState, EbookSource, ImportPanelProps } from './types';

const MAX_BROWSER_EBOOK_UPLOAD_BYTES = 95 * 1024 * 1024;
const BLOCKING_EBOOK_WARNING_TYPES = new Set(['unreadable_ebook']);
export function useEbookImport({ ebookInboxDirectory, ebookInboxFiles, loading, duplicateStrategy, targetBookId,
  setDuplicateStrategy, setTargetBookId, onPreviewInboxEbook, onPreviewTranslatedEbook,
  onImportTranslatedEbook }: Pick<ImportPanelProps,
  'onPreviewInboxEbook' | 'onPreviewTranslatedEbook' | 'onImportTranslatedEbook'> & {
  ebookInboxDirectory: string;
  ebookInboxFiles: NonNullable<ImportPanelProps['ebookInboxFiles']>;
  loading: boolean;
  duplicateStrategy: EbookDuplicateStrategy;
  targetBookId: string;
  setDuplicateStrategy(strategy: EbookDuplicateStrategy): void;
  setTargetBookId(bookId: string): void;
}) {
  const [ebookSource, setEbookSource] = useState<EbookSource>('upload');
  const [ebookFile, setEbookFile] = useState<File | null>(null);
  const [selectedInboxFile, setSelectedInboxFile] = useState('');
  const [ebookPreview, setEbookPreview] = useState<EbookPreview | null>(null);
  const [ebookPreviewState, setEbookPreviewState] = useState<EbookPreviewState>('idle');
  const [ebookPreviewError, setEbookPreviewError] = useState('');
  const [confirmedExistingBookId, setConfirmedExistingBookId] = useState<number | null>(null);
  const [ebookSubmissionBlocked, setEbookSubmissionBlocked] = useState(false);
  const ebookPreviewRequestToken = useRef(0);
  const [lastEbookImportResult, setLastEbookImportResult] = useState<EbookImportResult | null>(null);
  const [splitMode, setSplitMode] = useState<EbookSplitMode>('auto');
  const selectedInboxEntry = ebookInboxFiles.find((entry) => entry.name === selectedInboxFile) ?? null;
  const selectedEbookFile: EbookPreviewFile | null =
    ebookSource === 'inbox'
      ? selectedInboxEntry
        ? { name: selectedInboxEntry.name, size: selectedInboxEntry.size }
        : null
      : ebookFile;
  const ebookHasBlockingWarning = Boolean(
    ebookPreview?.warnings?.some((warning) => BLOCKING_EBOOK_WARNING_TYPES.has(warning.type)),
  );
  const existingBookId = ebookPreview?.dry_run?.existing_book_id ?? null;
  const requiresExistingBookConfirmation = Boolean(
    ebookPreview?.dry_run?.requires_existing_book_confirmation,
  );
  const existingBookConfirmed = !requiresExistingBookConfirmation
    || (existingBookId !== null && confirmedExistingBookId === existingBookId);
  const ebookPreviewRetryAvailable =
    !loading
    && ebookPreviewState !== 'loading'
    && (ebookSource === 'inbox'
      ? Boolean(selectedInboxFile && onPreviewInboxEbook)
      : Boolean(
        ebookFile
        && ebookFile.size <= MAX_BROWSER_EBOOK_UPLOAD_BYTES
        && onPreviewTranslatedEbook,
      ));
  function parsedTargetBookId(value = targetBookId): number | null {
    return value ? Number.parseInt(value, 10) : null;
  }

  function invalidateEbookPreviewRequests(): number {
    ebookPreviewRequestToken.current += 1;
    return ebookPreviewRequestToken.current;
  }

  async function previewEbookFile(
    nextFile: File,
    nextSplitMode: EbookSplitMode,
    nextDuplicateStrategy = duplicateStrategy,
    nextTargetBookId = targetBookId,
  ): Promise<void> {
    const requestToken = invalidateEbookPreviewRequests();
    setConfirmedExistingBookId(null);
    setEbookPreview(null);
    setEbookPreviewError('');
    setEbookSubmissionBlocked(false);

    if (!onPreviewTranslatedEbook) {
      setEbookPreviewState('error');
      setEbookPreviewError('Ebook preview is not available.');
      return;
    }

    setEbookPreviewState('loading');
    try {
      const preview = await onPreviewTranslatedEbook(nextFile, nextSplitMode, {
        duplicateStrategy: nextDuplicateStrategy,
        targetBookId: parsedTargetBookId(nextTargetBookId),
      });
      if (requestToken !== ebookPreviewRequestToken.current) return;
      setEbookPreview(preview);
      setEbookPreviewState('ready');
    } catch (error) {
      if (requestToken !== ebookPreviewRequestToken.current) return;
      setEbookPreviewState('error');
      setEbookPreviewError(errorMessage(error));
    }
  }

  async function previewInboxFile(
    filename: string,
    nextSplitMode: EbookSplitMode,
    nextDuplicateStrategy = duplicateStrategy,
    nextTargetBookId = targetBookId,
  ): Promise<void> {
    const requestToken = invalidateEbookPreviewRequests();
    setConfirmedExistingBookId(null);
    setEbookPreview(null);
    setEbookPreviewError('');
    setEbookSubmissionBlocked(false);

    if (!filename) {
      setEbookPreviewState('idle');
      return;
    }

    if (!onPreviewInboxEbook) {
      setEbookPreviewState('error');
      setEbookPreviewError('Server inbox preview is not available.');
      return;
    }

    setEbookPreviewState('loading');
    try {
      const preview = await onPreviewInboxEbook(filename, nextSplitMode, {
        duplicateStrategy: nextDuplicateStrategy,
        targetBookId: parsedTargetBookId(nextTargetBookId),
      });
      if (requestToken !== ebookPreviewRequestToken.current) return;
      setEbookPreview(preview);
      setEbookPreviewState('ready');
    } catch (error) {
      if (requestToken !== ebookPreviewRequestToken.current) return;
      setEbookPreviewState('error');
      setEbookPreviewError(errorMessage(error));
    }
  }

  function handleEbookFile(nextFile: File | null): void {
    invalidateEbookPreviewRequests();
    setConfirmedExistingBookId(null);
    setEbookSource('upload');
    setEbookFile(nextFile);
    setSelectedInboxFile('');
    setEbookPreview(null);
    setEbookPreviewError('');
    setEbookSubmissionBlocked(false);
    setLastEbookImportResult(null);
    if (nextFile && nextFile.size > MAX_BROWSER_EBOOK_UPLOAD_BYTES) {
      setEbookPreviewState('error');
      setEbookPreviewError(
        `File lớn hơn 95 MB (${formatBytes(nextFile.size)}). Cloudflare có thể chặn upload lớn; hãy copy file vào ${ebookInboxDirectory} rồi chọn Server inbox.`,
      );
      return;
    }
    setEbookPreviewState(nextFile ? 'loading' : 'idle');
    if (nextFile) {
      void previewEbookFile(nextFile, splitMode);
    }
  }

  function handleEbookFileChange(event: ChangeEvent<HTMLInputElement>): void {
    handleEbookFile(event.target.files?.[0] ?? null);
  }

  function handleEbookDrop(event: DragEvent<HTMLLabelElement>): void {
    event.preventDefault();
    handleEbookFile(event.dataTransfer.files[0] ?? null);
  }

  function handleEbookSourceChange(nextSource: EbookSource): void {
    invalidateEbookPreviewRequests();
    setConfirmedExistingBookId(null);
    setEbookSource(nextSource);
    setEbookPreview(null);
    setEbookPreviewError('');
    setEbookSubmissionBlocked(false);
    setLastEbookImportResult(null);
    if (nextSource === 'upload') {
      setSelectedInboxFile('');
      setEbookPreviewState('idle');
      return;
    }
    setEbookFile(null);
    setEbookPreviewState(selectedInboxFile ? 'loading' : 'idle');
    if (selectedInboxFile) {
      void previewInboxFile(selectedInboxFile, splitMode);
    }
  }

  function handleInboxFileChange(event: ChangeEvent<HTMLSelectElement>): void {
    const filename = event.target.value;
    invalidateEbookPreviewRequests();
    setConfirmedExistingBookId(null);
    setEbookSource('inbox');
    setEbookFile(null);
    setSelectedInboxFile(filename);
    setLastEbookImportResult(null);
    void previewInboxFile(filename, splitMode);
  }

  function handleSplitModeChange(event: ChangeEvent<HTMLSelectElement>): void {
    const nextSplitMode = event.target.value as EbookSplitMode;
    invalidateEbookPreviewRequests();
    setConfirmedExistingBookId(null);
    setSplitMode(nextSplitMode);
    if (ebookSource === 'inbox' && selectedInboxFile) {
      void previewInboxFile(selectedInboxFile, nextSplitMode);
    } else if (ebookFile && ebookFile.size <= MAX_BROWSER_EBOOK_UPLOAD_BYTES) {
      void previewEbookFile(ebookFile, nextSplitMode);
    }
  }

  function handleTargetBookChange(event: ChangeEvent<HTMLSelectElement>): void {
    const nextTargetBookId = event.target.value;
    invalidateEbookPreviewRequests();
    setConfirmedExistingBookId(null);
    setTargetBookId(nextTargetBookId);
    if (ebookSource === 'inbox' && selectedInboxFile) {
      void previewInboxFile(selectedInboxFile, splitMode, duplicateStrategy, nextTargetBookId);
    } else if (ebookFile && ebookFile.size <= MAX_BROWSER_EBOOK_UPLOAD_BYTES) {
      void previewEbookFile(ebookFile, splitMode, duplicateStrategy, nextTargetBookId);
    }
  }

  function handleDuplicateStrategyChange(nextDuplicateStrategy: EbookDuplicateStrategy): void {
    invalidateEbookPreviewRequests();
    setConfirmedExistingBookId(null);
    setDuplicateStrategy(nextDuplicateStrategy);
    setLastEbookImportResult(null);
    if (ebookSource === 'inbox' && selectedInboxFile) {
      void previewInboxFile(selectedInboxFile, splitMode, nextDuplicateStrategy, targetBookId);
    } else if (ebookFile && ebookFile.size <= MAX_BROWSER_EBOOK_UPLOAD_BYTES) {
      void previewEbookFile(ebookFile, splitMode, nextDuplicateStrategy, targetBookId);
    }
  }

  function retryEbookPreview(): void {
    if (!ebookPreviewRetryAvailable) return;
    if (ebookSource === 'inbox') {
      void previewInboxFile(selectedInboxFile, splitMode, duplicateStrategy, targetBookId);
      return;
    }
    if (ebookFile) {
      void previewEbookFile(ebookFile, splitMode, duplicateStrategy, targetBookId);
    }
  }

  async function submitTranslatedEbook(): Promise<void> {
    if (!onImportTranslatedEbook) return;
    if (ebookSource === 'upload' && !ebookFile) return;
    if (ebookSource === 'inbox' && !selectedInboxFile) return;

    setEbookPreviewError('');
    try {
      const result = await onImportTranslatedEbook({
        ...(ebookSource === 'upload'
          ? { file: ebookFile ?? undefined, uploadId: ebookPreview?.upload_id }
          : { inboxFile: ebookPreview?.inbox_file ?? selectedInboxFile }),
        duplicateStrategy,
        splitMode,
        targetBookId: targetBookId ? Number.parseInt(targetBookId, 10) : undefined,
        ...(confirmedExistingBookId !== null && confirmedExistingBookId === existingBookId
          ? { confirmedExistingBookId }
          : {}),
      });
      setLastEbookImportResult(result ?? null);
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        invalidateEbookPreviewRequests();
        setConfirmedExistingBookId(null);
        setEbookPreview(null);
        setEbookPreviewState('error');
        setEbookSubmissionBlocked(false);
      } else {
        setEbookSubmissionBlocked(true);
      }
      setEbookPreviewError(errorMessage(error));
    }
  }

  function leaveEbookMode(): void {
    invalidateEbookPreviewRequests();
    setConfirmedExistingBookId(null);
    setEbookPreview(null);
    setEbookPreviewState('idle');
    setEbookPreviewError('');
    setEbookSubmissionBlocked(false);
  }

  function enterEbookMode(): void {
    if (ebookSource === 'inbox' && selectedInboxFile) {
      void previewInboxFile(selectedInboxFile, splitMode, duplicateStrategy, targetBookId);
    } else if (ebookFile && ebookFile.size <= MAX_BROWSER_EBOOK_UPLOAD_BYTES) {
      void previewEbookFile(ebookFile, splitMode, duplicateStrategy, targetBookId);
    }
  }

  function cancelEbookPreview(): void {
    invalidateEbookPreviewRequests();
    setConfirmedExistingBookId(null);
  }

  return {
    ebookSource, ebookFile, selectedInboxFile, ebookPreview, ebookPreviewState, ebookPreviewError,
    confirmedExistingBookId, setConfirmedExistingBookId, ebookSubmissionBlocked,
    lastEbookImportResult, splitMode, selectedEbookFile, ebookHasBlockingWarning,
    existingBookConfirmed, ebookPreviewRetryAvailable,
    handleEbookFileChange, handleEbookDrop, handleEbookSourceChange, handleInboxFileChange,
    handleSplitModeChange, handleTargetBookChange, handleDuplicateStrategyChange,
    retryEbookPreview, submitTranslatedEbook, leaveEbookMode, enterEbookMode, cancelEbookPreview,
  };
}
