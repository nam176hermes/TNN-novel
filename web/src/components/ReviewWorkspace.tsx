import { useEffect, useState } from 'react';

export type ReviewIssue = {
  type: string;
  message: string;
};

type Props = {
  sourceParagraph: string;
  translatedParagraph: string;
  issues: ReviewIssue[];
  onPolish: () => void;
  onRetranslate: () => void;
  onSave: (text: string) => void;
};

export default function ReviewWorkspace({
  sourceParagraph,
  translatedParagraph,
  issues,
  onPolish,
  onRetranslate,
  onSave,
}: Props) {
  const [text, setText] = useState(translatedParagraph);

  useEffect(() => {
    setText(translatedParagraph);
  }, [sourceParagraph, translatedParagraph]);

  return (
    <section aria-label="Review workspace" className="review-workspace panel">
      <div className="review-column">
        <p className="section-label">Source</p>
        <h3>Chinese paragraph</h3>
        <p className="review-source">{sourceParagraph}</p>
      </div>

      <div className="review-column">
        <label className="review-editor">
          <span>Vietnamese translation</span>
          <textarea onChange={(event) => setText(event.target.value)} value={text} />
        </label>
      </div>

      <aside className="review-actions" aria-label="QA repair actions">
        <div>
          <p className="section-label">QA Issues</p>
          <h3>Repair queue</h3>
        </div>

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
          <p className="empty-detail">No QA issues for this paragraph.</p>
        )}

        <div className="review-action-list">
          <button className="secondary-action" onClick={onPolish} type="button">
            Polish paragraph
          </button>
          <button className="secondary-action" onClick={onRetranslate} type="button">
            Retranslate paragraph
          </button>
          <button className="primary-action" onClick={() => onSave(text)} type="button">
            Save edited translation
          </button>
        </div>
      </aside>
    </section>
  );
}
