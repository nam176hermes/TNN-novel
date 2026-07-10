import { describe, expect, it, vi } from 'vitest';
import { ApiClient } from './client';

describe('glossary and TM API', () => {
  it('searches translation memory', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        results: [
          {
            source_text: '他拿起灵石。',
            translation_text: 'Hắn cầm linh thạch lên.',
            match_score: 100,
            stored_score: 98,
          },
        ],
        total: 1,
      }),
    });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    const results = await client.searchTm('他拿起灵石。');

    expect(results[0].match_score).toBe(100);
    expect(fetchMock).toHaveBeenCalledWith(
      'http://test/api/glossary/tm/search?q=%E4%BB%96%E6%8B%BF%E8%B5%B7%E7%81%B5%E7%9F%B3%E3%80%82',
      expect.objectContaining({ headers: expect.objectContaining({ Authorization: 'Bearer access' }) }),
    );
  });

  it('updates glossary metadata and locks terms', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ message: 'Term updated' }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ message: 'Term locked' }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ message: 'Term unlocked' }),
      });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    await client.updateGlossaryTerm(7, {
      target_term: 'Trúc Cơ kỳ',
      term_type: 'realm',
      genre: 'tien_hiep',
      priority: 40,
      locked: 1,
    });
    await client.lockGlossaryTerm(7);
    await client.unlockGlossaryTerm(7);

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      'http://test/api/glossary/terms/7',
      expect.objectContaining({
        method: 'PATCH',
        headers: expect.objectContaining({
          Authorization: 'Bearer access',
          'Content-Type': 'application/json',
        }),
        body: JSON.stringify({
          target_term: 'Trúc Cơ kỳ',
          term_type: 'realm',
          genre: 'tien_hiep',
          priority: 40,
          locked: 1,
        }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      'http://test/api/glossary/terms/7/lock',
      expect.objectContaining({ method: 'POST' }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      'http://test/api/glossary/terms/7/unlock',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('approves and rejects glossary terms through explicit review endpoints', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ message: 'Term approved' }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ message: 'Term rejected' }),
      });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    await client.approveGlossaryTerm(7);
    await client.rejectGlossaryTerm(8);

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      'http://test/api/glossary/terms/7/approve',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      'http://test/api/glossary/terms/8/reject',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
  });

  it('loads glossary terms for a book', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        items: [
          {
            id: 7,
            book_id: 1,
            source_term: '筑基',
            target_term: 'Trúc Cơ',
            locked: 1,
            genre: 'tien_hiep',
            term_type: 'realm',
            priority: 40,
          },
        ],
        total: 1,
      }),
    });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    const terms = await client.getGlossaryTerms(1);

    expect(terms[0].term_type).toBe('realm');
    expect(fetchMock).toHaveBeenCalledWith(
      'http://test/api/glossary?book_id=1&per_page=500',
      expect.objectContaining({ headers: expect.objectContaining({ Authorization: 'Bearer access' }) }),
    );
  });
});
