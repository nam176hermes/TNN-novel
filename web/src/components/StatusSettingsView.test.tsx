import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { SystemBackupItem, SystemStatus } from '../api/types';
import StatusSettingsView from './StatusSettingsView';

afterEach(cleanup);

const status: SystemStatus = {
  active_jobs: 1,
  active_provider: 'gemini',
  api_ready: true,
  app_version: '0.1.0',
  asset_protection_enabled: true,
  backup_recommendation: 'System backup is separate from book export. Run scripts/backup-local.sh before upgrades or public deploy changes.',
  build: 'phase1',
  cache_count: 4,
  cache_size_bytes: 2048,
  data_directory_available: true,
  data_size_bytes: 8192,
  database_available: true,
  db_size_bytes: 4096,
  last_failed_job: {
    job_id: 'job-restarted',
    status: 'failed',
    progress: 2,
    total: 10,
    message: 'Server restarted during job. Please retry the job.',
    error: 'Server restarted during job',
  },
  ollama_host: 'http://localhost:11434/v1',
  ollama_model: 'qwen3:14b',
  public_deploy: true,
  queued_jobs: 0,
  recent_operational_errors: [],
  retrying_jobs: 0,
  running_jobs: 1,
  interrupted_jobs: 0,
  failed_jobs: 1,
  upload_max_bytes: 104857600,
  storage_health: 'healthy',
  storage_label: 'Configured data storage',
};

const latestBackup: SystemBackupItem = {
  created_at: '2026-07-09T10:00:00Z',
  download_url: '/api/system/backups/novel-pipeline-backup-test.tar.gz/download',
  encrypted: false,
  excluded_modules: ['exports', 'job_logs', 'secrets'],
  filename: 'novel-pipeline-backup-test.tar.gz',
  included_modules: ['database', 'uploads', 'covers', 'book_assets', 'glossary_qa', 'managed_sources', 'settings', 'audio'],
  manifest: {},
  secrets_included: false,
  size_bytes: 4096,
};

describe('StatusSettingsView', () => {
  it('renders runtime status without exposing secrets', () => {
    const onRetryJob = vi.fn();
    render(
      <StatusSettingsView
        error=""
        loading={false}
        onRefresh={() => undefined}
        onRetryJob={onRetryJob}
        retryLoading={false}
        status={status}
      />,
    );

    expect(screen.getByRole('heading', { name: 'Trạng thái hệ thống' })).toBeVisible();
    expect(screen.getByText('Public deploy')).toBeVisible();
    expect(screen.getByText('Bật')).toBeVisible();
    expect(screen.getByText('API readiness')).toBeVisible();
    expect(screen.getByText('Sẵn sàng')).toBeVisible();
    expect(screen.getByText('Active provider')).toBeVisible();
    expect(screen.getByText('gemini')).toBeVisible();
    expect(screen.getByText('Upload max')).toBeVisible();
    expect(screen.getByText('100.0 MB')).toBeVisible();
    expect(screen.getByText('Asset protection')).toBeVisible();
    expect(screen.getByText('Đang bảo vệ')).toBeVisible();
    expect(screen.getByText('Running jobs')).toBeVisible();
    expect(screen.getByText('1 / 1')).toBeVisible();

    const failedJob = screen.getByRole('region', { name: 'Job lỗi gần nhất' });
    expect(within(failedJob).getByText('Server đã restart khi job đang chạy. Hãy chạy lại job.')).toBeVisible();
    expect(screen.getByText('Database available')).toBeVisible();
    expect(screen.getByText('Data storage available')).toBeVisible();
    expect(screen.getByText('Configured data storage')).toBeVisible();
    expect(screen.queryByText(/\/home\/|\/mnt\/|[A-Z]:\\/)).not.toBeInTheDocument();
    expect(screen.getByText(/System backup is separate from book export/)).toBeVisible();
    expect(screen.queryByText(/api[_-]?key/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/sk-test|top-secret|provider-secret/i)).not.toBeInTheDocument();
  });

  it('shows durable job and operational error visibility', () => {
    const opsStatus = {
      ...status,
      active_jobs: 3,
      queued_jobs: 1,
      retrying_jobs: 1,
      interrupted_jobs: 1,
      failed_jobs: 2,
      recent_operational_errors: [
        {
          id: 7,
          event_type: 'provider_failure',
          severity: 'error',
          source: 'job_service',
          message: 'Provider attempt failed. Check server logs.',
          job_id: 'job-provider',
          details: { provider_id: 'gemini' },
          created_at: '2026-06-30T12:00:00Z',
        },
      ],
      recent_backup_events: [
        {
          id: 8,
          event_type: 'backup_success',
          severity: 'info',
          source: 'backup-local',
          message: 'Backup completed',
          job_id: '',
          details: { backup_name: 'novel-pipeline-backup-test.tar.gz' },
          created_at: '2026-06-30T12:01:00Z',
        },
      ],
    } as SystemStatus & {
      queued_jobs: number;
      retrying_jobs: number;
      interrupted_jobs: number;
      failed_jobs: number;
      recent_operational_errors: Array<Record<string, unknown>>;
      recent_backup_events: Array<Record<string, unknown>>;
    };

    render(
      <StatusSettingsView
        error=""
        loading={false}
        onRefresh={() => undefined}
        status={opsStatus}
      />,
    );

    expect(screen.getByText('Queued jobs')).toBeVisible();
    expect(screen.getByText('1 queued · 1 retrying')).toBeVisible();
    expect(screen.getByText('Interrupted / failed')).toBeVisible();
    expect(screen.getByText('1 interrupted · 2 failed')).toBeVisible();
    expect(screen.getByRole('region', { name: 'Recent operational errors' })).toBeVisible();
    expect(screen.getByText('provider_failure · job-provider')).toBeVisible();
    expect(screen.getByText('Provider attempt failed. Check server logs.')).toBeVisible();
    expect(screen.getByText('Last backup event: backup_success · Backup completed')).toBeVisible();
    expect(screen.queryByText(/provider-secret|sk-test/i)).not.toBeInTheDocument();
  });

  it('offers retry for the last failed job with a loading state', async () => {
    const onRetryJob = vi.fn().mockResolvedValue(undefined);
    const { rerender } = render(
      <StatusSettingsView
        error=""
        loading={false}
        onRefresh={() => undefined}
        onRetryJob={onRetryJob}
        retryLoading={false}
        status={status}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Chạy lại' }));
    expect(onRetryJob).toHaveBeenCalledWith('job-restarted');

    rerender(
      <StatusSettingsView
        error=""
        loading={false}
        onRefresh={() => undefined}
        onRetryJob={onRetryJob}
        retryLoading
        status={status}
      />,
    );

    expect(screen.getByRole('button', { name: 'Đang chạy lại...' })).toBeDisabled();
  });

  it('wires auto-refresh interval and backup guidance controls', async () => {
    const onRefreshIntervalChange = vi.fn();
    const onCreateBackup = vi.fn();
    const onCreateEncryptedBackup = vi.fn();
    const onDownloadBackup = vi.fn();
    render(
      <StatusSettingsView
        backupBusy={false}
        error=""
        latestBackup={latestBackup}
        loading={false}
        onCreateBackup={onCreateBackup}
        onCreateEncryptedBackup={onCreateEncryptedBackup}
        onDownloadBackup={onDownloadBackup}
        onRefresh={() => undefined}
        onRefreshIntervalChange={onRefreshIntervalChange}
        refreshIntervalSeconds={10}
        status={status}
      />,
    );

    await userEvent.selectOptions(screen.getByLabelText('Chu kỳ tự động làm mới'), '30');
    expect(onRefreshIntervalChange).toHaveBeenCalledWith(30);

    await userEvent.click(screen.getByRole('button', { name: 'Mở hướng dẫn' }));
    expect(screen.getByText(/Dừng server trước khi restore/)).toBeVisible();
    expect(screen.getByText(/Secrets và provider API keys bị loại khỏi backup mặc định/)).toBeVisible();

    await userEvent.click(screen.getByRole('button', { name: 'Tạo backup' }));
    expect(onCreateBackup).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole('button', { name: 'Backup mã hóa' }));
    expect(onCreateEncryptedBackup).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole('button', { name: 'Tải backup' }));
    expect(onDownloadBackup).toHaveBeenCalledWith('novel-pipeline-backup-test.tar.gz');
  });

  it('shows loading and error states', () => {
    render(
      <StatusSettingsView
        error="Không kết nối được API. Kiểm tra server local, Cloudflare Tunnel, hoặc mạng."
        loading
        onRefresh={() => undefined}
        status={null}
      />,
    );

    expect(screen.getByText('Đang tải trạng thái hệ thống')).toBeVisible();
    expect(screen.getByRole('alert')).toHaveTextContent('Không kết nối được API');
  });
});
