import type { BookAudioPlaylistItem, ExportDownload, ReaderDictionaryFile, ReaderDictionaryPack } from '../api/types';
import {
  cacheReaderBlobAsset,
  cacheReaderAssetsFromHtml,
  cacheReaderAudio,
  putCachedChapterAsync,
  type ReaderAssetCacheSummary,
  type ReaderAudioCacheSummary,
} from './readerCache';
import { saveCachedReaderDictionaryPack } from './readerDictionaryCache';

export const READER_OFFLINE_MANIFEST_STORAGE_KEY = 'novel-reader-offline-manifest-v1';
const READER_OFFLINE_MANIFEST_VERSION = 3;

export type ReaderOfflineCacheChapter = {
  audio_path?: string | null;
  book_id: number;
  content_html_path?: string | null;
  has_translation?: boolean;
  id: number;
};

export type ReaderOfflineCacheClient = {
  chapterAudioUrl(bookId: number, chapterId: number): string;
  downloadReaderDictionary?(filename: string): Promise<ExportDownload>;
  getBookAudioPlaylist?(bookId: number): Promise<{ chapters: BookAudioPlaylistItem[] }>;
  getChapterContent(bookId: number, chapterId: number): Promise<{ html: string; text: string } | null>;
  getChapterTranslation(bookId: number, chapterId: number): Promise<string | null>;
  getReaderDictionaryPack(bookId: number, options?: { chapterId?: number | null }): Promise<ReaderDictionaryPack>;
  listReaderDictionaries?(): Promise<ReaderDictionaryFile[]>;
  readerDictionaryDownloadUrl?(filename: string): string;
};

export type ReaderOfflineCacheSummary = {
  assetsCached: number;
  assetsFailed: number;
  assetsTotal: number;
  audioCached: number;
  audioFailed: number;
  audioTotal: number;
  chaptersCached: number;
  chaptersFailed: number;
  chaptersTotal: number;
  dictionaryCached: boolean;
};

export type ReaderOfflineManifestCover = {
  cached: boolean;
  failed: boolean;
  sizeBytes: number;
  url: string;
};

export type ReaderOfflineCacheProgress = ReaderOfflineCacheSummary & {
  currentChapterId?: number;
};

export type ReaderOfflineManifestChapter = {
  cached: boolean;
  failed: boolean;
  htmlCached: boolean;
  id: number;
  textCached: boolean;
};

export type ReaderOfflineManifestAsset = ReaderAssetCacheSummary & {
  chapterId: number;
};

export type ReaderOfflineManifestAudio = ReaderAudioCacheSummary & {
  chapterId: number;
};

export type ReaderOfflineManifestDictionaryFile = {
  cached: boolean;
  failed: boolean;
  filename: string;
  sizeBytes: number;
  url: string;
};

export type ReaderOfflineManifestDictionaryChapterPack = {
  cached: boolean;
  chapterId: number;
  counts: ReaderDictionaryPack['counts'];
  failed: boolean;
  generatedAt: string;
  sourceCount: number;
};

export type ReaderOfflineManifest = {
  assets: ReaderOfflineManifestAsset[];
  audio: ReaderOfflineManifestAudio[];
  bookId: number;
  cachedAt: string;
  chapterIds: number[];
  chapters: ReaderOfflineManifestChapter[];
  checksum: string;
  cover: ReaderOfflineManifestCover | null;
  dictionary: {
    cached: boolean;
    chapterPacks: ReaderOfflineManifestDictionaryChapterPack[];
    counts: ReaderDictionaryPack['counts'];
    files: ReaderOfflineManifestDictionaryFile[];
    generatedAt: string;
    sourceCount: number;
  };
  summary: ReaderOfflineCacheSummary;
  version: number;
};

type ReaderOfflineManifestStore = Record<string, ReaderOfflineManifest>;

export type CacheBookForOfflineOptions = {
  bookId: number;
  cacheAssets?: (bookId: number, chapterId: number, html: string, baseUrl?: string) => Promise<ReaderAssetCacheSummary>;
  cacheAudio?: (bookId: number, chapterId: number, url: string) => Promise<ReaderAudioCacheSummary>;
  chapters: ReaderOfflineCacheChapter[];
  client: ReaderOfflineCacheClient;
  coverUrl?: string | null;
  onProgress?: (progress: ReaderOfflineCacheProgress) => void;
};

export type CacheChapterForOfflineOptions = {
  audioUrl?: string;
  bookId: number;
  cacheAssets?: (bookId: number, chapterId: number, html: string, baseUrl?: string) => Promise<ReaderAssetCacheSummary>;
  cacheAudio?: (bookId: number, chapterId: number, url: string) => Promise<ReaderAudioCacheSummary>;
  chapter: ReaderOfflineCacheChapter;
  client: ReaderOfflineCacheClient;
};

function getBrowserStorage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function emptySummary(chaptersTotal: number): ReaderOfflineCacheSummary {
  return {
    assetsCached: 0,
    assetsFailed: 0,
    assetsTotal: 0,
    audioCached: 0,
    audioFailed: 0,
    audioTotal: 0,
    chaptersCached: 0,
    chaptersFailed: 0,
    chaptersTotal,
    dictionaryCached: false,
  };
}

function translatedOfflineChapters(
  bookId: number,
  chapters: ReaderOfflineCacheChapter[],
): ReaderOfflineCacheChapter[] {
  return chapters.filter((chapter) => (
    chapter.book_id === bookId
    && chapter.has_translation
  ));
}

function readerOfflineAssetBase(contentHtmlPath?: string | null): string | undefined {
  const path = contentHtmlPath?.trim() ?? '';
  if (!path) return undefined;
  if (/^https?:\/\//i.test(path) || path.startsWith('/book-assets/')) return path;
  return undefined;
}

function cacheOfflineReaderAssets(
  bookId: number,
  chapterId: number,
  html: string,
  baseUrl?: string,
): Promise<ReaderAssetCacheSummary> {
  return cacheReaderAssetsFromHtml(bookId, chapterId, html, undefined, baseUrl);
}

function fallbackReaderDictionaryDownloadUrl(filename: string): string {
  return `/api/reader/dictionaries/${encodeURIComponent(filename)}/download`;
}

function emptyReaderDictionaryCounts(): ReaderDictionaryPack['counts'] {
  return {
    builtin: 0,
    glossary: 0,
    offline_dictionary: 0,
    xray: 0,
  };
}

async function cacheOfflineReaderDictionaryFile(
  bookId: number,
  file: ReaderDictionaryFile,
  client: ReaderOfflineCacheClient,
): Promise<ReaderOfflineManifestDictionaryFile> {
  const url = client.readerDictionaryDownloadUrl?.(file.filename) ?? fallbackReaderDictionaryDownloadUrl(file.filename);
  if (!client.downloadReaderDictionary) {
    return {
      cached: false,
      failed: true,
      filename: file.filename,
      sizeBytes: 0,
      url,
    };
  }
  const download = await client.downloadReaderDictionary(file.filename);
  const summary = await cacheReaderBlobAsset(
    bookId,
    0,
    url,
    download.blob,
    download.mediaType,
  );
  const cached = summary.cached > 0 && summary.failed === 0;
  return {
    cached,
    failed: !cached,
    filename: file.filename,
    sizeBytes: file.size_bytes || summary.sizeBytes || download.blob.size,
    url,
  };
}

function validManifest(value: unknown): value is ReaderOfflineManifest {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const manifest = value as Partial<ReaderOfflineManifest>;
  return (
    manifest.version === READER_OFFLINE_MANIFEST_VERSION
    && Array.isArray(manifest.assets)
    && Array.isArray(manifest.audio)
    && Number.isInteger(manifest.bookId)
    && typeof manifest.cachedAt === 'string'
    && Array.isArray(manifest.chapterIds)
    && manifest.chapterIds.every((chapterId) => Number.isInteger(chapterId))
    && Array.isArray(manifest.chapters)
    && typeof manifest.checksum === 'string'
    && typeof manifest.dictionary === 'object'
    && manifest.dictionary !== null
    && typeof manifest.summary === 'object'
    && manifest.summary !== null
  );
}

function loadReaderOfflineManifestStore(
  storage: Storage | null = getBrowserStorage(),
): ReaderOfflineManifestStore {
  if (!storage) return {};
  try {
    const parsed = JSON.parse(storage.getItem(READER_OFFLINE_MANIFEST_STORAGE_KEY) ?? '{}') as unknown;
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    return Object.fromEntries(
      Object.entries(parsed)
        .filter((entry): entry is [string, ReaderOfflineManifest] => validManifest(entry[1])),
    );
  } catch {
    return {};
  }
}

function saveReaderOfflineManifestStore(
  store: ReaderOfflineManifestStore,
  storage: Storage | null = getBrowserStorage(),
): void {
  if (!storage) return;
  try {
    storage.setItem(READER_OFFLINE_MANIFEST_STORAGE_KEY, JSON.stringify(store));
  } catch {
    // Manifest improves diagnostics, but cache data itself remains usable without it.
  }
}

function stableJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(',')}]`;
  if (value && typeof value === 'object') {
    return `{${Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, entry]) => `${JSON.stringify(key)}:${stableJson(entry)}`)
      .join(',')}}`;
  }
  return JSON.stringify(value);
}

function manifestChecksum(value: unknown): string {
  const text = stableJson(value);
  let hash = 0x811c9dc5;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(16).padStart(8, '0');
}

export function loadReaderOfflineManifest(
  bookId: number,
  storage: Storage | null = getBrowserStorage(),
): ReaderOfflineManifest | null {
  if (!Number.isInteger(bookId) || bookId <= 0) return null;
  return loadReaderOfflineManifestStore(storage)[String(bookId)] ?? null;
}

export function removeReaderOfflineManifest(
  bookId: number,
  storage: Storage | null = getBrowserStorage(),
): void {
  if (!Number.isInteger(bookId) || bookId <= 0) return;
  const store = loadReaderOfflineManifestStore(storage);
  if (!store[String(bookId)]) return;
  delete store[String(bookId)];
  saveReaderOfflineManifestStore(store, storage);
}

function saveReaderOfflineManifest(
  manifest: ReaderOfflineManifest,
  storage: Storage | null = getBrowserStorage(),
): void {
  const store = loadReaderOfflineManifestStore(storage);
  store[String(manifest.bookId)] = manifest;
  saveReaderOfflineManifestStore(store, storage);
}

function emptyReaderOfflineDictionary(): ReaderOfflineManifest['dictionary'] {
  return {
    cached: false,
    chapterPacks: [],
    counts: emptyReaderDictionaryCounts(),
    files: [],
    generatedAt: '',
    sourceCount: 0,
  };
}

function normalizedReaderOfflineDictionary(
  dictionary: Partial<ReaderOfflineManifest['dictionary']> | undefined,
): ReaderOfflineManifest['dictionary'] {
  return {
    cached: Boolean(dictionary?.cached),
    chapterPacks: Array.isArray(dictionary?.chapterPacks) ? dictionary.chapterPacks : [],
    counts: dictionary?.counts ?? emptyReaderDictionaryCounts(),
    files: Array.isArray(dictionary?.files) ? dictionary.files : [],
    generatedAt: dictionary?.generatedAt ?? '',
    sourceCount: dictionary?.sourceCount ?? 0,
  };
}

function emptyReaderOfflineManifest(bookId: number): ReaderOfflineManifest {
  const payload = {
    assets: [] as ReaderOfflineManifestAsset[],
    audio: [] as ReaderOfflineManifestAudio[],
    bookId,
    chapterIds: [] as number[],
    chapters: [] as ReaderOfflineManifestChapter[],
    cover: null as ReaderOfflineManifestCover | null,
    dictionary: emptyReaderOfflineDictionary(),
    summary: emptySummary(0),
    version: READER_OFFLINE_MANIFEST_VERSION,
  };
  return {
    ...payload,
    cachedAt: new Date().toISOString(),
    checksum: manifestChecksum(payload),
  };
}

function replaceChapterEntry<T extends { chapterId: number }>(entries: T[], entry: T | null, chapterId: number): T[] {
  const next = entries.filter((item) => item.chapterId !== chapterId);
  if (entry) next.push(entry);
  return next;
}

function replaceManifestChapterEntry(
  entries: ReaderOfflineManifestChapter[],
  entry: ReaderOfflineManifestChapter,
): ReaderOfflineManifestChapter[] {
  const next = entries.filter((item) => item.id !== entry.id);
  next.push(entry);
  return next.sort((left, right) => left.id - right.id);
}

function recomputeManifestSummary(manifest: Omit<ReaderOfflineManifest, 'cachedAt' | 'checksum'>): ReaderOfflineCacheSummary {
  const dictionary = normalizedReaderOfflineDictionary(manifest.dictionary);
  return {
    assetsCached: manifest.assets.reduce((total, item) => total + item.cached, 0),
    assetsFailed: manifest.assets.reduce((total, item) => total + item.failed, 0),
    assetsTotal: manifest.assets.reduce((total, item) => total + item.total, 0),
    audioCached: manifest.audio.filter((item) => item.cached).length,
    audioFailed: manifest.audio.filter((item) => item.failed).length,
    audioTotal: manifest.audio.length,
    chaptersCached: manifest.chapters.filter((item) => item.cached && !item.failed).length,
    chaptersFailed: manifest.chapters.filter((item) => item.failed).length,
    chaptersTotal: manifest.chapters.length,
    dictionaryCached: dictionary.cached
      || dictionary.chapterPacks.some((pack) => pack.cached && !pack.failed),
  };
}

function saveReaderOfflineManifestPayload(
  manifest: Omit<ReaderOfflineManifest, 'cachedAt' | 'checksum'>,
  storage: Storage | null = getBrowserStorage(),
): ReaderOfflineManifest {
  const summary = recomputeManifestSummary(manifest);
  const payload = {
    ...manifest,
    chapterIds: [...new Set(manifest.chapters.map((chapter) => chapter.id))].sort((left, right) => left - right),
    dictionary: normalizedReaderOfflineDictionary(manifest.dictionary),
    summary,
  };
  const saved = {
    ...payload,
    cachedAt: new Date().toISOString(),
    checksum: manifestChecksum(payload),
  };
  saveReaderOfflineManifest(saved, storage);
  return saved;
}

export function removeReaderOfflineManifestChapter(
  bookId: number,
  chapterId: number,
  storage: Storage | null = getBrowserStorage(),
): void {
  const manifest = loadReaderOfflineManifest(bookId, storage);
  if (!manifest) return;
  const chapters = manifest.chapters.filter((chapter) => chapter.id !== chapterId);
  if (chapters.length === 0) {
    removeReaderOfflineManifest(bookId, storage);
    return;
  }
  saveReaderOfflineManifestPayload({
    ...manifest,
    assets: manifest.assets.filter((asset) => asset.chapterId !== chapterId),
    audio: manifest.audio.filter((audio) => audio.chapterId !== chapterId),
    chapterIds: chapters.map((chapter) => chapter.id),
    chapters,
    dictionary: {
      ...normalizedReaderOfflineDictionary(manifest.dictionary),
      chapterPacks: normalizedReaderOfflineDictionary(manifest.dictionary).chapterPacks.filter((pack) => pack.chapterId !== chapterId),
    },
    summary: recomputeManifestSummary({ ...manifest, chapters }),
  }, storage);
}

export async function cacheChapterForOffline({
  audioUrl,
  bookId,
  cacheAssets = cacheOfflineReaderAssets,
  cacheAudio = cacheReaderAudio,
  chapter,
  client,
}: CacheChapterForOfflineOptions): Promise<ReaderOfflineCacheSummary> {
  const summary = emptySummary(1);
  const manifest = loadReaderOfflineManifest(bookId) ?? emptyReaderOfflineManifest(bookId);
  let nextDictionary = normalizedReaderOfflineDictionary(manifest.dictionary);
  let manifestChapter: ReaderOfflineManifestChapter = {
    cached: false,
    failed: true,
    htmlCached: false,
    id: chapter.id,
    textCached: false,
  };
  let manifestAssets = manifest.assets.filter((asset) => asset.chapterId !== chapter.id);
  let manifestAudio = manifest.audio.filter((audio) => audio.chapterId !== chapter.id);

  try {
    const pack = await client.getReaderDictionaryPack(bookId, { chapterId: chapter.id });
    saveCachedReaderDictionaryPack(pack);
    summary.dictionaryCached = true;
    nextDictionary = {
      ...nextDictionary,
      cached: true,
      chapterPacks: replaceChapterEntry(nextDictionary.chapterPacks, {
        cached: true,
        chapterId: chapter.id,
        counts: pack.counts,
        failed: false,
        generatedAt: pack.generated_at,
        sourceCount: pack.source_count,
      }, chapter.id),
    };
  } catch {
    nextDictionary = {
      ...nextDictionary,
      chapterPacks: replaceChapterEntry(nextDictionary.chapterPacks, {
        cached: false,
        chapterId: chapter.id,
        counts: emptyReaderDictionaryCounts(),
        failed: true,
        generatedAt: '',
        sourceCount: 0,
      }, chapter.id),
    };
  }

  try {
    const richContent = chapter.content_html_path
      ? await client.getChapterContent(bookId, chapter.id)
      : null;
    const translation = richContent?.text ?? await client.getChapterTranslation(bookId, chapter.id) ?? '';
    const html = richContent?.html ?? '';
    await putCachedChapterAsync({
      bookId,
      chapterId: chapter.id,
      html,
      sourceText: '',
      text: translation,
    });
    summary.chaptersCached = 1;
    manifestChapter = {
      cached: true,
      failed: false,
      htmlCached: Boolean(html.trim()),
      id: chapter.id,
      textCached: Boolean(translation.trim()),
    };

    if (html.trim()) {
      const assetBase = readerOfflineAssetBase(chapter.content_html_path);
      const assetSummary = assetBase
        ? await cacheAssets(bookId, chapter.id, html, assetBase)
        : await cacheAssets(bookId, chapter.id, html);
      manifestAssets = replaceChapterEntry(manifestAssets, {
        ...assetSummary,
        chapterId: chapter.id,
      }, chapter.id);
      summary.assetsCached = assetSummary.cached;
      summary.assetsFailed = assetSummary.failed;
      summary.assetsTotal = assetSummary.total;
    }

    const normalizedAudioUrl = audioUrl?.trim() || (chapter.audio_path ? client.chapterAudioUrl(bookId, chapter.id) : '');
    if (normalizedAudioUrl) {
      summary.audioTotal = 1;
      const audioSummary = await cacheAudio(bookId, chapter.id, normalizedAudioUrl);
      manifestAudio = replaceChapterEntry(manifestAudio, {
        ...audioSummary,
        chapterId: chapter.id,
      }, chapter.id);
      if (audioSummary.cached) summary.audioCached = 1;
      if (audioSummary.failed) summary.audioFailed = 1;
    }
  } catch {
    summary.chaptersFailed = 1;
  }

  saveReaderOfflineManifestPayload({
    ...manifest,
    assets: manifestAssets,
    audio: manifestAudio,
    chapters: replaceManifestChapterEntry(manifest.chapters, manifestChapter),
    dictionary: nextDictionary,
    summary,
  });

  return summary;
}

export async function cacheBookForOffline({
  bookId,
  cacheAssets = cacheOfflineReaderAssets,
  cacheAudio = cacheReaderAudio,
  chapters,
  client,
  coverUrl,
  onProgress,
}: CacheBookForOfflineOptions): Promise<ReaderOfflineCacheSummary> {
  const targets = translatedOfflineChapters(bookId, chapters);
  const summary = emptySummary(targets.length);
  const manifestAssets: ReaderOfflineManifestAsset[] = [];
  const manifestAudio: ReaderOfflineManifestAudio[] = [];
  const manifestChapters: ReaderOfflineManifestChapter[] = [];
  const dictionary = {
    cached: false,
    chapterPacks: [] as ReaderOfflineManifestDictionaryChapterPack[],
    counts: emptyReaderDictionaryCounts(),
    files: [] as ReaderOfflineManifestDictionaryFile[],
    generatedAt: '',
    sourceCount: 0,
  };
  let cover: ReaderOfflineManifestCover | null = null;
  let audioPlaylistByChapterId = new Map<number, BookAudioPlaylistItem>();

  function emit(currentChapterId?: number): void {
    onProgress?.({ ...summary, currentChapterId });
  }

  if (client.getBookAudioPlaylist) {
    try {
      const playlist = await client.getBookAudioPlaylist(bookId);
      audioPlaylistByChapterId = new Map(
        playlist.chapters.map((item) => [item.chapter_id, item]),
      );
    } catch {
      audioPlaylistByChapterId = new Map();
    }
  }

  try {
    const pack = await client.getReaderDictionaryPack(bookId, { chapterId: null });
    saveCachedReaderDictionaryPack(pack);
    summary.dictionaryCached = true;
    dictionary.cached = true;
    dictionary.counts = pack.counts;
    dictionary.generatedAt = pack.generated_at;
    dictionary.sourceCount = pack.source_count;
    emit();
  } catch {
    summary.dictionaryCached = false;
    emit();
  }

  for (const chapter of targets) {
    try {
      const pack = await client.getReaderDictionaryPack(bookId, { chapterId: chapter.id });
      saveCachedReaderDictionaryPack(pack);
      summary.dictionaryCached = true;
      dictionary.cached = true;
      dictionary.chapterPacks.push({
        cached: true,
        chapterId: chapter.id,
        counts: pack.counts,
        failed: false,
        generatedAt: pack.generated_at,
        sourceCount: pack.source_count,
      });
    } catch {
      dictionary.chapterPacks.push({
        cached: false,
        chapterId: chapter.id,
        counts: emptyReaderDictionaryCounts(),
        failed: true,
        generatedAt: '',
        sourceCount: 0,
      });
    }
    emit(chapter.id);
  }

  if (client.listReaderDictionaries && client.downloadReaderDictionary) {
    try {
      const files = await client.listReaderDictionaries();
      for (const file of files) {
        try {
          dictionary.files.push(await cacheOfflineReaderDictionaryFile(bookId, file, client));
        } catch {
          dictionary.files.push({
            cached: false,
            failed: true,
            filename: file.filename,
            sizeBytes: 0,
            url: client.readerDictionaryDownloadUrl?.(file.filename) ?? fallbackReaderDictionaryDownloadUrl(file.filename),
          });
        }
      }
      emit();
    } catch {
      emit();
    }
  }

  const normalizedCoverUrl = coverUrl?.trim() ?? '';
  if (normalizedCoverUrl) {
    try {
      const coverSummary = await cacheAssets(
        bookId,
        0,
        `<img src="${normalizedCoverUrl}" alt="Book cover">`,
      );
      summary.assetsCached += coverSummary.cached;
      summary.assetsFailed += coverSummary.failed;
      summary.assetsTotal += coverSummary.total;
      cover = {
        cached: coverSummary.cached > 0 && coverSummary.failed === 0,
        failed: coverSummary.failed > 0,
        sizeBytes: coverSummary.sizeBytes,
        url: normalizedCoverUrl,
      };
      emit();
    } catch {
      summary.assetsFailed += 1;
      summary.assetsTotal += 1;
      cover = {
        cached: false,
        failed: true,
        sizeBytes: 0,
        url: normalizedCoverUrl,
      };
      emit();
    }
  }

  for (const chapter of targets) {
    try {
      const richContent = chapter.content_html_path
        ? await client.getChapterContent(bookId, chapter.id)
        : null;
      const translation = richContent?.text ?? await client.getChapterTranslation(bookId, chapter.id) ?? '';
      const html = richContent?.html ?? '';
      await putCachedChapterAsync({
        bookId,
        chapterId: chapter.id,
        html,
        sourceText: '',
        text: translation,
      });
      summary.chaptersCached += 1;
      manifestChapters.push({
        cached: true,
        failed: false,
        htmlCached: Boolean(html.trim()),
        id: chapter.id,
        textCached: Boolean(translation.trim()),
      });

      if (html.trim()) {
        const assetBase = readerOfflineAssetBase(chapter.content_html_path);
        const assetSummary = assetBase
          ? await cacheAssets(bookId, chapter.id, html, assetBase)
          : await cacheAssets(bookId, chapter.id, html);
        manifestAssets.push({
          ...assetSummary,
          chapterId: chapter.id,
        });
        summary.assetsCached += assetSummary.cached;
        summary.assetsFailed += assetSummary.failed;
        summary.assetsTotal += assetSummary.total;
      }

      const playlistAudio = audioPlaylistByChapterId.get(chapter.id);
      const audioUrl = playlistAudio?.stream_url || (chapter.audio_path ? client.chapterAudioUrl(bookId, chapter.id) : '');
      if (audioUrl) {
        summary.audioTotal += 1;
        const audioSummary = await cacheAudio(bookId, chapter.id, audioUrl);
        manifestAudio.push({
          ...audioSummary,
          chapterId: chapter.id,
        });
        if (audioSummary.cached) summary.audioCached += 1;
        if (audioSummary.failed) summary.audioFailed += 1;
      }
    } catch {
      summary.chaptersFailed += 1;
      manifestChapters.push({
        cached: false,
        failed: true,
        htmlCached: false,
        id: chapter.id,
        textCached: false,
      });
    }
    emit(chapter.id);
  }

  const manifestPayload = {
    assets: manifestAssets,
    audio: manifestAudio,
    bookId,
    chapterIds: targets.map((chapter) => chapter.id),
    chapters: manifestChapters,
    cover,
    dictionary,
    summary,
    version: READER_OFFLINE_MANIFEST_VERSION,
  };
  saveReaderOfflineManifest({
    ...manifestPayload,
    cachedAt: new Date().toISOString(),
    checksum: manifestChecksum(manifestPayload),
  });

  return summary;
}
