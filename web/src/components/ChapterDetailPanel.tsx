import { Eye, ShieldCheck, Volume2 } from 'lucide-react';
import type { Chapter } from '../api/types';

type Props = {
  chapter: Chapter | null;
  onOpenReview?: (chapterId: number) => void;
  onRunQa?: (chapterId: number) => void;
  onGenerateTts?: (chapterId: number) => void;
};

function qaScoreLabel(score?: number): string {
  return typeof score === 'number' ? score.toFixed(1) : 'No QA report';
}

export default function ChapterDetailPanel({ chapter, onOpenReview, onRunQa, onGenerateTts }: Props) {
  if (!chapter) {
    return (
      <aside aria-label="Chapter detail" className="detail-panel panel">
        <p className="empty-detail">Select a chapter to inspect pipeline state.</p>
      </aside>
    );
  }

  return (
    <aside aria-labelledby="chapter-detail-title" className="detail-panel panel">
      <div className="panel-header">
        <div>
          <p className="section-label">Chapter detail</p>
          <h3 id="chapter-detail-title">
            {chapter.chapter_number}. {chapter.title}
          </h3>
        </div>
        <span className="status-chip">{chapter.latest_job_status ?? chapter.status}</span>
      </div>

      <dl className="detail-list">
        <div>
          <dt>Book</dt>
          <dd>{chapter.book_title ?? `Book ${chapter.book_id}`}</dd>
        </div>
        <div>
          <dt>Status</dt>
          <dd>{chapter.status}</dd>
        </div>
        <div>
          <dt>Provider</dt>
          <dd>{chapter.latest_provider ? `${chapter.latest_provider} · ${chapter.latest_model ?? 'default'}` : 'Not assigned'}</dd>
        </div>
      </dl>

      <section aria-labelledby="chapter-preview-title" className="detail-section">
        <div className="detail-section-header">
          <h4 id="chapter-preview-title">Text preview</h4>
          <button
            aria-label="Open review for selected chapter"
            onClick={() => onOpenReview?.(chapter.id)}
            type="button"
          >
            <Eye aria-hidden="true" size={15} />
            Open Review
          </button>
        </div>
        <div className="preview-columns">
          <div>
            <span>Source</span>
            <p>{chapter.source_preview ?? 'Source preview is not loaded.'}</p>
          </div>
          <div>
            <span>Vietnamese</span>
            <p>{chapter.translation_preview ?? 'Translation preview is not available.'}</p>
          </div>
        </div>
      </section>

      <section aria-labelledby="chapter-qa-title" className="detail-section">
        <div className="detail-section-header">
          <h4 id="chapter-qa-title">QA</h4>
          <button aria-label="Run QA for selected chapter" onClick={() => onRunQa?.(chapter.id)} type="button">
            <ShieldCheck aria-hidden="true" size={15} />
            Run QA
          </button>
        </div>
        <dl className="qa-grid">
          <div>
            <dt>Score</dt>
            <dd>{qaScoreLabel(chapter.qa_score)}</dd>
          </div>
          <div>
            <dt>Verdict</dt>
            <dd>{chapter.qa_verdict ?? 'Pending'}</dd>
          </div>
          <div>
            <dt>Issues</dt>
            <dd>{chapter.qa_issue_count ?? 0}</dd>
          </div>
        </dl>
        {chapter.top_issues?.length ? (
          <ul className="issue-list">
            {chapter.top_issues.map((issue) => (
              <li key={issue}>{issue}</li>
            ))}
          </ul>
        ) : null}
      </section>

      <section aria-labelledby="chapter-audio-title" className="detail-section">
        <div className="detail-section-header">
          <h4 id="chapter-audio-title">Audio</h4>
          <button
            aria-label="Generate TTS for selected chapter"
            onClick={() => onGenerateTts?.(chapter.id)}
            type="button"
          >
            <Volume2 aria-hidden="true" size={15} />
            Generate TTS
          </button>
        </div>
        <p>{chapter.audio_path ? 'Audio file ready for playback and export.' : 'No audio generated yet.'}</p>
        {chapter.error ? <p className="error-note">Latest error: {chapter.error}</p> : null}
      </section>
    </aside>
  );
}
