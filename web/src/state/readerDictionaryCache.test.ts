import { describe, expect, it } from 'vitest';
import type { ReaderDictionaryPack, ReaderDictionaryResponse } from '../api/types';
import {
  loadCachedReaderDictionaryPack,
  loadCachedReaderDictionaryResult,
  lookupCachedReaderDictionaryPack,
  readerDictionaryCacheKey,
  saveCachedReaderDictionaryPack,
  saveCachedReaderDictionaryResult,
} from './readerDictionaryCache';

function storage(): Storage {
  const values = new Map<string, string>();
  return {
    get length() {
      return values.size;
    },
    clear: () => values.clear(),
    getItem: (key: string) => values.get(key) ?? null,
    key: (index: number) => Array.from(values.keys())[index] ?? null,
    removeItem: (key: string) => {
      values.delete(key);
    },
    setItem: (key: string, value: string) => {
      values.set(key, value);
    },
  };
}

const response: ReaderDictionaryResponse = {
  book_id: 42,
  chapter_id: 102,
  query: 'đạo tâm',
  sources: [
    {
      category: 'concept',
      definition: 'Tâm cảnh tu đạo, căn cơ ý chí của tu sĩ.',
      provider: 'reader_cn_vi.tsv',
      source: 'offline_dictionary',
      target: 'đạo tâm',
      term: '道心',
      variants: ['dao tam'],
    },
  ],
  offline_count: 1,
  online: {
    count: 0,
    error: '',
    status: 'skipped',
  },
};

const pack: ReaderDictionaryPack = {
  book_id: 42,
  chapter_id: 102,
  sources: [
    {
      category: 'concept',
      definition: 'Tâm cảnh tu đạo, căn cơ ý chí của tu sĩ.',
      provider: 'reader_cn_vi.tsv',
      source: 'offline_dictionary',
      target: 'đạo tâm',
      term: '道心',
      variants: ['dao tam'],
    },
    {
      category: 'character',
      definition: 'Nhân vật chính.',
      source: 'xray',
      target: 'Hàn Lập',
      term: 'Hàn Lập',
      aliases: ['Han Li'],
    },
  ],
  source_count: 2,
  counts: {
    builtin: 0,
    glossary: 0,
    offline_dictionary: 1,
    xray: 1,
  },
  online: {
    count: 0,
    error: '',
    status: 'skipped',
  },
  generated_at: '2026-06-29T10:00:00Z',
};

describe('readerDictionaryCache', () => {
  it('stores and loads reader dictionary responses by normalized query', () => {
    const target = storage();

    saveCachedReaderDictionaryResult(response, target, '2026-06-29T10:00:00Z');

    expect(readerDictionaryCacheKey(42, '  ĐẠO   TÂM ')).toBe('42:đạo tâm');
    expect(loadCachedReaderDictionaryResult(42, 'Đạo Tâm', target)).toMatchObject({
      book_id: 42,
      query: 'đạo tâm',
      sources: [{ term: '道心', target: 'đạo tâm' }],
      cache: {
        hit: true,
        scope: 'browser',
        stored: false,
        updated_at: '2026-06-29T10:00:00Z',
      },
    });
  });

  it('ignores malformed cached dictionary payloads', () => {
    const target = storage();
    target.setItem('novel-reader-dictionary-cache-v1', '{"42:bad":{"result":{"book_id":"bad"}}}');

    expect(loadCachedReaderDictionaryResult(42, 'bad', target)).toBeNull();

    target.setItem('novel-reader-dictionary-cache-v1', 'not-json');
    expect(loadCachedReaderDictionaryResult(42, 'bad', target)).toBeNull();
  });

  it('stores dictionary packs and resolves offline lookup results from pack cache', () => {
    const target = storage();

    saveCachedReaderDictionaryPack(pack, target, '2026-06-29T10:01:00Z');

    expect(loadCachedReaderDictionaryPack(42, 102, target)).toMatchObject({
      book_id: 42,
      chapter_id: 102,
      source_count: 2,
      cache: {
        hit: true,
        scope: 'browser-pack',
        stored: false,
        updated_at: '2026-06-29T10:01:00Z',
      },
    });
    expect(lookupCachedReaderDictionaryPack(42, 'Đạo Tâm', 102, target)).toMatchObject({
      book_id: 42,
      chapter_id: 102,
      query: 'Đạo Tâm',
      offline_count: 1,
      online: {
        status: 'skipped',
        count: 0,
        error: '',
      },
      cache: {
        hit: true,
        scope: 'browser-pack',
        stored: false,
        updated_at: '2026-06-29T10:01:00Z',
      },
      sources: [
        {
          source: 'offline_dictionary',
          term: '道心',
          target: 'đạo tâm',
        },
      ],
    });
    expect(lookupCachedReaderDictionaryPack(42, 'Han Li', 102, target)?.sources[0]).toMatchObject({
      source: 'xray',
      term: 'Hàn Lập',
    });
    expect(lookupCachedReaderDictionaryPack(42, 'han lap', 102, target)?.sources[0]).toMatchObject({
      source: 'xray',
      term: 'Hàn Lập',
    });
  });

  it('orders cached pack phrase matches by their position in the selected text', () => {
    const target = storage();
    saveCachedReaderDictionaryPack({
      ...pack,
      counts: {
        builtin: 2,
        glossary: 0,
        offline_dictionary: 0,
        xray: 0,
      },
      source_count: 2,
      sources: [
        {
          category: 'item',
          definition: 'Đá chứa linh khí dùng để tu luyện.',
          provider: 'cn-vi-webnovel-lexicon',
          source: 'builtin',
          target: 'linh thạch',
          term: '灵石',
        },
        {
          category: 'item',
          definition: 'Pháp khí chứa đồ có không gian riêng.',
          provider: 'cn-vi-webnovel-lexicon',
          source: 'builtin',
          target: 'túi trữ vật',
          term: '储物袋',
        },
      ],
    }, target, '2026-06-29T10:02:00Z');

    expect(
      lookupCachedReaderDictionaryPack(
        42,
        'hắn vỗ nhẹ 储物袋 rồi lấy ra một viên 灵石',
        102,
        target,
      )?.sources.map((source) => source.term),
    ).toEqual(['储物袋', '灵石']);
  });

  it('matches traditional Chinese queries against simplified cached pack terms', () => {
    const target = storage();
    saveCachedReaderDictionaryPack({
      ...pack,
      counts: {
        builtin: 1,
        glossary: 0,
        offline_dictionary: 0,
        xray: 0,
      },
      source_count: 1,
      sources: [
        {
          category: 'concept',
          definition: 'Khí/nguồn năng lượng trời đất mà tu sĩ hấp thu để tu luyện.',
          provider: 'cn-vi-webnovel-lexicon',
          source: 'builtin',
          target: 'linh khí',
          term: '灵气',
        },
      ],
    }, target, '2026-06-29T10:03:00Z');

    expect(lookupCachedReaderDictionaryPack(42, '靈氣', 102, target)?.sources[0]).toMatchObject({
      source: 'builtin',
      target: 'linh khí',
      term: '灵气',
    });
  });
});
