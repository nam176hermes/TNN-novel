export type ReviewEditorProps = {
  sourceText: string;
  translationText: string;
  savedTranslationText: string | null;
  loading?: boolean;
  onChange: (text: string) => void;
  onSave: (text: string) => void;
  onCopyTranslation?: () => void;
};

export default function ReviewEditor({
  sourceText,
  translationText,
  savedTranslationText,
  loading = false,
  onChange,
  onSave,
  onCopyTranslation,
}: ReviewEditorProps) {
  const isDirty = translationText !== (savedTranslationText ?? '');

  return (
    <section aria-label="Chapter editor" className="chapter-editor panel">
      <div className="review-column">
        <p className="section-label">Source</p>
        <h3>Original chapter</h3>
        <article className="review-source">{sourceText || 'No source text loaded.'}</article>
      </div>

      <div className="review-column">
        <label className="review-editor">
          <span>Vietnamese translation</span>
          <textarea
            disabled={loading}
            onChange={(event) => onChange(event.target.value)}
            value={translationText}
          />
        </label>

        <div className="review-action-list">
          {onCopyTranslation ? (
            <button className="secondary-action" disabled={loading} onClick={onCopyTranslation} type="button">
              Copy
            </button>
          ) : null}
          <button
            className="primary-action"
            disabled={loading || !isDirty}
            onClick={() => onSave(translationText)}
            type="button"
          >
            Save
          </button>
        </div>
      </div>
    </section>
  );
}
