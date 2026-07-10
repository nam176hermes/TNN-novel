import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ApiError, type ApiClient } from '../api/client';
import type { CostEstimate, Provider, ProviderTestResult, ProviderUsage } from '../api/types';
import { defaultProviderId } from './translator';
import { formatError, type AsyncState, type LoadState } from './types';

const emptyProviders: AsyncState<Provider[]> = { data: [], error: '', state: 'idle' };

export function useProviders(client: ApiClient, enabled: boolean, onAuthError?: () => void) {
  const [providers, setProviders] = useState<AsyncState<Provider[]>>(emptyProviders);
  const [usage, setUsage] = useState<ProviderUsage | null>(null);
  const [selectedProviderId, setSelectedProviderId] = useState('');
  const [estimate, setEstimate] = useState<CostEstimate | null>(null);
  const [estimateState, setEstimateState] = useState<LoadState>('idle');
  const [estimateError, setEstimateError] = useState('');
  const [testResult, setTestResult] = useState<ProviderTestResult | null>(null);
  const [testState, setTestState] = useState<LoadState>('idle');
  const [testError, setTestError] = useState('');
  const [keySaveState, setKeySaveState] = useState<LoadState>('idle');
  const [keySaveError, setKeySaveError] = useState('');
  const [keySaveMessage, setKeySaveMessage] = useState('');
  const refreshRequestIdRef = useRef(0);
  const estimateRequestIdRef = useRef(0);
  const testRequestIdRef = useRef(0);
  const keySaveRequestIdRef = useRef(0);

  const reset = useCallback(() => {
    refreshRequestIdRef.current += 1;
    estimateRequestIdRef.current += 1;
    setProviders(emptyProviders);
    setUsage(null);
    setSelectedProviderId('');
    setEstimate(null);
    setEstimateState('idle');
    setEstimateError('');
    setTestResult(null);
    setTestState('idle');
    setTestError('');
    setKeySaveState('idle');
    setKeySaveError('');
    setKeySaveMessage('');
  }, []);

  const refresh = useCallback(async () => {
    if (!enabled) {
      reset();
      return { providers: [] as Provider[], usage: null as ProviderUsage | null };
    }

    const requestId = refreshRequestIdRef.current + 1;
    refreshRequestIdRef.current = requestId;
    setProviders((current) => ({ data: current.data, error: '', state: 'loading' }));

    try {
      const [nextProviders, nextUsage] = await Promise.all([client.getProviders(), client.getProviderUsage()]);
      if (requestId !== refreshRequestIdRef.current) return { providers: nextProviders, usage: nextUsage };

      setProviders({
        data: nextProviders,
        error: '',
        state: nextProviders.length > 0 ? 'ready' : 'empty',
      });
      setUsage(nextUsage);
      setSelectedProviderId((current) => {
        if (current && nextProviders.some((provider) => provider.id === current)) return current;
        return nextProviders.length > 0 ? defaultProviderId(nextProviders) : '';
      });

      return { providers: nextProviders, usage: nextUsage };
    } catch (error) {
      if (requestId !== refreshRequestIdRef.current) throw error;
      if (error instanceof ApiError && error.status === 401) {
        onAuthError?.();
      }
      setProviders((current) => ({ data: current.data, error: formatError(error), state: 'error' }));
      throw error;
    }
  }, [client, enabled, onAuthError, reset]);

  const estimateForSource = useCallback(
    async (sourceChars: number, chapterCount = 1) => {
      if (!enabled || !selectedProviderId || sourceChars <= 0 || chapterCount <= 0) {
        estimateRequestIdRef.current += 1;
        setEstimate(null);
        setEstimateState('idle');
        setEstimateError('');
        return null;
      }

      const requestId = estimateRequestIdRef.current + 1;
      estimateRequestIdRef.current = requestId;
      setEstimateError('');
      setEstimateState('loading');

      try {
        const nextEstimate = await client.estimateCost(selectedProviderId, sourceChars, chapterCount, 0.03);
        if (requestId !== estimateRequestIdRef.current) return nextEstimate;
        setEstimate(nextEstimate);
        setEstimateState('ready');
        return nextEstimate;
      } catch (error) {
        if (requestId !== estimateRequestIdRef.current) throw error;
        if (error instanceof ApiError && error.status === 401) {
          onAuthError?.();
        }
        setEstimate(null);
        setEstimateError(formatError(error));
        setEstimateState('error');
        throw error;
      }
    },
    [client, enabled, onAuthError, selectedProviderId],
  );

  const testProvider = useCallback(
    async (providerId: string, prompt = 'Translate this Chinese sentence to Vietnamese: 他拿起灵石。') => {
      if (!enabled || !providerId) {
        testRequestIdRef.current += 1;
        setTestResult(null);
        setTestState('idle');
        setTestError('');
        return null;
      }

      const requestId = testRequestIdRef.current + 1;
      testRequestIdRef.current = requestId;
      setTestResult(null);
      setTestError('');
      setTestState('loading');

      try {
        const result = await client.testProvider(providerId, prompt);
        if (requestId !== testRequestIdRef.current) return result;
        setTestResult(result);
        setTestState(result.ok ? 'ready' : 'error');
        return result;
      } catch (error) {
        if (requestId !== testRequestIdRef.current) throw error;
        if (error instanceof ApiError && error.status === 401) {
          onAuthError?.();
        }
        setTestResult(null);
        setTestError(formatError(error));
        setTestState('error');
        throw error;
      }
    },
    [client, enabled, onAuthError],
  );

  const saveProviderKey = useCallback(
    async (providerId: string, apiKey: string) => {
      if (!enabled || !providerId) {
        keySaveRequestIdRef.current += 1;
        setKeySaveState('idle');
        setKeySaveError('');
        setKeySaveMessage('');
        return null;
      }

      const requestId = keySaveRequestIdRef.current + 1;
      keySaveRequestIdRef.current = requestId;
      setKeySaveError('');
      setKeySaveMessage('');
      setKeySaveState('loading');

      try {
        const savedProvider = await client.saveProviderKey(providerId, apiKey);
        if (requestId !== keySaveRequestIdRef.current) return savedProvider;
        setProviders((current) => ({
          ...current,
          data: current.data.map((provider) => (provider.id === savedProvider.id ? savedProvider : provider)),
        }));
        setKeySaveMessage(`Đã lưu API key cho ${savedProvider.label}.`);
        setKeySaveState('ready');
        return savedProvider;
      } catch (error) {
        if (requestId !== keySaveRequestIdRef.current) throw error;
        if (error instanceof ApiError && error.status === 401) {
          onAuthError?.();
        }
        setKeySaveError(formatError(error));
        setKeySaveMessage('');
        setKeySaveState('error');
        throw error;
      }
    },
    [client, enabled, onAuthError],
  );

  useEffect(() => {
    if (!enabled) {
      reset();
      return;
    }

    void refresh().catch(() => {});
  }, [enabled, refresh, reset]);

  useEffect(() => {
    setEstimate(null);
    setEstimateState('idle');
    setEstimateError('');
    estimateRequestIdRef.current += 1;
    setTestResult(null);
    setTestState('idle');
    setTestError('');
    testRequestIdRef.current += 1;
    setKeySaveError('');
    setKeySaveMessage('');
    setKeySaveState('idle');
    keySaveRequestIdRef.current += 1;
  }, [selectedProviderId]);

  const selectedProvider = useMemo(
    () => providers.data.find((provider) => provider.id === selectedProviderId) ?? null,
    [providers.data, selectedProviderId],
  );

  return {
    estimate,
    estimateError,
    estimateForSource,
    estimateState,
    keySaveError,
    keySaveMessage,
    keySaveState,
    providers,
    refresh,
    saveProviderKey,
    selectedProvider,
    selectedProviderId,
    selectedProviderMissingKey: selectedProvider?.api_key_set === false,
    setSelectedProviderId,
    testError,
    testProvider,
    testResult,
    testState,
    usage,
  };
}
