import {
  absoluteCharOffsetForParagraph,
  paragraphLocation,
  type ParagraphLocation,
} from './readerLocation';
import type { ReaderProgressSnapshot, ReaderProgressTextAnchor } from './readerProgress';

const ANCHOR_BEFORE_CHARS = 48;
const ANCHOR_AFTER_CHARS = 48;
const ANCHOR_CONTEXT_CHARS = 32;
const MAX_ANCHOR_MATCHES = 200;

function joinedBlocks(blocks: string[]): string {
  return blocks.join('\n\n');
}

function commonPrefixLength(left: string, right: string): number {
  const max = Math.min(left.length, right.length);
  let index = 0;
  while (index < max && left[index] === right[index]) index += 1;
  return index;
}

function commonSuffixLength(left: string, right: string): number {
  const max = Math.min(left.length, right.length);
  let index = 0;
  while (index < max && left[left.length - 1 - index] === right[right.length - 1 - index]) index += 1;
  return index;
}

function locationFromAbsoluteOffset(blocks: string[], absoluteCharOffset: number): ParagraphLocation | null {
  return paragraphLocation(
    blocks.map((paragraph, index) => ({ index, paragraph })),
    absoluteCharOffset,
  );
}

function scoreAnchorMatch(text: string, anchor: ReaderProgressTextAnchor, index: number, expectedOffset: number): number {
  const prefix = text.slice(Math.max(0, index - anchor.prefix.length), index);
  const suffixStart = index + anchor.text.length;
  const suffix = text.slice(suffixStart, suffixStart + anchor.suffix.length);
  const prefixScore = commonSuffixLength(prefix, anchor.prefix);
  const suffixScore = commonPrefixLength(suffix, anchor.suffix);
  const distancePenalty = Math.min(100, Math.abs((index + anchor.offset) - expectedOffset) / 1000);
  return prefixScore * 2 + suffixScore * 2 + anchor.text.length - distancePenalty;
}

function locateAnchorText(text: string, anchor: ReaderProgressTextAnchor, expectedOffset: number): number | null {
  if (!anchor.text) return null;

  let bestIndex = -1;
  let bestScore = Number.NEGATIVE_INFINITY;
  let searchIndex = text.indexOf(anchor.text);
  let matchCount = 0;
  while (searchIndex >= 0 && matchCount < MAX_ANCHOR_MATCHES) {
    const score = scoreAnchorMatch(text, anchor, searchIndex, expectedOffset);
    if (score > bestScore) {
      bestScore = score;
      bestIndex = searchIndex;
    }
    matchCount += 1;
    searchIndex = text.indexOf(anchor.text, searchIndex + 1);
  }

  return bestIndex >= 0 ? bestIndex + anchor.offset : null;
}

export function buildReaderProgressTextAnchor(
  blocks: string[],
  paragraphIndex: number | undefined,
  charOffset: number | undefined,
): ReaderProgressTextAnchor | undefined {
  if (paragraphIndex === undefined || paragraphIndex < 0 || blocks.length === 0) return undefined;
  const text = joinedBlocks(blocks);
  if (!text) return undefined;
  const absoluteCharOffset = absoluteCharOffsetForParagraph(blocks, paragraphIndex, charOffset);
  const safeOffset = Math.min(text.length, Math.max(0, absoluteCharOffset));
  const start = Math.max(0, safeOffset - ANCHOR_BEFORE_CHARS);
  const end = Math.min(text.length, safeOffset + ANCHOR_AFTER_CHARS);
  const anchorText = text.slice(start, end);
  if (!anchorText) return undefined;
  return {
    offset: safeOffset - start,
    prefix: text.slice(Math.max(0, start - ANCHOR_CONTEXT_CHARS), start),
    suffix: text.slice(end, Math.min(text.length, end + ANCHOR_CONTEXT_CHARS)),
    text: anchorText,
    version: 1,
  };
}

export function resolveReaderProgressTextAnchor(
  blocks: string[],
  snapshot: Pick<ReaderProgressSnapshot, 'absoluteCharOffset' | 'anchor' | 'charOffset' | 'paragraphIndex'>,
): ParagraphLocation | null {
  const fallbackOffset = snapshot.absoluteCharOffset
    ?? absoluteCharOffsetForParagraph(blocks, snapshot.paragraphIndex, snapshot.charOffset);
  if (blocks.length === 0) return null;
  const text = joinedBlocks(blocks);
  const anchorOffset = snapshot.anchor ? locateAnchorText(text, snapshot.anchor, fallbackOffset) : null;
  return locationFromAbsoluteOffset(blocks, anchorOffset ?? fallbackOffset);
}
