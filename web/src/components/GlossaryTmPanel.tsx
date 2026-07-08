import { useEffect, useState } from 'react';
import type { GlossaryTerm, GlossaryTermUpdate, TmSearchResult } from '../api/types';

type Props = {
  pendingCount: number;
  bestMatch: TmSearchResult | null;
  glossaryTerms: GlossaryTerm[];
  onUpdateTerm(termId: number, updates: GlossaryTermUpdate): void;
  onLockToggle(termId: number, locked: boolean): void;
};

type TermRowProps = {
  term: GlossaryTerm;
  onUpdateTerm(termId: number, updates: GlossaryTermUpdate): void;
  onLockToggle(termId: number, locked: boolean): void;
};

function GlossaryTermRow({ term, onUpdateTerm, onLockToggle }: TermRowProps) {
  const [targetTerm, setTargetTerm] = useState(term.target_term);
  const [termType, setTermType] = useState(term.term_type || term.category || 'term');
  const [genre, setGenre] = useState(term.genre || '');
  const [priority, setPriority] = useState(String(term.priority ?? 0));
  const locked = term.locked === 1;

  useEffect(() => {
    setTargetTerm(term.target_term);
    setTermType(term.term_type || term.category || 'term');
    setGenre(term.genre || '');
    setPriority(String(term.priority ?? 0));
  }, [term]);

  function saveTerm(): void {
    onUpdateTerm(term.id, {
      target_term: targetTerm,
      term_type: termType,
      genre,
      priority: Number(priority) || 0,
    });
  }

  return (
    <article className="glossary-term-row">
      <div className="glossary-term-source">
        <strong>{term.source_term}</strong>
        <span className={locked ? 'status-chip' : 'status-chip status-chip-muted'}>
          {locked ? 'Locked' : 'Unlocked'}
        </span>
      </div>

      <label>
        <span>Vietnamese</span>
        <input
          aria-label={`Vietnamese term for ${term.source_term}`}
          onChange={(event) => setTargetTerm(event.target.value)}
          value={targetTerm}
        />
      </label>

      <div className="glossary-term-metadata">
        <label>
          <span>Type</span>
          <select
            aria-label={`Term type for ${term.source_term}`}
            onChange={(event) => setTermType(event.target.value)}
            value={termType}
          >
            <option value="term">Thuật ngữ</option>
            <option value="character">Nhân vật</option>
            <option value="realm">Cảnh giới</option>
            <option value="artifact">Pháp bảo</option>
            <option value="technique">Chiêu thức</option>
            <option value="sect">Môn phái</option>
            <option value="place">Địa danh</option>
            <option value="title">Danh xưng</option>
          </select>
        </label>

        <label>
          <span>Genre</span>
          <input
            aria-label={`Genre for ${term.source_term}`}
            onChange={(event) => setGenre(event.target.value)}
            value={genre}
          />
        </label>

        <label>
          <span>Priority</span>
          <input
            aria-label={`Priority for ${term.source_term}`}
            min="0"
            onChange={(event) => setPriority(event.target.value)}
            type="number"
            value={priority}
          />
        </label>
      </div>

      <div className="dialog-actions">
        <button aria-label={`Save ${term.source_term}`} className="secondary-action" onClick={saveTerm} type="button">
          Save
        </button>
        <button
          aria-label={`${locked ? 'Unlock' : 'Lock'} ${term.source_term}`}
          className={locked ? 'secondary-action' : 'primary-action'}
          onClick={() => onLockToggle(term.id, !locked)}
          type="button"
        >
          {locked ? 'Unlock' : 'Lock'}
        </button>
      </div>
    </article>
  );
}

export default function GlossaryTmPanel({
  pendingCount,
  bestMatch,
  glossaryTerms,
  onUpdateTerm,
  onLockToggle,
}: Props) {
  return (
    <section aria-labelledby="glossary-tm-title" className="terminology-panel panel">
      <div className="panel-header">
        <div>
          <p className="section-label">Terminology memory</p>
          <h3 id="glossary-tm-title">Glossary/TM</h3>
        </div>
        <span className="status-chip">{pendingCount} pending terms</span>
      </div>

      {bestMatch ? (
        <article className="tm-match">
          <strong>TM {bestMatch.match_score}%</strong>
          <div>
            <span>Source</span>
            <p>{bestMatch.source_text}</p>
          </div>
          <div>
            <span>Vietnamese</span>
            <p>{bestMatch.translation_text}</p>
          </div>
        </article>
      ) : (
        <p className="empty-detail">No TM match selected</p>
      )}

      {glossaryTerms.length > 0 ? (
        <div className="glossary-term-list">
          {glossaryTerms.slice(0, 12).map((term) => (
            <GlossaryTermRow
              key={term.id}
              onLockToggle={onLockToggle}
              onUpdateTerm={onUpdateTerm}
              term={term}
            />
          ))}
        </div>
      ) : null}
    </section>
  );
}
