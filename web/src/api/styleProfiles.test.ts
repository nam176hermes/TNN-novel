import { describe, expect, it, vi } from 'vitest';
import { ApiClient } from './client';

describe('style profile API methods', () => {
  it('loads style profiles', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        profiles: [
          {
            id: 'tien_hiep',
            label: 'Tiên hiệp',
            pronoun_rules: 'ta/ngươi',
            han_viet_level: 'high',
            preferred_terms: 'tu vi',
            banned_modern_terms: 'tôi, bạn',
            prompt_rules: 'cổ trang',
            is_default: 1,
          },
        ],
      }),
    });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    const profiles = await client.getStyleProfiles();

    expect(profiles[0].id).toBe('tien_hiep');
    expect(fetchMock).toHaveBeenCalledWith(
      'http://test/api/style-profiles',
      expect.objectContaining({ headers: expect.objectContaining({ Authorization: 'Bearer access' }) }),
    );
  });

  it('sets default style profile', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        message: 'Default style profile updated',
        default: {
          id: 'kiem_hiep',
          label: 'Kiếm hiệp',
          is_default: 1,
        },
      }),
    });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    const profile = await client.setDefaultStyleProfile('kiem_hiep');

    expect(profile.id).toBe('kiem_hiep');
    expect(fetchMock).toHaveBeenCalledWith(
      'http://test/api/style-profiles/default',
      expect.objectContaining({
        method: 'PATCH',
        headers: expect.objectContaining({
          Authorization: 'Bearer access',
          'Content-Type': 'application/json',
        }),
        body: JSON.stringify({ style_profile_id: 'kiem_hiep' }),
      }),
    );
  });
});
