import type { Chapter, JobStatus, ProviderUsage } from '../api/types';

export type OpsInsightsProps = {
  chapters: Chapter[];
  usage: ProviderUsage | null;
  activeJob: JobStatus | null;
};

function countStatuses(chapters: Chapter[]): Array<[string, number]> {
  const counts = new Map<string, number>();

  chapters.forEach((chapter) => {
    counts.set(chapter.status, (counts.get(chapter.status) ?? 0) + 1);
  });

  return Array.from(counts.entries()).sort(([left], [right]) => left.localeCompare(right));
}

export default function OpsInsights({ chapters, usage, activeJob }: OpsInsightsProps) {
  const statuses = countStatuses(chapters);
  const maxCount = Math.max(1, ...statuses.map(([, count]) => count));

  return (
    <section aria-label="Operations insights" className="ops-insights panel">
      <div className="panel-header">
        <div>
          <p className="section-label">Operations</p>
          <h3>Insights</h3>
        </div>
      </div>

      <div>
        <h4>Status counts</h4>
        {statuses.length > 0 ? (
          <ul className="ops-status-list">
            {statuses.map(([status, count]) => (
              <li key={status}>
                <span>{status}</span>
                <div className="ops-bar" style={{ width: `${Math.max(8, (count / maxCount) * 100)}%` }} />
                <strong>{count}</strong>
              </li>
            ))}
          </ul>
        ) : (
          <p className="empty-detail">No chapters loaded</p>
        )}
      </div>

      <dl className="estimate-grid">
        <div>
          <dt>Active job status</dt>
          <dd>{activeJob ? activeJob.status : 'No active job'}</dd>
        </div>
        <div>
          <dt>Estimated total cost</dt>
          <dd>{usage ? `$${usage.total_estimated_cost_usd.toFixed(4)}` : '$0.0000'}</dd>
        </div>
        <div>
          <dt>Total tokens</dt>
          <dd>{usage ? usage.total_tokens : 0}</dd>
        </div>
      </dl>
    </section>
  );
}
