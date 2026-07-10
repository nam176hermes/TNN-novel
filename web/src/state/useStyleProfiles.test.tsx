import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ApiClient, ApiError } from '../api/client';
import type { StyleProfile } from '../api/types';
import { fixtureStyleProfile } from '../test/fixtures';
import { useStyleProfiles } from './useStyleProfiles';

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((next, fail) => {
    resolve = next;
    reject = fail;
  });

  return { promise, resolve, reject };
}

describe('useStyleProfiles', () => {
  it('loads profiles and selects the default profile', async () => {
    const client = {
      getStyleProfiles: vi.fn().mockResolvedValue([
        { ...fixtureStyleProfile, id: 'kiem_hiep', label: 'Kiếm hiệp', is_default: 0 },
        fixtureStyleProfile,
      ]),
      setDefaultStyleProfile: vi.fn(),
    } as unknown as ApiClient;

    const { result } = renderHook(() => useStyleProfiles(client, true));

    await waitFor(() => expect(result.current.profiles.state).toBe('ready'));
    expect(result.current.selectedStyleProfileId).toBe('tien_hiep');
  });

  it('reports empty data and resets when disabled', async () => {
    const client = {
      getStyleProfiles: vi.fn().mockResolvedValue([]),
      setDefaultStyleProfile: vi.fn(),
    } as unknown as ApiClient;

    const { result, rerender } = renderHook(({ enabled }) => useStyleProfiles(client, enabled), {
      initialProps: { enabled: true },
    });

    await waitFor(() => expect(result.current.profiles.state).toBe('empty'));
    expect(result.current.selectedStyleProfileId).toBe('');

    rerender({ enabled: false });

    expect(result.current.profiles.state).toBe('idle');
    expect(result.current.profiles.data).toEqual([]);
    expect(result.current.selectedStyleProfileId).toBe('');
  });

  it('preserves a valid selected profile and marks the returned default profile', async () => {
    const profiles: StyleProfile[] = [
      fixtureStyleProfile,
      { ...fixtureStyleProfile, id: 'kiem_hiep', label: 'Kiếm hiệp', is_default: 0 },
    ];
    const client = {
      getStyleProfiles: vi.fn().mockResolvedValue(profiles),
      setDefaultStyleProfile: vi.fn().mockResolvedValue({ ...profiles[1], is_default: 1 }),
    } as unknown as ApiClient;

    const { result } = renderHook(() => useStyleProfiles(client, true));

    await waitFor(() => expect(result.current.profiles.state).toBe('ready'));
    await act(async () => {
      await result.current.setDefaultProfile('kiem_hiep');
    });

    expect(result.current.selectedStyleProfileId).toBe('kiem_hiep');
    expect(result.current.profiles.data).toEqual([
      expect.objectContaining({ id: 'tien_hiep', is_default: 0 }),
      expect.objectContaining({ id: 'kiem_hiep', is_default: 1 }),
    ]);

    await act(async () => {
      await result.current.refresh();
    });

    expect(result.current.selectedStyleProfileId).toBe('kiem_hiep');
  });

  it('ignores stale default-profile failures after a newer selection succeeds', async () => {
    const profiles: StyleProfile[] = [
      fixtureStyleProfile,
      { ...fixtureStyleProfile, id: 'kiem_hiep', label: 'Kiếm hiệp', is_default: 0 },
    ];
    const slowDefault = deferred<StyleProfile>();
    const fastDefault = deferred<StyleProfile>();
    const client = {
      getStyleProfiles: vi.fn().mockResolvedValue(profiles),
      setDefaultStyleProfile: vi.fn()
        .mockReturnValueOnce(slowDefault.promise)
        .mockReturnValueOnce(fastDefault.promise),
    } as unknown as ApiClient;

    const { result } = renderHook(() => useStyleProfiles(client, true));

    await waitFor(() => expect(result.current.profiles.state).toBe('ready'));

    let firstSelection!: Promise<StyleProfile | null>;
    let secondSelection!: Promise<StyleProfile | null>;
    act(() => {
      firstSelection = result.current.setDefaultProfile('kiem_hiep');
      secondSelection = result.current.setDefaultProfile('tien_hiep');
    });

    fastDefault.resolve({ ...fixtureStyleProfile, is_default: 1 });
    await act(async () => {
      await secondSelection;
    });

    expect(result.current.selectedStyleProfileId).toBe('tien_hiep');

    slowDefault.reject(new Error('old profile failed'));
    await act(async () => {
      await expect(firstSelection).resolves.toBeNull();
    });

    expect(result.current.selectedStyleProfileId).toBe('tien_hiep');
    expect(result.current.profiles.data).toEqual([
      expect.objectContaining({ id: 'tien_hiep', is_default: 1 }),
      expect.objectContaining({ id: 'kiem_hiep', is_default: 0 }),
    ]);
  });

  it('ignores stale out-of-order profile refresh responses', async () => {
    const slowProfiles = deferred<StyleProfile[]>();
    const fastProfiles = deferred<StyleProfile[]>();
    const client = {
      getStyleProfiles: vi.fn()
        .mockReturnValueOnce(slowProfiles.promise)
        .mockReturnValueOnce(fastProfiles.promise),
      setDefaultStyleProfile: vi.fn(),
    } as unknown as ApiClient;

    const { result } = renderHook(() => useStyleProfiles(client, true));

    await act(async () => {
      void result.current.refresh();
    });

    fastProfiles.resolve([{ ...fixtureStyleProfile, id: 'fresh', label: 'Fresh', is_default: 1 }]);

    await waitFor(() => expect(result.current.selectedStyleProfileId).toBe('fresh'));

    slowProfiles.resolve([{ ...fixtureStyleProfile, id: 'stale', label: 'Stale', is_default: 1 }]);

    await waitFor(() => expect(result.current.selectedStyleProfileId).toBe('fresh'));
    expect(result.current.profiles.data[0]?.id).toBe('fresh');
  });

  it('calls onAuthError when profile refresh returns 401', async () => {
    const onAuthError = vi.fn();
    const client = {
      getStyleProfiles: vi.fn().mockRejectedValue(new ApiError('Expired', 401)),
      setDefaultStyleProfile: vi.fn(),
    } as unknown as ApiClient;

    renderHook(() => useStyleProfiles(client, true, onAuthError));

    await waitFor(() => expect(onAuthError).toHaveBeenCalledTimes(1));
  });
});
