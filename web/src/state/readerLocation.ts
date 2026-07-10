export type ReaderParagraph = {
  index: number;
  paragraph: string;
};

export type ParagraphLocation = {
  paragraphIndex: number;
  charOffset: number;
  absoluteCharOffset: number;
};

export type ReaderTextLocation = {
  absoluteCharOffset: number;
  charOffset: number;
  paragraphIndex: number;
};

export type ReaderParagraphMeasurement = {
  bottom: number;
  canSplit?: boolean;
  charLength?: number;
  index: number;
  pageBreakAfter?: boolean;
  pageBreakBefore?: boolean;
  pageBreakOffsets?: number[];
  preferStandalone?: boolean;
  top: number;
};

export type ReaderViewportPage = {
  endIndex: number;
  endChar?: number;
  startChar?: number;
  startIndex: number;
};

export type ReaderFallbackPageHint = {
  pageBreakAfter?: boolean;
  pageBreakBefore?: boolean;
  preferStandalone?: boolean;
};

export type ReaderChapterReadingStats = {
  estimatedMinutes: number;
  estimatedMinutesRemaining: number;
  remainingWords: number;
  totalWords: number;
};

function clampInteger(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min;
  return Math.min(max, Math.max(min, Math.round(value)));
}

function clampPercent(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.min(100, Math.max(0, value));
}

function isCjkCharacter(value: string): boolean {
  return /[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]/u.test(value);
}

export function countWords(text: string): number {
  if (!text.trim()) return 0;
  const cjkCount = Array.from(text).filter(isCjkCharacter).length;
  const nonCjkText = text.replace(/[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]/gu, ' ');
  const tokenCount = nonCjkText
    .trim()
    .split(/[^\p{L}\p{N}]+/u)
    .filter(Boolean)
    .length;
  return cjkCount + tokenCount;
}

export function estimateReadingMinutes(wordCount: number, wordsPerMinute = 320): number {
  if (!Number.isFinite(wordCount) || wordCount <= 0) return 0;
  if (!Number.isFinite(wordsPerMinute) || wordsPerMinute <= 0) return 0;
  return Math.max(1, Math.ceil(wordCount / wordsPerMinute));
}

export function wordsRemainingForProgress(wordCount: number, progressPercent: number): number {
  if (!Number.isFinite(wordCount) || wordCount <= 0) return 0;
  const remainingRatio = (100 - clampPercent(progressPercent)) / 100;
  return Math.max(0, Math.ceil(wordCount * remainingRatio));
}

export function readingStatsForText(
  text: string,
  progressPercent: number,
  wordsPerMinute = 320,
): ReaderChapterReadingStats {
  const totalWords = countWords(text);
  const remainingWords = wordsRemainingForProgress(totalWords, progressPercent);
  return {
    estimatedMinutes: estimateReadingMinutes(totalWords, wordsPerMinute),
    estimatedMinutesRemaining: estimateReadingMinutes(remainingWords, wordsPerMinute),
    remainingWords,
    totalWords,
  };
}

export function pageForParagraph(paragraphIndex: number, paragraphsPerPage: number): number {
  if (!Number.isFinite(paragraphIndex) || !Number.isFinite(paragraphsPerPage) || paragraphsPerPage <= 0) return 0;
  return Math.max(0, Math.floor(Math.max(0, paragraphIndex) / paragraphsPerPage));
}

export function fallbackParagraphPages(
  paragraphCount: number,
  paragraphsPerPage: number,
  hints: ReaderFallbackPageHint[] = [],
): ReaderViewportPage[] {
  if (!Number.isFinite(paragraphCount) || paragraphCount <= 0) return [{ startIndex: 0, endIndex: 0 }];
  const safeParagraphsPerPage = clampInteger(paragraphsPerPage, 1, Math.max(1, paragraphCount));
  const pages: ReaderViewportPage[] = [];

  function pushPage(startIndex: number, endIndex: number): void {
    if (endIndex <= startIndex) return;
    const previousPage = pages[pages.length - 1];
    if (previousPage?.startIndex === startIndex && previousPage.endIndex === endIndex) return;
    pages.push({ startIndex, endIndex });
  }

  let pageStartIndex = 0;
  for (let index = 0; index < paragraphCount; index += 1) {
    const hint = hints[index] ?? {};

    if (hint.pageBreakBefore && index > pageStartIndex) {
      pushPage(pageStartIndex, index);
      pageStartIndex = index;
    }

    if (hint.preferStandalone) {
      if (index > pageStartIndex) {
        pushPage(pageStartIndex, index);
      }
      pushPage(index, index + 1);
      pageStartIndex = index + 1;
      continue;
    }

    const pageSize = index - pageStartIndex + 1;
    if (pageSize >= safeParagraphsPerPage || hint.pageBreakAfter) {
      pushPage(pageStartIndex, index + 1);
      pageStartIndex = index + 1;
    }
  }

  if (pageStartIndex < paragraphCount) {
    pushPage(pageStartIndex, paragraphCount);
  }

  return pages;
}

export function pageIndexForParagraph(
  paragraphIndex: number | undefined,
  pages: ReaderViewportPage[],
  fallbackPageIndex?: number,
  charOffset?: number,
): number {
  const hasFallbackPageIndex = typeof fallbackPageIndex === 'number' && Number.isInteger(fallbackPageIndex);
  const safeFallbackPageIndex = hasFallbackPageIndex ? Math.max(0, fallbackPageIndex) : 0;
  const safeParagraphIndex = typeof paragraphIndex === 'number' && Number.isInteger(paragraphIndex)
    ? paragraphIndex
    : -1;
  if (safeParagraphIndex < 0 || pages.length === 0) {
    return safeFallbackPageIndex;
  }
  const safeCharOffset = typeof charOffset === 'number' && Number.isFinite(charOffset)
    ? Math.max(0, Math.round(charOffset))
    : null;
  const matchingPages = pages
    .map((page, index) => ({ page, index }))
    .filter(({ page }) => safeParagraphIndex >= page.startIndex && safeParagraphIndex < page.endIndex);

  if (safeCharOffset !== null && matchingPages.length > 0) {
    if (hasFallbackPageIndex) {
      const fallbackPage = matchingPages.find(({ page, index }) => {
        if (index !== safeFallbackPageIndex) return false;
        const startChar = page.startChar ?? 0;
        const endChar = page.endChar ?? Number.POSITIVE_INFINITY;
        return safeCharOffset >= startChar && safeCharOffset <= endChar;
      });
      if (fallbackPage) return fallbackPage.index;
    }

    const rangedPage = matchingPages.find(({ page }, index) => {
      const startChar = page.startChar ?? 0;
      const endChar = page.endChar ?? Number.POSITIVE_INFINITY;
      const isLastMatchingPage = index === matchingPages.length - 1;
      return safeCharOffset >= startChar && (safeCharOffset < endChar || (isLastMatchingPage && safeCharOffset === endChar));
    });
    if (rangedPage) return rangedPage.index;
  }

  const index = pages.findIndex((page) => (
    safeParagraphIndex >= page.startIndex && safeParagraphIndex < page.endIndex
  ));
  return index >= 0 ? index : safeFallbackPageIndex;
}

export function paginateParagraphsByViewport(
  measurements: ReaderParagraphMeasurement[],
  viewportHeight: number,
): ReaderViewportPage[] {
  const orderedMeasurements = measurements
    .filter((item) => (
      Number.isInteger(item.index)
      && item.index >= 0
      && Number.isFinite(item.top)
      && Number.isFinite(item.bottom)
      && item.bottom >= item.top
    ))
    .sort((left, right) => left.index - right.index);

  if (orderedMeasurements.length === 0 || !Number.isFinite(viewportHeight) || viewportHeight <= 0) {
    return [];
  }

  const pages: ReaderViewportPage[] = [];
  const safeViewportHeight = Math.max(160, viewportHeight);
  let pageStartIndex: number | null = null;
  let pageTop = 0;
  let previousIndex: number | null = null;

  function pushPage(startIndex: number | null, endIndex: number | null): void {
    if (startIndex === null || endIndex === null || endIndex < startIndex) return;
    const page = { startIndex, endIndex: endIndex + 1 };
    const previousPage = pages[pages.length - 1];
    if (previousPage?.startIndex === page.startIndex && previousPage.endIndex === page.endIndex) return;
    pages.push(page);
  }

  function pushCharPage(index: number, startChar: number, endChar: number): void {
    if (endChar <= startChar) return;
    pages.push({
      endChar,
      endIndex: index + 1,
      startChar,
      startIndex: index,
    });
  }

  function normalizedPageBreakOffsets(offsets: number[] | undefined, charLength: number): number[] {
    if (!offsets || offsets.length === 0) return [];
    const unique = new Set<number>();
    for (const offset of offsets) {
      const safeOffset = clampInteger(offset, 0, charLength);
      if (safeOffset > 0 && safeOffset < charLength) {
        unique.add(safeOffset);
      }
    }
    return [...unique].sort((left, right) => left - right);
  }

  for (const measurement of orderedMeasurements) {
    if (pageStartIndex === null) {
      pageStartIndex = measurement.index;
      pageTop = measurement.top;
    }

    if (measurement.pageBreakBefore && previousIndex !== null && measurement.index > pageStartIndex) {
      pushPage(pageStartIndex, previousIndex);
      pageStartIndex = measurement.index;
      pageTop = measurement.top;
      previousIndex = null;
    }

    const blockHeight = measurement.bottom - measurement.top;
    const charLength = Math.max(0, Math.round(measurement.charLength ?? 0));
    const canSplit = measurement.canSplit !== false;
    if (blockHeight > safeViewportHeight && charLength > 0 && canSplit) {
      if (previousIndex !== null && measurement.index > pageStartIndex) {
        pushPage(pageStartIndex, previousIndex);
      }
      const measuredBreaks = normalizedPageBreakOffsets(measurement.pageBreakOffsets, charLength);
      if (measuredBreaks.length > 0) {
        let startChar = 0;
        for (const endChar of [...measuredBreaks, charLength]) {
          pushCharPage(measurement.index, startChar, endChar);
          startChar = endChar;
        }
      } else {
        const pageCount = Math.max(1, Math.ceil(blockHeight / safeViewportHeight));
        const charsPerPage = Math.max(1, Math.ceil(charLength / pageCount));
        for (let startChar = 0; startChar < charLength; startChar += charsPerPage) {
          pushCharPage(measurement.index, startChar, Math.min(charLength, startChar + charsPerPage));
        }
      }
      pageStartIndex = null;
      previousIndex = null;
      continue;
    }

    if (measurement.preferStandalone) {
      if (previousIndex !== null && measurement.index > pageStartIndex) {
        pushPage(pageStartIndex, previousIndex);
      }
      pushPage(measurement.index, measurement.index);
      pageStartIndex = null;
      previousIndex = null;
      continue;
    }

    const wouldOverflow = measurement.bottom - pageTop > safeViewportHeight;
    if (wouldOverflow && measurement.index > pageStartIndex && previousIndex !== null) {
      pushPage(pageStartIndex, previousIndex);
      pageStartIndex = measurement.index;
      pageTop = measurement.top;
    }
    previousIndex = measurement.index;

    if (measurement.pageBreakAfter) {
      pushPage(pageStartIndex, previousIndex);
      pageStartIndex = null;
      previousIndex = null;
    }
  }

  pushPage(pageStartIndex, previousIndex);

  return pages;
}

export function paragraphLocation(
  paragraphs: ReaderParagraph[],
  absoluteCharOffset: number,
): ParagraphLocation | null {
  if (paragraphs.length === 0) return null;

  const lastParagraph = paragraphs[paragraphs.length - 1];
  const totalLength = paragraphs.reduce(
    (total, item, index) => total + item.paragraph.length + (index === paragraphs.length - 1 ? 0 : 2),
    0,
  );
  const safeOffset = clampInteger(absoluteCharOffset, 0, Math.max(0, totalLength));
  let cursor = 0;

  for (let index = 0; index < paragraphs.length; index += 1) {
    const item = paragraphs[index];
    const paragraphEnd = cursor + item.paragraph.length;
    if (safeOffset <= paragraphEnd) {
      return {
        paragraphIndex: item.index,
        charOffset: safeOffset - cursor,
        absoluteCharOffset: safeOffset,
      };
    }
    const nextParagraph = paragraphs[index + 1];
    const nextParagraphStart = paragraphEnd + 2;
    if (nextParagraph && safeOffset < nextParagraphStart) {
      return {
        paragraphIndex: nextParagraph.index,
        charOffset: 0,
        absoluteCharOffset: nextParagraphStart,
      };
    }
    cursor = paragraphEnd + 2;
  }

  return {
    paragraphIndex: lastParagraph.index,
    charOffset: lastParagraph.paragraph.length,
    absoluteCharOffset: safeOffset,
  };
}

export function absoluteCharOffsetForParagraph(
  paragraphs: string[],
  paragraphIndex: number | undefined,
  charOffset: number | undefined,
): number {
  if (paragraphIndex === undefined || paragraphIndex < 0 || paragraphs.length === 0) return 0;
  const safeParagraphIndex = Math.min(paragraphs.length - 1, Math.max(0, paragraphIndex));
  let absoluteOffset = 0;
  for (let index = 0; index < safeParagraphIndex; index += 1) {
    absoluteOffset += (paragraphs[index] ?? '').length + 2;
  }
  const paragraph = paragraphs[safeParagraphIndex] ?? '';
  return absoluteOffset + Math.min(paragraph.length, Math.max(0, charOffset ?? 0));
}

function isAriaHiddenElement(node: Node): boolean {
  return node.nodeType === Node.ELEMENT_NODE
    && (node as Element).getAttribute('aria-hidden')?.toLowerCase() === 'true';
}

function isCssHiddenElement(node: Node): boolean {
  if (node.nodeType !== Node.ELEMENT_NODE) return false;
  const element = node as HTMLElement;
  const inlineStyle = element.style;
  if (
    element.hasAttribute('hidden')
    || inlineStyle.display.toLowerCase() === 'none'
    || inlineStyle.visibility.toLowerCase() === 'hidden'
    || inlineStyle.visibility.toLowerCase() === 'collapse'
  ) {
    return true;
  }

  const ownerWindow = element.ownerDocument?.defaultView;
  if (!ownerWindow || typeof ownerWindow.getComputedStyle !== 'function') return false;
  try {
    const computed = ownerWindow.getComputedStyle(element);
    return computed.display.toLowerCase() === 'none'
      || computed.visibility.toLowerCase() === 'hidden'
      || computed.visibility.toLowerCase() === 'collapse';
  } catch {
    return false;
  }
}

function isRubyAnnotationElement(node: Node): boolean {
  return node.nodeType === Node.ELEMENT_NODE
    && (node as Element).matches('rt,rp');
}

function isLineBreakElement(node: Node): boolean {
  return node.nodeType === Node.ELEMENT_NODE
    && (node as Element).matches('br');
}

function hasAriaHiddenAncestor(node: Node, root: Node): boolean {
  let current: Node | null = node.nodeType === Node.ELEMENT_NODE ? node : node.parentNode;
  while (current) {
    if (current !== root && isAriaHiddenElement(current)) return true;
    if (current === root) return false;
    current = current.parentNode;
  }
  return false;
}

function hasRubyAnnotationAncestor(node: Node, root: Node): boolean {
  let current: Node | null = node.nodeType === Node.ELEMENT_NODE ? node : node.parentNode;
  while (current) {
    if (current !== root && isRubyAnnotationElement(current)) return true;
    if (current === root) return false;
    current = current.parentNode;
  }
  return false;
}

function hasCssHiddenAncestor(node: Node, root: Node): boolean {
  let current: Node | null = node.nodeType === Node.ELEMENT_NODE ? node : node.parentNode;
  while (current) {
    if (current !== root && isCssHiddenElement(current)) return true;
    if (current === root) return false;
    current = current.parentNode;
  }
  return false;
}

function textLengthInReadableModel(node: Node, includeAriaHidden: boolean): number {
  if (node.nodeType === Node.TEXT_NODE) return node.textContent?.length ?? 0;
  if (isCssHiddenElement(node)) return 0;
  if (isRubyAnnotationElement(node)) return 0;
  if (!includeAriaHidden && isAriaHiddenElement(node)) return 0;
  if (isLineBreakElement(node)) return 1;
  return Array.from(node.childNodes).reduce(
    (total, child) => total + textLengthInReadableModel(child, includeAriaHidden),
    0,
  );
}

function readableModelIncludesAriaHidden(root: Node): boolean {
  return textLengthInReadableModel(root, false) <= 0;
}

export function textLength(node: Node): number {
  return textLengthInReadableModel(node, readableModelIncludesAriaHidden(node));
}

type ReadableTextToken = {
  kind: 'separator';
  length: number;
} | {
  kind: 'text';
  length: number;
  node: Text;
};

function readableTextTokens(node: Node, includeAriaHidden: boolean): ReadableTextToken[] {
  if (node.nodeType === Node.TEXT_NODE) {
    return [{ kind: 'text', length: node.textContent?.length ?? 0, node: node as Text }];
  }
  if (isCssHiddenElement(node) || isRubyAnnotationElement(node) || (!includeAriaHidden && isAriaHiddenElement(node))) {
    return [];
  }
  if (isLineBreakElement(node)) {
    return [{ kind: 'separator', length: 1 }];
  }
  return Array.from(node.childNodes).flatMap((child) => readableTextTokens(child, includeAriaHidden));
}

export function textNodeAtOffset(root: Node, charOffset: number): { node: Text; offset: number } | null {
  const includeAriaHidden = readableModelIncludesAriaHidden(root);
  const tokens = readableTextTokens(root, includeAriaHidden);
  let cursor = 0;
  let lastTextNode: Text | null = null;
  let pendingSeparatorOffset = false;
  for (const token of tokens) {
    if (token.kind === 'separator') {
      if (charOffset <= cursor + token.length) {
        pendingSeparatorOffset = true;
      }
      cursor += token.length;
      continue;
    }
    lastTextNode = token.node;
    if (pendingSeparatorOffset && charOffset <= cursor) {
      return { node: token.node, offset: 0 };
    }
    pendingSeparatorOffset = false;
    if (charOffset <= cursor + token.length) {
      return {
        node: token.node,
        offset: Math.min(token.length, Math.max(0, charOffset - cursor)),
      };
    }
    cursor += token.length;
  }
  return lastTextNode ? { node: lastTextNode, offset: lastTextNode.textContent?.length ?? 0 } : null;
}

export function collapsedRangeRectAtTextOffset(root: Node, charOffset: number): DOMRect | null {
  const target = textNodeAtOffset(root, Math.max(0, charOffset));
  if (!target) return null;
  const range = (root.ownerDocument ?? document).createRange();
  range.setStart(target.node, target.offset);
  range.collapse(true);
  const rects = typeof range.getClientRects === 'function' ? Array.from(range.getClientRects()) : [];
  const rect = rects.find((item) => Number.isFinite(item.top) && Number.isFinite(item.bottom))
    ?? (typeof range.getBoundingClientRect === 'function' ? range.getBoundingClientRect() : null);
  if (!rect || !Number.isFinite(rect.top) || !Number.isFinite(rect.bottom)) return null;
  if (rect.bottom <= rect.top && rect.height <= 0) return null;
  return rect;
}

function rootElementForGeometry(root: Node): HTMLElement | null {
  const element = root.nodeType === Node.ELEMENT_NODE ? root as Element : root.parentElement;
  return element instanceof HTMLElement ? element : null;
}

function numericStylePx(value: string): number {
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function lineHeightPx(styles: CSSStyleDeclaration, fontSize: number): number {
  const parsed = Number.parseFloat(styles.lineHeight);
  if (Number.isFinite(parsed) && parsed > 0) return parsed;
  return Math.max(1, fontSize * 1.2);
}

function estimatedTextOffsetFromPointInNode(root: Node, x: number, y: number): number | null {
  const element = rootElementForGeometry(root);
  const total = textLength(root);
  if (!element || total <= 0) return null;

  const rect = element.getBoundingClientRect();
  if (
    !Number.isFinite(rect.top)
    || !Number.isFinite(rect.left)
    || !Number.isFinite(rect.width)
    || !Number.isFinite(rect.height)
    || rect.width <= 0
    || rect.height <= 0
  ) {
    return null;
  }

  const styles = (element.ownerDocument.defaultView ?? window).getComputedStyle(element);
  const fontSize = Math.max(1, numericStylePx(styles.fontSize) || 16);
  const lineHeight = lineHeightPx(styles, fontSize);
  const paddingLeft = numericStylePx(styles.paddingLeft);
  const paddingRight = numericStylePx(styles.paddingRight);
  const contentLeft = rect.left + paddingLeft;
  const contentWidth = Math.max(
    1,
    (element.clientWidth || rect.width) - paddingLeft - paddingRight,
  );
  const averageCharWidth = Math.max(1, fontSize * 0.5);
  const charsPerLine = Math.max(1, Math.floor(contentWidth / averageCharWidth));
  const lineIndex = clampInteger(Math.floor((y - rect.top) / lineHeight), 0, Math.ceil(total / charsPerLine));
  const columnIndex = clampInteger(Math.floor((x - contentLeft) / averageCharWidth), 0, charsPerLine);
  return Math.min(total, Math.max(0, lineIndex * charsPerLine + columnIndex));
}

export function textOffsetFromPointInNode(root: Node, x: number, y: number): number | null {
  const total = textLength(root);
  if (total <= 0) return null;

  const nativeRange = caretRangeFromPoint(root.ownerDocument ?? document, x, y);
  if (nativeRange && nodeContains(root, nativeRange.startContainer)) {
    const nativeOffset = textOffsetWithinNode(root, nativeRange.startContainer, nativeRange.startOffset);
    if (nativeOffset !== null) {
      return Math.min(total, Math.max(0, nativeOffset));
    }
  }

  let low = 0;
  let high = total;
  let candidate = total;
  let hasMeasuredRect = false;

  while (low <= high) {
    const midpoint = Math.floor((low + high) / 2);
    const rect = collapsedRangeRectAtTextOffset(root, midpoint);
    if (!rect) break;
    hasMeasuredRect = true;
    if (rect.bottom < y) {
      low = midpoint + 1;
    } else {
      candidate = midpoint;
      high = midpoint - 1;
    }
  }

  if (!hasMeasuredRect) return estimatedTextOffsetFromPointInNode(root, x, y);

  const lineStart = Math.min(total, Math.max(0, candidate));
  let lineEnd = total;
  low = lineStart;
  high = total;
  while (low <= high) {
    const midpoint = Math.floor((low + high) / 2);
    const rect = collapsedRangeRectAtTextOffset(root, midpoint);
    if (!rect) break;
    if (rect.top > y) {
      lineEnd = midpoint;
      high = midpoint - 1;
    } else {
      low = midpoint + 1;
    }
  }

  const start = lineStart;
  const end = Math.max(start, Math.min(total, lineEnd));
  let bestOffset = start;
  let bestScore = Number.POSITIVE_INFINITY;

  function measureScore(offset: number): void {
    const rect = collapsedRangeRectAtTextOffset(root, offset);
    if (!rect) return;
    const verticalDistance = y < rect.top ? rect.top - y : y > rect.bottom ? y - rect.bottom : 0;
    const horizontalDistance = Math.abs((Number.isFinite(rect.left) ? rect.left : x) - x);
    const score = verticalDistance * 1000 + horizontalDistance;
    if (score < bestScore) {
      bestScore = score;
      bestOffset = offset;
    }
  }

  const lineLength = end - start;
  if (lineLength <= 512) {
    for (let offset = start; offset <= end; offset += 1) measureScore(offset);
    return bestOffset;
  }

  let horizontalLow = start;
  let horizontalHigh = end;
  let horizontalCandidate = end;
  while (horizontalLow <= horizontalHigh) {
    const midpoint = Math.floor((horizontalLow + horizontalHigh) / 2);
    const rect = collapsedRangeRectAtTextOffset(root, midpoint);
    if (!rect || !Number.isFinite(rect.left)) break;
    if (rect.left < x) {
      horizontalLow = midpoint + 1;
    } else {
      horizontalCandidate = midpoint;
      horizontalHigh = midpoint - 1;
    }
  }

  const scanStart = Math.max(start, horizontalCandidate - 16);
  const scanEnd = Math.min(end, horizontalCandidate + 16);
  for (let offset = scanStart; offset <= scanEnd; offset += 1) measureScore(offset);

  return bestOffset;
}

export function pageBreakOffsetsForViewportSlices(root: Node, viewportHeight: number): number[] {
  const total = textLength(root);
  if (total <= 0 || !Number.isFinite(viewportHeight) || viewportHeight <= 0) return [];

  const element = rootElementForGeometry(root);
  if (!element) return [];
  const rect = element.getBoundingClientRect();
  const height = rect.bottom - rect.top;
  if (
    !Number.isFinite(rect.top)
    || !Number.isFinite(rect.left)
    || !Number.isFinite(height)
    || height <= viewportHeight
  ) {
    return [];
  }

  const pageCount = Math.max(1, Math.ceil(height / viewportHeight));
  const offsets: number[] = [];
  let previousOffset = 0;
  for (let pageIndex = 1; pageIndex < pageCount; pageIndex += 1) {
    const y = rect.top + viewportHeight * pageIndex + 1;
    const x = rect.left + 1;
    const offset = textOffsetFromPointInNode(root, x, y);
    if (offset === null) continue;
    const safeOffset = clampInteger(offset, 0, total);
    if (safeOffset > previousOffset && safeOffset < total) {
      offsets.push(safeOffset);
      previousOffset = safeOffset;
    }
  }
  return offsets;
}

function nodeContains(root: Node, target: Node): boolean {
  return root === target || root.contains(target);
}

export function textOffsetWithinNode(root: Node, targetNode: Node, targetOffset: number): number | null {
  if (!nodeContains(root, targetNode)) return null;

  const documentRef = root.ownerDocument ?? document;
  const includeAriaHidden = readableModelIncludesAriaHidden(root);
  let offset = 0;

  if (targetNode.nodeType === Node.TEXT_NODE) {
    if (
      hasCssHiddenAncestor(targetNode, root)
      || hasRubyAnnotationAncestor(targetNode, root)
      || (!includeAriaHidden && hasAriaHiddenAncestor(targetNode, root))
    ) {
      try {
        const range = documentRef.createRange();
        range.setStart(root, 0);
        range.setEnd(targetNode, 0);
        return textLengthInReadableModel(range.cloneContents(), includeAriaHidden);
      } catch {
        return offset;
      }
    }

    const tokens = readableTextTokens(root, includeAriaHidden);
    for (const token of tokens) {
      if (token.kind === 'separator') {
        offset += token.length;
        continue;
      }
      if (token.node === targetNode) {
        return offset + Math.min(token.length, Math.max(0, targetOffset));
      }
      offset += token.length;
    }
    return null;
  }

  try {
    const range = documentRef.createRange();
    range.setStart(root, 0);
    range.setEnd(targetNode, Math.max(0, targetOffset));
    return textLengthInReadableModel(range.cloneContents(), includeAriaHidden);
  } catch {
    // Fall through to element child accounting for unusual DOM ranges.
  }

  if (targetNode.nodeType !== Node.ELEMENT_NODE) return null;

  const children = Array.from(targetNode.childNodes).slice(0, Math.max(0, targetOffset));
  const childOffset = children.reduce(
    (total, child) => total + textLengthInReadableModel(child, includeAriaHidden),
    0,
  );
  const beforeTarget = documentRef.createRange();
  beforeTarget.setStart(root, 0);
  beforeTarget.setEnd(targetNode, 0);
  return textLengthInReadableModel(beforeTarget.cloneContents(), includeAriaHidden) + childOffset;
}

type CaretDocument = Document & {
  caretPositionFromPoint?: (x: number, y: number) => { offsetNode: Node; offset: number } | null;
  caretRangeFromPoint?: (x: number, y: number) => Range | null;
};

type ReaderViewportTextLocationOptions = {
  anchorOffsetPx?: number;
  blockSelector?: string;
  excludeBlockAncestorSelector?: string;
  fallbackToBoundary?: boolean;
  fallbackToGeometry?: boolean;
  textSelector?: string;
};

function nodeElement(node: Node): Element | null {
  return node.nodeType === Node.ELEMENT_NODE ? node as Element : node.parentElement;
}

function caretRangeFromPoint(documentRef: Document, x: number, y: number): Range | null {
  const caretDocument = documentRef as CaretDocument;
  const position = caretDocument.caretPositionFromPoint?.(x, y);
  if (position) {
    const range = documentRef.createRange();
    range.setStart(position.offsetNode, position.offset);
    range.collapse(true);
    return range;
  }
  return caretDocument.caretRangeFromPoint?.(x, y) ?? null;
}

function paragraphIndexFromBlock(block: HTMLElement): number | null {
  const paragraphIndex = Number(block.dataset.paragraphIndex);
  return Number.isInteger(paragraphIndex) && paragraphIndex >= 0 ? paragraphIndex : null;
}

function charStartOffsetFromBlock(block: HTMLElement): number {
  const charStart = Number(block.dataset.charStart);
  return Number.isInteger(charStart) && charStart >= 0 ? charStart : 0;
}

function textElementForBlock(block: HTMLElement, textSelector: string): HTMLElement {
  return block.querySelector<HTMLElement>(textSelector) ?? block;
}

function blockIsExcluded(block: HTMLElement, excludeBlockAncestorSelector?: string): boolean {
  return Boolean(excludeBlockAncestorSelector && block.closest(excludeBlockAncestorSelector));
}

function blockFromNode(
  container: HTMLElement,
  node: Node,
  blockSelector: string,
  excludeBlockAncestorSelector?: string,
): HTMLElement | null {
  const element = nodeElement(node);
  const block = element?.closest<HTMLElement>(blockSelector) ?? null;
  return block && container.contains(block) && !blockIsExcluded(block, excludeBlockAncestorSelector) ? block : null;
}

function currentBlockFromViewportAnchor(
  container: HTMLElement,
  blockSelector: string,
  anchorOffsetPx: number,
  excludeBlockAncestorSelector?: string,
): HTMLElement | null {
  const blocks = Array.from(container.querySelectorAll<HTMLElement>(blockSelector))
    .filter((block) => !blockIsExcluded(block, excludeBlockAncestorSelector));
  if (blocks.length === 0) return null;

  const containerRect = container.getBoundingClientRect();
  const anchorY = containerRect.top + anchorOffsetPx;
  const blockRects = blocks.map((block) => ({
    block,
    rect: block.getBoundingClientRect(),
  }));
  return blockRects.find(({ rect }) => rect.top <= anchorY && rect.bottom > anchorY)?.block
    ?? blockRects.find(({ rect }) => rect.top > anchorY && rect.bottom >= containerRect.top)?.block
    ?? [...blockRects].reverse().find(({ rect }) => rect.bottom > containerRect.top)?.block
    ?? blockRects.find(({ rect }) => rect.bottom >= containerRect.top)?.block
    ?? blocks[blocks.length - 1];
}

type ReadableViewportBlock = {
  block: HTMLElement;
  charStart: number;
  paragraphIndex: number;
  rect: DOMRect;
  textLength: number;
};

function readableViewportBlocks(
  container: HTMLElement,
  blockSelector: string,
  textSelector: string,
  excludeBlockAncestorSelector?: string,
): ReadableViewportBlock[] {
  return Array.from(container.querySelectorAll<HTMLElement>(blockSelector))
    .filter((block) => !blockIsExcluded(block, excludeBlockAncestorSelector))
    .map((block) => {
      const paragraphIndex = paragraphIndexFromBlock(block);
      const textElement = textElementForBlock(block, textSelector);
      const rect = block.getBoundingClientRect();
      const blockTextLength = textLength(textElement);
      if (
        paragraphIndex === null
        || blockTextLength <= 0
        || !Number.isFinite(rect.top)
        || !Number.isFinite(rect.bottom)
        || rect.bottom <= rect.top
      ) {
        return null;
      }
      return {
        block,
        charStart: charStartOffsetFromBlock(block),
        paragraphIndex,
        rect,
        textLength: blockTextLength,
      };
    })
    .filter((item): item is ReadableViewportBlock => item !== null);
}

function locationForBlockOffset(
  blocks: string[],
  paragraphIndex: number,
  charOffset: number,
  block?: HTMLElement,
): ReaderTextLocation {
  const blockStartOffset = block ? charStartOffsetFromBlock(block) : 0;
  const paragraphLength = (blocks[paragraphIndex] ?? '').length;
  const safeCharOffset = Math.min(paragraphLength, Math.max(0, Math.round(blockStartOffset + charOffset)));
  return {
    absoluteCharOffset: absoluteCharOffsetForParagraph(blocks, paragraphIndex, safeCharOffset),
    charOffset: safeCharOffset,
    paragraphIndex,
  };
}

function textLocationFromRange(
  container: HTMLElement,
  blocks: string[],
  range: Range,
  blockSelector: string,
  textSelector: string,
  excludeBlockAncestorSelector?: string,
): ReaderTextLocation | null {
  const block = blockFromNode(container, range.startContainer, blockSelector, excludeBlockAncestorSelector);
  if (!block) return null;
  const paragraphIndex = paragraphIndexFromBlock(block);
  if (paragraphIndex === null) return null;
  const textElement = textElementForBlock(block, textSelector);
  const charOffset = textOffsetWithinNode(textElement, range.startContainer, range.startOffset);
  if (charOffset === null) return null;
  return locationForBlockOffset(blocks, paragraphIndex, charOffset, block);
}

function textLocationFromPoint(
  block: HTMLElement,
  blocks: string[],
  x: number,
  y: number,
  textSelector: string,
): ReaderTextLocation | null {
  const paragraphIndex = paragraphIndexFromBlock(block);
  if (paragraphIndex === null) return null;
  const textElement = textElementForBlock(block, textSelector);
  const charOffset = textOffsetFromPointInNode(textElement, x, y);
  if (charOffset === null) return null;
  return locationForBlockOffset(blocks, paragraphIndex, charOffset, block);
}

function boundaryTextLocationNearAnchor(
  container: HTMLElement,
  blocks: string[],
  blockSelector: string,
  textSelector: string,
  anchorY: number,
  excludeBlockAncestorSelector?: string,
): ReaderTextLocation | null {
  const readableBlocks = readableViewportBlocks(container, blockSelector, textSelector, excludeBlockAncestorSelector);
  const nextBlock = readableBlocks.find(({ rect }) => rect.top >= anchorY);
  if (nextBlock) {
    return locationForBlockOffset(blocks, nextBlock.paragraphIndex, nextBlock.charStart);
  }

  const previousBlock = [...readableBlocks].reverse().find(({ rect }) => rect.top <= anchorY);
  if (previousBlock) {
    return locationForBlockOffset(
      blocks,
      previousBlock.paragraphIndex,
      previousBlock.charStart + previousBlock.textLength,
    );
  }

  return null;
}

export function readerTextLocationFromViewportAnchor(
  container: HTMLElement | null,
  blocks: string[],
  options: ReaderViewportTextLocationOptions = {},
): ReaderTextLocation | null {
  if (!container || blocks.length === 0) return null;
  const blockSelector = options.blockSelector ?? '.reader-paragraph-block[data-paragraph-index]';
  const textSelector = options.textSelector ?? '.reader-paragraph-text';
  const anchorOffsetPx = options.anchorOffsetPx ?? 12;
  const excludeBlockAncestorSelector = options.excludeBlockAncestorSelector;
  const fallbackToGeometry = options.fallbackToGeometry ?? true;
  const fallbackToBoundary = options.fallbackToBoundary ?? true;
  const block = currentBlockFromViewportAnchor(container, blockSelector, anchorOffsetPx, excludeBlockAncestorSelector);
  if (!block) return null;

  const containerRect = container.getBoundingClientRect();
  const anchorY = containerRect.top + anchorOffsetPx;
  const textElement = textElementForBlock(block, textSelector);
  const blockRect = block.getBoundingClientRect();
  const textRect = textElement.getBoundingClientRect();
  if (!Number.isFinite(textRect.height) || textRect.height <= 0 || textLength(textElement) <= 0) {
    if (!fallbackToGeometry) return null;
    if (!fallbackToBoundary) return null;
    return boundaryTextLocationNearAnchor(
      container,
      blocks,
      blockSelector,
      textSelector,
      anchorY,
      excludeBlockAncestorSelector,
    );
  }
  if (blockRect.top > anchorY) {
    if (!fallbackToGeometry) return null;
    const paragraphIndex = paragraphIndexFromBlock(block);
    return paragraphIndex === null ? null : locationForBlockOffset(blocks, paragraphIndex, 0);
  }

  const x = Math.min(textRect.right - 1, Math.max(textRect.left + 1, textRect.left + 8));
  const y = Math.min(textRect.bottom - 1, Math.max(textRect.top + 1, anchorY));
  const range = caretRangeFromPoint(textElement.ownerDocument, x, y);
  if (range) {
    const rangeBlock = blockFromNode(container, range.startContainer, blockSelector, excludeBlockAncestorSelector);
    const rangeLocation = rangeBlock === block
      ? textLocationFromRange(container, blocks, range, blockSelector, textSelector, excludeBlockAncestorSelector)
      : null;
    if (rangeLocation) return rangeLocation;
  }

  if (!fallbackToGeometry) return null;
  return textLocationFromPoint(block, blocks, x, y, textSelector)
    ?? (fallbackToBoundary ? boundaryTextLocationNearAnchor(
      container,
      blocks,
      blockSelector,
      textSelector,
      anchorY,
      excludeBlockAncestorSelector,
    ) : null);
}

export function bookProgressPercent(input: {
  chapterIndex: number;
  chapterCount: number;
  chapterPercent: number;
}): number {
  const { chapterIndex, chapterCount, chapterPercent } = input;
  if (!Number.isFinite(chapterCount) || chapterCount <= 0) return 0;

  const safeChapterIndex = clampInteger(chapterIndex, 0, chapterCount - 1);
  const safeChapterPercent = clampPercent(chapterPercent);
  return Math.min(100, Math.max(0, Math.round(((safeChapterIndex + safeChapterPercent / 100) / chapterCount) * 100)));
}
