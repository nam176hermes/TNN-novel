import { useCallback, useEffect, useRef, useState } from 'react';
import type { ExportFormat, ExportResponse, SystemBackupItem, SystemStatus } from '../api/types';
import type { WorkflowView } from '../components/WorkflowShell';
import { isAuthError, type AppWorkflowOptions } from './appWorkflow';
import { formatError, type AsyncState } from './types';
import type { useAppJobs } from './useAppJobs';
import type { useLibrary } from './useLibrary';

const emptySystemStatus: AsyncState<SystemStatus | null> = { data: null, error: '', state: 'idle' };
export function useAppOperations({ session, expireSession, setBackendError, setBackendSuccess,
  activeView, library, jobState }: Pick<AppWorkflowOptions,
    'session' | 'expireSession' | 'setBackendError' | 'setBackendSuccess'> & {
    activeView: WorkflowView;
    library: ReturnType<typeof useLibrary>;
    jobState: ReturnType<typeof useAppJobs>['jobState'];
  }) {
  const [exportLoading, setExportLoading] = useState(false);
  const [exportError, setExportError] = useState('');
  const [lastExport, setLastExport] = useState<ExportResponse | null>(null);
  const [backupJobId, setBackupJobId] = useState('');
  const [backupError, setBackupError] = useState('');
  const [backupListError, setBackupListError] = useState('');
  const [backupListLoading, setBackupListLoading] = useState(false);
  const [backups, setBackups] = useState<SystemBackupItem[]>([]);
  const handledBackupJobIdRef = useRef('');
  const [systemStatus, setSystemStatus] = useState<AsyncState<SystemStatus | null>>(emptySystemStatus);
  const [statusRefreshSeconds, setStatusRefreshSeconds] = useState(10);
  const [retryLoadingJobId, setRetryLoadingJobId] = useState('');
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

  const backupJob = backupJobId && jobState.activeJob?.job_id === backupJobId
    ? jobState.activeJob
    : null;
  const backupBusy = Boolean(
    backupJob && ['queued', 'running'].includes(backupJob.status.toLowerCase()),
  );
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

  return {
    exportLoading, exportError, lastExport, backupError, backupListError, backupListLoading,
    backups, backupJob, backupBusy, systemStatus, statusRefreshSeconds, setStatusRefreshSeconds,
    retryLoadingJobId, loadSystemStatus, handleRetryFailedJob,
    handleExportBook, handleCreateBackup, handleCreateEncryptedBackup, handleDownloadBackup,
  };
}
