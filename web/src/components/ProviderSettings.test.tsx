import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { Provider } from '../api/types';
import { ProviderSettings } from './ProviderSettings';

const providers: Provider[] = [
  {
    id: 'sample-provider',
    label: 'Sample Provider',
    base_url: 'https://api.example.test/v1',
    model: 'sample-model-v1',
    api_key_env: 'SAMPLE_API_KEY',
    api_key_set: false,
    temperature: 0.2,
    timeout_seconds: 45,
    supports_streaming: 1,
    supports_batch: 0,
    cost_input_per_1m: 0.1,
    cost_output_per_1m: 0.4,
    enabled: 1,
    notes: 'Primary translation lane',
  },
];

describe('ProviderSettings', () => {
  it('renders provider metadata and cost controls in a dashboard table', () => {
    render(<ProviderSettings providers={providers} />);

    expect(screen.getByRole('heading', { name: 'Providers' })).toBeInTheDocument();
    expect(screen.getByText('Sample Provider')).toBeVisible();
    expect(screen.getByText('sample-model-v1')).toBeVisible();
    expect(screen.getByText('Key missing')).toBeVisible();
    expect(screen.getByText('$0.10 / 1M input')).toBeVisible();
    expect(screen.getByText('$0.40 / 1M output')).toBeVisible();
  });
});
