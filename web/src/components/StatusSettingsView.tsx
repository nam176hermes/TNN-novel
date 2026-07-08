import type { SystemStatus } from '../api/types';
import { formatError } from '../state/types';
import { useState } from 'react';
import {
  Activity,
  AlertTriangle,
  ArchiveRestore,
  Boxes,
  CheckCircle2,
  Cloud,
  Copy,
  Database,
  HardDrive,
  ListChecks,
  RefreshCw,
  ShieldCheck,
} from 'lucide-react';

type StatusSettingsViewProps = {
  error: string;
  loading: boolean;
  onRefresh(): void | Promise<void>;
  onRefreshIntervalChange?(seconds: number): void;
  onRetryJob?: (jobId: string) => void | Promise<void>;
  refreshIntervalSeconds?: number;
  retryLoading?: boolean;
  status: SystemStatus | null;
};

function formatBytes(value: number): string {
  if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  if (value >= 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${value.toLocaleString()} bytes`;
}

function yesNo(value: boolean, yes = 'Bật', no = 'Tắt'): string {
  return value ? yes : no;
}

function statusRows(status: SystemStatus) {
  const queuedJobs = status.queued_jobs ?? 0;
  const retryingJobs = status.retrying_jobs ?? 0;
  const interruptedJobs = status.interrupted_jobs ?? 0;
  const failedJobs = status.failed_jobs ?? 0;
  return [
    ['Public deploy', yesNo(status.public_deploy)],
    ['API readiness', status.api_ready ? 'Sẵn sàng' : 'Có lỗi'],
    ['Active provider', status.active_provider || 'Chưa chọn'],
    ['Upload max', formatBytes(status.upload_max_bytes)],
    ['Asset protection', yesNo(status.asset_protection_enabled, 'Đang bảo vệ', 'Chưa bật')],
    ['Running jobs', `${status.running_jobs.toLocaleString()} / ${status.active_jobs.toLocaleString()}`],
    ['Queued jobs', `${queuedJobs.toLocaleString()} queued · ${retryingJobs.toLocaleString()} retrying`],
    [
      'Interrupted / failed',
      `${interruptedJobs.toLocaleString()} interrupted · ${failedJobs.toLocaleString()} failed`,
    ],
    ['Version', [status.app_version, status.build].filter(Boolean).join(' · ') || '-'],
    ['Database', status.database_path || 'Ẩn trong public deploy'],
    ['Data directory', status.data_dir || '-'],
    ['Cache', `${status.cache_count.toLocaleString()} mục · ${formatBytes(status.cache_size_bytes)}`],
    ['Database size', formatBytes(status.db_size_bytes)],
  ];
}

export default function StatusSettingsView({
  error,
  loading,
  onRefresh,
  onRefreshIntervalChange,
  onRetryJob,
  refreshIntervalSeconds = 10,
  retryLoading = false,
  status,
}: StatusSettingsViewProps) {
  const [backupHelpOpen, setBackupHelpOpen] = useState(false);
  const failedJob = status?.last_failed_job ?? null;
  const failedJobMessage = failedJob?.error || failedJob?.message || '';
  const previousError = failedJob?.previous_error?.trim() ?? '';
  const retryCount = failedJob?.retry_count ?? 0;
  const recentOperationalErrors = status?.recent_operational_errors ?? [];
  const recentBackupEvent = status?.recent_backup_events?.[0] ?? null;
  const rows = status ? statusRows(status) : [];
  const firstColumnRows = rows.slice(0, 7);
  const secondColumnRows = rows.slice(7);

  return (
    <section aria-labelledby="system-status-title" className="workflow-management-view status-settings-view">
      <header className="management-view-header">
        <div>
          <p className="section-label">
            Runtime <span>/ Trạng thái hệ thống</span>
          </p>
          <h2 id="system-status-title">Trạng thái hệ thống</h2>
        </div>
        <div className="status-header-actions">
          <span className="auto-refresh-indicator">
            <i aria-hidden="true" />
            Tự động làm mới: {onRefreshIntervalChange ? 'đang bật' : 'thủ công'}
          </span>
          <select
            aria-label="Chu kỳ tự động làm mới"
            disabled={!onRefreshIntervalChange}
            onChange={(event) => onRefreshIntervalChange?.(Number(event.target.value))}
            value={refreshIntervalSeconds}
          >
            <option value={10}>10s</option>
            <option value={30}>30s</option>
            <option value={60}>60s</option>
          </select>
          <button
            className="secondary-action"
            disabled={loading}
            onClick={() => {
              void onRefresh();
            }}
            type="button"
          >
            <RefreshCw aria-hidden="true" size={16} />
            Làm mới
          </button>
        </div>
      </header>

      {loading ? <p className="status-chip">Đang tải trạng thái hệ thống</p> : null}
      {error ? <p className="status-error" role="alert">{error}</p> : null}

      {status ? (
        <>
          <section aria-label="Tổng quan hệ thống" className="panel status-overview-panel">
            <div className="panel-header">
              <h3>Tổng quan hệ thống</h3>
            </div>
            <div className="status-overview-grid">
              <article>
                <CheckCircle2 aria-hidden="true" size={22} />
                <span>API Readiness</span>
                <strong>{status.api_ready ? 'Ready' : 'Needs check'}</strong>
                <small>{status.api_ready ? 'Healthy' : 'Needs attention'}</small>
              </article>
              <article>
                <Cloud aria-hidden="true" size={22} />
                <span>Active Provider</span>
                <strong>{status.active_provider ? status.active_provider.toUpperCase() : 'None'}</strong>
                <small>{status.active_provider ? 'Online' : 'Offline'}</small>
              </article>
              <article>
                <Boxes aria-hidden="true" size={22} />
                <span>Running Jobs</span>
                <strong>{status.running_jobs.toLocaleString()} running</strong>
                <small>{status.running_jobs ? 'Busy' : 'Idle'}</small>
              </article>
              <article>
                <ListChecks aria-hidden="true" size={22} />
                <span>Queue</span>
                <strong>{(status.queued_jobs ?? 0).toLocaleString()}</strong>
                <small>Queued</small>
              </article>
              <article>
                <ShieldCheck aria-hidden="true" size={22} />
                <span>System</span>
                <strong>{status.asset_protection_enabled ? 'Bảo vệ' : 'Mở'}</strong>
                <small>{status.asset_protection_enabled ? 'Protected' : 'Open'}</small>
              </article>
            </div>
          </section>

          <section aria-label="Thông tin runtime" className="panel status-runtime-panel">
            <div className="panel-header">
              <h3>Thông tin Runtime</h3>
            </div>
            <div className="status-runtime-grid">
              {[firstColumnRows, secondColumnRows].map((column, index) => (
                <table className="provider-table status-settings-table" key={index}>
                  <tbody>
                    {column.map(([label, value]) => (
                      <tr key={label}>
                        <th scope="row">{label}</th>
                        <td>{value}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ))}
            </div>
          </section>

          <section aria-label="Hiệu suất hệ thống" className="panel status-performance-panel">
            <div className="panel-header">
              <h3>Hiệu suất hệ thống</h3>
            </div>
            <div className="status-performance-grid">
              <article>
                <ListChecks aria-hidden="true" size={18} />
                <span>Queue Length</span>
                <strong>{(status.queued_jobs ?? 0).toLocaleString()}</strong>
                <small>{status.active_jobs ? 'Có job' : 'Không có job'}</small>
                <i className="sparkline sparkline-blue" />
              </article>
              <article>
                <Activity aria-hidden="true" size={18} />
                <span>Active Jobs</span>
                <strong>{status.active_jobs.toLocaleString()}</strong>
                <small>{status.running_jobs.toLocaleString()} running</small>
                <i className="sparkline sparkline-green" />
              </article>
              <article>
                <Database aria-hidden="true" size={18} />
                <span>Cache Items</span>
                <strong>{status.cache_count.toLocaleString()}</strong>
                <small>cache mục</small>
                <i className="sparkline sparkline-purple" />
              </article>
              <article>
                <HardDrive aria-hidden="true" size={18} />
                <span>Disk Usage</span>
                <strong>{formatBytes(status.db_size_bytes)}</strong>
                <small>SQLite</small>
                <i className="sparkline sparkline-gold" />
              </article>
            </div>
          </section>
        </>
      ) : !loading ? (
        <p className="empty-detail">Chưa tải được trạng thái hệ thống.</p>
      ) : null}

      {failedJob ? (
        <section aria-label="Job lỗi gần nhất" className="panel failed-job-panel">
          <div className="section-heading-row">
            <div>
              <p className="section-label failed-job-label">
                <AlertTriangle aria-hidden="true" size={15} />
                Last failed job
              </p>
              <h3>{failedJob.job_id}</h3>
            </div>
            <div className="topbar-actions">
              <span className="status-chip status-chip-warning">{failedJob.status}</span>
              {onRetryJob ? (
                <button
                  className="secondary-action"
                  disabled={retryLoading}
                  onClick={() => {
                    void onRetryJob(failedJob.job_id);
                  }}
                  type="button"
                >
                  {retryLoading ? 'Đang chạy lại...' : 'Chạy lại'}
                </button>
              ) : null}
            </div>
          </div>
          <p>{failedJobMessage ? formatError(new Error(failedJobMessage)) : 'Job lỗi nhưng không có chi tiết.'}</p>
          {previousError ? (
            <p className="empty-detail">
              Lỗi trước đó: {formatError(new Error(previousError))}
            </p>
          ) : null}
          <p className="empty-detail">
            {failedJob.progress.toLocaleString()} / {failedJob.total.toLocaleString()}
            {retryCount > 0 ? ` · Retry ${retryCount.toLocaleString()}` : ''}
            {failedJob.finished_at ? ` · ${failedJob.finished_at}` : ''}
          </p>
          <div className="failed-job-actions">
            <button
              className="secondary-action"
              onClick={() => {
                document.querySelector('[aria-label="Recent operational errors"]')?.scrollIntoView({
                  block: 'start',
                  behavior: 'smooth',
                });
              }}
              type="button"
            >
              <ListChecks aria-hidden="true" size={15} />
              Xem log chi tiết
            </button>
            <button
              className="secondary-action"
              onClick={() => {
                void navigator.clipboard?.writeText(failedJobMessage || failedJob.job_id);
              }}
              type="button"
            >
              <Copy aria-hidden="true" size={15} />
              Sao chép
            </button>
          </div>
        </section>
      ) : null}

      {recentOperationalErrors.length > 0 ? (
        <section aria-label="Recent operational errors" className="panel">
          <div className="section-heading-row">
            <div>
              <p className="section-label">Operations</p>
              <h3>Recent operational errors</h3>
            </div>
          </div>
          <ul className="compact-list">
            {recentOperationalErrors.slice(0, 5).map((event) => (
              <li key={event.id}>
                <strong>{[event.event_type, event.job_id].filter(Boolean).join(' · ')}</strong>
                <span>{event.message}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {status?.backup_recommendation ? (
        <section aria-label="Backup" className="panel backup-status-panel">
          <div className="section-heading-row">
            <div>
              <p className="section-label">Backup</p>
              <h3>Khôi phục dữ liệu</h3>
            </div>
            <button
              aria-expanded={backupHelpOpen}
              className="secondary-action"
              onClick={() => setBackupHelpOpen((current) => !current)}
              type="button"
            >
              <ArchiveRestore aria-hidden="true" size={16} />
              Mở hướng dẫn
            </button>
          </div>
          <p>{status.backup_recommendation}</p>
          {backupHelpOpen ? (
            <div className="inline-help-panel">
              <p>
                Dừng server trước khi restore. Tạo backup bằng scripts/backup-local.sh,
                kiểm tra bằng restore drill, rồi chỉ khôi phục vào data directory khi đã xác nhận archive đúng.
              </p>
            </div>
          ) : null}
          {recentBackupEvent ? (
            <p className="empty-detail">
              Last backup event: {recentBackupEvent.event_type} · {recentBackupEvent.message}
            </p>
          ) : null}
        </section>
      ) : null}
    </section>
  );
}
