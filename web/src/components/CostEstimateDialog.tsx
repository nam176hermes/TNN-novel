import type { CostEstimate } from '../api/types';

type Props = {
  estimate: CostEstimate;
  onConfirm: () => void;
  onCancel: () => void;
};

function formatInteger(value: number): string {
  return new Intl.NumberFormat('en-US').format(value);
}

export default function CostEstimateDialog({ estimate, onConfirm, onCancel }: Props) {
  const overBudget = !estimate.within_budget;

  return (
    <section aria-label="Cost estimate" className="dialog cost-dialog" role="dialog">
      <div className="dialog-header">
        <div>
          <p className="section-label">Cost guard</p>
          <h2>Cost estimate</h2>
        </div>
        <span className={overBudget ? 'status-chip status-chip-warning' : 'status-chip status-chip-success'}>
          {overBudget ? 'Over budget' : 'Within budget'}
        </span>
      </div>

      <dl className="estimate-grid">
        <div>
          <dt>Provider</dt>
          <dd>{estimate.provider_id}</dd>
        </div>
        <div>
          <dt>Model</dt>
          <dd>{estimate.model}</dd>
        </div>
        <div>
          <dt>Chapters</dt>
          <dd>{estimate.chapter_count}</dd>
        </div>
        <div>
          <dt>Input tokens</dt>
          <dd>{formatInteger(estimate.estimated_input_tokens)}</dd>
        </div>
        <div>
          <dt>Output tokens</dt>
          <dd>{formatInteger(estimate.estimated_output_tokens)}</dd>
        </div>
      </dl>

      <strong className="estimate-total">Estimated cost: ${estimate.estimated_cost_usd.toFixed(6)}</strong>

      <div className="dialog-actions">
        <button className="secondary-action" onClick={onCancel} type="button">
          Cancel
        </button>
        <button className={overBudget ? 'danger-action' : 'primary-action'} onClick={onConfirm} type="button">
          {overBudget ? 'Confirm override' : 'Start job'}
        </button>
      </div>
    </section>
  );
}
