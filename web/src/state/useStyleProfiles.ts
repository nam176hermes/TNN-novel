import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, type ApiClient } from '../api/client';
import type { StyleProfile } from '../api/types';
import { formatError, type AsyncState } from './types';

const emptyProfiles: AsyncState<StyleProfile[]> = { data: [], error: '', state: 'idle' };

function nextSelectedStyleProfileId(profiles: StyleProfile[], currentId: string): string {
  if (currentId && profiles.some((profile) => profile.id === currentId)) return currentId;
  return profiles.find((profile) => profile.is_default === 1)?.id ?? profiles[0]?.id ?? '';
}

export function useStyleProfiles(client: ApiClient, enabled: boolean, onAuthError?: () => void) {
  const [profiles, setProfiles] = useState<AsyncState<StyleProfile[]>>(emptyProfiles);
  const [selectedStyleProfileId, setSelectedStyleProfileId] = useState('');
  const refreshRequestIdRef = useRef(0);
  const defaultRequestIdRef = useRef(0);

  const reset = useCallback(() => {
    refreshRequestIdRef.current += 1;
    defaultRequestIdRef.current += 1;
    setProfiles(emptyProfiles);
    setSelectedStyleProfileId('');
  }, []);

  const refresh = useCallback(async () => {
    if (!enabled) {
      reset();
      return [];
    }

    const requestId = refreshRequestIdRef.current + 1;
    refreshRequestIdRef.current = requestId;
    setProfiles((current) => ({ data: current.data, error: '', state: 'loading' }));

    try {
      const nextProfiles = await client.getStyleProfiles();
      if (requestId !== refreshRequestIdRef.current) return nextProfiles;

      setProfiles({
        data: nextProfiles,
        error: '',
        state: nextProfiles.length > 0 ? 'ready' : 'empty',
      });
      setSelectedStyleProfileId((current) => nextSelectedStyleProfileId(nextProfiles, current));
      return nextProfiles;
    } catch (error) {
      if (requestId !== refreshRequestIdRef.current) throw error;
      if (error instanceof ApiError && error.status === 401) {
        onAuthError?.();
      }
      setProfiles((current) => ({ data: current.data, error: formatError(error), state: 'error' }));
      throw error;
    }
  }, [client, enabled, onAuthError, reset]);

  const setDefaultProfile = useCallback(
    async (styleProfileId: string) => {
      if (!enabled || !styleProfileId) return null;

      const requestId = defaultRequestIdRef.current + 1;
      defaultRequestIdRef.current = requestId;
      setSelectedStyleProfileId(styleProfileId);

      try {
        const profile = await client.setDefaultStyleProfile(styleProfileId);
        if (requestId !== defaultRequestIdRef.current) return null;
        setProfiles((current) => ({
          data: current.data.map((item) => ({ ...item, is_default: item.id === profile.id ? 1 : 0 })),
          error: current.error,
          state: current.state,
        }));
        setSelectedStyleProfileId(profile.id);
        return profile;
      } catch (error) {
        if (requestId !== defaultRequestIdRef.current) return null;
        if (error instanceof ApiError && error.status === 401) {
          onAuthError?.();
        }
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

  return {
    profiles,
    refresh,
    selectedStyleProfileId,
    setDefaultProfile,
    setSelectedStyleProfileId,
  };
}
