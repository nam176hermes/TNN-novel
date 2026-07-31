import { renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { ApiClient } from '../api/client';
import { fixtureChapter } from '../test/fixtures';
import { useReaderChapterData } from './useReaderChapterData';

describe('useReaderChapterData', () => {
  it('owns source, translation, rich content, and QA for one canonical chapter key', async () => {
    const client = {
      getChapterSource: vi.fn().mockResolvedValue('原文'),
      getChapterTranslation: vi.fn().mockResolvedValue('Bản dịch'),
      getChapterContent: vi.fn().mockResolvedValue({ html: '<p>Bản dịch</p>', text: 'Bản dịch' }),
      getQaReport: vi.fn().mockResolvedValue({ book_id: 42, chapter_id: 4201, issues: [] }),
      saveChapterTranslation: vi.fn().mockResolvedValue(undefined),
      startQaJob: vi.fn(),
    } as unknown as ApiClient;

    const { result } = renderHook(() => useReaderChapterData(
      client,
      true,
      { ...fixtureChapter, content_html_path: '/book-assets/42/chapter-1.xhtml' },
    ));

    await waitFor(() => expect(result.current.text.state).toBe('ready'));
    await waitFor(() => expect(result.current.qa.state).toBe('ready'));

    expect(result.current.chapterKey).toBe('42:4201');
    expect(result.current.text.sourceText).toBe('原文');
    expect(result.current.text.translationText).toBe('Bản dịch');
    expect(result.current.qa.report).toMatchObject({ book_id: 42, chapter_id: 4201 });
    expect(client.getChapterSource).toHaveBeenCalledTimes(1);
    expect(client.getChapterTranslation).toHaveBeenCalledTimes(1);
    expect(client.getChapterContent).toHaveBeenCalledTimes(1);
    expect(client.getQaReport).toHaveBeenCalledTimes(1);
  });

  it('uses 15 canonical resource requests for four rapid chapter transitions without duplicates', async () => {
    const getChapterSource = vi.fn((_bookId: number, chapterId: number) => Promise.resolve(`source-${chapterId}`));
    const getChapterTranslation = vi.fn((_bookId: number, chapterId: number) => Promise.resolve(`translation-${chapterId}`));
    const getQaReport = vi.fn((_bookId: number, chapterId: number) => Promise.resolve({
      book_id: 42,
      chapter_id: chapterId,
      issues: [],
    }));
    const client = {
      getChapterSource,
      getChapterTranslation,
      getChapterContent: vi.fn(),
      getQaReport,
      saveChapterTranslation: vi.fn(),
      startQaJob: vi.fn(),
    } as unknown as ApiClient;
    const chapterIds = [4201, 4202, 4203, 4204, 4205];
    const { rerender } = renderHook(
      ({ chapterId }) => useReaderChapterData(
        client,
        true,
        { ...fixtureChapter, id: chapterId, content_html_path: null },
        undefined,
        [],
        { cacheOwnership: 'external' },
      ),
      { initialProps: { chapterId: chapterIds[0] } },
    );

    await waitFor(() => expect(client.getQaReport).toHaveBeenCalledTimes(1));
    for (const [index, chapterId] of chapterIds.slice(1).entries()) {
      rerender({ chapterId });
      await waitFor(() => expect(client.getQaReport).toHaveBeenCalledTimes(index + 2));
    }

    expect(getChapterSource).toHaveBeenCalledTimes(5);
    expect(getChapterTranslation).toHaveBeenCalledTimes(5);
    expect(getQaReport).toHaveBeenCalledTimes(5);
    expect(client.getChapterContent).not.toHaveBeenCalled();
    expect(
      getChapterSource.mock.calls.length
      + getChapterTranslation.mock.calls.length
      + getQaReport.mock.calls.length,
    ).toBe(15);
  });
});
