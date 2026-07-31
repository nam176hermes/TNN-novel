export const READER_RESUME_STORAGE_KEY = 'novel-reader-resume-v1';
const READER_RESUME_VERSION = 1;
const MAX_READER_RESUME_LABEL_LENGTH = 500;

export type ReaderResumeState = {
  bookId: number;
  bookTitle: string;
  chapterId: number;
  chapterNumber: number;
  chapterTitle: string;
  contentRevision: string;
  version: 1;
};

export type ReaderResumeInput = Omit<ReaderResumeState, 'version'>;

function browserStorage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function boundedLabel(value: string): string {
  return value.trim().slice(0, MAX_READER_RESUME_LABEL_LENGTH);
}

function normalizeReaderResume(value: unknown): ReaderResumeState | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const candidate = value as Partial<ReaderResumeState>;
  if (
    candidate.version !== READER_RESUME_VERSION
    || !Number.isInteger(candidate.bookId)
    || Number(candidate.bookId) <= 0
    || !Number.isInteger(candidate.chapterId)
    || Number(candidate.chapterId) <= 0
    || !Number.isInteger(candidate.chapterNumber)
    || Number(candidate.chapterNumber) < 0
    || typeof candidate.bookTitle !== 'string'
    || typeof candidate.chapterTitle !== 'string'
    || typeof candidate.contentRevision !== 'string'
  ) return null;

  return {
    bookId: Number(candidate.bookId),
    bookTitle: boundedLabel(candidate.bookTitle),
    chapterId: Number(candidate.chapterId),
    chapterNumber: Number(candidate.chapterNumber),
    chapterTitle: boundedLabel(candidate.chapterTitle),
    contentRevision: boundedLabel(candidate.contentRevision),
    version: READER_RESUME_VERSION,
  };
}

export function loadReaderResume(storage: Storage | null = browserStorage()): ReaderResumeState | null {
  if (!storage) return null;
  try {
    return normalizeReaderResume(JSON.parse(storage.getItem(READER_RESUME_STORAGE_KEY) ?? 'null'));
  } catch {
    return null;
  }
}

export function saveReaderResume(
  input: ReaderResumeInput,
  storage: Storage | null = browserStorage(),
): ReaderResumeState | null {
  if (!storage) return null;
  const normalized = normalizeReaderResume({ ...input, version: READER_RESUME_VERSION });
  if (!normalized) return null;
  try {
    storage.setItem(READER_RESUME_STORAGE_KEY, JSON.stringify(normalized));
    return normalized;
  } catch {
    return null;
  }
}

export function clearReaderResume(storage: Storage | null = browserStorage()): void {
  try {
    storage?.removeItem(READER_RESUME_STORAGE_KEY);
  } catch {
    // Resume metadata is optional and must not block logout.
  }
}
