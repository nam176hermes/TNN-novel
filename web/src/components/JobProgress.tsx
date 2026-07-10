import type { JobStageTiming, JobStatus } from '../api/types';
import { formatError } from '../state/types';

type Props = {
  job: JobStatus | null;
  onCancel?: () => void | Promise<void>;
};

function clampPercent(progress: number, total: number): number {
  if (total <= 0) return 0;
  return Math.min(100, Math.max(0, Math.round((progress / total) * 100)));
}

function canCancel(status: string): boolean {
  return !['completed', 'failed', 'cancelled', 'canceled'].includes(status.toLowerCase());
}

function formatElapsedMs(elapsedMs: number | undefined): string {
  if (!elapsedMs || elapsedMs <= 0) return '-';
  if (elapsedMs < 1000) return `${elapsedMs} ms`;
  const seconds = elapsedMs / 1000;
  return `${seconds < 10 ? seconds.toFixed(1) : seconds.toFixed(0)} s`;
}

function stageMeta(stage: JobStageTiming): string {
  return [stage.status, stage.provider_id, stage.model].filter(Boolean).join(' · ');
}

export default function JobProgress({ job, onCancel }: Props) {
  if (!job) {
    return (
      <section aria-label="Job progress" className="job-progress panel">
        <div className="job-progress-empty">No active job</div>
      </section>
    );
  }

  const percent = clampPercent(job.progress, job.total);
  const stageTimings = job.stage_timings ?? [];
  const failedMessage = job.status.toLowerCase() === 'failed'
    ? formatError(new Error(job.error || job.message || 'Translation job failed'))
    : '';
  const metadata = [
    job.state ? `State ${job.state}` : '',
    job.current_step ? `Step ${job.current_step}` : '',
    job.current_chapter_id ? `Chapter ${job.current_chapter_id}` : '',
    job.total_chunks ? `Chunk ${job.current_chunk_index ?? 0}/${job.total_chunks}` : '',
    job.provider || job.model ? [job.provider, job.model].filter(Boolean).join(' / ') : '',
    job.preset_id ? `Preset ${job.preset_id}` : '',
    job.chunk_size ? `Chunk ${job.chunk_size} ký tự` : '',
    job.active_stage ? `Stage ${job.active_stage}` : '',
    job.retry_count ? `Retry ${job.retry_count}` : '',
  ].filter(Boolean);

  return (
    <section aria-label="Job progress" className="job-progress panel">
      <div className="job-row">
        <strong>{job.status}</strong>
        <span>
          {job.progress} / {job.total}
        </span>
      </div>
      <progress aria-label="Job completion" max={100} value={percent}>
        {percent}%
      </progress>
      {metadata.length > 0 ? (
        <div className="job-metadata" aria-label="Job metadata">
          {metadata.map((item) => (
            <span key={item}>{item}</span>
          ))}
        </div>
      ) : null}
      <p>{job.message || 'Waiting for provider update'}</p>
      {job.cancel_requested ? <p className="status-error">Cancel requested. Job will stop at the next safe checkpoint.</p> : null}
      {failedMessage ? <p className="status-error">{failedMessage}</p> : null}
      {stageTimings.length > 0 ? (
        <ul className="stage-timing-list job-progress-stage-timing" aria-label="Timing theo stage hiện tại">
          {stageTimings.map((stage) => (
            <li key={stage.stage}>
              <div>
                <strong>{stage.stage}</strong>
                <span>{stageMeta(stage)}</span>
                {stage.error ? <span className="status-error">{stage.error}</span> : null}
              </div>
              <span>{formatElapsedMs(stage.elapsed_ms)}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {onCancel && canCancel(job.status) ? (
        <button
          className="secondary-action job-cancel-action"
          onClick={() => {
            void onCancel();
          }}
          type="button"
        >
          Cancel job
        </button>
      ) : null}
    </section>
  );
}
