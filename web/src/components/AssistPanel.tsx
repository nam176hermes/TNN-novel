import { useState, type FormEvent } from 'react';
import type { GlossaryTerm, JobStatus, TmSearchResult } from '../api/types';
import type { NormalizedQaIssue } from '../state/useQa';
import type { LoadState } from '../state/types';
import JobProgress from './JobProgress';

export type AssistPanelProps = {
  activeJob: JobStatus | null;
  glossaryError: string;
  pendingGlossaryCount: number;
  qaIssues: NormalizedQaIssue[];
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
  onApplyQaFix: (issue: NormalizedQaIssue) => void,
) {
  if (qaIssues.length > 0) {
    return (
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
    );
  }

  if (qaState === 'loading') return <p className="empty-detail">Đang tải QA...</p>;
  if (qaState === 'error') return null;
  return <p className="empty-detail">Chưa có QA</p>;
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
        {renderQaState(qaState, qaIssues, onApplyQaFix)}
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
