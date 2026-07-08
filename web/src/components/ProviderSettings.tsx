import type { Provider } from '../api/types';

type ProviderSettingsProps = {
  providers: Provider[];
};

function formatCost(value: number, direction: 'input' | 'output'): string {
  return `$${value.toFixed(2)} / 1M ${direction}`;
}

function boolLabel(value: boolean | number): boolean {
  return value === true || value === 1;
}

export function ProviderSettings({ providers }: ProviderSettingsProps) {
  return (
    <section aria-labelledby="provider-settings-title" className="panel provider-settings">
      <div className="panel-header">
        <div>
          <p className="section-label">Provider settings</p>
          <h3 id="provider-settings-title">Providers</h3>
        </div>
      </div>

      <table className="provider-table provider-settings-table">
        <thead>
          <tr>
            <th>Provider</th>
            <th>Model</th>
            <th>Base URL</th>
            <th>Env var</th>
            <th>Key</th>
            <th>Input cost</th>
            <th>Output cost</th>
            <th>Enabled</th>
          </tr>
        </thead>
        <tbody>
          {providers.map((provider) => {
            const keySet = boolLabel(provider.api_key_set);
            const enabled = boolLabel(provider.enabled);

            return (
              <tr key={provider.id}>
                <th scope="row">
                  <span className="provider-name">{provider.label}</span>
                </th>
                <td>{provider.model}</td>
                <td className="provider-url">{provider.base_url}</td>
                <td>
                  <code>{provider.api_key_env}</code>
                </td>
                <td>
                  <span className={keySet ? 'status-chip status-chip-success' : 'status-chip status-chip-warning'}>
                    {keySet ? 'Key set' : 'Key missing'}
                  </span>
                </td>
                <td>{formatCost(provider.cost_input_per_1m, 'input')}</td>
                <td>{formatCost(provider.cost_output_per_1m, 'output')}</td>
                <td>{enabled ? 'Enabled' : 'Disabled'}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}
