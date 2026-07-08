import { useState } from 'react';
import type { Provider, ProviderTestResult, ProviderUsage } from '../api/types';
import type { LoadState } from '../state/types';
import { HelpCircle, MoreVertical, Plus, Send, Sparkles } from 'lucide-react';
import deepseekLogo from '../assets/reference-ui/provider-deepseek.png';
import geminiLogo from '../assets/reference-ui/provider-gemini.png';
import ollamaLogo from '../assets/reference-ui/provider-ollama.png';
import openrouterLogo from '../assets/reference-ui/provider-openrouter.png';

export type ProvidersViewProps = {
  keySaveError?: string;
  keySaveMessage?: string;
  keySaveState?: LoadState;
  onSaveProviderKey?(providerId: string, apiKey: string): Promise<void> | void;
  onTestProvider(providerId: string): void;
  providers: Provider[];
  testError: string;
  testResult: ProviderTestResult | null;
  testState: LoadState;
  usage: ProviderUsage | null;
};

function isEnabled(value: boolean | number): boolean {
  return value === true || value === 1;
}

function formatCostPerMillion(value: number, direction: 'input' | 'output'): string {
  return `$${value.toFixed(2)} / 1M ${direction}`;
}

function formatTotalCost(value: number): string {
  return `$${value.toFixed(4)}`;
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat('vi-VN').format(value);
}

function providerLogo(provider: Provider): string {
  const key = `${provider.id} ${provider.label}`.toLowerCase();
  if (key.includes('deepseek')) return deepseekLogo;
  if (key.includes('gemini') || key.includes('google')) return geminiLogo;
  if (key.includes('ollama')) return ollamaLogo;
  if (key.includes('openrouter')) return openrouterLogo;
  return openrouterLogo;
}

export default function ProvidersView({
  keySaveError = '',
  keySaveMessage = '',
  keySaveState = 'idle',
  onSaveProviderKey,
  onTestProvider,
  providers,
  testError,
  testResult,
  testState,
  usage,
}: ProvidersViewProps) {
  const [draftKeys, setDraftKeys] = useState<Record<string, string>>({});
  const [helpOpen, setHelpOpen] = useState(false);
  const [providerNotice, setProviderNotice] = useState('');
  const totalTokens = usage?.total_tokens ?? 0;
  const totalCost = usage?.total_estimated_cost_usd ?? 0;
  const selectedTestProvider =
    providers.find((provider) => provider.api_key_set === true && isEnabled(provider.enabled)) ?? providers[0] ?? null;

  async function saveProviderKey(provider: Provider): Promise<void> {
    const nextKey = (draftKeys[provider.id] || '').trim();
    if (!nextKey || !onSaveProviderKey) return;
    try {
      await onSaveProviderKey(provider.id, nextKey);
      setDraftKeys((current) => ({ ...current, [provider.id]: '' }));
    } catch {
      // The parent owns the visible error state.
    }
  }

  return (
    <section aria-labelledby="providers-view-title" className="workflow-management-view providers-view">
      <header className="panel workbench-title">
        <div>
          <p className="section-label">Workflow</p>
          <h2 id="providers-view-title">Model API</h2>
        </div>
        <button
          aria-expanded={helpOpen}
          className="secondary-action help-action"
          onClick={() => setHelpOpen((current) => !current)}
          type="button"
        >
          <HelpCircle aria-hidden="true" size={16} />
          Hướng dẫn
        </button>
      </header>

      {helpOpen ? (
        <section aria-label="Hướng dẫn Model API" className="panel inline-help-panel">
          <p>
            Provider hiện được nạp từ cấu hình backend/env. Dán API key vào provider đã có,
            lưu key, rồi dùng “Test kết nối” để tạo attempt thật và kiểm tra model.
          </p>
        </section>
      ) : null}

      <section aria-labelledby="provider-usage-title" className="panel">
        <div className="panel-header">
          <div>
            <p className="section-label">Chi phí</p>
            <h3 id="provider-usage-title">Sử dụng hiện tại</h3>
          </div>
        </div>
        <dl className="estimate-grid">
          <div>
            <dt>Tổng token</dt>
            <dd>{formatNumber(totalTokens)}</dd>
          </div>
          <div>
            <dt>Chi phí ước tính</dt>
            <dd>{formatTotalCost(totalCost)}</dd>
          </div>
        </dl>
      </section>

      <section aria-labelledby="providers-table-title" className="panel">
        <div className="panel-header">
          <div>
            <p className="section-label">Provider</p>
            <h3 id="providers-table-title">Danh sách provider</h3>
          </div>
          <button
            className="secondary-action"
            onClick={() => setProviderNotice('Thêm provider tùy biến chưa có UI an toàn; hãy thêm provider qua cấu hình backend/env rồi restart server.')}
            type="button"
          >
            <Plus aria-hidden="true" size={16} />
            Thêm provider
          </button>
        </div>
        {providerNotice ? <p className="status-chip">{providerNotice}</p> : null}
        {keySaveState === 'loading' ? <p className="empty-detail">Đang lưu API key...</p> : null}
        {keySaveMessage ? <p className="status-success">{keySaveMessage}</p> : null}
        {keySaveError ? <p className="status-error">{keySaveError}</p> : null}

        {providers.length > 0 ? (
          <table className="provider-table providers-management-table">
            <thead>
              <tr>
                <th>Provider</th>
                <th>Model</th>
                <th>Key</th>
                <th>Env var</th>
                <th>Base URL</th>
                <th>Giá / 1M</th>
                <th aria-label="Thao tác" />
              </tr>
            </thead>
            <tbody>
              {providers.map((provider) => {
                const keySet = provider.api_key_set === true;
                const enabled = isEnabled(provider.enabled);

                return (
                  <tr key={provider.id}>
                    <th scope="row">
                      <span className="provider-identity">
                        <img alt="" aria-hidden="true" className="provider-logo-mark provider-logo-image" src={providerLogo(provider)} />
                        {provider.label}
                      </span>
                    </th>
                    <td>{provider.model}</td>
                    <td>
                      <span className={keySet ? 'status-chip status-chip-success' : 'status-chip status-chip-warning'}>
                        {keySet ? 'Đã cấu hình' : 'Thiếu key'}
                      </span>
                      {provider.api_key_env ? (
                        <form
                          className="provider-key-form"
                          onSubmit={(event) => {
                            event.preventDefault();
                            void saveProviderKey(provider);
                          }}
                        >
                          <label>
                            <span>API key cho {provider.label}</span>
                            <input
                              aria-label={`API key cho ${provider.label}`}
                              autoComplete="off"
                              onChange={(event) => setDraftKeys((current) => ({
                                ...current,
                                [provider.id]: event.target.value,
                              }))}
                              placeholder="Dán key mới"
                              type="password"
                              value={draftKeys[provider.id] || ''}
                            />
                          </label>
                          <button
                            className="secondary-action"
                            disabled={keySaveState === 'loading' || !(draftKeys[provider.id] || '').trim()}
                            type="submit"
                            aria-label={`Lưu key cho ${provider.label}`}
                          >
                            Lưu key
                          </button>
                        </form>
                      ) : null}
                      {!keySet ? <p className="empty-detail provider-missing-key-note">Thiếu API key</p> : null}
                    </td>
                    <td>
                      <code>{provider.api_key_env}</code>
                    </td>
                    <td className="provider-url">{provider.base_url}</td>
                    <td className="provider-pricing-cell">
                      <span>{formatCostPerMillion(provider.cost_input_per_1m, 'input')}</span>
                      <span>{formatCostPerMillion(provider.cost_output_per_1m, 'output')}</span>
                      <small>{enabled ? '1 concurrent' : 'Đang tắt'}</small>
                    </td>
                    <td>
                      <button
                        aria-label="Test model"
                        className="icon-action provider-row-test"
                        disabled={!keySet || !enabled || testState === 'loading'}
                        onClick={() => onTestProvider(provider.id)}
                        type="button"
                      >
                        <MoreVertical aria-hidden="true" size={17} />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : (
          <p className="empty-detail">Chưa có provider nào</p>
        )}
      </section>

      <section aria-labelledby="provider-test-title" className="panel">
        <div className="panel-header">
          <div>
            <p className="section-label">Kết nối</p>
            <h3 id="provider-test-title">Kết quả test model</h3>
          </div>
        </div>
        <div className="provider-test-controls">
          <label>
            <span>Provider</span>
            <input
              aria-label="Provider dùng để test kết nối"
              readOnly
              value={selectedTestProvider?.label ?? 'Chưa có provider'}
            />
          </label>
          <label>
            <span>Model</span>
            <input
              aria-label="Model dùng để test kết nối"
              readOnly
              value={selectedTestProvider?.model ?? 'Chưa có model'}
            />
          </label>
          <button
            className="primary-action provider-test-connect"
            disabled={
              !selectedTestProvider ||
              selectedTestProvider.api_key_set !== true ||
              !isEnabled(selectedTestProvider.enabled) ||
              testState === 'loading'
            }
            onClick={() => {
              if (selectedTestProvider) onTestProvider(selectedTestProvider.id);
            }}
            type="button"
          >
            <Send aria-hidden="true" size={16} />
            Test kết nối
          </button>
        </div>
        {testState === 'loading' ? <p className="empty-detail provider-test-empty"><Sparkles aria-hidden="true" size={22} /> Đang kiểm tra provider...</p> : null}
        {testError ? <p className="status-error">{testError}</p> : null}
        {testResult ? (
          <dl className="estimate-grid">
            <div>
              <dt>Provider</dt>
              <dd>{testResult.provider_id}</dd>
            </div>
            <div>
              <dt>Model</dt>
              <dd>{testResult.model}</dd>
            </div>
            <div>
              <dt>Trạng thái</dt>
              <dd>{testResult.ok ? 'OK' : 'Không có phản hồi'}</dd>
            </div>
            <div>
              <dt>Mẫu trả về</dt>
              <dd>{testResult.sample || 'Không có nội dung'}</dd>
            </div>
          </dl>
        ) : testState === 'idle' ? (
          <p className="empty-detail provider-test-empty">
            <Send aria-hidden="true" size={22} />
            Chưa test kết nối. Chọn provider và model rồi nhấn "Test kết nối" để kiểm tra.
          </p>
        ) : null}
      </section>
    </section>
  );
}
