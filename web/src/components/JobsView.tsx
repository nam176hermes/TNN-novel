import type { JobAttempt, JobLogEntry, JobStatus, TtsJobStatus } from '../api/types';
import type { AsyncState } from '../state/types';
import JobProgress from './JobProgress';
import { ClipboardList, Lightbulb, RefreshCw, Send } from 'lucide-react';

export type JobsViewProps = {
  activeJob: JobStatus | null;
  attempts: AsyncState<JobAttempt[]>;
  logs?: AsyncState<JobLogEntry[]>;
  jobs?: AsyncState<JobStatus[]>;
  onCancelJob?: () => void | Promise<void>;
  onOpenProviders?: () => void;
  onRefresh?: () => void | Promise<void>;
  onRetryTtsChunks?: (jobId: string) => void | Promise<void>;
  ttsJob?: AsyncState<TtsJobStatus | null>;
  ttsRetrying?: boolean;
};

type StageTiming = {
  stage: string;
  elapsedMs: number;
  attempts: number;
  failures: number;
};

type StageTimingSummary = {
  totalMs: number;
  slowest: StageTiming | null;
  stages: StageTiming[];
};

const STAGE_ORDER = ['translate', 'polish', 'qa', 'rewrite'];

function formatElapsedMs(elapsedMs: number | undefined): string {
  if (!elapsedMs || elapsedMs <= 0) return '-';
  if (elapsedMs < 1000) return `${elapsedMs} ms`;
  const seconds = elapsedMs / 1000;
  return `${seconds < 10 ? seconds.toFixed(1) : seconds.toFixed(0)} s`;
}

function formatDurationSeconds(seconds: number | undefined): string {
  if (!seconds || seconds <= 0) return '-';
  return `${seconds < 10 ? seconds.toFixed(1) : seconds.toFixed(0)} s`;
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return '-';
  return value.replace('T', ' ').replace(/\.\d+(?:[+-]\d\d:\d\d|Z)?$/, '').replace(/\+00:00$/, ' UTC');
}

function formatJobType(jobType: string | undefined): string {
  const normalized = (jobType || '').trim();
  if (!normalized) return 'job';
  if (normalized === 'tts') return 'TTS';
  if (normalized === 'qa') return 'QA';
  return normalized;
}

function formatJobProgress(job: JobStatus): string {
  const total = Math.max(0, job.total ?? 0);
  const progress = Math.max(0, job.progress ?? 0);
  return total > 0 ? `${progress} / ${total}` : '-';
}

function formatChunkProgress(job: JobStatus): string {
  const totalChunks = Math.max(0, job.total_chunks ?? 0);
  if (totalChunks <= 0) return '-';
  return `${Math.max(0, job.current_chunk_index ?? 0)} / ${totalChunks}`;
}

function sortStageTiming(left: StageTiming, right: StageTiming): number {
  const leftIndex = STAGE_ORDER.indexOf(left.stage);
  const rightIndex = STAGE_ORDER.indexOf(right.stage);
  if (leftIndex !== -1 || rightIndex !== -1) {
    if (leftIndex === -1) return 1;
    if (rightIndex === -1) return -1;
    return leftIndex - rightIndex;
  }
  return left.stage.localeCompare(right.stage);
}

function summarizeStageTiming(attempts: JobAttempt[]): StageTimingSummary {
  const byStage = new Map<string, StageTiming>();

  for (const attempt of attempts) {
    const elapsedMs = Math.max(0, attempt.elapsed_ms ?? 0);
    if (elapsedMs <= 0) continue;

    const stage = (attempt.stage || 'unknown').trim() || 'unknown';
    const current = byStage.get(stage) ?? { stage, elapsedMs: 0, attempts: 0, failures: 0 };
    current.elapsedMs += elapsedMs;
    current.attempts += 1;
    if (attempt.error || attempt.status.toLowerCase().includes('fail')) {
      current.failures += 1;
    }
    byStage.set(stage, current);
  }

  const stages = Array.from(byStage.values()).sort(sortStageTiming);
  const totalMs = stages.reduce((sum, stage) => sum + stage.elapsedMs, 0);
  const slowest = stages.reduce<StageTiming | null>(
    (current, stage) => (!current || stage.elapsedMs > current.elapsedMs ? stage : current),
    null,
  );

  return { totalMs, slowest, stages };
}

export default function JobsView({
  activeJob,
  attempts,
  logs,
  jobs,
  onCancelJob,
  onOpenProviders,
  onRefresh,
  onRetryTtsChunks,
  ttsJob,
  ttsRetrying = false,
}: JobsViewProps) {
  const timing = summarizeStageTiming(attempts.data);
  const ttsJobData = ttsJob?.data ?? null;
  const ttsChunks = ttsJobData?.chunks ?? [];
  const ttsFailedChunks = ttsChunks.filter((chunk) => ['failed', 'qa_failed'].includes(chunk.status));
  const ttsJobId = ttsJobData?.id || ttsJobData?.job_id || activeJob?.job_id || '';
  const jobHistory = jobs?.data ?? [];
  const jobLogs = logs?.data ?? [];
  const jobsLoading = jobs?.state === 'loading';
  const refreshLoading = attempts.state === 'loading' || jobsLoading;

  return (
    <section aria-labelledby="jobs-view-title" className="workflow-management-view jobs-view">
      <header className="panel workbench-title">
        <div>
          <p className="section-label">Workflow</p>
          <h2 id="jobs-view-title">Tác vụ</h2>
          <p className="view-subtitle">Tạo và quản lý các tác vụ dịch hoặc xử lý bằng model AI.</p>
        </div>
      </header>

      <section aria-labelledby="create-job-title" className="panel job-create-panel">
        <div className="panel-header">
          <h3 id="create-job-title">Nguồn tạo tác vụ</h3>
        </div>
        <div className="job-create-form">
          <aside className="job-hint-box">
            <Lightbulb aria-hidden="true" size={20} />
            <div>
              <strong>Tác vụ được tạo từ thao tác thật</strong>
              <ul>
                <li>Dịch, QA và TTS được tạo từ Bàn dịch hoặc Đọc truyện.</li>
                <li>Provider/model attempts được tạo từ trang Model API khi bạn test kết nối.</li>
              </ul>
            </div>
          </aside>
          <div className="job-create-actions">
            <button
              className="secondary-action"
              disabled={!onRefresh || refreshLoading}
              onClick={() => {
                void onRefresh?.();
              }}
              type="button"
            >
              <RefreshCw aria-hidden="true" size={16} />
              {refreshLoading ? 'Đang làm mới...' : 'Làm mới'}
            </button>
            <button
              className="primary-action"
              disabled={!onOpenProviders}
              onClick={() => onOpenProviders?.()}
              type="button"
            >
              <Send aria-hidden="true" size={16} />
              Mở Model API
            </button>
          </div>
        </div>
      </section>

      <section aria-labelledby="active-job-title" className="panel job-list-panel">
        <div className="panel-header">
          <div>
            <h3 id="active-job-title">Danh sách tác vụ</h3>
            <p className="empty-detail">Quản lý và theo dõi các tác vụ đã tạo.</p>
          </div>
          <button
            className="secondary-action"
            disabled={!onRefresh || refreshLoading}
            onClick={() => {
              void onRefresh?.();
            }}
            type="button"
          >
            <RefreshCw aria-hidden="true" size={16} />
            {refreshLoading ? 'Đang làm mới...' : 'Làm mới'}
          </button>
        </div>
        {activeJob ? (
          <div className="job-active-card">
            <p className="section-label">Đang chạy</p>
            <JobProgress job={activeJob} onCancel={onCancelJob} />
          </div>
        ) : (
          <div className="job-empty-card">
            <ClipboardList aria-hidden="true" size={64} />
            <h3>Chưa có tác vụ nào</h3>
            <p>Hãy bắt đầu dịch, QA, TTS hoặc test provider để tạo tác vụ thật.</p>
            <p className="empty-detail job-running-empty">Không có tác vụ đang chạy</p>
            <JobProgress job={activeJob} onCancel={onCancelJob} />
            <button
              className="primary-action"
              disabled={!onOpenProviders}
              onClick={() => onOpenProviders?.()}
              type="button"
            >
              <Send aria-hidden="true" size={16} />
              Mở Model API
            </button>
          </div>
        )}
      </section>

      <section aria-labelledby="job-list-history-title" className="panel job-history-panel">
        <div className="panel-header">
          <div>
            <p className="section-label">Lịch sử</p>
            <h3 id="job-list-history-title">Job gần đây</h3>
          </div>
        </div>
        {jobsLoading ? <p className="empty-detail">Đang tải job gần đây...</p> : null}
        {jobs?.error ? <p className="status-error">{jobs.error}</p> : null}
        {jobHistory.length > 0 ? (
          <table className="provider-table job-history-table">
            <thead>
              <tr>
                <th>Loại</th>
                  <th>Trạng thái</th>
                  <th>State</th>
                  <th>Step</th>
                  <th>Tiến độ</th>
                  <th>Chunk</th>
                  <th>Provider/model</th>
                  <th>Retry</th>
                  <th>Cập nhật</th>
                  <th>Thông báo</th>
                  <th>Tạo lúc</th>
                  <th>Lỗi</th>
              </tr>
            </thead>
            <tbody>
              {jobHistory.map((job) => (
                <tr key={job.job_id}>
                  <th scope="row">{formatJobType(job.job_type)}</th>
                  <td>{job.status || '-'}</td>
                  <td>{job.state || '-'}</td>
                  <td>{job.current_step || job.active_stage || '-'}</td>
                  <td>{formatJobProgress(job)}</td>
                  <td>{formatChunkProgress(job)}</td>
                  <td>{[job.provider, job.model].filter(Boolean).join(' / ') || '-'}</td>
                  <td>{job.retry_count ?? 0}</td>
                  <td>{formatTimestamp(job.updated_at)}</td>
                  <td>{job.message || '-'}</td>
                  <td>{formatTimestamp(job.created_at)}</td>
                  <td>{job.last_safe_error || job.error || job.previous_error || '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : !jobsLoading && !jobs?.error ? (
          <p className="empty-detail">Chưa có lịch sử tác vụ</p>
        ) : null}
      </section>

      {activeJob?.job_type === 'tts' || ttsJobData || ttsJob?.state === 'loading' || ttsJob?.error ? (
        <section aria-labelledby="tts-job-report-title" className="panel tts-job-report">
          <div className="panel-header">
            <div>
              <p className="section-label">Audio</p>
              <h3 id="tts-job-report-title">TTS chunk report</h3>
            </div>
            <button
              className="secondary-action"
              disabled={!onRetryTtsChunks || !ttsJobId || ttsFailedChunks.length === 0 || ttsRetrying}
              onClick={() => {
                if (ttsJobId) void onRetryTtsChunks?.(ttsJobId);
              }}
              type="button"
            >
              <RefreshCw aria-hidden="true" size={16} />
              {ttsRetrying ? 'Đang retry...' : 'Retry failed chunks'}
            </button>
          </div>
          {ttsJob?.state === 'loading' ? <p className="empty-detail">Đang tải TTS report...</p> : null}
          {ttsJob?.error ? <p className="status-error">{ttsJob.error}</p> : null}
          {ttsJobData ? (
            <>
              <dl className="tts-job-summary">
                <div>
                  <dt>Provider</dt>
                  <dd>{ttsJobData.provider || '-'}</dd>
                </div>
                <div>
                  <dt>Model</dt>
                  <dd>{ttsJobData.model || '-'}</dd>
                </div>
                <div>
                  <dt>Trạng thái</dt>
                  <dd>{ttsJobData.status}</dd>
                </div>
                <div>
                  <dt>Tiến độ</dt>
                  <dd>{ttsJobData.progress ?? activeJob?.progress ?? 0}%</dd>
                </div>
              </dl>
              {ttsJobData.error_message ? <p className="status-error">{ttsJobData.error_message}</p> : null}
              {ttsChunks.length > 0 ? (
                <table className="provider-table tts-chunk-table">
                  <thead>
                    <tr>
                      <th>Chunk</th>
                      <th>Trạng thái</th>
                      <th>QA</th>
                      <th>Thời lượng</th>
                      <th>Lỗi</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ttsChunks.map((chunk) => (
                      <tr key={chunk.id || `${ttsJobId}-${chunk.chunk_index}`}>
                        <th scope="row">{chunk.chunk_index + 1}</th>
                        <td>{chunk.status}</td>
                        <td>{chunk.qa_status || '-'}</td>
                        <td>{formatDurationSeconds(chunk.duration_seconds)}</td>
                        <td>{chunk.error_message || '-'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="empty-detail">Chưa có chunk report cho job này.</p>
              )}
            </>
          ) : null}
        </section>
      ) : null}

      {timing.stages.length > 0 ? (
        <section aria-labelledby="stage-timing-title" className="panel job-stage-timing">
          <div className="panel-header">
            <div>
              <p className="section-label">Hiệu năng</p>
              <h3 id="stage-timing-title">Timing theo stage</h3>
            </div>
          </div>
          <div className="stage-timing-summary">
            <dl className="stage-timing-card">
              <dt>Tổng thời gian</dt>
              <dd>{formatElapsedMs(timing.totalMs)}</dd>
            </dl>
            <dl className="stage-timing-card">
              <dt>Stage chậm nhất</dt>
              <dd>
                {timing.slowest ? (
                  <>
                    <span>{timing.slowest.stage}</span>
                    <strong>{formatElapsedMs(timing.slowest.elapsedMs)}</strong>
                  </>
                ) : (
                  '-'
                )}
              </dd>
            </dl>
          </div>
          <ul className="stage-timing-list" aria-label="Breakdown timing theo stage">
            {timing.stages.map((stage) => (
              <li key={stage.stage}>
                <div>
                  <strong>{stage.stage}</strong>
                  <span>
                    {stage.attempts} attempt{stage.attempts > 1 ? 's' : ''}
                    {stage.failures > 0 ? ` · ${stage.failures} lỗi` : ''}
                  </span>
                </div>
                <span>{formatElapsedMs(stage.elapsedMs)}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {logs?.state === 'loading' || logs?.error || jobLogs.length > 0 ? (
        <section aria-labelledby="job-log-title" className="panel job-log-panel">
          <div className="panel-header">
            <div>
              <p className="section-label">Quan sát</p>
              <h3 id="job-log-title">Log tác vụ</h3>
            </div>
          </div>
          {logs?.state === 'loading' ? <p className="empty-detail">Đang tải log tác vụ...</p> : null}
          {logs?.error ? <p className="status-error">{logs.error}</p> : null}
          {jobLogs.length > 0 ? (
            <table className="provider-table job-log-table">
              <thead>
                <tr>
                  <th>Thời gian</th>
                  <th>Event</th>
                  <th>State</th>
                  <th>Step</th>
                  <th>Thông báo</th>
                </tr>
              </thead>
              <tbody>
                {jobLogs.map((entry) => (
                  <tr key={entry.id}>
                    <td>{formatTimestamp(entry.created_at)}</td>
                    <th scope="row">{entry.event_type}</th>
                    <td>{entry.state || '-'}</td>
                    <td>{entry.step || '-'}</td>
                    <td>{entry.message || '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
        </section>
      ) : null}

      {attempts.state === 'loading' || attempts.error || attempts.data.length > 0 ? (
        <section aria-labelledby="job-history-title" className="panel">
          <div className="panel-header">
            <div>
              <p className="section-label">Lịch sử</p>
              <h3 id="job-history-title">Attempts provider/model</h3>
            </div>
          </div>
          {attempts.state === 'loading' ? <p className="empty-detail">Đang tải attempts...</p> : null}
          {attempts.error ? <p className="status-error">{attempts.error}</p> : null}
          {attempts.data.length > 0 ? (
            <table className="provider-table job-attempts-table">
              <thead>
                <tr>
                  <th>Stage</th>
                  <th>Provider</th>
                  <th>Model</th>
                  <th>Chương</th>
                  <th>Trạng thái</th>
                  <th>Thời gian</th>
                  <th>Lỗi</th>
                </tr>
              </thead>
              <tbody>
                {attempts.data.map((attempt, index) => (
                  <tr key={attempt.id ?? `${attempt.job_id}-${index}`}>
                    <td>{attempt.stage || '-'}</td>
                    <th scope="row">{attempt.provider_id || 'unknown'}</th>
                    <td>{attempt.model || 'default'}</td>
                    <td>{attempt.chapter_id ?? '-'}</td>
                    <td>{attempt.status || 'unknown'}</td>
                    <td>{formatElapsedMs(attempt.elapsed_ms)}</td>
                    <td>{attempt.error || '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
        </section>
      ) : null}
    </section>
  );
}
