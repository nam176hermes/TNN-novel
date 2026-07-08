import type { Chapter, ReaderProgress } from '../api/types';

const STORAGE_KEY = 'novel-reader-progress-v1';
const SYNC_STORAGE_KEY = 'novel-reader-sync-v1';

export type ReaderProgressMode = 'scroll' | 'paginated';

export type ReaderProgressTextAnchor = {
  offset: number;
  prefix: string;
  suffix: string;
  text: string;
  version: 1;
};

export type ReaderProgressSnapshot = {
  chapterId: number;
  percent: number;
  position: number;
  totalChapters: number;
  anchor?: ReaderProgressTextAnchor;
  mode?: ReaderProgressMode;
  paragraphIndex?: number;
  charOffset?: number;
  absoluteCharOffset?: number;
  pageIndex?: number;
  updatedAt?: string;
};

export type ReaderProgressSnapshotOptions = {
  anchor?: ReaderProgressTextAnchor | null;
  mode?: ReaderProgressMode;
  percent?: number;
  paragraphIndex?: number;
  charOffset?: number;
  absoluteCharOffset?: number;
  pageIndex?: number;
  updatedAt?: string;
};

function getBrowserStorage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function clampPercent(position: number, totalChapters: number): number {
  if (!Number.isFinite(position) || !Number.isFinite(totalChapters) || totalChapters <= 0) return 0;
  return Math.min(100, Math.max(0, Math.round((position / totalChapters) * 100)));
}

function normalizePercent(value: unknown): number | undefined {
  if (typeof value !== 'number' || !Number.isFinite(value)) return undefined;
  return Math.min(100, Math.max(0, Math.round(value)));
}

function isReaderProgressMode(value: unknown): value is ReaderProgressMode {
  return value === 'scroll' || value === 'paginated';
}

function normalizeOptionalInteger(value: unknown): number | undefined {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 0) return undefined;
  return value;
}

function normalizeProgressTextAnchor(value: unknown): ReaderProgressTextAnchor | undefined {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined;
  const anchor = value as Partial<ReaderProgressTextAnchor>;
  const offset = normalizeOptionalInteger(anchor.offset);
  if (
    anchor.version !== 1
    || offset === undefined
    || typeof anchor.text !== 'string'
    || typeof anchor.prefix !== 'string'
    || typeof anchor.suffix !== 'string'
    || offset > anchor.text.length
  ) {
    return undefined;
  }
  return {
    offset,
    prefix: anchor.prefix.slice(0, 128),
    suffix: anchor.suffix.slice(0, 128),
    text: anchor.text.slice(0, 256),
    version: 1,
  };
}

function timestampMs(value: string | undefined): number | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function normalizeSnapshot(value: unknown): ReaderProgressSnapshot | null {
  if (Number.isInteger(value) && Number(value) > 0) {
    return {
      chapterId: Number(value),
      percent: 0,
      position: 0,
      totalChapters: 0,
    };
  }

  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const entry = value as Record<string, unknown>;
  const chapterId = Number(entry.chapterId);
  if (!Number.isInteger(chapterId) || chapterId <= 0) return null;

  const position = Number(entry.position);
  const totalChapters = Number(entry.totalChapters);
  const percent = normalizePercent(entry.percent);
  const snapshot: ReaderProgressSnapshot = {
    chapterId,
    percent: percent ?? clampPercent(position, totalChapters),
    position: Number.isFinite(position) && position > 0 ? position : 0,
    totalChapters: Number.isFinite(totalChapters) && totalChapters > 0 ? totalChapters : 0,
  };
  const mode = isReaderProgressMode(entry.mode) ? entry.mode : undefined;
  const anchor = normalizeProgressTextAnchor(entry.anchor);
  const paragraphIndex = normalizeOptionalInteger(entry.paragraphIndex);
  const charOffset = normalizeOptionalInteger(entry.charOffset);
  const absoluteCharOffset = normalizeOptionalInteger(entry.absoluteCharOffset);
  const pageIndex = normalizeOptionalInteger(entry.pageIndex);
  const updatedAt = typeof entry.updatedAt === 'string' ? entry.updatedAt : undefined;

  if (anchor) snapshot.anchor = anchor;
  if (mode) snapshot.mode = mode;
  if (paragraphIndex !== undefined) snapshot.paragraphIndex = paragraphIndex;
  if (charOffset !== undefined) snapshot.charOffset = charOffset;
  if (absoluteCharOffset !== undefined) snapshot.absoluteCharOffset = absoluteCharOffset;
  if (pageIndex !== undefined) snapshot.pageIndex = pageIndex;
  if (updatedAt) snapshot.updatedAt = updatedAt;
  return snapshot;
}

function readProgress(storage: Storage | null): Record<string, ReaderProgressSnapshot> {
  if (!storage) return {};
  try {
    const parsed = JSON.parse(storage.getItem(STORAGE_KEY) ?? '{}') as unknown;
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    return Object.fromEntries(
      Object.entries(parsed)
        .map(([key, value]) => [key, normalizeSnapshot(value)] as const)
        .filter((entry): entry is [string, ReaderProgressSnapshot] => entry[1] !== null),
    );
  } catch {
    return {};
  }
}

function readSyncStore(storage: Storage | null): Record<string, string> {
  if (!storage) return {};
  try {
    const parsed = JSON.parse(storage.getItem(SYNC_STORAGE_KEY) ?? '{}') as unknown;
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    return Object.fromEntries(
      Object.entries(parsed)
        .filter((entry): entry is [string, string] => (
          typeof entry[0] === 'string'
          && typeof entry[1] === 'string'
          && entry[1].trim().length > 0
        )),
    );
  } catch {
    return {};
  }
}

export function loadReaderProgress(bookId: number, storage: Storage | null = getBrowserStorage()): number | null {
  return loadReaderProgressSnapshot(bookId, storage)?.chapterId ?? null;
}

export function loadReaderProgressSnapshot(
  bookId: number,
  storage: Storage | null = getBrowserStorage(),
): ReaderProgressSnapshot | null {
  return readProgress(storage)[String(bookId)] ?? null;
}

export function loadReaderLastSyncAt(
  bookId: number,
  storage: Storage | null = getBrowserStorage(),
): string | null {
  if (!Number.isInteger(bookId) || bookId <= 0) return null;
  return readSyncStore(storage)[String(bookId)] ?? null;
}

export function saveReaderLastSyncAt(
  bookId: number,
  serverTime: string,
  storage: Storage | null = getBrowserStorage(),
): void {
  if (!storage || !Number.isInteger(bookId) || bookId <= 0 || !serverTime.trim()) return;
  try {
    storage.setItem(SYNC_STORAGE_KEY, JSON.stringify({
      ...readSyncStore(storage),
      [String(bookId)]: serverTime,
    }));
  } catch {
    // Sync remains best-effort when browser storage is unavailable.
  }
}

export function saveReaderProgress(
  bookId: number,
  chapterId: number,
  storage: Storage | null = getBrowserStorage(),
): void {
  if (!storage || !Number.isInteger(bookId) || !Number.isInteger(chapterId) || chapterId <= 0) return;
  const progress = readProgress(storage);
  const current = progress[String(bookId)];
  if (current?.chapterId === chapterId) {
    progress[String(bookId)] = current;
    try {
      storage.setItem(STORAGE_KEY, JSON.stringify(progress));
    } catch {
      // Ignore storage quota/private-mode failures; reading still works without persistence.
    }
    return;
  }
  progress[String(bookId)] = {
    chapterId,
    percent: 0,
    position: 0,
    totalChapters: 0,
    updatedAt: new Date().toISOString(),
  };
  try {
    storage.setItem(STORAGE_KEY, JSON.stringify(progress));
  } catch {
    // Ignore storage quota/private-mode failures; reading still works without persistence.
  }
}

export function saveReaderProgressSnapshot(
  bookId: number,
  chapterId: number,
  position: number,
  totalChapters: number,
  storage: Storage | null = getBrowserStorage(),
  options: ReaderProgressSnapshotOptions = {},
): void {
  if (!storage || !Number.isInteger(bookId) || !Number.isInteger(chapterId) || chapterId <= 0) return;
  const progress = readProgress(storage);
  const safePosition = Number.isFinite(position) && position > 0 ? Math.round(position) : 0;
  const safeTotal = Number.isFinite(totalChapters) && totalChapters > 0 ? Math.round(totalChapters) : 0;
  const nextSnapshot: ReaderProgressSnapshot = {
    chapterId,
    percent: normalizePercent(options.percent) ?? clampPercent(safePosition, safeTotal),
    position: safePosition,
    totalChapters: safeTotal,
  };
  const paragraphIndex = normalizeOptionalInteger(options.paragraphIndex);
  const charOffset = normalizeOptionalInteger(options.charOffset);
  const absoluteCharOffset = normalizeOptionalInteger(options.absoluteCharOffset);
  const pageIndex = normalizeOptionalInteger(options.pageIndex);
  const anchor = normalizeProgressTextAnchor(options.anchor);

  if (anchor) nextSnapshot.anchor = anchor;
  if (isReaderProgressMode(options.mode)) nextSnapshot.mode = options.mode;
  if (paragraphIndex !== undefined) nextSnapshot.paragraphIndex = paragraphIndex;
  if (charOffset !== undefined) nextSnapshot.charOffset = charOffset;
  if (absoluteCharOffset !== undefined) nextSnapshot.absoluteCharOffset = absoluteCharOffset;
  if (pageIndex !== undefined) nextSnapshot.pageIndex = pageIndex;
  nextSnapshot.updatedAt = typeof options.updatedAt === 'string' ? options.updatedAt : new Date().toISOString();

  progress[String(bookId)] = nextSnapshot;
  try {
    storage.setItem(STORAGE_KEY, JSON.stringify(progress));
  } catch {
    // Ignore storage quota/private-mode failures; reading still works without persistence.
  }
}

export function remoteReaderProgressToSnapshot(progress: ReaderProgress): ReaderProgressSnapshot {
  const position = Number.isFinite(progress.percent) ? Math.min(100, Math.max(0, Math.round(progress.percent))) : 0;
  const snapshot: ReaderProgressSnapshot = {
    chapterId: progress.chapter_id,
    percent: position,
    position,
    totalChapters: 100,
  };

  const mode = isReaderProgressMode(progress.mode) ? progress.mode : undefined;
  const paragraphIndex = normalizeOptionalInteger(progress.paragraph_index);
  const charOffset = normalizeOptionalInteger(progress.char_offset);
  const absoluteCharOffset = normalizeOptionalInteger(progress.absolute_char_offset);
  const pageIndex = normalizeOptionalInteger(progress.page_index);
  const anchor = normalizeProgressTextAnchor(progress.anchor);
  const hasLaterParagraphLocation = (paragraphIndex ?? 0) > 0 || (charOffset ?? 0) > 0;
  if (mode) snapshot.mode = mode;
  if (paragraphIndex !== undefined) snapshot.paragraphIndex = paragraphIndex;
  if (charOffset !== undefined) snapshot.charOffset = charOffset;
  if (absoluteCharOffset !== undefined && (absoluteCharOffset > 0 || !hasLaterParagraphLocation)) {
    snapshot.absoluteCharOffset = absoluteCharOffset;
  }
  if (pageIndex !== undefined) snapshot.pageIndex = pageIndex;
  if (anchor) snapshot.anchor = anchor;
  if (typeof progress.updated_at === 'string' && progress.updated_at) snapshot.updatedAt = progress.updated_at;
  return snapshot;
}

export function chooseLatestReaderProgressSnapshot(
  local: ReaderProgressSnapshot | null,
  remote: ReaderProgressSnapshot,
): ReaderProgressSnapshot {
  if (!local) return remote;

  const localTime = timestampMs(local.updatedAt);
  const remoteTime = timestampMs(remote.updatedAt);
  if (localTime !== null && remoteTime !== null) {
    return remoteTime >= localTime ? remote : local;
  }
  if (localTime !== null) return local;
  return remote;
}

export function resolveReaderChapterId(
  chapters: Chapter[],
  preferredChapterId?: number | null,
  bookId?: number | null,
  storage: Storage | null = getBrowserStorage(),
): number | null {
  const readableChapters = [...chapters]
    .filter((chapter) => chapter.has_translation)
    .sort((left, right) => {
      if (left.chapter_number !== right.chapter_number) return left.chapter_number - right.chapter_number;
      return left.id - right.id;
    });

  const readableIds = new Set(readableChapters.map((chapter) => chapter.id));
  if (preferredChapterId !== null && preferredChapterId !== undefined && readableIds.has(preferredChapterId)) {
    return preferredChapterId;
  }

  const savedChapterId = bookId === null || bookId === undefined ? null : loadReaderProgress(bookId, storage);
  if (savedChapterId !== null && readableIds.has(savedChapterId)) {
    return savedChapterId;
  }

  return readableChapters[0]?.id ?? chapters[0]?.id ?? null;
}
