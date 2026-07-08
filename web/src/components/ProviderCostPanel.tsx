import type { CostEstimate, Provider, StyleProfile } from '../api/types';

export type QualityMode = 'cheap' | 'balanced' | 'careful';

export type ProviderCostPanelProps = {
  providers: Provider[];
  styleProfiles: StyleProfile[];
  selectedProviderId: string;
  selectedStyleProfileId: string;
  selectedMode: QualityMode;
  estimate: CostEstimate | null;
  estimating?: boolean;
  translating?: boolean;
  onProviderChange(providerId: string): void;
  onStyleProfileChange(styleProfileId: string): void;
  onModeChange(mode: QualityMode): void;
  onEstimate(): void;
  onTranslate(): void;
};

function hasKey(provider: Provider | undefined): boolean {
  return provider?.api_key_set === true;
}

export default function ProviderCostPanel({
  providers,
  styleProfiles,
  selectedProviderId,
  selectedStyleProfileId,
  selectedMode,
  estimate,
  estimating = false,
  translating = false,
  onProviderChange,
  onStyleProfileChange,
  onModeChange,
  onEstimate,
  onTranslate,
}: ProviderCostPanelProps) {
  const selectedProvider = providers.find((provider) => provider.id === selectedProviderId);
  const selectedProviderMissingKey = Boolean(selectedProvider) && !hasKey(selectedProvider);
  const translateDisabled = translating || !selectedProvider || selectedProviderMissingKey;

  return (
    <section aria-label="Provider and cost controls" className="provider-cost-panel panel">
      <div className="panel-header">
        <div>
          <p className="section-label">Provider</p>
          <h3>Translate controls</h3>
        </div>
        {selectedProviderMissingKey ? <span className="status-chip status-chip-warning">Key missing</span> : null}
      </div>

      <div className="control-grid">
        <label>
          <span>Provider</span>
          <select onChange={(event) => onProviderChange(event.target.value)} value={selectedProviderId}>
            {providers.map((provider) => (
              <option key={provider.id} value={provider.id}>
                {provider.label}
              </option>
            ))}
          </select>
        </label>

        <label>
          <span>Quality mode</span>
          <select onChange={(event) => onModeChange(event.target.value as QualityMode)} value={selectedMode}>
            <option value="cheap">Cheap</option>
            <option value="balanced">Balanced</option>
            <option value="careful">Careful</option>
          </select>
        </label>

        <label>
          <span>Style profile</span>
          <select
            disabled={styleProfiles.length === 0}
            onChange={(event) => onStyleProfileChange(event.target.value)}
            value={selectedStyleProfileId}
          >
            {styleProfiles.length === 0 ? <option value="">None</option> : null}
            {styleProfiles.map((profile) => (
              <option key={profile.id} value={profile.id}>
                {profile.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {selectedProvider ? (
        <p className="empty-detail">
          {selectedProvider.model} · {selectedProvider.api_key_env}
        </p>
      ) : (
        <p className="empty-detail">No provider selected</p>
      )}

      {estimate ? (
        <dl className="estimate-grid">
          <div>
            <dt>Input tokens</dt>
            <dd>{estimate.estimated_input_tokens}</dd>
          </div>
          <div>
            <dt>Output tokens</dt>
            <dd>{estimate.estimated_output_tokens}</dd>
          </div>
          <div>
            <dt>Chapters</dt>
            <dd>{estimate.chapter_count}</dd>
          </div>
        </dl>
      ) : (
        <p className="empty-detail">No estimate yet</p>
      )}

      {estimate ? <strong className="estimate-total">Estimated cost: ${estimate.estimated_cost_usd.toFixed(4)}</strong> : null}

      <div className="dialog-actions">
        <button className="secondary-action" disabled={estimating} onClick={onEstimate} type="button">
          {estimating ? 'Estimating' : 'Estimate'}
        </button>
        <button className="primary-action" disabled={translateDisabled} onClick={onTranslate} type="button">
          Translate
        </button>
      </div>
    </section>
  );
}
