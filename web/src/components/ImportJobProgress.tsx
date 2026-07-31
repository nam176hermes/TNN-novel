import { useEffect, useMemo, useRef, useState } from 'react';
import type { ChapterTask, ImportJobStatus } from '../api/types';
import {
  mapImportJobErrorCode,
  type ImportJobState,
} from '../state/useImportJob';

const TASK_PAGE_SIZE = 20;
const TERMINAL_STATUSES = new Set<ImportJobStatus>([
  'succeeded',
  'partially_succeeded',
  'failed',
  'cancelled',
]);

const FETCH_METHOD_LABELS: Record<string, string> = {
  direct_http: 'Kết nối trực tiếp',
  stealth_browser_headed: 'Trình duyệt ẩn danh',
  browser_session: 'Phiên trình duyệt',
  user_verification_required: 'Cần xác minh thủ công',
};

const TASK_STATUS_LABELS: Record<string, string> = {
  queued: 'Đang chờ',
  running: 'Đang xử lý',
  waiting_retry: 'Chờ thử lại',
  succeeded: 'Hoàn tất',
  failed: 'Thất bại',
  cancelled: 'Đã hủy',
  user_verification_required: 'Cần xác minh',
};

const TASK_STAGE_LABELS: Record<string, string> = {
  queued: 'Chờ xử lý',
  fetching: 'Đang tải',
  waiting_retry: 'Chờ thử lại',
  parsing: 'Đang phân tích',
  validating: 'Đang kiểm tra',
  importing: 'Đang lưu',
  succeeded: 'Đã lưu',
  failed: 'Có lỗi',
  cancelled: 'Đã hủy',
  user_verification_required: 'Chờ xác minh',
};

const OPERATION_LABELS: Record<string, string> = {
  created: 'Tạo mới',
  updated: 'Cập nhật',
  skipped_duplicate: 'Bỏ qua trùng',
  created_or_updated: 'Đã lưu',
};

function jobStatusCopy(state: ImportJobState): { heading: string; label: string } {
  if (state.phase === 'creating') return { heading: 'Đang tạo job import', label: 'Đang tạo…' };
  if (state.phase === 'reconnecting') return { heading: 'Đang khôi phục tiến độ', label: 'Đang kết nối lại…' };
  if (state.phase === 'error') return { heading: 'Không thể theo dõi job', label: 'Có lỗi kết nối' };
  switch (state.snapshot?.status) {
    case 'queued': return { heading: 'Job đang chờ xử lý', label: 'Đang chờ' };
    case 'running': return { heading: 'Đang import chương', label: 'Đang chạy' };
    case 'succeeded': return { heading: 'Import hoàn tất', label: 'Hoàn tất' };
    case 'partially_succeeded': return { heading: 'Import hoàn tất một phần', label: 'Hoàn tất một phần' };
    case 'failed': return { heading: 'Import thất bại', label: 'Thất bại' };
    case 'cancelled': return { heading: 'Job đã bị hủy', label: 'Đã hủy' };
    default: return { heading: 'Đang chuẩn bị import', label: 'Đang chờ' };
  }
}

function elapsedMilliseconds(startedAt: string, finishedAt: string, now: number): number {
  const started = Date.parse(startedAt);
  if (!Number.isFinite(started)) return 0;
  const finished = Date.parse(finishedAt);
  return Math.max(0, (Number.isFinite(finished) ? finished : now) - started);
}

function formatElapsed(value: number): string {
  const totalSeconds = Math.floor(value / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return minutes > 0 ? `${minutes} phút ${seconds} giây` : `${seconds} giây`;
}

function operationLabel(task: ChapterTask): string {
  if (task.operation) return OPERATION_LABELS[task.operation] ?? task.operation;
  return task.status === 'succeeded' ? 'Đã lưu' : '—';
}

function taskError(task: ChapterTask): string {
  return mapImportJobErrorCode(task.error_code, task.retryable)?.message ?? '';
}

export type ImportJobProgressProps = {
  state: ImportJobState;
  onCancel: () => Promise<unknown> | void;
  onRetryFailed: () => Promise<unknown> | void;
  onReset?: () => void;
  onReturnToLibrary?: () => void;
};

export default function ImportJobProgress({
  state,
  onCancel,
  onRetryFailed,
  onReset,
  onReturnToLibrary,
}: ImportJobProgressProps) {
  const [taskPage, setTaskPage] = useState(0);
  const [action, setAction] = useState<'cancel' | 'retry' | ''>('');
  const [now, setNow] = useState(() => Date.now());
  const focusRef = useRef<HTMLHeadingElement>(null);
  const snapshot = state.snapshot;
  const terminal = Boolean(snapshot && TERMINAL_STATUSES.has(snapshot.status));
  const statusCopy = jobStatusCopy(state);
  const totalTaskPages = Math.max(1, Math.ceil((snapshot?.tasks.length ?? 0) / TASK_PAGE_SIZE));
  const visibleTasks = useMemo(
    () => snapshot?.tasks.slice(taskPage * TASK_PAGE_SIZE, (taskPage + 1) * TASK_PAGE_SIZE) ?? [],
    [snapshot?.tasks, taskPage],
  );

  useEffect(() => {
    if (taskPage >= totalTaskPages) setTaskPage(totalTaskPages - 1);
  }, [taskPage, totalTaskPages]);

  useEffect(() => {
    if (state.phase === 'error' || terminal) focusRef.current?.focus();
  }, [state.phase, terminal]);

  useEffect(() => {
    if (snapshot?.status !== 'running') return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [snapshot?.status]);

  async function runAction(nextAction: 'cancel' | 'retry'): Promise<void> {
    setAction(nextAction);
    try {
      if (nextAction === 'cancel') await onCancel();
      else await onRetryFailed();
    } finally {
      setAction('');
    }
  }

  const elapsed = snapshot
    ? elapsedMilliseconds(snapshot.started_at, snapshot.finished_at, now)
    : 0;
  const retryableFailure = snapshot?.tasks.some((task) => task.status === 'failed' && task.retryable) ?? false;

  return (
    <section
      aria-label="Tiến độ import URL"
      aria-live="polite"
      aria-busy={state.phase === 'creating' || state.phase === 'reconnecting'}
      className="import-job-progress"
    >
      <header className="import-job-progress-header">
        <div>
          <p className="section-label">Import URL · {state.jobId || 'Đang khởi tạo'}</p>
          <h4 ref={focusRef} tabIndex={-1}>{statusCopy.heading}</h4>
          <p>{statusCopy.label}{elapsed > 0 ? ` · ${formatElapsed(elapsed)}` : ''}</p>
        </div>
        <span className={`status-chip import-job-status-${snapshot?.status ?? state.phase}`}>
          {statusCopy.label}
        </span>
      </header>

      {state.error ? (
        <p className="status-error" role="alert">{state.error.message}</p>
      ) : null}

      <dl className="import-job-counts" aria-label="Tóm tắt job">
        <div><dt>Tổng</dt><dd data-count="total">{snapshot?.total ?? 0}</dd></div>
        <div><dt>Đang chờ</dt><dd>{snapshot?.queued_count ?? 0}</dd></div>
        <div><dt>Đang chạy</dt><dd>{snapshot?.running_count ?? 0}</dd></div>
        <div><dt>Hoàn tất</dt><dd>{snapshot?.succeeded_count ?? 0}</dd></div>
        <div><dt>Thất bại</dt><dd>{snapshot?.failed_count ?? 0}</dd></div>
        <div><dt>Đã hủy</dt><dd>{snapshot?.cancelled_count ?? 0}</dd></div>
      </dl>

      {visibleTasks.length > 0 ? (
        <div className="import-job-task-list-wrap">
          <ol className="import-job-task-list" aria-label="Tiến độ từng chương">
            {visibleTasks.map((task) => {
              const error = taskError(task);
              return (
                <li key={task.id} data-status={task.status}>
                  <div className="import-job-task-title">
                    <span>#{task.chapter_number}</span>
                    <strong>{task.title || `Chương ${task.chapter_number}`}</strong>
                    <span className={`status-chip task-status-${task.status}`}>
                      {TASK_STATUS_LABELS[task.status] ?? task.status}
                    </span>
                  </div>
                  <dl className="import-job-task-meta">
                    <div><dt>Giai đoạn</dt><dd>{TASK_STAGE_LABELS[task.stage] ?? task.stage}</dd></div>
                    <div><dt>Lần thử</dt><dd>{task.attempts}</dd></div>
                    <div><dt>Kết nối</dt><dd>{FETCH_METHOD_LABELS[task.fetch_method] ?? 'Chưa tải'}</dd></div>
                    <div><dt>Độ dài</dt><dd>{task.text_length.toLocaleString('vi-VN')} ký tự</dd></div>
                    <div><dt>Thao tác</dt><dd>{operationLabel(task)}</dd></div>
                    <div><dt>Thời gian</dt><dd>{formatElapsed(task.elapsed_ms)}</dd></div>
                  </dl>
                  {error ? <p className="import-job-task-error">{error}</p> : null}
                </li>
              );
            })}
          </ol>
          {totalTaskPages > 1 ? (
            <nav aria-label="Phân trang tác vụ" className="import-pagination">
              <button
                aria-label="Trang tác vụ trước"
                className="secondary-action"
                disabled={taskPage === 0}
                onClick={() => setTaskPage((page) => Math.max(0, page - 1))}
                type="button"
              >
                Trước
              </button>
              <span>Trang {taskPage + 1}/{totalTaskPages}</span>
              <button
                aria-label="Trang tác vụ sau"
                className="secondary-action"
                disabled={taskPage >= totalTaskPages - 1}
                onClick={() => setTaskPage((page) => Math.min(totalTaskPages - 1, page + 1))}
                type="button"
              >
                Sau
              </button>
            </nav>
          ) : null}
        </div>
      ) : null}

      <div className="import-job-actions">
        {!terminal && state.phase !== 'error' ? (
          <button
            className="secondary-action destructive-action"
            disabled={action !== '' || state.phase === 'creating'}
            onClick={() => void runAction('cancel')}
            type="button"
          >
            {action === 'cancel' ? 'Đang hủy…' : 'Hủy job'}
          </button>
        ) : null}
        {retryableFailure ? (
          <button
            className="primary-action"
            disabled={action !== ''}
            onClick={() => void runAction('retry')}
            type="button"
          >
            {action === 'retry' ? 'Đang thử lại…' : 'Thử lại chương lỗi'}
          </button>
        ) : null}
        {state.phase === 'error' && onReset ? (
          <button className="secondary-action" onClick={onReset} type="button">
            Quay lại chọn chương
          </button>
        ) : null}
        {terminal && onReturnToLibrary ? (
          <button className="primary-action" onClick={onReturnToLibrary} type="button">
            Về Thư viện
          </button>
        ) : null}
      </div>
    </section>
  );
}
