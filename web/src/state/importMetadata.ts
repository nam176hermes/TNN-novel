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

export type DetectedImportMetadata = {
  title: string;
  chapterNumber: number | null;
  chapterTitle: string;
};

export function cleanBookTitle(title: string): string {
  return title
    .trim()
    .replace(/\.[A-Za-z0-9]{1,8}$/, '')
    .replace(/\[(?:raw|txt|source|cn|zh)\]/gi, '')
    .replace(/\((?:raw|txt|source|cn|zh)\)/gi, '')
    .replace(/^[《》「」『』\[\]\(\)（）\s]+|[《》「」『』\[\]\(\)（）\s]+$/g, '')
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

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

function detectChapterFromLine(line: string): Pick<DetectedImportMetadata, 'chapterNumber' | 'chapterTitle'> {
  const patterns = [
    /^\s*第\s*([0-9]+|[零〇一二两三四五六七八九十百千万]+)\s*[章节回卷]\s*(.*)$/,
    /^\s*Ch(?:apter)?\.?\s*([0-9]+)\s*[:：.\-\s]*(.*)$/i,
    /^\s*Chương\s*([0-9]+)\s*[:：.\-\s]*(.*)$/i,
  ];

  for (const pattern of patterns) {
    const match = line.match(pattern);
    if (!match) continue;
    return {
      chapterNumber: parseChineseNumber(match[1]),
      chapterTitle: match[2]?.trim() ?? '',
    };
  }

  return { chapterNumber: null, chapterTitle: '' };
}

export function detectImportMetadata({
  title = '',
  chapterNumber = null,
  chapterTitle = '',
  text = '',
  filename = '',
}: {
  title?: string;
  chapterNumber?: number | null;
  chapterTitle?: string;
  text?: string;
  filename?: string;
}): DetectedImportMetadata {
  let detectedTitle = cleanBookTitle(title);
  let detectedChapterNumber = chapterNumber && chapterNumber > 0 ? chapterNumber : null;
  let detectedChapterTitle = chapterTitle.trim();

  if (filename) {
    const stem = filename.replace(/\.[A-Za-z0-9]{1,8}$/, '');
    const match = stem.match(
      /^\s*(.+?)\s*[-_]\s*(?:Chương|Chapter|Ch\.?|第)\s*([0-9]+|[零〇一二两三四五六七八九十百千万]+)\s*[-_：:\s]*(.*)$/i,
    );
    if (match) {
      detectedTitle ||= cleanBookTitle(match[1]);
      detectedChapterNumber = parseChineseNumber(match[2]) ?? detectedChapterNumber;
      detectedChapterTitle ||= match[3]?.trim() ?? '';
    }
  }

  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);

  for (const line of lines.slice(0, 5)) {
    if (!detectedTitle) {
      const titleMatch = line.match(/^《(.+?)》$/);
      if (titleMatch) {
        detectedTitle = cleanBookTitle(titleMatch[1]);
        continue;
      }
    }

    const chapter = detectChapterFromLine(line);
    if (chapter.chapterNumber !== null) {
      detectedChapterNumber = chapter.chapterNumber;
      detectedChapterTitle ||= chapter.chapterTitle;
      break;
    }
  }

  return {
    title: detectedTitle,
    chapterNumber: detectedChapterNumber,
    chapterTitle: detectedChapterTitle,
  };
}
