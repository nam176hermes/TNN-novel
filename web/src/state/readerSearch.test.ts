import { describe, expect, it } from 'vitest';
import type { Chapter } from '../api/types';
import { createReaderSearchMatcher, searchCurrentChapter, searchReaderMarks, searchTextParagraphs } from './readerSearch';
import type { ReaderChapterMarks } from './readerMarks';

const chapter: Chapter = {
  audio_path: null,
  book_id: 42,
  chapter_number: 2,
  has_translation: true,
  id: 102,
  status: 'translated',
  title: 'Thanh Ngưu trấn',
};

const marks: ReaderChapterMarks = {
  bookmarked: false,
  highlights: [
    {
      charEnd: 43,
      charStart: 20,
      id: 'h1',
      paragraphIndex: 1,
      text: 'Lục ca, ta cảm tạ huynh.',
    },
  ],
  notes: [
    {
      charEnd: 70,
      charStart: 50,
      id: 'n1',
      note: 'Giữ xưng hô cổ trang.',
      paragraphIndex: 2,
      text: 'Không dùng tôi bạn.',
    },
  ],
};

describe('readerSearch', () => {
  it('matches plain text case-insensitively by default', () => {
    const results = searchTextParagraphs(['Hàn Lập khẽ gật đầu.'], chapter, 'hàn lập');

    expect(results).toMatchObject([
      {
        chapter_id: 102,
        chapter_number: 2,
        char_end: 'Hàn Lập'.length,
        char_start: 0,
        paragraph_index: 0,
        source: 'translation',
      },
    ]);
  });

  it('supports case sensitive, whole word, and regex matching', () => {
    expect(searchTextParagraphs(['Lục ca gặp lục bình.'], chapter, 'lục', { caseSensitive: true })).toHaveLength(1);
    expect(searchTextParagraphs(['Lục ca gặp lục bình.'], chapter, 'Lục', { caseSensitive: true })).toHaveLength(1);
    expect(searchTextParagraphs(['Lục ca gặp lục bình.'], chapter, 'lục', { wholeWord: true })).toHaveLength(1);
    expect(searchTextParagraphs(['Lục ca gặp lục bình.'], chapter, 'lục b', { wholeWord: true })).toHaveLength(0);
    expect(searchTextParagraphs(['Hàn Lập khẽ gật đầu.'], chapter, 'Hàn\\s+Lập', { regex: true })).toHaveLength(1);
    expect(createReaderSearchMatcher('[', { regex: true })).toBeNull();
  });

  it('searches notes and highlights when their scopes are enabled', () => {
    expect(searchReaderMarks(marks, chapter, 'cảm tạ', { scopes: ['highlights'] })).toMatchObject([
      {
        paragraph_index: 1,
        char_start: 20 + 'Lục ca, ta '.length,
        char_end: 20 + 'Lục ca, ta cảm tạ'.length,
        source: 'highlight',
      },
    ]);
    expect(searchReaderMarks(marks, chapter, 'xưng hô', { scopes: ['notes'] })).toMatchObject([
      {
        paragraph_index: 2,
        char_start: 50,
        char_end: 70,
        source: 'note',
      },
    ]);
    expect(searchReaderMarks(marks, chapter, 'xưng hô', { scopes: ['translation'] })).toEqual([]);
  });

  it('combines current chapter translation, notes, and highlight results', () => {
    const results = searchCurrentChapter({
      chapter,
      marks,
      paragraphs: ['Hàn Lập khẽ gật đầu.', 'Lục ca, ta cảm tạ huynh.'],
      query: 'Lục|xưng hô',
      options: { regex: true, scopes: ['translation', 'notes', 'highlights'] },
    });

    expect(results.map((result) => result.source)).toEqual(['translation', 'highlight', 'note']);
  });
});
