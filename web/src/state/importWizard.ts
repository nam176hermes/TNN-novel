const chineseDigits: Record<string, number> = {
  零: 0,
  '〇': 0,
  一: 1,
  二: 2,
  两: 2,
  三: 3,
  四: 4,
  五: 5,
  六: 6,
  七: 7,
  八: 8,
  九: 9,
};

const chineseUnits: Record<string, number> = {
  十: 10,
  百: 100,
  千: 1000,
  万: 10000,
};

const CJK_PATTERN = /[\u3400-\u4dbf\u4e00-\u9fff]/g;
const VIETNAMESE_PATTERN = /[ăâđêôơưáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ]/i;

export type ImportContentKind = 'raw' | 'translated' | 'both' | 'unknown';
export type ImportSourceKind = 'paste' | 'txt' | 'epub' | 'url' | 'catalog';

export type DetectedImportChapter = {
  chapterNumber: number;
  title: string;
  text: string;
  startLine: number;
  endLine: number;
  startChar: number;
  endChar: number;
  detection: 'heading' | 'fallback';
};

export type ImportPreviewWarning = {
  type:
    | 'duplicate_chapter'
    | 'duplicate_lines'
    | 'language_mismatch'
    | 'too_short'
    | 'long_single_chapter'
    | 'unknown_language';
  message: string;
};

export type ImportPreviewSummary = {
  chapterCount: number;
  characterCount: number;
  duplicateChapterNumbers: number[];
  firstTitle: string;
  lastTitle: string;
  contentKind: ImportContentKind;
  chapters: DetectedImportChapter[];
  warnings: ImportPreviewWarning[];
};

export type ExistingChapterLike = {
  chapter_number?: number | null;
  title?: string | null;
};

function parseChineseNumber(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  if (/^\d+$/.test(trimmed)) return Number.parseInt(trimmed, 10);
  if (trimmed in chineseDigits) return chineseDigits[trimmed];

  let total = 0;
  let section = 0;
  let number = 0;
  let sawNumeric = false;

  for (const char of trimmed) {
    if (char in chineseDigits) {
      number = chineseDigits[char];
      sawNumeric = true;
      continue;
    }
    const unit = chineseUnits[char];
    if (!unit) return null;
    sawNumeric = true;
    if (unit === 10000) {
      section = section + number || 1;
      total += section * unit;
      section = 0;
    } else {
      section += (number || 1) * unit;
    }
    number = 0;
  }

  const parsed = total + section + number;
  return sawNumeric && parsed > 0 ? parsed : null;
}

function detectHeading(line: string): { chapterNumber: number; title: string } | null {
  const patterns = [
    /^\s*第\s*([0-9]+|[零〇一二两三四五六七八九十百千万]+)\s*[章节回卷]\s*[:：.\-\s]*(.*)$/,
    /^\s*(?:Ch(?:apter)?\.?|Chương)\s*([0-9]+)\s*[:：.\-\s]*(.*)$/i,
    /^\s*([0-9]+)\s*[.、]\s+(.{1,80})$/,
  ];

  for (const pattern of patterns) {
    const match = line.match(pattern);
    if (!match) continue;
    const chapterNumber = parseChineseNumber(match[1]);
    if (!chapterNumber) continue;
    return {
      chapterNumber,
      title: (match[2] || `Chương ${chapterNumber}`).trim(),
    };
  }

  return null;
}

function lineOffsets(text: string, lines: string[]): number[] {
  const offsets: number[] = [];
  let cursor = 0;
  for (const line of lines) {
    offsets.push(cursor);
    cursor += line.length + 1;
  }
  return offsets;
}

export function cleanImportedText(text: string): string {
  const lines = text
    .replace(/\r\n?/g, '\n')
    .split('\n')
    .map((line) => line.trimEnd());
  const filtered = lines.filter((line) => {
    const normalized = line.trim().toLowerCase();
    if (!normalized) return true;
    return !(
      /^nguồn\s*:/i.test(line)
      || /^source\s*:/i.test(line)
      || /đọc truyện tại/i.test(line)
      || /truyện được đăng tại/i.test(line)
      || /69shu|69shuba|qidian|biquge|uukanshu|novel543/i.test(line)
    );
  });

  return filtered
    .join('\n')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

export function detectImportChapters(text: string): DetectedImportChapter[] {
  const normalized = cleanImportedText(text);
  const lines = normalized.split('\n');
  const offsets = lineOffsets(normalized, lines);
  const headings = lines
    .map((line, index) => ({ heading: detectHeading(line), index }))
    .filter((item): item is { heading: { chapterNumber: number; title: string }; index: number } => Boolean(item.heading));

  if (headings.length === 0) {
    return [{
      chapterNumber: 1,
      title: 'Toàn bộ nội dung',
      text: normalized,
      startLine: 0,
      endLine: Math.max(0, lines.length - 1),
      startChar: 0,
      endChar: normalized.length,
      detection: 'fallback',
    }];
  }

  return headings.map((item, index) => {
    const next = headings[index + 1];
    const startLine = item.index;
    const endLine = next ? Math.max(item.index, next.index - 1) : Math.max(item.index, lines.length - 1);
    const startChar = offsets[startLine] ?? 0;
    const endChar = next ? Math.max(startChar, (offsets[next.index] ?? normalized.length) - 1) : normalized.length;
    return {
      chapterNumber: item.heading.chapterNumber,
      title: item.heading.title || `Chương ${item.heading.chapterNumber}`,
      text: normalized.slice(startChar, endChar).trim(),
      startLine,
      endLine,
      startChar,
      endChar,
      detection: 'heading',
    };
  });
}

export function detectImportContentKind(text: string): ImportContentKind {
  const trimmed = cleanImportedText(text);
  const cjkCount = trimmed.match(CJK_PATTERN)?.length ?? 0;
  const latinLetters = trimmed.match(/[A-Za-zÀ-ỹ]/g)?.length ?? 0;
  const hasVietnamese = VIETNAMESE_PATTERN.test(trimmed) || /\b(bản dịch|chương|trời|người|hắn|nàng)\b/i.test(trimmed);
  const meaningfulChars = cjkCount + latinLetters;

  if (meaningfulChars < 4) return 'unknown';
  if (cjkCount > 0 && hasVietnamese && latinLetters > 8) return 'both';
  if (cjkCount >= Math.max(4, latinLetters * 0.35)) return 'raw';
  if (hasVietnamese || latinLetters > 20) return 'translated';
  return 'unknown';
}

function duplicateLineRatio(text: string): number {
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 8);
  if (lines.length < 4) return 0;
  const unique = new Set(lines);
  return 1 - unique.size / lines.length;
}

export function buildImportPreview({
  text,
  selectedKind,
  existingChapters = [],
}: {
  text: string;
  selectedKind: ImportContentKind;
  existingChapters?: ExistingChapterLike[];
}): ImportPreviewSummary {
  const cleaned = cleanImportedText(text);
  const chapters = detectImportChapters(cleaned);
  const contentKind = detectImportContentKind(cleaned);
  const existingNumbers = new Set(
    existingChapters
      .map((chapter) => Number(chapter.chapter_number ?? 0))
      .filter((value) => Number.isFinite(value) && value > 0),
  );
  const seenNumbers = new Set<number>();
  const duplicateChapterNumbers = [...new Set(
    chapters
      .map((chapter) => chapter.chapterNumber)
      .filter((chapterNumber) => {
        if (seenNumbers.has(chapterNumber) || existingNumbers.has(chapterNumber)) return true;
        seenNumbers.add(chapterNumber);
        return false;
      }),
  )];
  const warnings: ImportPreviewWarning[] = [];

  if (duplicateChapterNumbers.length > 0) {
    warnings.push({
      type: 'duplicate_chapter',
      message: `Có ${duplicateChapterNumbers.length.toLocaleString('vi-VN')} số chương trùng. Chọn bỏ qua hoặc xác nhận ghi đè trước khi lưu.`,
    });
  }

  if (cleaned.length < 80) {
    warnings.push({
      type: 'too_short',
      message: 'Nội dung có vẻ quá ngắn. Hãy kiểm tra trước khi lưu.',
    });
  }

  if (chapters.length === 1 && cleaned.length > 80_000) {
    warnings.push({
      type: 'long_single_chapter',
      message: 'Một chương đơn rất dài. Nếu đây là nhiều chương, hãy kiểm tra lại heading trước khi import.',
    });
  }

  if (duplicateLineRatio(cleaned) > 0.35) {
    warnings.push({
      type: 'duplicate_lines',
      message: 'Nội dung có nhiều dòng lặp lại, có thể còn watermark/quảng cáo.',
    });
  }

  if (contentKind === 'unknown') {
    warnings.push({
      type: 'unknown_language',
      message: 'Chưa xác định được raw Trung hay bản dịch Việt.',
    });
  } else if (selectedKind !== 'unknown' && selectedKind !== 'both' && contentKind !== selectedKind) {
    warnings.push({
      type: 'language_mismatch',
      message: 'Ngôn ngữ phát hiện không khớp lựa chọn nội dung.',
    });
  }

  return {
    chapterCount: chapters.length,
    characterCount: cleaned.length,
    duplicateChapterNumbers,
    firstTitle: chapters[0]?.title ?? '',
    lastTitle: chapters[chapters.length - 1]?.title ?? '',
    contentKind,
    chapters,
    warnings,
  };
}
