export type QualityIssue = { type: string; message: string };
export type QualityDetails = {
  fidelity?: number;
  style?: number;
  glossary?: number;
  audiobook?: number;
};

export type QualityPanelProps = {
  score?: number;
  verdict?: string;
  details?: QualityDetails;
  issues: QualityIssue[];
  loading?: boolean;
  onRunQa: () => void;
};

export default function QualityPanel({
  score,
  verdict,
  details,
  issues,
  loading = false,
  onRunQa,
}: QualityPanelProps) {
  const detailRows = [
    ['Fidelity', details?.fidelity],
    ['Style', details?.style],
    ['Glossary', details?.glossary],
    ['Audiobook', details?.audiobook],
  ].filter((row): row is [string, number] => typeof row[1] === 'number');
  const hasQa = typeof score === 'number' || Boolean(verdict) || detailRows.length > 0 || issues.length > 0;

  return (
    <section aria-label="Quality panel" className="quality-panel panel">
      <div className="panel-header">
        <div>
          <p className="section-label">Quality</p>
          <h3>QA review</h3>
        </div>
        <button className="secondary-action" disabled={loading} onClick={onRunQa} type="button">
          Run QA
        </button>
      </div>

      {hasQa ? (
        <>
          <dl className="quality-summary">
            {typeof score === 'number' ? (
              <div>
                <dt>Score</dt>
                <dd>{score}</dd>
              </div>
            ) : null}
            {verdict ? (
              <div>
                <dt>Verdict</dt>
                <dd>{verdict}</dd>
              </div>
            ) : null}
            {detailRows.map(([label, value]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>

          {issues.length > 0 ? (
            <ul className="review-issues">
              {issues.map((issue) => (
                <li key={`${issue.type}-${issue.message}`}>
                  <span>{issue.type}</span>
                  {issue.message}
                </li>
              ))}
            </ul>
          ) : (
            <p className="empty-detail">No QA issues found.</p>
          )}
        </>
      ) : (
        <p className="empty-detail">No QA</p>
      )}
    </section>
  );
}
