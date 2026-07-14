import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../api/client';
import { ApiClient } from '../api/client';
import { fixtureChapter } from '../test/fixtures';
import * as readerCacheModule from './readerCache';
import { hasCachedChapter, putCachedChapter } from './readerCache';
import { useChapterText } from './useChapterText';

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });

  return { promise, resolve };
}

describe('useChapterText', () => {
  afterEach(() => {
    window.localStorage.clear();
  });

  it('loads source and translation, tracks dirty state, and saves edits', async () => {
    const client = {
      getChapterSource: vi.fn().mockResolvedValue('原文'),
      getChapterTranslation: vi.fn().mockResolvedValue('Bản dịch'),
      getChapterContent: vi.fn().mockResolvedValue({ text: 'Bản dịch', html: '<p>Bản dịch</p><img src="/book-assets/42/sword.png" alt="Kiếm"/>' }),
      saveChapterTranslation: vi.fn().mockResolvedValue(undefined),
    } as unknown as ApiClient;

    const { result } = renderHook(() =>
      useChapterText(client, true, { ...fixtureChapter, audio_path: '', content_html_path: '/tmp/translated.html' }),
    );

    await waitFor(() => expect(result.current.state).toBe('ready'));
    expect(result.current.sourceText).toBe('原文');
    expect(result.current.translationText).toBe('Bản dịch');
    expect(result.current.contentHtml).toBe('<p>Bản dịch</p><img src="/book-assets/42/sword.png" alt="Kiếm"/>');

    act(() => result.current.setTranslationText('Bản dịch sửa'));
    expect(result.current.isDirty).toBe(true);

    await act(async () => result.current.save());
    expect(client.saveChapterTranslation).toHaveBeenCalledWith(42, 4201, 'Bản dịch sửa');
    expect(result.current.isDirty).toBe(false);
  });

  it('uses content_html_path as the asset base for relative EPUB rich content', async () => {
    const originalIndexedDb = window.indexedDB;
    const originalCreateObjectUrl = URL.createObjectURL;
    const originalFetch = globalThis.fetch;
    const createObjectUrl = vi.fn(() => 'blob:reader-hook-bg');
    const fetcher = vi.fn(async (url: RequestInfo | URL) => ({
      blob: async () => new Blob([`bytes:${String(url)}`], { type: 'image/jpeg' }),
      headers: new Headers({ 'content-type': 'image/jpeg' }),
      ok: true,
    })) as unknown as typeof fetch;
    Object.defineProperty(window, 'indexedDB', { configurable: true, value: undefined });
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectUrl });
    Object.defineProperty(globalThis, 'fetch', { configurable: true, value: fetcher });
    const richHtml = '<p style="background-image: url(\'./images/bg.jpg\')">Bản dịch</p>';
    const client = {
      getChapterSource: vi.fn().mockResolvedValue('原文'),
      getChapterTranslation: vi.fn().mockResolvedValue('Bản dịch'),
      getChapterContent: vi.fn().mockResolvedValue({ text: 'Bản dịch', html: richHtml }),
      saveChapterTranslation: vi.fn().mockResolvedValue(undefined),
    } as unknown as ApiClient;

    try {
      const { result } = renderHook(() =>
        useChapterText(client, true, {
          ...fixtureChapter,
          audio_path: '',
          content_html_path: '/book-assets/42/OEBPS/chapter-1.xhtml',
        }),
      );

      await waitFor(() => expect(fetcher).toHaveBeenCalledWith(
        '/book-assets/42/OEBPS/images/bg.jpg',
        { credentials: 'same-origin' },
      ));
      await waitFor(() => expect(result.current.contentHtml).toContain("url('blob:reader-hook-bg')"));
      expect(fetcher).not.toHaveBeenCalledWith('/images/bg.jpg', { credentials: 'same-origin' });
    } finally {
      Object.defineProperty(window, 'indexedDB', { configurable: true, value: originalIndexedDb });
      Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: originalCreateObjectUrl });
      Object.defineProperty(globalThis, 'fetch', { configurable: true, value: originalFetch });
    }
  });

  it('leaves cached fallback reads to the offline controller while refreshing from the API', async () => {
    putCachedChapter({
      bookId: 42,
      chapterId: 4201,
      html: '',
      sourceText: '舊原文',
      text: 'Bản dịch cache',
    });
    const source = deferred<string>();
    const translation = deferred<string | null>();
    const getCachedChapter = vi.spyOn(readerCacheModule, 'getCachedChapterAsync');
    const client = {
      getChapterSource: vi.fn().mockReturnValue(source.promise),
      getChapterTranslation: vi.fn().mockReturnValue(translation.promise),
      getChapterContent: vi.fn(),
      saveChapterTranslation: vi.fn().mockResolvedValue(undefined),
    } as unknown as ApiClient;

    const { result } = renderHook(() =>
      useChapterText(client, true, { ...fixtureChapter, audio_path: '' }),
    );

    await waitFor(() => expect(client.getChapterSource).toHaveBeenCalledTimes(1));
    expect(getCachedChapter).not.toHaveBeenCalled();
    expect(result.current.translationText).toBe('');
    expect(result.current.state).toBe('loading');

    source.resolve('新原文');
    translation.resolve('Bản dịch mới');

    await waitFor(() => expect(result.current.translationText).toBe('Bản dịch mới'));
    expect(result.current.sourceText).toBe('新原文');
  });

  it('removes stale cache when the API no longer has translated text', async () => {
    putCachedChapter({
      bookId: 42,
      chapterId: 4201,
      html: '',
      sourceText: '舊原文',
      text: 'Bản dịch cũ',
    });
    const client = {
      getChapterSource: vi.fn().mockResolvedValue('新原文'),
      getChapterTranslation: vi.fn().mockResolvedValue(null),
      getChapterContent: vi.fn(),
      saveChapterTranslation: vi.fn().mockResolvedValue(undefined),
    } as unknown as ApiClient;

    const { result } = renderHook(() =>
      useChapterText(client, true, { ...fixtureChapter, audio_path: '' }),
    );

    await waitFor(() => expect(result.current.sourceText).toBe('新原文'));
    expect(result.current.translationText).toBe('');
    await waitFor(() => expect(hasCachedChapter(42, 4201)).toBe(false));
  });

  it('ignores stale out-of-order load results for a previous chapter', async () => {
    const source42 = deferred<string>();
    const translation42 = deferred<string | null>();
    const source43 = deferred<string>();
    const translation43 = deferred<string | null>();
    const client = {
      getChapterSource: vi.fn((bookId: number, chapterId: number) => {
        if (bookId === 42 && chapterId === 4201) return source42.promise;
        if (bookId === 42 && chapterId === 4301) return source43.promise;
        throw new Error(`Unexpected source request ${bookId}/${chapterId}`);
      }),
      getChapterTranslation: vi.fn((bookId: number, chapterId: number) => {
        if (bookId === 42 && chapterId === 4201) return translation42.promise;
        if (bookId === 42 && chapterId === 4301) return translation43.promise;
        throw new Error(`Unexpected translation request ${bookId}/${chapterId}`);
      }),
      getChapterContent: vi.fn().mockResolvedValue({ text: '', html: '' }),
      saveChapterTranslation: vi.fn().mockResolvedValue(undefined),
    } as unknown as ApiClient;

    const { result, rerender } = renderHook(
      ({ chapter }) => useChapterText(client, true, chapter),
      { initialProps: { chapter: { ...fixtureChapter, audio_path: '' } } },
    );

    rerender({
      chapter: { ...fixtureChapter, id: 4301, title: 'New Chapter', audio_path: '' },
    });

    source43.resolve('Nguồn mới');
    translation43.resolve('Bản dịch mới');

    await waitFor(() => expect(result.current.state).toBe('ready'));
    expect(result.current.sourceText).toBe('Nguồn mới');
    expect(result.current.translationText).toBe('Bản dịch mới');

    source42.resolve('Nguồn cũ');
    translation42.resolve('Bản dịch cũ');

    await waitFor(() => expect(result.current.sourceText).toBe('Nguồn mới'));
    expect(result.current.translationText).toBe('Bản dịch mới');
  });

  it('calls onAuthError when chapter text load returns 401', async () => {
    const onAuthError = vi.fn();
    const client = {
      getChapterSource: vi.fn().mockRejectedValue(new ApiError('Expired', 401)),
      getChapterTranslation: vi.fn(),
      getChapterContent: vi.fn(),
      saveChapterTranslation: vi.fn(),
    } as unknown as ApiClient;

    renderHook(() => useChapterText(client, true, { ...fixtureChapter, audio_path: '' }, onAuthError));

    await waitFor(() => expect(onAuthError).toHaveBeenCalledTimes(1));
  });
});
