export const READER_CACHE_STORAGE_KEY = 'novel-reader-cache-v1';
const READER_ASSET_CACHE_STORAGE_KEY = 'novel-reader-asset-cache-v1';
const READER_AUDIO_CACHE_STORAGE_KEY = 'novel-reader-audio-cache-v1';
export const READER_CACHE_UPDATED_EVENT = 'novel-reader-cache-updated';

const READER_CACHE_DB_NAME = 'novel-reader-cache';
const READER_CACHE_DB_VERSION = 3;
const READER_CACHE_STORE_NAME = 'chapters';
const READER_CACHE_ASSET_STORE_NAME = 'assets';
const READER_CACHE_AUDIO_STORE_NAME = 'audio';
const MAX_READER_CACHE_ENTRIES = 80;

export type ReaderCachedChapter = {
  bookId: number;
  cachedAt: string;
  chapterId: number;
  html: string;
  sourceText: string;
  text: string;
};

export type ReaderCacheStore = Record<string, ReaderCachedChapter>;

type ReaderCachedChapterRecord = ReaderCachedChapter & {
  key: string;
};

type ReaderCachedAssetRecord = {
  blob: Blob;
  bookChapterKey: string;
  bookId: number;
  cachedAt: string;
  chapterId: number;
  contentType: string;
  key: string;
  sizeBytes: number;
  url: string;
};

type ReaderCachedAssetFallbackRecord = Omit<ReaderCachedAssetRecord, 'blob'> & {
  dataUrl: string;
};

type ReaderCachedAudioRecord = {
  blob: Blob;
  bookChapterKey: string;
  bookId: number;
  cachedAt: string;
  chapterId: number;
  contentType: string;
  key: string;
  sizeBytes: number;
  url: string;
};

type ReaderCachedAudioFallbackRecord = Omit<ReaderCachedAudioRecord, 'blob'> & {
  dataUrl: string;
};

export type ReaderAssetCacheSummary = {
  cached: number;
  failed: number;
  sizeBytes: number;
  total: number;
  urls: string[];
};

export type ReaderAudioCacheSummary = {
  cached: boolean;
  failed: boolean;
  sizeBytes: number;
  url: string;
};

export type ReaderCacheStatus = {
  audioCount: number;
  audioSizeBytes: number;
  audioSizeLabel: string;
  assetCount: number;
  assetSizeBytes: number;
  assetSizeLabel: string;
  currentCached: boolean;
  nextCached: boolean | null;
  sizeBytes: number;
  sizeLabel: string;
};

export function readerCacheKey(bookId: number, chapterId: number): string {
  return `${bookId}:${chapterId}`;
}

export function readerAssetCacheKey(bookId: number, chapterId: number, url: string): string {
  return `${bookId}:${chapterId}:${normalizeReaderAssetUrl(url)}`;
}

export function readerAudioCacheKey(bookId: number, chapterId: number, url: string): string {
  return `${bookId}:${chapterId}:${normalizeReaderAssetUrl(url)}`;
}

function readerBookChapterAssetKey(bookId: number, chapterId: number): string {
  return `${bookId}:${chapterId}`;
}

function getBrowserStorage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function getBrowserIndexedDb(): IDBFactory | null {
  try {
    return window.indexedDB ?? null;
  } catch {
    return null;
  }
}

function emitReaderCacheUpdated(): void {
  if (typeof window === 'undefined') return;
  try {
    window.dispatchEvent(new Event(READER_CACHE_UPDATED_EVENT));
  } catch {
    // Cache updates should never interrupt reading.
  }
}

const browserFetch: typeof fetch = (input, init) => fetch(input, init);

const cachedAssetObjectUrls = new Map<string, string>();
const cachedAudioObjectUrls = new Map<string, string>();

function isCachedChapter(value: unknown): value is ReaderCachedChapter {
  if (!value || typeof value !== 'object') return false;
  const chapter = value as Partial<ReaderCachedChapter>;
  return (
    Number.isInteger(chapter.bookId)
    && Number.isInteger(chapter.chapterId)
    && typeof chapter.cachedAt === 'string'
    && typeof chapter.html === 'string'
    && typeof chapter.text === 'string'
  );
}

function cachedChapterRecord(chapter: ReaderCachedChapter): ReaderCachedChapterRecord {
  return {
    ...chapter,
    key: readerCacheKey(chapter.bookId, chapter.chapterId),
  };
}

function cachedChapterFromRecord(record: unknown): ReaderCachedChapter | null {
  if (!isCachedChapter(record)) return null;
  return {
    bookId: record.bookId,
    cachedAt: record.cachedAt,
    chapterId: record.chapterId,
    html: record.html,
    sourceText: typeof record.sourceText === 'string' ? record.sourceText : '',
    text: record.text,
  };
}

function isCachedAssetRecord(value: unknown): value is ReaderCachedAssetRecord {
  if (!value || typeof value !== 'object') return false;
  const asset = value as Partial<ReaderCachedAssetRecord>;
  return (
    Number.isInteger(asset.bookId)
    && Number.isInteger(asset.chapterId)
    && typeof asset.bookChapterKey === 'string'
    && typeof asset.cachedAt === 'string'
    && typeof asset.contentType === 'string'
    && typeof asset.key === 'string'
    && typeof asset.sizeBytes === 'number'
    && typeof asset.url === 'string'
    && asset.blob instanceof Blob
  );
}

function isCachedAssetFallbackRecord(value: unknown): value is ReaderCachedAssetFallbackRecord {
  if (!value || typeof value !== 'object') return false;
  const asset = value as Partial<ReaderCachedAssetFallbackRecord>;
  return (
    Number.isInteger(asset.bookId)
    && Number.isInteger(asset.chapterId)
    && typeof asset.bookChapterKey === 'string'
    && typeof asset.cachedAt === 'string'
    && typeof asset.contentType === 'string'
    && typeof asset.dataUrl === 'string'
    && typeof asset.key === 'string'
    && typeof asset.sizeBytes === 'number'
    && typeof asset.url === 'string'
  );
}

function isCachedAudioRecord(value: unknown): value is ReaderCachedAudioRecord {
  if (!value || typeof value !== 'object') return false;
  const audio = value as Partial<ReaderCachedAudioRecord>;
  return (
    Number.isInteger(audio.bookId)
    && Number.isInteger(audio.chapterId)
    && typeof audio.bookChapterKey === 'string'
    && typeof audio.cachedAt === 'string'
    && typeof audio.contentType === 'string'
    && typeof audio.key === 'string'
    && typeof audio.sizeBytes === 'number'
    && typeof audio.url === 'string'
    && audio.blob instanceof Blob
  );
}

function isCachedAudioFallbackRecord(value: unknown): value is ReaderCachedAudioFallbackRecord {
  if (!value || typeof value !== 'object') return false;
  const audio = value as Partial<ReaderCachedAudioFallbackRecord>;
  return (
    Number.isInteger(audio.bookId)
    && Number.isInteger(audio.chapterId)
    && typeof audio.bookChapterKey === 'string'
    && typeof audio.cachedAt === 'string'
    && typeof audio.contentType === 'string'
    && typeof audio.dataUrl === 'string'
    && typeof audio.key === 'string'
    && typeof audio.sizeBytes === 'number'
    && typeof audio.url === 'string'
  );
}

function normalizeReaderAssetUrl(value: string, baseUrl?: string): string {
  const trimmed = value.trim();
  if (!trimmed) return '';
  try {
    if (typeof window !== 'undefined' && window.location?.origin) {
      const base = baseUrl ? new URL(baseUrl, window.location.origin).href : window.location.origin;
      const parsed = new URL(trimmed, base);
      if (parsed.origin === window.location.origin) {
        return `${parsed.pathname}${parsed.search}${parsed.hash}`;
      }
      return parsed.href;
    }
  } catch {
    return trimmed;
  }
  return trimmed;
}

function readerAssetReference(value: string, baseUrl?: string): { assetUrl: string; fragment: string } {
  const trimmed = value.trim();
  if (!trimmed || trimmed.startsWith('#')) return { assetUrl: '', fragment: '' };
  const normalized = normalizeReaderAssetUrl(trimmed, baseUrl);
  if (!normalized || normalized.startsWith('#')) return { assetUrl: '', fragment: '' };
  const hashIndex = normalized.indexOf('#');
  if (hashIndex < 0) return { assetUrl: normalized, fragment: '' };
  if (hashIndex === 0) return { assetUrl: '', fragment: '' };
  return {
    assetUrl: normalized.slice(0, hashIndex),
    fragment: normalized.slice(hashIndex),
  };
}

function isCacheableReaderAssetUrl(value: string, baseUrl?: string): boolean {
  const normalized = readerAssetReference(value, baseUrl).assetUrl;
  if (!normalized) return false;
  if (/^(blob|data|javascript|mailto):/i.test(normalized)) return false;
  if (normalized.startsWith('/')) return true;
  try {
    const parsed = new URL(normalized);
    return parsed.protocol === 'http:' || parsed.protocol === 'https:';
  } catch {
    return !normalized.includes(':');
  }
}

function appendReaderAssetUrl(urls: string[], value: string, baseUrl?: string): void {
  if (isCacheableReaderAssetUrl(value, baseUrl)) {
    urls.push(readerAssetReference(value, baseUrl).assetUrl);
  }
}

function appendReaderSrcsetAssetUrls(urls: string[], value: string, baseUrl?: string): void {
  const srcset = value.trim();
  let index = 0;

  while (index < srcset.length) {
    while (index < srcset.length && /[\s,]/.test(srcset[index] ?? '')) {
      index += 1;
    }

    const start = index;
    const isDataUrl = srcset.slice(index, index + 5).toLowerCase() === 'data:';
    while (index < srcset.length) {
      const char = srcset[index] ?? '';
      if (/\s/.test(char)) break;
      if (char === ',' && !isDataUrl) break;
      index += 1;
    }

    appendReaderAssetUrl(urls, srcset.slice(start, index), baseUrl);

    while (index < srcset.length && srcset[index] !== ',') {
      index += 1;
    }
    if (srcset[index] === ',') {
      index += 1;
    }
  }
}

function readReaderCssUrlMatch(match: RegExpExecArray): string {
  return match[1] ?? match[2] ?? match[3]?.trim() ?? match[4] ?? match[5] ?? '';
}

function appendReaderCssAssetUrls(urls: string[], value: string, baseUrl?: string): void {
  const cssAssetPattern = /url\(\s*(?:"([^"]*)"|'([^']*)'|([^'")]*?))\s*\)|@import\s+(?:"([^"]+)"|'([^']+)')/gi;
  let match = cssAssetPattern.exec(value);
  while (match) {
    appendReaderAssetUrl(
      urls,
      readReaderCssUrlMatch(match) || match[4] || match[5] || '',
      baseUrl,
    );
    match = cssAssetPattern.exec(value);
  }
}

function linkReferencesReaderAsset(relValue: string, asValue: string): boolean {
  const relTokens = relValue.toLowerCase().split(/\s+/).filter(Boolean);
  const normalizedAsValue = asValue.toLowerCase();
  if (relTokens.includes('stylesheet') || normalizedAsValue === 'style') return true;
  if (!relTokens.some((token) => token === 'preload' || token === 'prefetch')) return false;
  return ['audio', 'font', 'image', 'track', 'video'].includes(normalizedAsValue);
}

function svgHrefReferencesReaderAsset(tagName: string): boolean {
  return tagName === 'image' || tagName === 'use' || tagName === 'feimage';
}

export async function hydrateReaderCssAssetUrls(
  value: string,
  resolveCachedUrl: (url: string) => Promise<string | null | undefined>,
  baseUrl?: string,
): Promise<{ changed: boolean; value: string }> {
  const cssUrlPattern = /url\(\s*(?:"([^"]*)"|'([^']*)'|([^'")]*?))\s*\)|@import\s+(?:"([^"]+)"|'([^']+)')/gi;
  let changed = false;
  let cursor = 0;
  let hydrated = '';
  let match = cssUrlPattern.exec(value);

  while (match) {
    const originalUrl = readReaderCssUrlMatch(match);
    if (isCacheableReaderAssetUrl(originalUrl, baseUrl)) {
      const reference = readerAssetReference(originalUrl, baseUrl);
      const cachedUrl = await resolveCachedUrl(reference.assetUrl);
      if (cachedUrl) {
        hydrated += `${value.slice(cursor, match.index)}${match[0].replace(originalUrl, `${cachedUrl}${reference.fragment}`)}`;
        cursor = match.index + match[0].length;
        changed = true;
      }
    }
    match = cssUrlPattern.exec(value);
  }

  return {
    changed,
    value: changed ? `${hydrated}${value.slice(cursor)}` : value,
  };
}

export async function hydrateReaderSrcsetAssetUrls(
  value: string,
  resolveCachedUrl: (url: string) => Promise<string | null | undefined>,
  baseUrl?: string,
): Promise<{ changed: boolean; value: string }> {
  let changed = false;
  let cursor = 0;
  let hydrated = '';
  let index = 0;

  while (index < value.length) {
    while (index < value.length && /[\s,]/.test(value[index] ?? '')) {
      index += 1;
    }

    const start = index;
    const isDataUrl = value.slice(index, index + 5).toLowerCase() === 'data:';
    while (index < value.length) {
      const char = value[index] ?? '';
      if (/\s/.test(char)) break;
      if (char === ',' && !isDataUrl) break;
      index += 1;
    }

    const originalUrl = value.slice(start, index);
    if (isCacheableReaderAssetUrl(originalUrl, baseUrl)) {
      const reference = readerAssetReference(originalUrl, baseUrl);
      const cachedUrl = await resolveCachedUrl(reference.assetUrl);
      if (cachedUrl) {
        hydrated += `${value.slice(cursor, start)}${cachedUrl}${reference.fragment}`;
        cursor = index;
        changed = true;
      }
    }

    while (index < value.length && value[index] !== ',') {
      index += 1;
    }
    if (value[index] === ',') {
      index += 1;
    }
  }

  return {
    changed,
    value: changed ? `${hydrated}${value.slice(cursor)}` : value,
  };
}

function appendReaderElementAssetUrls(urls: string[], element: Element, baseUrl?: string): void {
  const tagName = element.tagName.toLowerCase();
  if (tagName === 'link') {
    if (linkReferencesReaderAsset(element.getAttribute('rel') ?? '', element.getAttribute('as') ?? '')) {
      appendReaderAssetUrl(urls, element.getAttribute('href') ?? '', baseUrl);
    }
  }
  if (tagName === 'img') {
    appendReaderAssetUrl(urls, element.getAttribute('src') ?? '', baseUrl);
    appendReaderAssetUrl(urls, element.getAttribute('data-src') ?? '', baseUrl);
    appendReaderAssetUrl(urls, element.getAttribute('data-original') ?? '', baseUrl);
    appendReaderAssetUrl(urls, element.getAttribute('data-lazy-src') ?? '', baseUrl);
  }
  if (tagName === 'audio' || tagName === 'source' || tagName === 'video') {
    appendReaderAssetUrl(urls, element.getAttribute('src') ?? '', baseUrl);
  }
  if (tagName === 'embed' || tagName === 'track') {
    appendReaderAssetUrl(urls, element.getAttribute('src') ?? '', baseUrl);
  }
  if (tagName === 'object') {
    appendReaderAssetUrl(urls, element.getAttribute('data') ?? '', baseUrl);
  }
  if (svgHrefReferencesReaderAsset(tagName)) {
    appendReaderAssetUrl(urls, element.getAttribute('href') ?? '', baseUrl);
    appendReaderAssetUrl(urls, element.getAttribute('xlink:href') ?? '', baseUrl);
  }
  if (tagName === 'img' || tagName === 'source') {
    appendReaderSrcsetAssetUrls(urls, element.getAttribute('srcset') ?? '', baseUrl);
    appendReaderSrcsetAssetUrls(urls, element.getAttribute('data-srcset') ?? '', baseUrl);
  }
  if (tagName === 'video') {
    appendReaderAssetUrl(urls, element.getAttribute('poster') ?? '', baseUrl);
  }
  appendReaderCssAssetUrls(urls, element.getAttribute('style') ?? '', baseUrl);
  if (tagName === 'style') {
    appendReaderCssAssetUrls(urls, element.textContent ?? '', baseUrl);
  }
}

function readReaderHtmlAttribute(tagHtml: string, name: string): string {
  const escapedName = name.replace(':', '\\:');
  const pattern = new RegExp(`\\b${escapedName}\\s*=\\s*(?:"([^"]*)"|'([^']*)'|([^\\s"'>]+))`, 'i');
  const match = pattern.exec(tagHtml);
  return match?.[1] ?? match?.[2] ?? match?.[3] ?? '';
}

function appendReaderHtmlTagAssetUrls(urls: string[], tagHtml: string, baseUrl?: string): void {
  const tagName = /^<\s*([a-z0-9:-]+)/i.exec(tagHtml)?.[1]?.toLowerCase() ?? '';
  if (tagName === 'link') {
    if (linkReferencesReaderAsset(readReaderHtmlAttribute(tagHtml, 'rel'), readReaderHtmlAttribute(tagHtml, 'as'))) {
      appendReaderAssetUrl(urls, readReaderHtmlAttribute(tagHtml, 'href'), baseUrl);
    }
  }
  if (tagName === 'img') {
    appendReaderAssetUrl(urls, readReaderHtmlAttribute(tagHtml, 'src'), baseUrl);
    appendReaderAssetUrl(urls, readReaderHtmlAttribute(tagHtml, 'data-src'), baseUrl);
    appendReaderAssetUrl(urls, readReaderHtmlAttribute(tagHtml, 'data-original'), baseUrl);
    appendReaderAssetUrl(urls, readReaderHtmlAttribute(tagHtml, 'data-lazy-src'), baseUrl);
  }
  if (tagName === 'audio' || tagName === 'source' || tagName === 'video') {
    appendReaderAssetUrl(urls, readReaderHtmlAttribute(tagHtml, 'src'), baseUrl);
  }
  if (tagName === 'embed' || tagName === 'track') {
    appendReaderAssetUrl(urls, readReaderHtmlAttribute(tagHtml, 'src'), baseUrl);
  }
  if (tagName === 'object') {
    appendReaderAssetUrl(urls, readReaderHtmlAttribute(tagHtml, 'data'), baseUrl);
  }
  if (svgHrefReferencesReaderAsset(tagName)) {
    appendReaderAssetUrl(urls, readReaderHtmlAttribute(tagHtml, 'href'), baseUrl);
    appendReaderAssetUrl(urls, readReaderHtmlAttribute(tagHtml, 'xlink:href'), baseUrl);
  }
  if (tagName === 'img' || tagName === 'source') {
    appendReaderSrcsetAssetUrls(urls, readReaderHtmlAttribute(tagHtml, 'srcset'), baseUrl);
    appendReaderSrcsetAssetUrls(urls, readReaderHtmlAttribute(tagHtml, 'data-srcset'), baseUrl);
  }
  if (tagName === 'video') {
    appendReaderAssetUrl(urls, readReaderHtmlAttribute(tagHtml, 'poster'), baseUrl);
  }
  appendReaderCssAssetUrls(urls, readReaderHtmlAttribute(tagHtml, 'style'), baseUrl);
}

function objectUrlForCachedAsset(asset: ReaderCachedAssetRecord): string {
  const cached = cachedAssetObjectUrls.get(asset.key);
  if (cached) return cached;
  const objectUrl = URL.createObjectURL(asset.blob);
  cachedAssetObjectUrls.set(asset.key, objectUrl);
  return objectUrl;
}

function objectUrlForCachedAudio(audio: ReaderCachedAudioRecord): string {
  const cached = cachedAudioObjectUrls.get(audio.key);
  if (cached) return cached;
  const objectUrl = URL.createObjectURL(audio.blob);
  cachedAudioObjectUrls.set(audio.key, objectUrl);
  return objectUrl;
}

function newestCachedAudioRecord(records: ReaderCachedAudioRecord[]): ReaderCachedAudioRecord | null {
  if (records.length === 0) return null;
  return [...records].sort((left, right) => right.cachedAt.localeCompare(left.cachedAt))[0] ?? null;
}

function readAudioFallbackStore(storage: Storage | null = getBrowserStorage()): Record<string, ReaderCachedAudioFallbackRecord> {
  if (!storage) return {};
  try {
    const parsed = JSON.parse(storage.getItem(READER_AUDIO_CACHE_STORAGE_KEY) ?? '{}') as unknown;
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    return Object.fromEntries(
      Object.entries(parsed)
        .map(([key, value]) => [key, isCachedAudioFallbackRecord(value) ? value : null] as const)
        .filter((entry): entry is [string, ReaderCachedAudioFallbackRecord] => entry[1] !== null),
    );
  } catch {
    return {};
  }
}

function writeAudioFallbackStore(
  store: Record<string, ReaderCachedAudioFallbackRecord>,
  storage: Storage | null = getBrowserStorage(),
): void {
  if (!storage) return;
  try {
    storage.setItem(READER_AUDIO_CACHE_STORAGE_KEY, JSON.stringify(store));
    emitReaderCacheUpdated();
  } catch {
    // Browser storage may be full; live audio streaming remains available.
  }
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = '';
  const chunkSize = 0x8000;
  for (let index = 0; index < bytes.length; index += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunkSize));
  }
  return btoa(binary);
}

function base64ToBytes(value: string): Uint8Array {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

function readAssetFallbackStore(storage: Storage | null = getBrowserStorage()): Record<string, ReaderCachedAssetFallbackRecord> {
  if (!storage) return {};
  try {
    const parsed = JSON.parse(storage.getItem(READER_ASSET_CACHE_STORAGE_KEY) ?? '{}') as unknown;
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    return Object.fromEntries(
      Object.entries(parsed)
        .map(([key, value]) => [key, isCachedAssetFallbackRecord(value) ? value : null] as const)
        .filter((entry): entry is [string, ReaderCachedAssetFallbackRecord] => entry[1] !== null),
    );
  } catch {
    return {};
  }
}

function writeAssetFallbackStore(
  store: Record<string, ReaderCachedAssetFallbackRecord>,
  storage: Storage | null = getBrowserStorage(),
): void {
  if (!storage) return;
  try {
    storage.setItem(READER_ASSET_CACHE_STORAGE_KEY, JSON.stringify(store));
    emitReaderCacheUpdated();
  } catch {
    // Browser storage may be full; live asset URLs remain available.
  }
}

async function assetFallbackRecordFromBlob(
  asset: Omit<ReaderCachedAssetRecord, 'bookChapterKey' | 'key'>,
): Promise<ReaderCachedAssetFallbackRecord> {
  const { blob, ...metadata } = asset;
  const key = readerAssetCacheKey(asset.bookId, asset.chapterId, asset.url);
  const bytes = new Uint8Array(await blob.arrayBuffer());
  return {
    ...metadata,
    bookChapterKey: readerBookChapterAssetKey(asset.bookId, asset.chapterId),
    dataUrl: `data:${asset.contentType || 'application/octet-stream'};base64,${bytesToBase64(bytes)}`,
    key,
  };
}

function cachedAssetFromFallbackRecord(record: ReaderCachedAssetFallbackRecord): ReaderCachedAssetRecord | null {
  const match = /^data:([^;,]+)?;base64,(.*)$/s.exec(record.dataUrl);
  if (!match) return null;
  try {
    const contentType = match[1] || record.contentType || 'application/octet-stream';
    const bytes = base64ToBytes(match[2]);
    const buffer = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;
    return {
      blob: new Blob([buffer], { type: contentType }),
      bookChapterKey: record.bookChapterKey,
      bookId: record.bookId,
      cachedAt: record.cachedAt,
      chapterId: record.chapterId,
      contentType,
      key: record.key,
      sizeBytes: record.sizeBytes,
      url: record.url,
    };
  } catch {
    return null;
  }
}

function getCachedAssetFallbackRecord(
  bookId: number,
  chapterId: number,
  url: string,
  storage: Storage | null = getBrowserStorage(),
): ReaderCachedAssetRecord | null {
  const record = readAssetFallbackStore(storage)[readerAssetCacheKey(bookId, chapterId, url)];
  return record ? cachedAssetFromFallbackRecord(record) : null;
}

async function putCachedAssetFallbackRecordAsync(
  asset: Omit<ReaderCachedAssetRecord, 'bookChapterKey' | 'key'>,
  storage: Storage | null = getBrowserStorage(),
): Promise<boolean> {
  if (!storage) return false;
  try {
    const record = await assetFallbackRecordFromBlob(asset);
    writeAssetFallbackStore({
      ...readAssetFallbackStore(storage),
      [record.key]: record,
    }, storage);
    return true;
  } catch {
    return false;
  }
}

function deleteAssetFallbackForChapter(bookId: number, chapterId: number): void {
  const store = readAssetFallbackStore();
  const nextEntries = Object.entries(store).filter(([, record]) => (
    record.bookId !== bookId || record.chapterId !== chapterId
  ));
  if (nextEntries.length === Object.keys(store).length) return;
  for (const [key, record] of Object.entries(store)) {
    if (record.bookId !== bookId || record.chapterId !== chapterId) continue;
    const objectUrl = cachedAssetObjectUrls.get(key);
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    cachedAssetObjectUrls.delete(key);
  }
  writeAssetFallbackStore(Object.fromEntries(nextEntries));
}

function deleteAssetFallbackForBook(bookId: number): void {
  const store = readAssetFallbackStore();
  const nextEntries = Object.entries(store).filter(([, record]) => record.bookId !== bookId);
  if (nextEntries.length === Object.keys(store).length) return;
  for (const [key, record] of Object.entries(store)) {
    if (record.bookId !== bookId) continue;
    const objectUrl = cachedAssetObjectUrls.get(key);
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    cachedAssetObjectUrls.delete(key);
  }
  writeAssetFallbackStore(Object.fromEntries(nextEntries));
}

function readerAssetFallbackSummary(): { count: number; keys: Set<string>; sizeBytes: number } {
  const records = Object.values(readAssetFallbackStore());
  return {
    count: records.length,
    keys: new Set(records.map((record) => record.key)),
    sizeBytes: records.reduce((total, asset) => total + asset.sizeBytes, 0),
  };
}

async function audioFallbackRecordFromBlob(
  audio: Omit<ReaderCachedAudioRecord, 'bookChapterKey' | 'key'>,
): Promise<ReaderCachedAudioFallbackRecord> {
  const { blob, ...metadata } = audio;
  const key = readerAudioCacheKey(audio.bookId, audio.chapterId, audio.url);
  const bytes = new Uint8Array(await blob.arrayBuffer());
  return {
    ...metadata,
    bookChapterKey: readerBookChapterAssetKey(audio.bookId, audio.chapterId),
    dataUrl: `data:${audio.contentType || 'audio/mpeg'};base64,${bytesToBase64(bytes)}`,
    key,
  };
}

function cachedAudioFromFallbackRecord(record: ReaderCachedAudioFallbackRecord): ReaderCachedAudioRecord | null {
  const match = /^data:([^;,]+)?;base64,(.*)$/s.exec(record.dataUrl);
  if (!match) return null;
  try {
    const contentType = match[1] || record.contentType || 'audio/mpeg';
    const bytes = base64ToBytes(match[2]);
    const buffer = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;
    return {
      blob: new Blob([buffer], { type: contentType }),
      bookChapterKey: record.bookChapterKey,
      bookId: record.bookId,
      cachedAt: record.cachedAt,
      chapterId: record.chapterId,
      contentType,
      key: record.key,
      sizeBytes: record.sizeBytes,
      url: record.url,
    };
  } catch {
    return null;
  }
}

function getCachedAudioFallbackRecord(
  bookId: number,
  chapterId: number,
  url: string,
  storage: Storage | null = getBrowserStorage(),
): ReaderCachedAudioRecord | null {
  const record = readAudioFallbackStore(storage)[readerAudioCacheKey(bookId, chapterId, url)];
  return record ? cachedAudioFromFallbackRecord(record) : null;
}

function getCachedAudioFallbackRecordForChapter(
  bookId: number,
  chapterId: number,
  storage: Storage | null = getBrowserStorage(),
): ReaderCachedAudioRecord | null {
  return newestCachedAudioRecord(
    Object.values(readAudioFallbackStore(storage))
      .filter((record) => record.bookId === bookId && record.chapterId === chapterId)
      .map(cachedAudioFromFallbackRecord)
      .filter((record): record is ReaderCachedAudioRecord => record !== null),
  );
}

async function putCachedAudioFallbackRecordAsync(
  audio: Omit<ReaderCachedAudioRecord, 'bookChapterKey' | 'key'>,
  storage: Storage | null = getBrowserStorage(),
): Promise<boolean> {
  if (!storage) return false;
  try {
    const record = await audioFallbackRecordFromBlob(audio);
    writeAudioFallbackStore({
      ...readAudioFallbackStore(storage),
      [record.key]: record,
    }, storage);
    return true;
  } catch {
    return false;
  }
}

function deleteAudioFallbackForChapter(bookId: number, chapterId: number): void {
  const store = readAudioFallbackStore();
  const nextEntries = Object.entries(store).filter(([, record]) => (
    record.bookId !== bookId || record.chapterId !== chapterId
  ));
  if (nextEntries.length === Object.keys(store).length) return;
  for (const [key, record] of Object.entries(store)) {
    if (record.bookId !== bookId || record.chapterId !== chapterId) continue;
    const objectUrl = cachedAudioObjectUrls.get(key);
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    cachedAudioObjectUrls.delete(key);
  }
  writeAudioFallbackStore(Object.fromEntries(nextEntries));
}

function deleteAudioFallbackForBook(bookId: number): void {
  const store = readAudioFallbackStore();
  const nextEntries = Object.entries(store).filter(([, record]) => record.bookId !== bookId);
  if (nextEntries.length === Object.keys(store).length) return;
  for (const [key, record] of Object.entries(store)) {
    if (record.bookId !== bookId) continue;
    const objectUrl = cachedAudioObjectUrls.get(key);
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    cachedAudioObjectUrls.delete(key);
  }
  writeAudioFallbackStore(Object.fromEntries(nextEntries));
}

function readerAudioFallbackSummary(): { count: number; keys: Set<string>; sizeBytes: number } {
  const records = Object.values(readAudioFallbackStore());
  return {
    count: records.length,
    keys: new Set(records.map((record) => record.key)),
    sizeBytes: records.reduce((total, audio) => total + audio.sizeBytes, 0),
  };
}

function normalizeCacheStore(value: unknown): ReaderCacheStore {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};

  const store: ReaderCacheStore = {};
  for (const [key, chapter] of Object.entries(value)) {
    if (!isCachedChapter(chapter)) continue;
    store[key] = {
      ...chapter,
      sourceText: typeof chapter.sourceText === 'string' ? chapter.sourceText : '',
    };
  }
  return store;
}

function pruneCacheStore(store: ReaderCacheStore): ReaderCacheStore {
  const entries = Object.entries(store);
  if (entries.length <= MAX_READER_CACHE_ENTRIES) return store;

  return Object.fromEntries(
    entries
      .sort((left, right) => Date.parse(right[1].cachedAt) - Date.parse(left[1].cachedAt))
      .slice(0, MAX_READER_CACHE_ENTRIES),
  );
}

export function loadReaderCache(storage: Storage | null = getBrowserStorage()): ReaderCacheStore {
  if (!storage) return {};
  try {
    return normalizeCacheStore(JSON.parse(storage.getItem(READER_CACHE_STORAGE_KEY) ?? '{}'));
  } catch {
    return {};
  }
}

function openReaderCacheDb(): Promise<IDBDatabase | null> {
  const indexedDb = getBrowserIndexedDb();
  if (!indexedDb) return Promise.resolve(null);

  return new Promise((resolve) => {
    const request = indexedDb.open(READER_CACHE_DB_NAME, READER_CACHE_DB_VERSION);
    request.onerror = () => resolve(null);
    request.onblocked = () => resolve(null);
    request.onupgradeneeded = () => {
      const db = request.result;
      const store = db.objectStoreNames.contains(READER_CACHE_STORE_NAME)
        ? request.transaction?.objectStore(READER_CACHE_STORE_NAME)
        : db.createObjectStore(READER_CACHE_STORE_NAME, { keyPath: 'key' });
      if (store && !store.indexNames.contains('bookId')) {
        store.createIndex('bookId', 'bookId', { unique: false });
      }
      if (store && !store.indexNames.contains('cachedAt')) {
        store.createIndex('cachedAt', 'cachedAt', { unique: false });
      }
      const assetStore = db.objectStoreNames.contains(READER_CACHE_ASSET_STORE_NAME)
        ? request.transaction?.objectStore(READER_CACHE_ASSET_STORE_NAME)
        : db.createObjectStore(READER_CACHE_ASSET_STORE_NAME, { keyPath: 'key' });
      if (assetStore && !assetStore.indexNames.contains('bookId')) {
        assetStore.createIndex('bookId', 'bookId', { unique: false });
      }
      if (assetStore && !assetStore.indexNames.contains('bookChapterKey')) {
        assetStore.createIndex('bookChapterKey', 'bookChapterKey', { unique: false });
      }
      if (assetStore && !assetStore.indexNames.contains('cachedAt')) {
        assetStore.createIndex('cachedAt', 'cachedAt', { unique: false });
      }
      const audioStore = db.objectStoreNames.contains(READER_CACHE_AUDIO_STORE_NAME)
        ? request.transaction?.objectStore(READER_CACHE_AUDIO_STORE_NAME)
        : db.createObjectStore(READER_CACHE_AUDIO_STORE_NAME, { keyPath: 'key' });
      if (audioStore && !audioStore.indexNames.contains('bookId')) {
        audioStore.createIndex('bookId', 'bookId', { unique: false });
      }
      if (audioStore && !audioStore.indexNames.contains('bookChapterKey')) {
        audioStore.createIndex('bookChapterKey', 'bookChapterKey', { unique: false });
      }
      if (audioStore && !audioStore.indexNames.contains('cachedAt')) {
        audioStore.createIndex('cachedAt', 'cachedAt', { unique: false });
      }
    };
    request.onsuccess = () => resolve(request.result);
  });
}

function idbRequest<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onerror = () => reject(request.error ?? new Error('IndexedDB request failed'));
    request.onsuccess = () => resolve(request.result);
  });
}

function transactionDone(transaction: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    transaction.onabort = () => reject(transaction.error ?? new Error('IndexedDB transaction aborted'));
    transaction.onerror = () => reject(transaction.error ?? new Error('IndexedDB transaction failed'));
    transaction.oncomplete = () => resolve();
  });
}

async function pruneIndexedReaderCache(db: IDBDatabase): Promise<void> {
  const readTx = db.transaction(READER_CACHE_STORE_NAME, 'readonly');
  const records = await idbRequest<ReaderCachedChapterRecord[]>(readTx.objectStore(READER_CACHE_STORE_NAME).getAll());
  const staleRecords = records
    .filter(isCachedChapter)
    .sort((left, right) => Date.parse(right.cachedAt) - Date.parse(left.cachedAt))
    .slice(MAX_READER_CACHE_ENTRIES);
  if (staleRecords.length === 0) return;
  const tx = db.transaction(READER_CACHE_STORE_NAME, 'readwrite');
  const store = tx.objectStore(READER_CACHE_STORE_NAME);
  for (const record of staleRecords) {
    store.delete(readerCacheKey(record.bookId, record.chapterId));
  }
  await transactionDone(tx);
}

async function getCachedAssetRecordAsync(
  bookId: number,
  chapterId: number,
  url: string,
): Promise<ReaderCachedAssetRecord | null> {
  const db = await openReaderCacheDb();
  if (!db) return getCachedAssetFallbackRecord(bookId, chapterId, url);
  try {
    const tx = db.transaction(READER_CACHE_ASSET_STORE_NAME, 'readonly');
    const record = await idbRequest<unknown>(
      tx.objectStore(READER_CACHE_ASSET_STORE_NAME).get(readerAssetCacheKey(bookId, chapterId, url)),
    );
    return isCachedAssetRecord(record) ? record : getCachedAssetFallbackRecord(bookId, chapterId, url);
  } catch {
    return getCachedAssetFallbackRecord(bookId, chapterId, url);
  } finally {
    db.close();
  }
}

async function putCachedAssetRecordAsync(asset: Omit<ReaderCachedAssetRecord, 'bookChapterKey' | 'key'>): Promise<boolean> {
  const db = await openReaderCacheDb();
  if (!db) return putCachedAssetFallbackRecordAsync(asset);
  const record: ReaderCachedAssetRecord = {
    ...asset,
    bookChapterKey: readerBookChapterAssetKey(asset.bookId, asset.chapterId),
    key: readerAssetCacheKey(asset.bookId, asset.chapterId, asset.url),
  };
  try {
    const tx = db.transaction(READER_CACHE_ASSET_STORE_NAME, 'readwrite');
    tx.objectStore(READER_CACHE_ASSET_STORE_NAME).put(record);
    await transactionDone(tx);
    emitReaderCacheUpdated();
    return true;
  } catch {
    // Asset cache is best-effort; chapter text cache remains usable.
    return putCachedAssetFallbackRecordAsync(asset);
  } finally {
    db.close();
  }
}

async function getCachedAudioRecordAsync(
  bookId: number,
  chapterId: number,
  url: string,
): Promise<ReaderCachedAudioRecord | null> {
  const db = await openReaderCacheDb();
  if (!db) return getCachedAudioFallbackRecord(bookId, chapterId, url);
  try {
    const tx = db.transaction(READER_CACHE_AUDIO_STORE_NAME, 'readonly');
    const record = await idbRequest<unknown>(
      tx.objectStore(READER_CACHE_AUDIO_STORE_NAME).get(readerAudioCacheKey(bookId, chapterId, url)),
    );
    return isCachedAudioRecord(record) ? record : getCachedAudioFallbackRecord(bookId, chapterId, url);
  } catch {
    return getCachedAudioFallbackRecord(bookId, chapterId, url);
  } finally {
    db.close();
  }
}

async function getCachedAudioRecordForChapterAsync(
  bookId: number,
  chapterId: number,
): Promise<ReaderCachedAudioRecord | null> {
  const db = await openReaderCacheDb();
  if (!db) return getCachedAudioFallbackRecordForChapter(bookId, chapterId);
  try {
    const tx = db.transaction(READER_CACHE_AUDIO_STORE_NAME, 'readonly');
    const records = await idbRequest<unknown[]>(
      tx.objectStore(READER_CACHE_AUDIO_STORE_NAME)
        .index('bookChapterKey')
        .getAll(readerBookChapterAssetKey(bookId, chapterId)),
    );
    const cached = newestCachedAudioRecord(records.filter(isCachedAudioRecord));
    return cached ?? getCachedAudioFallbackRecordForChapter(bookId, chapterId);
  } catch {
    return getCachedAudioFallbackRecordForChapter(bookId, chapterId);
  } finally {
    db.close();
  }
}

async function putCachedAudioRecordAsync(audio: Omit<ReaderCachedAudioRecord, 'bookChapterKey' | 'key'>): Promise<boolean> {
  const db = await openReaderCacheDb();
  if (!db) return false;
  const record: ReaderCachedAudioRecord = {
    ...audio,
    bookChapterKey: readerBookChapterAssetKey(audio.bookId, audio.chapterId),
    key: readerAudioCacheKey(audio.bookId, audio.chapterId, audio.url),
  };
  try {
    const tx = db.transaction(READER_CACHE_AUDIO_STORE_NAME, 'readwrite');
    tx.objectStore(READER_CACHE_AUDIO_STORE_NAME).put(record);
    await transactionDone(tx);
    emitReaderCacheUpdated();
    return true;
  } catch {
    // Audio cache is best-effort; live streaming remains available.
    return false;
  } finally {
    db.close();
  }
}

async function deleteAssetsForChapterAsync(bookId: number, chapterId: number): Promise<void> {
  const db = await openReaderCacheDb();
  if (!db) {
    deleteAssetFallbackForChapter(bookId, chapterId);
    return;
  }
  try {
    const readTx = db.transaction(READER_CACHE_ASSET_STORE_NAME, 'readonly');
    const index = readTx.objectStore(READER_CACHE_ASSET_STORE_NAME).index('bookChapterKey');
    const records = await idbRequest<ReaderCachedAssetRecord[]>(
      index.getAll(readerBookChapterAssetKey(bookId, chapterId)),
    );
    const keys = records.filter(isCachedAssetRecord).map((record) => {
      const objectUrl = cachedAssetObjectUrls.get(record.key);
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      cachedAssetObjectUrls.delete(record.key);
      return record.key;
    });
    if (keys.length === 0) return;
    const writeTx = db.transaction(READER_CACHE_ASSET_STORE_NAME, 'readwrite');
    const store = writeTx.objectStore(READER_CACHE_ASSET_STORE_NAME);
    for (const key of keys) {
      store.delete(key);
    }
    await transactionDone(writeTx);
  } catch {
    // Best-effort cleanup.
  } finally {
    deleteAssetFallbackForChapter(bookId, chapterId);
    db.close();
  }
}

async function deleteAudioForChapterAsync(bookId: number, chapterId: number): Promise<void> {
  const db = await openReaderCacheDb();
  if (!db) {
    deleteAudioFallbackForChapter(bookId, chapterId);
    return;
  }
  try {
    const readTx = db.transaction(READER_CACHE_AUDIO_STORE_NAME, 'readonly');
    const index = readTx.objectStore(READER_CACHE_AUDIO_STORE_NAME).index('bookChapterKey');
    const records = await idbRequest<ReaderCachedAudioRecord[]>(
      index.getAll(readerBookChapterAssetKey(bookId, chapterId)),
    );
    const keys = records.filter(isCachedAudioRecord).map((record) => {
      const objectUrl = cachedAudioObjectUrls.get(record.key);
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      cachedAudioObjectUrls.delete(record.key);
      return record.key;
    });
    if (keys.length === 0) return;
    const writeTx = db.transaction(READER_CACHE_AUDIO_STORE_NAME, 'readwrite');
    const store = writeTx.objectStore(READER_CACHE_AUDIO_STORE_NAME);
    for (const key of keys) {
      store.delete(key);
    }
    await transactionDone(writeTx);
  } catch {
    // Best-effort cleanup.
  } finally {
    deleteAudioFallbackForChapter(bookId, chapterId);
    db.close();
  }
}

async function deleteAssetsForBookAsync(bookId: number): Promise<void> {
  const db = await openReaderCacheDb();
  if (!db) {
    deleteAssetFallbackForBook(bookId);
    return;
  }
  try {
    const readTx = db.transaction(READER_CACHE_ASSET_STORE_NAME, 'readonly');
    const index = readTx.objectStore(READER_CACHE_ASSET_STORE_NAME).index('bookId');
    const records = await idbRequest<ReaderCachedAssetRecord[]>(index.getAll(bookId));
    const keys = records.filter(isCachedAssetRecord).map((record) => {
      const objectUrl = cachedAssetObjectUrls.get(record.key);
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      cachedAssetObjectUrls.delete(record.key);
      return record.key;
    });
    if (keys.length === 0) return;
    const writeTx = db.transaction(READER_CACHE_ASSET_STORE_NAME, 'readwrite');
    const store = writeTx.objectStore(READER_CACHE_ASSET_STORE_NAME);
    for (const key of keys) {
      store.delete(key);
    }
    await transactionDone(writeTx);
  } catch {
    // Best-effort cleanup.
  } finally {
    deleteAssetFallbackForBook(bookId);
    db.close();
  }
}

async function deleteAudioForBookAsync(bookId: number): Promise<void> {
  const db = await openReaderCacheDb();
  if (!db) {
    deleteAudioFallbackForBook(bookId);
    return;
  }
  try {
    const readTx = db.transaction(READER_CACHE_AUDIO_STORE_NAME, 'readonly');
    const index = readTx.objectStore(READER_CACHE_AUDIO_STORE_NAME).index('bookId');
    const records = await idbRequest<ReaderCachedAudioRecord[]>(index.getAll(bookId));
    const keys = records.filter(isCachedAudioRecord).map((record) => {
      const objectUrl = cachedAudioObjectUrls.get(record.key);
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      cachedAudioObjectUrls.delete(record.key);
      return record.key;
    });
    if (keys.length === 0) return;
    const writeTx = db.transaction(READER_CACHE_AUDIO_STORE_NAME, 'readwrite');
    const store = writeTx.objectStore(READER_CACHE_AUDIO_STORE_NAME);
    for (const key of keys) {
      store.delete(key);
    }
    await transactionDone(writeTx);
  } catch {
    // Best-effort cleanup.
  } finally {
    deleteAudioFallbackForBook(bookId);
    db.close();
  }
}

async function readerAssetCacheSummaryAsync(): Promise<{ count: number; sizeBytes: number }> {
  const fallbackSummary = readerAssetFallbackSummary();
  const db = await openReaderCacheDb();
  if (!db) return {
    count: fallbackSummary.count,
    sizeBytes: fallbackSummary.sizeBytes,
  };
  try {
    const tx = db.transaction(READER_CACHE_ASSET_STORE_NAME, 'readonly');
    const records = await idbRequest<unknown[]>(tx.objectStore(READER_CACHE_ASSET_STORE_NAME).getAll());
    const assets = records.filter(isCachedAssetRecord);
    const indexedKeys = new Set(assets.map((asset) => asset.key));
    const fallbackOnly = Object.values(readAssetFallbackStore())
      .filter((asset) => !indexedKeys.has(asset.key));
    return {
      count: assets.length + fallbackOnly.length,
      sizeBytes: assets.reduce((total, asset) => total + asset.sizeBytes, 0)
        + fallbackOnly.reduce((total, asset) => total + asset.sizeBytes, 0),
    };
  } catch {
    return {
      count: fallbackSummary.count,
      sizeBytes: fallbackSummary.sizeBytes,
    };
  } finally {
    db.close();
  }
}

async function readerAudioCacheSummaryAsync(): Promise<{ count: number; sizeBytes: number }> {
  const fallbackSummary = readerAudioFallbackSummary();
  const db = await openReaderCacheDb();
  if (!db) return {
    count: fallbackSummary.count,
    sizeBytes: fallbackSummary.sizeBytes,
  };
  try {
    const tx = db.transaction(READER_CACHE_AUDIO_STORE_NAME, 'readonly');
    const records = await idbRequest<unknown[]>(tx.objectStore(READER_CACHE_AUDIO_STORE_NAME).getAll());
    const audioRecords = records.filter(isCachedAudioRecord);
    const indexedKeys = new Set(audioRecords.map((audio) => audio.key));
    const fallbackOnly = Object.values(readAudioFallbackStore())
      .filter((audio) => !indexedKeys.has(audio.key));
    return {
      count: audioRecords.length + fallbackOnly.length,
      sizeBytes: audioRecords.reduce((total, audio) => total + audio.sizeBytes, 0)
        + fallbackOnly.reduce((total, audio) => total + audio.sizeBytes, 0),
    };
  } catch {
    return {
      count: fallbackSummary.count,
      sizeBytes: fallbackSummary.sizeBytes,
    };
  } finally {
    db.close();
  }
}

export function extractReaderAssetUrls(html: string, baseUrl?: string): string[] {
  const contentHtml = html.trim();
  if (!contentHtml) return [];
  const urls: string[] = [];

  if (typeof DOMParser !== 'undefined') {
    const documentRef = new DOMParser().parseFromString(contentHtml, 'text/html');
    for (const element of Array.from(documentRef.querySelectorAll(
      'audio[src], embed[src], img[src], img[srcset], img[data-src], img[data-original], img[data-lazy-src], img[data-srcset], object[data], source[src], source[srcset], source[data-srcset], track[src], image[href], image[xlink\\:href], feImage[href], feImage[xlink\\:href], use[href], use[xlink\\:href], video[src], video[poster], link[href], [style], style',
    ))) {
      appendReaderElementAssetUrls(urls, element, baseUrl);
    }
  } else {
    const assetTagPattern = /<(?:audio|embed|img|object|source|track|image|feImage|use|video|link)\b[^>]*>/gi;
    let match = assetTagPattern.exec(contentHtml);
    while (match) {
      appendReaderHtmlTagAssetUrls(urls, match[0], baseUrl);
      match = assetTagPattern.exec(contentHtml);
    }
    const styleTagPattern = /<style\b[^>]*>([\s\S]*?)<\/style>/gi;
    let styleMatch = styleTagPattern.exec(contentHtml);
    while (styleMatch) {
      appendReaderCssAssetUrls(urls, styleMatch[1] ?? '', baseUrl);
      styleMatch = styleTagPattern.exec(contentHtml);
    }
  }

  return Array.from(new Set(urls));
}

export async function cacheReaderAssetsFromHtml(
  bookId: number,
  chapterId: number,
  html: string,
  fetcher: typeof fetch = browserFetch,
  baseUrl?: string,
): Promise<ReaderAssetCacheSummary> {
  const urls = extractReaderAssetUrls(html, baseUrl);
  const seenUrls = new Set(urls);
  let cached = 0;
  let failed = 0;
  let sizeBytes = 0;

  function enqueueCssAssets(cssText: string, stylesheetUrl: string): void {
    for (const nestedUrl of extractReaderAssetUrls(`<style>${cssText}</style>`, stylesheetUrl)) {
      if (seenUrls.has(nestedUrl)) continue;
      seenUrls.add(nestedUrl);
      urls.push(nestedUrl);
    }
  }

  function isStylesheetAsset(url: string, contentType: string): boolean {
    return contentType.toLowerCase().split(';', 1)[0].trim() === 'text/css'
      || url.toLowerCase().split('?', 1)[0].endsWith('.css');
  }

  for (let index = 0; index < urls.length; index += 1) {
    const url = urls[index];
    const cachedRecord = await getCachedAssetRecordAsync(bookId, chapterId, url);
    if (cachedRecord) {
      cached += 1;
      if (isStylesheetAsset(url, cachedRecord.contentType)) {
        enqueueCssAssets(await cachedRecord.blob.text(), url);
      }
      continue;
    }
    try {
      const response = await fetcher(url, { credentials: 'same-origin' });
      if (!response.ok) {
        failed += 1;
        continue;
      }
      const blob = await response.blob();
      const contentType = response.headers.get('content-type') ?? blob.type ?? 'application/octet-stream';
      const assetSize = blob.size;
      if (isStylesheetAsset(url, contentType)) {
        enqueueCssAssets(await blob.text(), url);
      }
      const stored = await putCachedAssetRecordAsync({
        blob,
        bookId,
        cachedAt: new Date().toISOString(),
        chapterId,
        contentType,
        sizeBytes: assetSize,
        url,
      });
      if (stored) {
        cached += 1;
        sizeBytes += assetSize;
      } else {
        failed += 1;
      }
    } catch {
      failed += 1;
    }
  }

  return {
    cached,
    failed,
    sizeBytes,
    total: urls.length,
    urls,
  };
}

export async function cacheReaderBlobAsset(
  bookId: number,
  chapterId: number,
  url: string,
  blob: Blob,
  contentType = blob.type || 'application/octet-stream',
): Promise<ReaderAssetCacheSummary> {
  const normalizedUrl = normalizeReaderAssetUrl(url);
  if (!normalizedUrl || blob.size <= 0) {
    return {
      cached: 0,
      failed: 1,
      sizeBytes: 0,
      total: 1,
      urls: [normalizedUrl || url],
    };
  }

  const existing = await getCachedAssetRecordAsync(bookId, chapterId, normalizedUrl);
  if (existing) {
    return {
      cached: 1,
      failed: 0,
      sizeBytes: existing.sizeBytes,
      total: 1,
      urls: [normalizedUrl],
    };
  }

  const stored = await putCachedAssetRecordAsync({
    blob,
    bookId,
    cachedAt: new Date().toISOString(),
    chapterId,
    contentType,
    sizeBytes: blob.size,
    url: normalizedUrl,
  });

  return {
    cached: stored ? 1 : 0,
    failed: stored ? 0 : 1,
    sizeBytes: stored ? blob.size : 0,
    total: 1,
    urls: [normalizedUrl],
  };
}

export async function hydrateReaderElementAssetUrls(
  element: Element,
  resolveCachedUrl: (url: string) => Promise<string | null | undefined>,
  baseUrl?: string,
): Promise<boolean> {
  let changed = false;
  const tagName = element.tagName.toLowerCase();
  const cachedUrlForAsset = async (url: string): Promise<string> => {
    if (!isCacheableReaderAssetUrl(url, baseUrl)) return '';
    const reference = readerAssetReference(url, baseUrl);
    const cachedUrl = await resolveCachedUrl(reference.assetUrl);
    return cachedUrl ? `${cachedUrl}${reference.fragment}` : '';
  };

  if (tagName === 'img') {
    const originalSrc = element.getAttribute('src') ?? '';
    const objectUrl = await cachedUrlForAsset(originalSrc);
    if (objectUrl) {
      element.setAttribute('data-original-src', originalSrc);
      element.setAttribute('src', objectUrl);
      changed = true;
    }

    for (const attributeName of ['data-src', 'data-original', 'data-lazy-src']) {
      const originalLazySrc = element.getAttribute(attributeName) ?? '';
      const lazyObjectUrl = await cachedUrlForAsset(originalLazySrc);
      if (!lazyObjectUrl) continue;
      element.setAttribute(`data-original-${attributeName}`, originalLazySrc);
      element.setAttribute(attributeName, lazyObjectUrl);
      if (!element.getAttribute('src')) {
        element.setAttribute('src', lazyObjectUrl);
      }
      changed = true;
    }
  }

  if (tagName === 'audio' || tagName === 'source' || tagName === 'video') {
    const originalSrc = element.getAttribute('src') ?? '';
    const objectUrl = await cachedUrlForAsset(originalSrc);
    if (objectUrl) {
      element.setAttribute('data-original-src', originalSrc);
      element.setAttribute('src', objectUrl);
      changed = true;
    }
  }

  if (tagName === 'embed' || tagName === 'track') {
    const originalSrc = element.getAttribute('src') ?? '';
    const objectUrl = await cachedUrlForAsset(originalSrc);
    if (objectUrl) {
      element.setAttribute('data-original-src', originalSrc);
      element.setAttribute('src', objectUrl);
      changed = true;
    }
  }

  if (tagName === 'object') {
    const originalData = element.getAttribute('data') ?? '';
    const objectUrl = await cachedUrlForAsset(originalData);
    if (objectUrl) {
      element.setAttribute('data-original-data', originalData);
      element.setAttribute('data', objectUrl);
      changed = true;
    }
  }

  if (svgHrefReferencesReaderAsset(tagName)) {
    for (const attributeName of ['href', 'xlink:href']) {
      const originalHref = element.getAttribute(attributeName) ?? '';
      const objectUrl = await cachedUrlForAsset(originalHref);
      if (!objectUrl) continue;
      element.setAttribute(`data-original-${attributeName.replace(':', '-')}`, originalHref);
      element.setAttribute(attributeName, objectUrl);
      changed = true;
    }
  }

  if (tagName === 'link' && linkReferencesReaderAsset(element.getAttribute('rel') ?? '', element.getAttribute('as') ?? '')) {
    const originalHref = element.getAttribute('href') ?? '';
    const objectUrl = await cachedUrlForAsset(originalHref);
    if (objectUrl) {
      element.setAttribute('data-original-href', originalHref);
      element.setAttribute('href', objectUrl);
      changed = true;
    }
  }

  if (tagName === 'img' || tagName === 'source') {
    const originalSrcset = element.getAttribute('srcset') ?? '';
    if (originalSrcset) {
      const hydratedSrcset = await hydrateReaderSrcsetAssetUrls(originalSrcset, resolveCachedUrl, baseUrl);
      if (hydratedSrcset.changed) {
        element.setAttribute('data-original-srcset', originalSrcset);
        element.setAttribute('srcset', hydratedSrcset.value);
        changed = true;
      }
    }

    const originalLazySrcset = element.getAttribute('data-srcset') ?? '';
    if (originalLazySrcset) {
      const hydratedLazySrcset = await hydrateReaderSrcsetAssetUrls(originalLazySrcset, resolveCachedUrl, baseUrl);
      if (hydratedLazySrcset.changed) {
        element.setAttribute('data-original-data-srcset', originalLazySrcset);
        element.setAttribute('data-srcset', hydratedLazySrcset.value);
        if (tagName === 'img' && !element.getAttribute('srcset')) {
          element.setAttribute('srcset', hydratedLazySrcset.value);
        }
        changed = true;
      }
    }
  }

  if (tagName === 'video') {
    const originalPoster = element.getAttribute('poster') ?? '';
    const objectUrl = await cachedUrlForAsset(originalPoster);
    if (objectUrl) {
      element.setAttribute('data-original-poster', originalPoster);
      element.setAttribute('poster', objectUrl);
      changed = true;
    }
  }

  const originalStyle = element.getAttribute('style') ?? '';
  if (originalStyle) {
    const hydratedStyle = await hydrateReaderCssAssetUrls(originalStyle, resolveCachedUrl, baseUrl);
    if (hydratedStyle.changed) {
      element.setAttribute('data-original-style', originalStyle);
      element.setAttribute('style', hydratedStyle.value);
      changed = true;
    }
  }

  if (tagName === 'style') {
    const originalCss = element.textContent ?? '';
    const hydratedCss = await hydrateReaderCssAssetUrls(originalCss, resolveCachedUrl, baseUrl);
    if (hydratedCss.changed) {
      element.setAttribute('data-original-css', originalCss);
      element.textContent = hydratedCss.value;
      changed = true;
    }
  }

  return changed;
}

export async function hydrateCachedReaderAssetUrls(
  bookId: number,
  chapterId: number,
  html: string,
  baseUrl?: string,
): Promise<string> {
  const contentHtml = html.trim();
  if (!contentHtml || typeof DOMParser === 'undefined' || typeof URL.createObjectURL !== 'function') return html;
  const documentRef = new DOMParser().parseFromString(contentHtml, 'text/html');
  let changed = false;

  const cachedObjectUrlForAsset = async (url: string): Promise<string> => {
    const asset = await getCachedAssetRecordAsync(bookId, chapterId, url);
    return asset ? objectUrlForCachedAsset(asset) : '';
  };

  for (const element of Array.from(documentRef.querySelectorAll(
    'audio[src], embed[src], img[src], img[srcset], img[data-src], img[data-original], img[data-lazy-src], img[data-srcset], object[data], source[src], source[srcset], source[data-srcset], track[src], image[href], image[xlink\\:href], feImage[href], feImage[xlink\\:href], use[href], use[xlink\\:href], video[src], video[poster], link[href], [style], style',
  ))) {
    if (await hydrateReaderElementAssetUrls(element, cachedObjectUrlForAsset, baseUrl)) changed = true;
  }

  return changed ? documentRef.body.innerHTML : html;
}

export async function cacheReaderAudio(
  bookId: number,
  chapterId: number,
  url: string,
  fetcher: typeof fetch = browserFetch,
): Promise<ReaderAudioCacheSummary> {
  const normalizedUrl = normalizeReaderAssetUrl(url);
  if (!normalizedUrl) {
    return {
      cached: false,
      failed: true,
      sizeBytes: 0,
      url: normalizedUrl,
    };
  }

  const existing = await getCachedAudioRecordAsync(bookId, chapterId, normalizedUrl);
  if (existing) {
    return {
      cached: true,
      failed: false,
      sizeBytes: existing.sizeBytes,
      url: normalizedUrl,
    };
  }

  try {
    const response = await fetcher(normalizedUrl, { credentials: 'include' });
    if (!response.ok) {
      return {
        cached: false,
        failed: true,
        sizeBytes: 0,
        url: normalizedUrl,
      };
    }
    const blob = await response.blob();
    const contentType = response.headers.get('content-type') ?? blob.type ?? 'audio/mpeg';
    const audioRecord = {
      blob,
      bookId,
      cachedAt: new Date().toISOString(),
      chapterId,
      contentType,
      sizeBytes: blob.size,
      url: normalizedUrl,
    };
    const stored = await putCachedAudioRecordAsync(audioRecord)
      || await putCachedAudioFallbackRecordAsync(audioRecord);
    return {
      cached: stored,
      failed: !stored,
      sizeBytes: stored ? blob.size : 0,
      url: normalizedUrl,
    };
  } catch {
    return {
      cached: false,
      failed: true,
      sizeBytes: 0,
      url: normalizedUrl,
    };
  }
}

export async function getCachedReaderAudioUrl(
  bookId: number,
  chapterId: number,
  url: string,
): Promise<string> {
  if (typeof URL.createObjectURL !== 'function') return '';
  const audio = await getCachedAudioRecordAsync(bookId, chapterId, url)
    ?? await getCachedAudioRecordForChapterAsync(bookId, chapterId);
  return audio ? objectUrlForCachedAudio(audio) : '';
}

export async function getCachedReaderAssetUrl(
  bookId: number,
  chapterId: number,
  url: string,
  baseUrl?: string,
): Promise<string> {
  if (typeof URL.createObjectURL !== 'function') return '';
  const reference = readerAssetReference(url, baseUrl);
  if (!reference.assetUrl) return '';
  const asset = await getCachedAssetRecordAsync(bookId, chapterId, reference.assetUrl);
  return asset ? `${objectUrlForCachedAsset(asset)}${reference.fragment}` : '';
}

export async function loadReaderCacheAsync(): Promise<ReaderCacheStore> {
  const db = await openReaderCacheDb();
  if (!db) return loadReaderCache();
  try {
    const tx = db.transaction(READER_CACHE_STORE_NAME, 'readonly');
    const records = await idbRequest<unknown[]>(tx.objectStore(READER_CACHE_STORE_NAME).getAll());
    const store: ReaderCacheStore = {};
    for (const record of records) {
      const chapter = cachedChapterFromRecord(record);
      if (!chapter) continue;
      store[readerCacheKey(chapter.bookId, chapter.chapterId)] = chapter;
    }
    return pruneCacheStore({ ...loadReaderCache(), ...store });
  } catch {
    return loadReaderCache();
  } finally {
    db.close();
  }
}

export function saveReaderCache(
  store: ReaderCacheStore,
  storage: Storage | null = getBrowserStorage(),
): ReaderCacheStore {
  const nextStore = pruneCacheStore(store);
  if (!storage) return nextStore;
  try {
    storage.setItem(READER_CACHE_STORAGE_KEY, JSON.stringify(nextStore));
    emitReaderCacheUpdated();
  } catch {
    // localStorage may be full or disabled. The reader can still fetch live content.
  }
  return nextStore;
}

export function getCachedChapter(
  bookId: number,
  chapterId: number,
  storage: Storage | null = getBrowserStorage(),
): ReaderCachedChapter | null {
  return loadReaderCache(storage)[readerCacheKey(bookId, chapterId)] ?? null;
}

export async function getCachedChapterAsync(bookId: number, chapterId: number): Promise<ReaderCachedChapter | null> {
  const db = await openReaderCacheDb();
  if (!db) return getCachedChapter(bookId, chapterId);
  try {
    const tx = db.transaction(READER_CACHE_STORE_NAME, 'readonly');
    const record = await idbRequest<unknown>(tx.objectStore(READER_CACHE_STORE_NAME).get(readerCacheKey(bookId, chapterId)));
    return cachedChapterFromRecord(record) ?? getCachedChapter(bookId, chapterId);
  } catch {
    return getCachedChapter(bookId, chapterId);
  } finally {
    db.close();
  }
}

export function hasCachedChapter(
  bookId: number,
  chapterId: number,
  storage: Storage | null = getBrowserStorage(),
): boolean {
  return Boolean(getCachedChapter(bookId, chapterId, storage));
}

export async function hasCachedChapterAsync(bookId: number, chapterId: number): Promise<boolean> {
  return Boolean(await getCachedChapterAsync(bookId, chapterId));
}

export function putCachedChapter(
  chapter: Omit<ReaderCachedChapter, 'cachedAt'> & { cachedAt?: string },
  storage: Storage | null = getBrowserStorage(),
): ReaderCacheStore {
  const store = loadReaderCache(storage);
  const key = readerCacheKey(chapter.bookId, chapter.chapterId);
  return saveReaderCache(
    {
      ...store,
      [key]: {
        bookId: chapter.bookId,
        cachedAt: chapter.cachedAt ?? new Date().toISOString(),
        chapterId: chapter.chapterId,
        html: chapter.html,
        sourceText: chapter.sourceText,
        text: chapter.text,
      },
    },
    storage,
  );
}

export async function putCachedChapterAsync(
  chapter: Omit<ReaderCachedChapter, 'cachedAt'> & { cachedAt?: string },
): Promise<void> {
  const cachedChapter: ReaderCachedChapter = {
    bookId: chapter.bookId,
    cachedAt: chapter.cachedAt ?? new Date().toISOString(),
    chapterId: chapter.chapterId,
    html: chapter.html,
    sourceText: chapter.sourceText,
    text: chapter.text,
  };
  const db = await openReaderCacheDb();
  if (!db) {
    putCachedChapter(cachedChapter);
    return;
  }
  try {
    const tx = db.transaction(READER_CACHE_STORE_NAME, 'readwrite');
    tx.objectStore(READER_CACHE_STORE_NAME).put(cachedChapterRecord(cachedChapter));
    await transactionDone(tx);
    await pruneIndexedReaderCache(db);
    emitReaderCacheUpdated();
  } catch {
    putCachedChapter(cachedChapter);
  } finally {
    db.close();
  }
}

export function removeCachedChapter(
  bookId: number,
  chapterId: number,
  storage: Storage | null = getBrowserStorage(),
): ReaderCacheStore {
  const store = loadReaderCache(storage);
  const key = readerCacheKey(bookId, chapterId);
  if (!store[key]) return store;
  const nextStore = { ...store };
  delete nextStore[key];
  return saveReaderCache(nextStore, storage);
}

export async function removeCachedChapterAsync(bookId: number, chapterId: number): Promise<void> {
  const db = await openReaderCacheDb();
  if (!db) {
    removeCachedChapter(bookId, chapterId);
    deleteAssetFallbackForChapter(bookId, chapterId);
    deleteAudioFallbackForChapter(bookId, chapterId);
    return;
  }
  try {
    const tx = db.transaction(READER_CACHE_STORE_NAME, 'readwrite');
    tx.objectStore(READER_CACHE_STORE_NAME).delete(readerCacheKey(bookId, chapterId));
    await transactionDone(tx);
    await deleteAssetsForChapterAsync(bookId, chapterId);
    await deleteAudioForChapterAsync(bookId, chapterId);
    emitReaderCacheUpdated();
  } catch {
    removeCachedChapter(bookId, chapterId);
    await deleteAssetsForChapterAsync(bookId, chapterId);
    await deleteAudioForChapterAsync(bookId, chapterId);
  } finally {
    db.close();
  }
}

export function removeCachedBook(
  bookId: number,
  storage: Storage | null = getBrowserStorage(),
): ReaderCacheStore {
  const store = loadReaderCache(storage);
  const nextEntries = Object.entries(store).filter(([, chapter]) => chapter.bookId !== bookId);
  if (nextEntries.length === Object.keys(store).length) return store;
  return saveReaderCache(Object.fromEntries(nextEntries), storage);
}

export async function removeCachedBookAsync(bookId: number): Promise<void> {
  const db = await openReaderCacheDb();
  if (!db) {
    removeCachedBook(bookId);
    deleteAssetFallbackForBook(bookId);
    deleteAudioFallbackForBook(bookId);
    return;
  }
  try {
    const readTx = db.transaction(READER_CACHE_STORE_NAME, 'readonly');
    const records = await idbRequest<ReaderCachedChapterRecord[]>(readTx.objectStore(READER_CACHE_STORE_NAME).getAll());
    const keys = records
      .filter((record) => isCachedChapter(record) && record.bookId === bookId)
      .map((record) => readerCacheKey(record.bookId, record.chapterId));
    if (keys.length > 0) {
      const writeTx = db.transaction(READER_CACHE_STORE_NAME, 'readwrite');
      const store = writeTx.objectStore(READER_CACHE_STORE_NAME);
      keys.forEach((key) => store.delete(key));
      await transactionDone(writeTx);
    }
    await deleteAssetsForBookAsync(bookId);
    await deleteAudioForBookAsync(bookId);
    emitReaderCacheUpdated();
  } catch {
    removeCachedBook(bookId);
    await deleteAssetsForBookAsync(bookId);
    await deleteAudioForBookAsync(bookId);
  } finally {
    db.close();
  }
}

export function estimateReaderCacheBytes(store: ReaderCacheStore = loadReaderCache()): number {
  try {
    return new Blob([JSON.stringify(store)]).size;
  } catch {
    return JSON.stringify(store).length;
  }
}

export function formatReaderCacheSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 KB';
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function readerCacheStatus({
  bookId,
  chapterId,
  nextChapterId,
  storage = getBrowserStorage(),
}: {
  bookId: number;
  chapterId: number;
  nextChapterId?: number | null;
  storage?: Storage | null;
}): ReaderCacheStatus {
  const store = loadReaderCache(storage);
  const sizeBytes = estimateReaderCacheBytes(store);
  return {
    audioCount: 0,
    audioSizeBytes: 0,
    audioSizeLabel: formatReaderCacheSize(0),
    assetCount: 0,
    assetSizeBytes: 0,
    assetSizeLabel: formatReaderCacheSize(0),
    currentCached: Boolean(store[readerCacheKey(bookId, chapterId)]),
    nextCached: nextChapterId ? Boolean(store[readerCacheKey(bookId, nextChapterId)]) : null,
    sizeBytes,
    sizeLabel: formatReaderCacheSize(sizeBytes),
  };
}

export async function readerCacheStatusAsync({
  bookId,
  chapterId,
  nextChapterId,
}: {
  bookId: number;
  chapterId: number;
  nextChapterId?: number | null;
}): Promise<ReaderCacheStatus> {
  const store = await loadReaderCacheAsync();
  const assetSummary = await readerAssetCacheSummaryAsync();
  const audioSummary = await readerAudioCacheSummaryAsync();
  const chapterSizeBytes = estimateReaderCacheBytes(store);
  const sizeBytes = chapterSizeBytes + assetSummary.sizeBytes + audioSummary.sizeBytes;
  return {
    audioCount: audioSummary.count,
    audioSizeBytes: audioSummary.sizeBytes,
    audioSizeLabel: formatReaderCacheSize(audioSummary.sizeBytes),
    assetCount: assetSummary.count,
    assetSizeBytes: assetSummary.sizeBytes,
    assetSizeLabel: formatReaderCacheSize(assetSummary.sizeBytes),
    currentCached: Boolean(store[readerCacheKey(bookId, chapterId)]),
    nextCached: nextChapterId ? Boolean(store[readerCacheKey(bookId, nextChapterId)]) : null,
    sizeBytes,
    sizeLabel: formatReaderCacheSize(sizeBytes),
  };
}
