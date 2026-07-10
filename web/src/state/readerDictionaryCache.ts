import type { ReaderDictionaryPack, ReaderDictionaryResponse, ReaderDictionarySource } from '../api/types';

export const READER_DICTIONARY_CACHE_STORAGE_KEY = 'novel-reader-dictionary-cache-v1';
export const READER_DICTIONARY_PACK_CACHE_STORAGE_KEY = 'novel-reader-dictionary-pack-cache-v1';
const MAX_READER_DICTIONARY_CACHE_ENTRIES = 200;
const MAX_READER_DICTIONARY_PACK_CACHE_ENTRIES = 20;
const DICTIONARY_SOURCE_PRIORITY: Record<string, number> = {
  glossary: 0,
  offline_dictionary: 1,
  builtin: 2,
  xray: 3,
  online: 4,
};
const TRADITIONAL_TO_SIMPLIFIED: Record<string, string> = {
  萬: '万',
  與: '与',
  東: '东',
  兩: '两',
  個: '个',
  為: '为',
  麗: '丽',
  書: '书',
  亂: '乱',
  爭: '争',
  於: '于',
  雲: '云',
  傳: '传',
  傷: '伤',
  儲: '储',
  兒: '儿',
  獸: '兽',
  內: '内',
  寫: '写',
  軍: '军',
  凍: '冻',
  劍: '剑',
  動: '动',
  勢: '势',
  勸: '劝',
  區: '区',
  華: '华',
  單: '单',
  雙: '双',
  發: '发',
  變: '变',
  葉: '叶',
  號: '号',
  後: '后',
  聽: '听',
  啟: '启',
  問: '问',
  嘗: '尝',
  嘯: '啸',
  噴: '喷',
  圖: '图',
  團: '团',
  國: '国',
  聖: '圣',
  場: '场',
  塊: '块',
  堅: '坚',
  執: '执',
  壽: '寿',
  夢: '梦',
  頭: '头',
  奪: '夺',
  嬰: '婴',
  學: '学',
  宮: '宫',
  實: '实',
  寧: '宁',
  寶: '宝',
  對: '对',
  尋: '寻',
  導: '导',
  將: '将',
  專: '专',
  層: '层',
  屬: '属',
  歲: '岁',
  峽: '峡',
  島: '岛',
  嶺: '岭',
  巔: '巅',
  師: '师',
  帶: '带',
  幫: '帮',
  廢: '废',
  廣: '广',
  開: '开',
  異: '异',
  張: '张',
  強: '强',
  彈: '弹',
  歸: '归',
  當: '当',
  錄: '录',
  徑: '径',
  徹: '彻',
  憶: '忆',
  懷: '怀',
  態: '态',
  總: '总',
  惡: '恶',
  驚: '惊',
  懼: '惧',
  懸: '悬',
  懶: '懒',
  應: '应',
  戲: '戏',
  戰: '战',
  掃: '扫',
  揚: '扬',
  撫: '抚',
  護: '护',
  報: '报',
  擔: '担',
  擁: '拥',
  攔: '拦',
  擊: '击',
  擋: '挡',
  擠: '挤',
  揮: '挥',
  換: '换',
  捲: '卷',
  掙: '挣',
  揀: '拣',
  煉: '炼',
  練: '练',
  築: '筑',
  氣: '气',
  靈: '灵',
  陣: '阵',
  門: '门',
  長: '长',
  風: '风',
  飛: '飞',
  龍: '龙',
  鳳: '凤',
  體: '体',
  術: '术',
  級: '级',
  階: '阶',
  訣: '诀',
  藥: '药',
  塵: '尘',
  虛: '虚',
  無: '无',
  轉: '转',
  結: '结',
  黃: '黄',
};

type CachedReaderDictionaryEntry = {
  cachedAt: string;
  result: ReaderDictionaryResponse;
};

type ReaderDictionaryCacheStore = Record<string, CachedReaderDictionaryEntry>;

type CachedReaderDictionaryPackEntry = {
  cachedAt: string;
  pack: ReaderDictionaryPack;
};

type ReaderDictionaryPackCacheStore = Record<string, CachedReaderDictionaryPackEntry>;

function getBrowserStorage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function normalizeDictionaryQuery(query: string): string {
  return query.replace(/\s+/g, ' ').trim().toLocaleLowerCase('vi-VN');
}

function stripVietnameseDiacritics(value: string): string {
  return value
    .replace(/đ/g, 'd')
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '');
}

function foldChineseVariants(value: string): string {
  return Array.from(value)
    .map((character) => TRADITIONAL_TO_SIMPLIFIED[character] ?? character)
    .join('');
}

function dictionaryMatchForms(value: string): Set<string> {
  const normalized = normalizeDictionaryQuery(value);
  if (!normalized) return new Set();
  const folded = foldChineseVariants(normalized);
  return new Set([
    normalized,
    folded,
    stripVietnameseDiacritics(normalized),
    stripVietnameseDiacritics(folded),
  ]);
}

export function readerDictionaryCacheKey(bookId: number, query: string): string {
  return `${bookId}:${normalizeDictionaryQuery(query)}`;
}

export function readerDictionaryPackCacheKey(bookId: number, chapterId?: number | null): string {
  return `${bookId}:${chapterId == null ? 'book' : chapterId}`;
}

function validResponse(value: unknown): value is ReaderDictionaryResponse {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const entry = value as Partial<ReaderDictionaryResponse>;
  const bookId = entry.book_id;
  return Number.isInteger(bookId)
    && Number(bookId) > 0
    && typeof entry.query === 'string'
    && Array.isArray(entry.sources)
    && typeof entry.online === 'object'
    && entry.online !== null
    && Number.isInteger(entry.offline_count);
}

function validPack(value: unknown): value is ReaderDictionaryPack {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const entry = value as Partial<ReaderDictionaryPack>;
  return Number.isInteger(entry.book_id)
    && Number(entry.book_id) > 0
    && (entry.chapter_id === null || Number.isInteger(entry.chapter_id))
    && Array.isArray(entry.sources)
    && Number.isInteger(entry.source_count)
    && typeof entry.counts === 'object'
    && entry.counts !== null
    && typeof entry.online === 'object'
    && entry.online !== null
    && typeof entry.generated_at === 'string';
}

function normalizeEntry(value: unknown): CachedReaderDictionaryEntry | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const entry = value as Partial<CachedReaderDictionaryEntry>;
  if (!validResponse(entry.result)) return null;
  return {
    cachedAt: typeof entry.cachedAt === 'string' ? entry.cachedAt : '',
    result: entry.result,
  };
}

function normalizePackEntry(value: unknown): CachedReaderDictionaryPackEntry | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const entry = value as Partial<CachedReaderDictionaryPackEntry>;
  if (!validPack(entry.pack)) return null;
  return {
    cachedAt: typeof entry.cachedAt === 'string' ? entry.cachedAt : '',
    pack: entry.pack,
  };
}

function readCache(storage: Storage | null): ReaderDictionaryCacheStore {
  if (!storage) return {};
  try {
    const parsed = JSON.parse(storage.getItem(READER_DICTIONARY_CACHE_STORAGE_KEY) ?? '{}') as unknown;
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    return Object.fromEntries(
      Object.entries(parsed)
        .map(([key, value]) => [key, normalizeEntry(value)] as const)
        .filter((entry): entry is [string, CachedReaderDictionaryEntry] => entry[1] !== null),
    );
  } catch {
    return {};
  }
}

function readPackCache(storage: Storage | null): ReaderDictionaryPackCacheStore {
  if (!storage) return {};
  try {
    const parsed = JSON.parse(storage.getItem(READER_DICTIONARY_PACK_CACHE_STORAGE_KEY) ?? '{}') as unknown;
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    return Object.fromEntries(
      Object.entries(parsed)
        .map(([key, value]) => [key, normalizePackEntry(value)] as const)
        .filter((entry): entry is [string, CachedReaderDictionaryPackEntry] => entry[1] !== null),
    );
  } catch {
    return {};
  }
}

function writeCache(cache: ReaderDictionaryCacheStore, storage: Storage | null): void {
  if (!storage) return;
  try {
    storage.setItem(READER_DICTIONARY_CACHE_STORAGE_KEY, JSON.stringify(cache));
  } catch {
    // Dictionary lookup should continue working when storage quota/private mode blocks persistence.
  }
}

function writePackCache(cache: ReaderDictionaryPackCacheStore, storage: Storage | null): void {
  if (!storage) return;
  try {
    storage.setItem(READER_DICTIONARY_PACK_CACHE_STORAGE_KEY, JSON.stringify(cache));
  } catch {
    // Dictionary lookup should keep working when storage quota/private mode blocks persistence.
  }
}

export function loadCachedReaderDictionaryResult(
  bookId: number,
  query: string,
  storage: Storage | null = getBrowserStorage(),
): ReaderDictionaryResponse | null {
  if (!Number.isInteger(bookId) || bookId <= 0) return null;
  const normalizedQuery = normalizeDictionaryQuery(query);
  if (!normalizedQuery) return null;
  const entry = readCache(storage)[readerDictionaryCacheKey(bookId, normalizedQuery)];
  if (!entry) return null;
  return {
    ...entry.result,
    cache: {
      hit: true,
      scope: 'browser',
      stored: false,
      updated_at: entry.cachedAt,
    },
  };
}

export function loadCachedReaderDictionaryPack(
  bookId: number,
  chapterId: number | null = null,
  storage: Storage | null = getBrowserStorage(),
): ReaderDictionaryPack | null {
  if (!Number.isInteger(bookId) || bookId <= 0) return null;
  const cache = readPackCache(storage);
  const entry = cache[readerDictionaryPackCacheKey(bookId, chapterId)]
    ?? (chapterId == null ? null : cache[readerDictionaryPackCacheKey(bookId, null)]);
  if (!entry) return null;
  return {
    ...entry.pack,
    cache: {
      hit: true,
      scope: 'browser-pack',
      stored: false,
      updated_at: entry.cachedAt,
    },
  };
}

export function saveCachedReaderDictionaryResult(
  result: ReaderDictionaryResponse,
  storage: Storage | null = getBrowserStorage(),
  cachedAt = new Date().toISOString(),
): void {
  if (!validResponse(result) || !result.query.trim()) return;
  const cache = readCache(storage);
  cache[readerDictionaryCacheKey(result.book_id, result.query)] = {
    cachedAt,
    result,
  };

  const entries = Object.entries(cache)
    .sort((left, right) => right[1].cachedAt.localeCompare(left[1].cachedAt))
    .slice(0, MAX_READER_DICTIONARY_CACHE_ENTRIES);
  writeCache(Object.fromEntries(entries), storage);
}

export function saveCachedReaderDictionaryPack(
  pack: ReaderDictionaryPack,
  storage: Storage | null = getBrowserStorage(),
  cachedAt = new Date().toISOString(),
): void {
  if (!validPack(pack)) return;
  const cache = readPackCache(storage);
  cache[readerDictionaryPackCacheKey(pack.book_id, pack.chapter_id)] = {
    cachedAt,
    pack,
  };

  const entries = Object.entries(cache)
    .sort((left, right) => right[1].cachedAt.localeCompare(left[1].cachedAt))
    .slice(0, MAX_READER_DICTIONARY_PACK_CACHE_ENTRIES);
  writePackCache(Object.fromEntries(entries), storage);
}

function sourceTextValues(source: ReaderDictionarySource): string[] {
  return [
    source.term,
    source.target,
    source.definition,
    source.category,
    source.provider,
    source.part_of_speech,
    ...(source.aliases ?? []),
    ...(source.variants ?? []),
  ].filter((value): value is string => typeof value === 'string' && value.trim().length > 0);
}

function sourceMatchesQuery(source: ReaderDictionarySource, normalizedQuery: string): boolean {
  return dictionaryMatchScore(normalizedQuery, sourceTextValues(source)) !== null;
}

function dictionaryMatchScore(query: string, values: string[]): [number, number, number] | null {
  const queryForms = dictionaryMatchForms(query);
  if (queryForms.size === 0) return null;
  let bestScore: [number, number, number] | null = null;
  for (const value of values) {
    const valueForms = dictionaryMatchForms(value);
    for (const queryForm of queryForms) {
      for (const valueForm of valueForms) {
        let score: [number, number, number] | null = null;
        if (valueForm === queryForm) {
          score = [0, 0, -valueForm.length];
        } else if (queryForm.includes(valueForm)) {
          score = [1, queryForm.indexOf(valueForm), -valueForm.length];
        } else if (valueForm.includes(queryForm)) {
          score = [2, valueForm.indexOf(queryForm), -queryForm.length];
        }
        if (score && (!bestScore || compareDictionaryScores(score, bestScore) < 0)) {
          bestScore = score;
        }
      }
    }
  }
  return bestScore;
}

function compareDictionaryScores(left: [number, number, number], right: [number, number, number]): number {
  for (let index = 0; index < left.length; index += 1) {
    if (left[index] !== right[index]) return left[index] - right[index];
  }
  return 0;
}

function rankDictionarySources(query: string, sources: ReaderDictionarySource[]): ReaderDictionarySource[] {
  return sources
    .map((source, index) => ({
      index,
      priority: DICTIONARY_SOURCE_PRIORITY[source.source] ?? 99,
      score: dictionaryMatchScore(query, sourceTextValues(source)) ?? [9, 1_000_000, 0] as [number, number, number],
      source,
    }))
    .sort((left, right) => (
      compareDictionaryScores(left.score, right.score)
      || left.priority - right.priority
      || left.index - right.index
    ))
    .map((item) => item.source);
}

export function lookupCachedReaderDictionaryPack(
  bookId: number,
  query: string,
  chapterId: number | null = null,
  storage: Storage | null = getBrowserStorage(),
): ReaderDictionaryResponse | null {
  const normalizedQuery = normalizeDictionaryQuery(query);
  if (!normalizedQuery) return null;

  const pack = loadCachedReaderDictionaryPack(bookId, chapterId, storage);
  if (!pack) return null;

  const sources = rankDictionarySources(
    normalizedQuery,
    pack.sources.filter((source) => sourceMatchesQuery(source, normalizedQuery)),
  );
  return {
    book_id: pack.book_id,
    chapter_id: pack.chapter_id,
    query: query.replace(/\s+/g, ' ').trim(),
    sources,
    offline_count: sources.length,
    online: {
      status: 'skipped',
      error: '',
      count: 0,
    },
    cache: {
      hit: true,
      scope: 'browser-pack',
      stored: false,
      updated_at: pack.cache?.updated_at,
    },
  };
}
