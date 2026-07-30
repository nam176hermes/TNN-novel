import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { Chapter } from '../../api/types';
import {
  ReaderInlineMarkdown,
  resolveReaderChapterDisplayTitle,
} from './readerTextPresentation';

const chapter: Chapter = {
  audio_path: null,
  book_id: 42,
  chapter_number: 12,
  has_translation: true,
  id: 120,
  status: 'translated',
  title: '第十二章 故人重逢',
};

describe('readerTextPresentation', () => {
  it('renders supported inline Markdown without exposing raw markers', () => {
    render(
      <p data-testid="paragraph">
        <ReaderInlineMarkdown text="Mở đầu **đậm nét** rồi `tĩnh tâm`." />
      </p>,
    );

    const paragraph = screen.getByTestId('paragraph');
    expect(paragraph).toHaveTextContent('Mở đầu đậm nét rồi tĩnh tâm.');
    expect(paragraph).not.toHaveTextContent('**');
    expect(paragraph).not.toHaveTextContent('`');
    expect(screen.getByText('đậm nét').tagName).toBe('STRONG');
    expect(screen.getByText('tĩnh tâm').tagName).toBe('CODE');
  });

  it('derives a Vietnamese chapter title from an explicit translated Markdown heading', () => {
    expect(resolveReaderChapterDisplayTitle(
      chapter,
      '**Chương 12: Gặp lại cố nhân**\n\nMột đoạn dịch.',
    )).toBe('Gặp lại cố nhân');
  });

  it('falls back to the source title for ordinary prose or Han headings', () => {
    expect(resolveReaderChapterDisplayTitle(chapter, 'Một đoạn dịch bình thường.')).toBe(chapter.title);
    expect(resolveReaderChapterDisplayTitle(chapter, '**第十二章 故人重逢**\n\nMột đoạn dịch.')).toBe(chapter.title);
  });
});
