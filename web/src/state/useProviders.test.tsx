import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ApiClient, ApiError } from '../api/client';
import type { CostEstimate, Provider, ProviderUsage } from '../api/types';
import { fixtureMissingKeyProvider, fixtureProvider, fixtureUsage } from '../test/fixtures';
import { useProviders } from './useProviders';

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });

  return { promise, resolve };
}

const fixtureEstimate: CostEstimate = {
  provider_id: 'gemini',
  model: 'gemini-live',
  chapter_count: 1,
  estimated_input_tokens: 12000,
  estimated_output_tokens: 16000,
  estimated_cost_usd: 0.0076,
  within_budget: true,
};

describe('useProviders', () => {
  it('loads providers and usage, selects the default enabled provider, and estimates cost', async () => {
    const client = {
      getProviders: vi.fn().mockResolvedValue([fixtureMissingKeyProvider, fixtureProvider]),
      getProviderUsage: vi.fn().mockResolvedValue(fixtureUsage),
      estimateCost: vi.fn().mockResolvedValue(fixtureEstimate),
    } as unknown as ApiClient;

    const { result } = renderHook(() => useProviders(client, true));

    await waitFor(() => expect(result.current.providers.state).toBe('ready'));

    expect(result.current.selectedProviderId).toBe('missing');
    expect(result.current.selectedProvider).toMatchObject({ id: 'missing' });
    expect(result.current.selectedProviderMissingKey).toBe(true);
    expect(result.current.usage).toBe(fixtureUsage);

    await act(async () => {
      await result.current.estimateForSource(24000, 2);
    });

    expect(client.estimateCost).toHaveBeenCalledWith('missing', 24000, 2, 0.03);
    expect(result.current.estimate).toBe(fixtureEstimate);
    expect(result.current.estimateState).toBe('ready');
  });

  it('reports honest empty provider data and resets when disabled', async () => {
    const client = {
      getProviders: vi.fn().mockResolvedValue([]),
      getProviderUsage: vi.fn().mockResolvedValue(fixtureUsage),
      estimateCost: vi.fn(),
    } as unknown as ApiClient;

    const { result, rerender } = renderHook(({ enabled }) => useProviders(client, enabled), {
      initialProps: { enabled: true },
    });

    await waitFor(() => expect(result.current.providers.state).toBe('empty'));
    expect(result.current.providers.data).toEqual([]);
    expect(result.current.selectedProviderId).toBe('');
    expect(result.current.usage).toBe(fixtureUsage);

    rerender({ enabled: false });

    expect(result.current.providers.state).toBe('idle');
    expect(result.current.providers.data).toEqual([]);
    expect(result.current.selectedProviderId).toBe('');
    expect(result.current.usage).toBeNull();
    expect(result.current.estimate).toBeNull();
  });

  it('preserves a valid selected provider across refreshes', async () => {
    const providers: Provider[] = [
      fixtureProvider,
      { ...fixtureProvider, id: 'deepseek', label: 'DeepSeek', enabled: 1 },
    ];
    const client = {
      getProviders: vi.fn().mockResolvedValue(providers),
      getProviderUsage: vi.fn().mockResolvedValue(fixtureUsage),
      estimateCost: vi.fn(),
    } as unknown as ApiClient;

    const { result } = renderHook(() => useProviders(client, true));

    await waitFor(() => expect(result.current.providers.state).toBe('ready'));

    act(() => result.current.setSelectedProviderId('deepseek'));
    await act(async () => {
      await result.current.refresh();
    });

    expect(result.current.selectedProviderId).toBe('deepseek');
  });

  it('tests a provider and records the result state', async () => {
    const providerTestResult = {
      provider_id: 'gemini',
      model: 'gemini-live',
      ok: true,
      sample: 'Hắn cầm linh thạch lên.',
    };
    const client = {
      getProviders: vi.fn().mockResolvedValue([fixtureProvider]),
      getProviderUsage: vi.fn().mockResolvedValue(fixtureUsage),
      estimateCost: vi.fn(),
      testProvider: vi.fn().mockResolvedValue(providerTestResult),
    } as unknown as ApiClient;

    const { result } = renderHook(() => useProviders(client, true));

    await waitFor(() => expect(result.current.providers.state).toBe('ready'));
    await act(async () => {
      await result.current.testProvider('gemini', '他拿起灵石。');
    });

    expect(client.testProvider).toHaveBeenCalledWith('gemini', '他拿起灵石。');
    expect(result.current.testState).toBe('ready');
    expect(result.current.testResult).toEqual(providerTestResult);
  });

  it('saves a provider key and updates provider key status in place', async () => {
    const savedProvider: Provider = { ...fixtureMissingKeyProvider, api_key_set: true };
    const client = {
      getProviders: vi.fn().mockResolvedValue([fixtureMissingKeyProvider]),
      getProviderUsage: vi.fn().mockResolvedValue(fixtureUsage),
      estimateCost: vi.fn(),
      saveProviderKey: vi.fn().mockResolvedValue(savedProvider),
    } as unknown as ApiClient;

    const { result } = renderHook(() => useProviders(client, true));

    await waitFor(() => expect(result.current.providers.state).toBe('ready'));
    await act(async () => {
      await result.current.saveProviderKey('missing', 'new-secret');
    });

    expect(client.saveProviderKey).toHaveBeenCalledWith('missing', 'new-secret');
    expect(result.current.keySaveState).toBe('ready');
    expect(result.current.keySaveMessage).toBe('Đã lưu API key cho Missing Key Provider.');
    expect(result.current.providers.data[0]).toMatchObject({ id: 'missing', api_key_set: true });
  });

  it('resets provider test result when the selected provider changes', async () => {
    const providers: Provider[] = [
      fixtureProvider,
      { ...fixtureProvider, id: 'deepseek', label: 'DeepSeek', enabled: 1 },
    ];
    const client = {
      getProviders: vi.fn().mockResolvedValue(providers),
      getProviderUsage: vi.fn().mockResolvedValue(fixtureUsage),
      estimateCost: vi.fn(),
      testProvider: vi.fn().mockResolvedValue({
        provider_id: 'gemini',
        model: 'gemini-live',
        ok: true,
        sample: 'OK',
      }),
    } as unknown as ApiClient;

    const { result } = renderHook(() => useProviders(client, true));

    await waitFor(() => expect(result.current.providers.state).toBe('ready'));
    await act(async () => {
      await result.current.testProvider('gemini');
    });
    expect(result.current.testState).toBe('ready');

    act(() => result.current.setSelectedProviderId('deepseek'));

    expect(result.current.testState).toBe('idle');
    expect(result.current.testResult).toBeNull();
  });

  it('ignores stale out-of-order provider refresh and estimate responses', async () => {
    const slowProviders = deferred<Provider[]>();
    const fastProviders = deferred<Provider[]>();
    const slowUsage = deferred<ProviderUsage>();
    const fastUsage = deferred<ProviderUsage>();
    const slowEstimate = deferred<CostEstimate>();
    const fastEstimate = deferred<CostEstimate>();
    const client = {
      getProviders: vi.fn()
        .mockReturnValueOnce(slowProviders.promise)
        .mockReturnValueOnce(fastProviders.promise),
      getProviderUsage: vi.fn()
        .mockReturnValueOnce(slowUsage.promise)
        .mockReturnValueOnce(fastUsage.promise),
      estimateCost: vi.fn()
        .mockReturnValueOnce(slowEstimate.promise)
        .mockReturnValueOnce(fastEstimate.promise),
    } as unknown as ApiClient;

    const { result } = renderHook(() => useProviders(client, true));

    await act(async () => {
      void result.current.refresh();
    });

    fastProviders.resolve([{ ...fixtureProvider, id: 'fresh', label: 'Fresh Provider' }]);
    fastUsage.resolve({ ...fixtureUsage, total_tokens: 100 });

    await waitFor(() => expect(result.current.selectedProviderId).toBe('fresh'));

    slowProviders.resolve([{ ...fixtureProvider, id: 'stale', label: 'Stale Provider' }]);
    slowUsage.resolve({ ...fixtureUsage, total_tokens: 999 });

    await waitFor(() => expect(result.current.selectedProviderId).toBe('fresh'));
    expect(result.current.providers.data[0]?.id).toBe('fresh');
    expect(result.current.usage?.total_tokens).toBe(100);

    await act(async () => {
      void result.current.estimateForSource(1000);
      void result.current.estimateForSource(2000);
    });

    fastEstimate.resolve({ ...fixtureEstimate, provider_id: 'fresh', estimated_cost_usd: 0.2 });
    await waitFor(() => expect(result.current.estimate?.estimated_cost_usd).toBe(0.2));

    slowEstimate.resolve({ ...fixtureEstimate, provider_id: 'fresh', estimated_cost_usd: 0.9 });
    await waitFor(() => expect(result.current.estimate?.estimated_cost_usd).toBe(0.2));
  });

  it('calls onAuthError when provider refresh returns 401', async () => {
    const onAuthError = vi.fn();
    const client = {
      getProviders: vi.fn().mockRejectedValue(new ApiError('Expired', 401)),
      getProviderUsage: vi.fn().mockResolvedValue(fixtureUsage),
      estimateCost: vi.fn(),
    } as unknown as ApiClient;

    renderHook(() => useProviders(client, true, onAuthError));

    await waitFor(() => expect(onAuthError).toHaveBeenCalledTimes(1));
  });
});
