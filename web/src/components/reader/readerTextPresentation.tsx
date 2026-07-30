import type { ReactNode } from 'react';
import type { Chapter } from '../../api/types';

type ReaderInlineSegment = {
  kind: 'code' | 'strong' | 'text';
  text: string;
};

const inlineMarkdownPattern = /(\*\*([^*\n]+)\*\*|__([^_\n]+)__|`([^`\n]+)`)/g;
const explicitHeadingPatterns = [
  /^#{1,6}\s+(.+)$/u,
  /^\*\*([^*\n]+)\*\*$/u,
  /^__([^_\n]+)__$/u,
];

function readerInlineSegments(text: string): ReaderInlineSegment[] {
  const segments: ReaderInlineSegment[] = [];
  let cursor = 0;
  for (const match of text.matchAll(inlineMarkdownPattern)) {
    const index = match.index ?? 0;
    if (index > cursor) segments.push({ kind: 'text', text: text.slice(cursor, index) });
    if (match[2] !== undefined || match[3] !== undefined) {
      segments.push({ kind: 'strong', text: match[2] ?? match[3] });
    } else {
      segments.push({ kind: 'code', text: match[4] ?? '' });
    }
    cursor = index + match[0].length;
  }
  if (cursor < text.length) segments.push({ kind: 'text', text: text.slice(cursor) });
  return segments.length > 0 ? segments : [{ kind: 'text', text }];
}

function explicitTranslatedHeading(text: string): string {
  const firstLine = text
    .split(/\r?\n/u)
    .map((line) => line.trim())
    .find(Boolean) ?? '';
  for (const pattern of explicitHeadingPatterns) {
    const match = firstLine.match(pattern);
    if (match?.[1]) return match[1].trim();
  }
  return '';
}

function withoutChapterPrefix(value: string, chapterNumber: number): string {
  const escapedChapterNumber = String(chapterNumber).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return value.replace(
    new RegExp(`^(?:Chương|Chuong|Chapter|Hồi|Hoi)\\s+${escapedChapterNumber}(?:\\s*[:.\\-–·]\\s*|\\s+)`, 'iu'),
    '',
  ).trim();
}

export function resolveReaderChapterDisplayTitle(chapter: Chapter, translationText: string): string {
  const fallback = chapter.title.trim() || `Chương ${chapter.chapter_number}`;
  const heading = explicitTranslatedHeading(translationText);
  if (!heading || /[\u3400-\u9fff]/u.test(heading)) return fallback;
  const title = withoutChapterPrefix(heading, chapter.chapter_number);
  if (!title || title.length > 160 || /[\u3400-\u9fff]/u.test(title)) return fallback;
  return title;
}

export function ReaderInlineMarkdown({ text }: { text: string }): ReactNode {
  const segments = readerInlineSegments(text);
  if (segments.length === 1 && segments[0]?.kind === 'text') return text;
  return segments.map((segment, index) => {
    const key = `${segment.kind}-${index}`;
    if (segment.kind === 'strong') return <strong key={key}>{segment.text}</strong>;
    if (segment.kind === 'code') return <code key={key}>{segment.text}</code>;
    return segment.text;
  });
}
