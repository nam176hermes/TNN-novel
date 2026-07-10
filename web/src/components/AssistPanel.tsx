import { useState, type FormEvent } from 'react';
import type { GlossaryTerm, JobStatus, QaReport, TmSearchResult } from '../api/types';
import type { NormalizedQaIssue } from '../state/useQa';
import type { LoadState } from '../state/types';
import JobProgress from './JobProgress';

export type AssistPanelProps = {
  activeJob: JobStatus | null;
  glossaryError: string;
  pendingGlossaryCount: number;
  qaIssues: NormalizedQaIssue[];
  qaReport?: QaReport | null;
  qaState: LoadState;
  relevantTerms: GlossaryTerm[];
  tmError: string;
  tmResults: TmSearchResult[];
  tmState: LoadState;
  onRunQa(): void;
  onApplyQaFix(issue: NormalizedQaIssue): void;
  onSearchTm(query: string): void;
};

function renderQaState(
  qaState: LoadState,
  qaIssues: NormalizedQaIssue[],
  qaReport: QaReport | null | undefined,
  onApplyQaFix: (issue: NormalizedQaIssue) => void,
) {
  const hasDeterministicSummary = Boolean(
    qaReport?.overall_status
      || typeof qaReport?.chinese_leakage_count === 'number'
      || typeof qaReport?.length_ratio === 'number'
      || qaReport?.missing_paragraph_warning
      || qaReport?.repetition_warning
      || qaReport?.term_consistency_status
      || qaReport?.name_consistency_status
      || (Array.isArray(qaReport?.glossary_violations) && qaReport.glossary_violations.length > 0),
  );

  const glossaryViolations = Array.isArray(qaReport?.glossary_violations)
    ? qaReport.glossary_violations
    : [];

  if (qaIssues.length > 0) {
    return (
      <>
        {hasDeterministicSummary ? <QaSummary report={qaReport} /> : null}
      <ul className="review-issues">
        {qaIssues.map((issue, index) => (
          <li key={`${issue.type}-${index}`}>
            <article className="qa-issue-card">
              <header>
                <span>{issue.type}</span>
                <p>{issue.message}</p>
              </header>
              {issue.segment ? (
                <div>
                  <strong>Đoạn lỗi</strong>
                  <p>{issue.segment}</p>
                </div>
              ) : null}
              {issue.reason ? (
                <div>
                  <strong>Lý do</strong>
                  <p>{issue.reason}</p>
                </div>
              ) : null}
              {issue.suggestedFix ? (
                <div>
                  <strong>Gợi ý sửa</strong>
                  <p>{issue.suggestedFix}</p>
                </div>
              ) : null}
              {issue.suggestedFix ? (
                <button className="primary-action" onClick={() => onApplyQaFix(issue)} type="button">
                  Apply fix {issue.type}
                </button>
              ) : null}
            </article>
          </li>
        ))}
      </ul>
        {glossaryViolations.length > 0 ? <GlossaryViolations violations={glossaryViolations} /> : null}
      </>
    );
  }

  if (qaState === 'loading') return <p className="empty-detail">Đang tải QA...</p>;
  if (qaState === 'error') return null;
  if (hasDeterministicSummary) {
    return (
      <>
        <QaSummary report={qaReport} />
        {glossaryViolations.length > 0 ? <GlossaryViolations violations={glossaryViolations} /> : null}
      </>
    );
  }
  return <p className="empty-detail">Chưa có QA</p>;
}

function boolWarning(value: unknown): boolean {
  return value === true || value === 1 || value === '1' || value === 'true';
}

function readString(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function QaSummary({ report }: { report: QaReport | null | undefined }) {
  if (!report) return null;
  const rows: Array<[string, string | number]> = [];
  if (report.overall_status) rows.push(['Trạng thái', report.overall_status]);
  if (typeof report.chinese_leakage_count === 'number') rows.push(['Rò chữ Trung', report.chinese_leakage_count]);
  if (typeof report.length_ratio === 'number') rows.push(['Tỷ lệ dài/ngắn', Number(report.length_ratio.toFixed(2))]);
  if (boolWarning(report.missing_paragraph_warning)) rows.push(['Thiếu đoạn', 'Cảnh báo']);
  if (boolWarning(report.repetition_warning)) rows.push(['Lặp nội dung', 'Cảnh báo']);
  if (report.name_consistency_status) rows.push(['Nhất quán tên', report.name_consistency_status]);
  if (report.term_consistency_status) rows.push(['Nhất quán thuật ngữ', report.term_consistency_status]);
  if (rows.length === 0) return null;

  return (
    <dl className="quality-summary assist-qa-summary" aria-label="Tổng quan QA chương">
      {rows.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function GlossaryViolations({ violations }: { violations: Array<Record<string, unknown>> }) {
  return (
    <div className="qa-issue-card assist-glossary-violations">
      <strong>Vi phạm thuật ngữ khóa</strong>
      <ul>
        {violations.map((violation, index) => {
          const sourceTerm = readString(violation.source_term) || readString(violation.raw_text) || 'Thuật ngữ';
          const expected = readString(violation.expected) || readString(violation.preferred_translation);
          const message = readString(violation.message) || readString(violation.reason);
          return (
            <li key={`${sourceTerm}-${index}`}>
              <span>{expected ? `${sourceTerm} -> ${expected}` : sourceTerm}</span>
              {message ? <p>{message}</p> : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function renderTmState(tmState: LoadState, tmResults: TmSearchResult[]) {
  if (tmState === 'idle') {
    return <p className="empty-detail">Nhập đoạn nguồn để tìm ký ức dịch.</p>;
  }

  if (tmState === 'loading') {
    return <p className="empty-detail">Đang tìm TM...</p>;
  }

  if (tmState === 'empty') {
    return <p className="empty-detail">Không tìm thấy TM phù hợp.</p>;
  }

  if (tmResults.length === 0) return null;

  return (
    <div className="tm-result-list">
      {tmResults.map((result, index) => (
        <article className="tm-match" key={`${result.source_text}-${index}`}>
          <strong>TM {result.match_score}%</strong>
          <div>
            <span>Source</span>
            <p>{result.source_text}</p>
          </div>
          <div>
            <span>Vietnamese</span>
            <p>{result.translation_text}</p>
          </div>
        </article>
      ))}
    </div>
  );
}

export default function AssistPanel({
  activeJob,
  glossaryError,
  pendingGlossaryCount,
  qaIssues,
  qaReport,
  qaState,
  relevantTerms,
  tmError,
  tmResults,
  tmState,
  onRunQa,
  onApplyQaFix,
  onSearchTm,
}: AssistPanelProps) {
  const [tmQuery, setTmQuery] = useState('');

  function handleTmSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    onSearchTm(tmQuery);
  }

  return (
    <aside aria-labelledby="assist-panel-title" className="assist-panel">
      <header className="assist-panel-title">
        <p className="section-label">Operator</p>
        <h2 id="assist-panel-title">Trợ lý dịch</h2>
      </header>

      <section aria-labelledby="assist-job-title" className="assist-panel-section assist-job-section">
        <div className="assist-section-header">
          <h3 id="assist-job-title">Tác vụ hiện tại</h3>
        </div>
        <JobProgress job={activeJob} />
      </section>

      <section aria-labelledby="assist-qa-title" className="assist-panel-section assist-qa-section">
        <div className="assist-section-header">
          <h3 id="assist-qa-title">QA</h3>
          <button className="secondary-action" onClick={onRunQa} type="button">
            Chạy QA
          </button>
        </div>
        {renderQaState(qaState, qaIssues, qaReport, onApplyQaFix)}
      </section>

      <section aria-labelledby="assist-terms-title" className="assist-panel-section assist-terms-section">
        <div className="assist-section-header">
          <h3 id="assist-terms-title">Thuật ngữ liên quan</h3>
          <span className="status-chip">{pendingGlossaryCount} thuật ngữ chờ duyệt</span>
        </div>
        {glossaryError ? <p className="status-error">{glossaryError}</p> : null}
        {relevantTerms.length > 0 ? (
          <ul className="term-hit-list">
            {relevantTerms.map((term) => (
              <li key={term.id}>
                <strong>{term.source_term}</strong>
                <span>{term.target_term}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="empty-detail">Không có thuật ngữ khớp đoạn nguồn.</p>
        )}
      </section>

      <section aria-labelledby="assist-tm-title" className="assist-panel-section assist-tm-section">
        <div className="assist-section-header">
          <h3 id="assist-tm-title">Translation Memory</h3>
        </div>
        <form className="tm-search" onSubmit={handleTmSubmit}>
          <label>
            <span>Tìm TM</span>
            <input
              onChange={(event) => setTmQuery(event.target.value)}
              type="search"
              value={tmQuery}
            />
          </label>
          <button className="secondary-action" type="submit">
            Tìm TM
          </button>
        </form>
        {tmError ? <p className="status-error">{tmError}</p> : null}
        {renderTmState(tmState, tmResults)}
      </section>
    </aside>
  );
}
