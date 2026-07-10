export type QualityIssue = { type: string; message: string };
export type QualityDetails = {
  fidelity?: number;
  style?: number;
  glossary?: number;
  audiobook?: number;
};
export type QualityGlossaryViolation = {
  source_term?: string;
  expected?: string;
  message?: string;
};

export type QualityPanelProps = {
  score?: number;
  verdict?: string;
  overallStatus?: string;
  chineseLeakageCount?: number;
  lengthRatio?: number;
  missingParagraphWarning?: boolean;
  repetitionWarning?: boolean;
  glossaryViolations?: QualityGlossaryViolation[];
  details?: QualityDetails;
  issues: QualityIssue[];
  loading?: boolean;
  onRunQa: () => void;
};

export default function QualityPanel({
  score,
  verdict,
  overallStatus,
  chineseLeakageCount,
  lengthRatio,
  missingParagraphWarning = false,
  repetitionWarning = false,
  glossaryViolations = [],
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
  const hasQa = typeof score === 'number'
    || Boolean(verdict)
    || Boolean(overallStatus)
    || typeof chineseLeakageCount === 'number'
    || typeof lengthRatio === 'number'
    || missingParagraphWarning
    || repetitionWarning
    || glossaryViolations.length > 0
    || detailRows.length > 0
    || issues.length > 0;

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
            {overallStatus ? (
              <div>
                <dt>Overall status</dt>
                <dd>{overallStatus}</dd>
              </div>
            ) : null}
            {typeof chineseLeakageCount === 'number' ? (
              <div>
                <dt>Chinese leakage</dt>
                <dd>{chineseLeakageCount}</dd>
              </div>
            ) : null}
            {typeof lengthRatio === 'number' ? (
              <div>
                <dt>Length ratio</dt>
                <dd>{lengthRatio}</dd>
              </div>
            ) : null}
            {missingParagraphWarning ? (
              <div>
                <dt>Missing paragraphs</dt>
                <dd>Warning</dd>
              </div>
            ) : null}
            {repetitionWarning ? (
              <div>
                <dt>Repeated text</dt>
                <dd>Warning</dd>
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
          {glossaryViolations.length > 0 ? (
            <div className="qa-issue-card">
              <strong>Glossary violations</strong>
              <ul>
                {glossaryViolations.map((violation, index) => (
                  <li key={`${violation.source_term ?? 'term'}-${index}`}>
                    <span>
                      {violation.source_term || 'Term'}
                      {violation.expected ? ` -> ${violation.expected}` : ''}
                    </span>
                    {violation.message ? <p>{violation.message}</p> : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </>
      ) : (
        <p className="empty-detail">No QA</p>
      )}
    </section>
  );
}
