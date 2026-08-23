import { describe, expect, it, vi } from 'vitest';
import { fixtureGlossaryTerm } from '../test/fixtures';
import { ApiClient } from './client';

describe('glossary and TM API', () => {
  it('queries a bounded review page with filters and an abort signal', async () => {
    const controller = new AbortController();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        facets: { locked: { '0': 1 }, mode: {}, review_status: { NEEDS_REVIEW: 1 }, scope: { book: 1 }, term_type: {} },
        items: [],
        page: 1,
        pages: 0,
        per_page: 50,
        scope: 'book',
        total: 0,
      }),
    });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    const result = await client.queryGlossaryTerms(
      {
        book_id: 42,
        page: 1,
        per_page: 50,
        q: '筑基',
        review_status: 'NEEDS_REVIEW,CONFLICT',
        scope: 'book',
        sort: 'review',
      },
      { signal: controller.signal },
    );

    expect(result.scope).toBe('book');
    expect(fetchMock).toHaveBeenCalledWith(
      'http://test/api/glossary?book_id=42&page=1&per_page=50&q=%E7%AD%91%E5%9F%BA&review_status=NEEDS_REVIEW%2CCONFLICT&scope=book&sort=review',
      expect.objectContaining({ signal: controller.signal }),
    );
  });

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

  it('loads every legacy workbench glossary page with bounded requests', async () => {
    const pageOne = Array.from({ length: 200 }, (_, index) => ({
      ...fixtureGlossaryTerm,
      id: index + 1,
      source_term: `术语-${index + 1}`,
    }));
    const pageTwo = Array.from({ length: 200 }, (_, index) => ({
      ...fixtureGlossaryTerm,
      id: index + 201,
      source_term: `术语-${index + 201}`,
    }));
    const pageThree = Array.from({ length: 101 }, (_, index) => ({
      ...fixtureGlossaryTerm,
      id: index + 401,
      source_term: `术语-${index + 401}`,
    }));
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ items: pageOne, page: 1, pages: 3, per_page: 200, total: 501 }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ items: pageTwo, page: 2, pages: 3, per_page: 200, total: 501 }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ items: pageThree, page: 3, pages: 3, per_page: 200, total: 501 }),
      });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    const terms = await client.getGlossaryTerms(1);

    expect(terms).toHaveLength(501);
    expect(terms[200].source_term).toBe('术语-201');
    expect(terms[500].source_term).toBe('术语-501');
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      'http://test/api/glossary?book_id=1&page=1&per_page=200&include_weak=0',
      expect.objectContaining({ headers: expect.objectContaining({ Authorization: 'Bearer access' }) }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      'http://test/api/glossary?book_id=1&page=3&per_page=200&include_weak=0',
      expect.objectContaining({ headers: expect.objectContaining({ Authorization: 'Bearer access' }) }),
    );
  });

  it('aborts legacy workbench aggregation between glossary pages', async () => {
    const controller = new AbortController();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ items: [fixtureGlossaryTerm], page: 1, pages: 2, per_page: 200, total: 201 }),
      })
      .mockImplementationOnce((_url, options) => new Promise((_resolve, reject) => {
        options.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
      }));
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);

    const load = client.getGlossaryTerms(1, { signal: controller.signal });
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    controller.abort();

    await expect(load).rejects.toMatchObject({ name: 'AbortError' });
    expect(fetchMock.mock.calls[1][1]).toEqual(expect.objectContaining({ signal: controller.signal }));
  });
});
