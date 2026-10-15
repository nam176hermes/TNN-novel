import type { Chapter, TranslatedBookSummary } from '../../api/types';
import type { ReaderOfflineManifest } from '../../state/readerOfflineCache';
import coverDocTu from '../../assets/reference-ui/cover-doc-tu-clean.png';
import coverThanhSon from '../../assets/reference-ui/cover-thanh-son-clean.png';

export function normalizedContentKey(value: string): string {
  return value.replace(/[\W_]+/gu, '').toLowerCase();
}

export function normalizeReaderCoverName(value: string): string {
  return value
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .replace(/đ/g, 'd')
    .replace(/Đ/g, 'D')
    .toLowerCase();
}

export function fallbackReaderCover(book: TranslatedBookSummary | null | undefined): string {
  if (!book) return '';
  const normalized = normalizeReaderCoverName(`${book.title} ${book.author}`);
  if (normalized.includes('doc tu')) return coverDocTu;
  if (normalized.includes('thanh son')) return coverThanhSon;
  return '';
}

export function translationLooksTitleOnly(text: string, chapter: Chapter): boolean {
  const textKey = normalizedContentKey(text);
  if (!textKey || textKey.length > 120) return false;
  const title = chapter.title.trim();
  const candidates = [
    title,
    `Chương ${chapter.chapter_number} ${title}`,
    `Chuong ${chapter.chapter_number} ${title}`,
    `Chapter ${chapter.chapter_number} ${title}`,
    `Hồi ${chapter.chapter_number} ${title}`,
    `Hoi ${chapter.chapter_number} ${title}`,
  ];
  return candidates.some((candidate) => normalizedContentKey(candidate) === textKey);
}

export function sortChapters(chapters: Chapter[]): Chapter[] {
  return [...chapters].sort((left, right) => {
    if (left.chapter_number !== right.chapter_number) return left.chapter_number - right.chapter_number;
    return left.id - right.id;
  });
}

export function formatCount(value: number): string {
  return Math.max(0, value).toLocaleString('vi-VN');
}

export function formatWordCount(value: number): string {
  return `${formatCount(value)} từ`;
}

export function formatWordsRemaining(value: number): string {
  return `${formatCount(value)} từ còn lại`;
}

export function formatReadingTime(minutes: number): string {
  return `${formatCount(minutes)} phút đọc`;
}

export function formatReadingTimeRemaining(minutes: number): string {
  return `${formatCount(minutes)} phút còn lại`;
}

export function formatDictionarySize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B';
  if (bytes < 1024) return `${Math.round(bytes)} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(bytes >= 10 * 1024 * 1024 ? 0 : 1)} MB`;
}

export function offlineManifestCoverageLabel(manifest: ReaderOfflineManifest): string {
  const chapterTotal = manifest.chapters.length || manifest.chapterIds.length;
  const cachedChapters = manifest.chapters.filter((chapter) => chapter.cached && !chapter.failed).length;
  const failedChapters = manifest.chapters.filter((chapter) => chapter.failed).length
    || manifest.summary.chaptersFailed;
  return `Đã tải ${formatCount(cachedChapters)}/${formatCount(chapterTotal)} chương · ${formatCount(failedChapters)} lỗi`;
}

export function offlineManifestResourcesLabel(manifest: ReaderOfflineManifest): string {
  return [
    `Tài nguyên ${formatCount(manifest.summary.assetsCached)}/${formatCount(manifest.summary.assetsTotal)} ảnh`,
    `${formatCount(manifest.summary.audioCached)}/${formatCount(manifest.summary.audioTotal)} audio`,
    `${formatCount(manifest.dictionary.sourceCount)} mục từ điển`,
  ].join(' · ');
}

