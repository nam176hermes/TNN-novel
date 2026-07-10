import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { vi } from 'vitest';
import type { Provider } from '../api/types';
import { fixtureMissingKeyProvider, fixtureProvider, fixtureUsage } from '../test/fixtures';
import ProvidersView from './ProvidersView';

afterEach(cleanup);

const providerWithSecret = {
  ...fixtureProvider,
  api_key: 'sk-secret-should-not-render',
} as Provider & { api_key: string };

const missingKeyProvider: Provider = {
  ...fixtureMissingKeyProvider,
  base_url: 'https://missing.example.test/v1',
  cost_input_per_1m: 0.2,
  cost_output_per_1m: 0.8,
  model: 'missing-model-v1',
};

describe('ProvidersView', () => {
  it('renders provider metadata, key status, pricing, and usage without exposing keys', () => {
    render(
      <ProvidersView
        onTestProvider={vi.fn()}
        providers={[providerWithSecret, missingKeyProvider]}
        testError=""
        testResult={null}
        testState="idle"
        usage={{
          ...fixtureUsage,
          total_prompt_tokens: 1200,
          total_completion_tokens: 800,
          total_tokens: 2000,
          total_estimated_cost_usd: 0.1234,
        }}
      />,
    );

    expect(screen.getByRole('heading', { name: 'Model API' })).toBeInTheDocument();
    expect(screen.getByText('Live Gemini')).toBeVisible();
    expect(screen.getByText('gemini-live')).toBeVisible();
    expect(screen.getByText('https://generativelanguage.googleapis.com/v1beta/openai')).toBeVisible();
    expect(screen.getByText('GEMINI_API_KEY')).toBeVisible();
    expect(screen.getByText('Đã cấu hình')).toBeVisible();
    expect(screen.getByText('Thiếu key')).toBeVisible();
    expect(screen.getByText('$0.10 / 1M input')).toBeVisible();
    expect(screen.getByText('$0.40 / 1M output')).toBeVisible();
    expect(screen.getByText('2.000')).toBeVisible();
    expect(screen.getByText('$0.1234')).toBeVisible();
    const testButtons = screen.getAllByRole('button', { name: 'Test model' });
    expect(testButtons[0]).toBeEnabled();
    expect(testButtons[1]).toBeDisabled();
    expect(screen.getByText('Thiếu API key')).toBeVisible();
    expect(screen.queryByText('sk-secret-should-not-render')).not.toBeInTheDocument();
  });

  it('calls provider test action and renders the result', async () => {
    const onTestProvider = vi.fn();
    render(
      <ProvidersView
        onTestProvider={onTestProvider}
        providers={[fixtureProvider]}
        testError=""
        testResult={{
          provider_id: 'gemini',
          model: 'gemini-live',
          ok: true,
          sample: 'Hắn cầm linh thạch lên.',
        }}
        testState="ready"
        usage={fixtureUsage}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Test model' }));

    expect(onTestProvider).toHaveBeenCalledWith('gemini');
    expect(screen.getByText('Hắn cầm linh thạch lên.')).toBeVisible();
  });

  it('lets the operator save a provider API key without rendering the secret as text', async () => {
    const onSaveProviderKey = vi.fn().mockResolvedValue(undefined);
    render(
      <ProvidersView
        keySaveError=""
        keySaveMessage=""
        keySaveState="idle"
        onSaveProviderKey={onSaveProviderKey}
        onTestProvider={vi.fn()}
        providers={[missingKeyProvider]}
        testError=""
        testResult={null}
        testState="idle"
        usage={fixtureUsage}
      />,
    );

    const keyInput = screen.getByLabelText('API key cho Missing Key Provider');
    await userEvent.type(keyInput, 'new-secret');
    await userEvent.click(screen.getByRole('button', { name: 'Lưu key cho Missing Key Provider' }));

    expect(onSaveProviderKey).toHaveBeenCalledWith('missing', 'new-secret');
    expect(keyInput).toHaveValue('');
    expect(screen.queryByText('new-secret')).not.toBeInTheDocument();
  });

  it('shows an honest empty state when no providers are configured', () => {
    render(
      <ProvidersView
        onTestProvider={vi.fn()}
        providers={[]}
        testError=""
        testResult={null}
        testState="idle"
        usage={null}
      />,
    );

    expect(screen.getByRole('heading', { name: 'Model API' })).toBeInTheDocument();
    expect(screen.getByText('Chưa có provider nào')).toBeVisible();
    expect(screen.getByText('0')).toBeVisible();
    expect(screen.getByText('$0.0000')).toBeVisible();
  });

  it('opens provider guidance and reports unsupported provider creation instead of no-op buttons', async () => {
    render(
      <ProvidersView
        onTestProvider={vi.fn()}
        providers={[fixtureProvider]}
        testError=""
        testResult={null}
        testState="idle"
        usage={fixtureUsage}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Hướng dẫn' }));
    expect(screen.getByRole('region', { name: 'Hướng dẫn Model API' })).toHaveTextContent('Test kết nối');

    await userEvent.click(screen.getByRole('button', { name: 'Thêm provider' }));
    expect(screen.getByText(/chưa có UI an toàn/i)).toBeVisible();
  });
});
