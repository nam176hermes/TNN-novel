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

  it('shows translation while optional source and HTML are still pending', async () => {
    const source = deferred<string>();
    const rich = deferred<{text: string; html: string}>();
    const client = {
      getChapterSource: vi.fn(() => source.promise),
      getChapterTranslation: vi.fn().mockResolvedValue('Đọc được ngay'),
      getChapterContent: vi.fn(() => rich.promise),
    } as unknown as ApiClient;
    const { result } = renderHook(() => useChapterText(client, true,
      { ...fixtureChapter, content_html_path: '/rich.html' }, undefined, [], { sourceEnabled: false }));
    await waitFor(() => expect(result.current.translationText).toBe('Đọc được ngay'));
    expect(result.current.state).toBe('ready');
    expect(client.getChapterSource).not.toHaveBeenCalled();
    await act(async () => { rich.resolve({text: 'Đọc được ngay', html: '<p>Đọc được ngay</p>'}); });
    expect(result.current.contentHtml).toContain('<p>');
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

  it('saves an explicit translated title without dropping unchanged rich content', async () => {
    const client = {
      getChapterTranslation: vi.fn().mockResolvedValue('Bản dịch'),
      getChapterContent: vi.fn().mockResolvedValue({text: 'Bản dịch', html: '<p>Bản dịch</p>'}),
      saveChapterTranslation: vi.fn().mockResolvedValue(7),
    } as unknown as ApiClient;
    const { result } = renderHook(() => useChapterText(client, true,
      {...fixtureChapter, content_revision: 7, content_html_path: '/rich.html'}, undefined, [], {sourceEnabled: false}));
    await waitFor(() => expect(result.current.contentHtml).toBe('<p>Bản dịch</p>'));
    act(() => result.current.setTranslatedTitle('Tiêu đề mới'));
    expect(result.current.isDirty).toBe(true);
    await act(async () => result.current.save());
    expect(client.saveChapterTranslation).toHaveBeenCalledWith(42, 4201, 'Bản dịch', 7, 'Tiêu đề mới');
    expect(result.current.contentHtml).toBe('<p>Bản dịch</p>');
    expect(result.current.isDirty).toBe(false);
  });

  it('ignores a late save response after the active chapter changes', async () => {
    const saved = deferred<number>();
    const client = {
      getChapterTranslation: vi.fn((_book, id) => Promise.resolve(`Chương ${id}`)),
      saveChapterTranslation: vi.fn(() => saved.promise),
    } as unknown as ApiClient;
    const {result, rerender} = renderHook(({chapter}) => useChapterText(client, true, chapter,
      undefined, [], {sourceEnabled: false}), {initialProps: {chapter: fixtureChapter}});
    await waitFor(() => expect(result.current.translationText).toBe('Chương 4201'));
    let saving: Promise<void>;
    act(() => { saving = result.current.save('Sửa chương cũ'); });
    rerender({chapter: {...fixtureChapter, id: 4202}});
    await waitFor(() => expect(result.current.translationText).toBe('Chương 4202'));
    await act(async () => { saved.resolve(8); await saving; });
    expect(result.current.translationText).toBe('Chương 4202');
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

  it('shows cached chapter text immediately by default while refreshing from the API', async () => {
    putCachedChapter({
      bookId: 42,
      chapterId: 4201,
      html: '',
      sourceText: '舊原文',
      text: 'Bản dịch cache',
    });
    const source = deferred<string>();
    const translation = deferred<string | null>();
    const client = {
      getChapterSource: vi.fn().mockReturnValue(source.promise),
      getChapterTranslation: vi.fn().mockReturnValue(translation.promise),
      getChapterContent: vi.fn(),
      saveChapterTranslation: vi.fn().mockResolvedValue(undefined),
    } as unknown as ApiClient;

    const { result } = renderHook(() =>
      useChapterText(client, true, { ...fixtureChapter, audio_path: '' }),
    );

    await waitFor(() => expect(result.current.translationText).toBe('Bản dịch cache'));
    expect(result.current.sourceText).toBe('舊原文');
    expect(result.current.state).toBe('ready');

    source.resolve('新原文');
    translation.resolve('Bản dịch mới');

    await waitFor(() => expect(result.current.translationText).toBe('Bản dịch mới'));
    expect(result.current.sourceText).toBe('新原文');
  });

  it('does not read the current cache when the Reader declares external cache ownership', async () => {
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
      useChapterText(
        client,
        true,
        { ...fixtureChapter, audio_path: '' },
        undefined,
        [],
        { cacheOwnership: 'external', sourceEnabled: true },
      ),
    );

    await waitFor(() => expect(client.getChapterSource).toHaveBeenCalledTimes(1));
    expect(getCachedChapter).not.toHaveBeenCalled();
    expect(result.current.translationText).toBe('');
    expect(result.current.state).toBe('loading');

    source.resolve('新原文');
    translation.resolve('Bản dịch mới');
    await waitFor(() => expect(result.current.translationText).toBe('Bản dịch mới'));
  });

  it('does not issue opportunistic translation prefetches when the Reader owns cache orchestration', async () => {
    const client = {
      getChapterSource: vi.fn().mockResolvedValue('原文'),
      getChapterTranslation: vi.fn().mockResolvedValue('Bản dịch'),
      getChapterContent: vi.fn(),
      saveChapterTranslation: vi.fn(),
    } as unknown as ApiClient;
    const nextChapter = {
      ...fixtureChapter,
      id: 4301,
      title: 'Chương kế',
      audio_path: '',
      content_html_path: null,
    };
    const { rerender } = renderHook(
      ({ chapter }) => useChapterText(
        client,
        true,
        chapter,
        undefined,
        [nextChapter],
        { cacheOwnership: 'external', sourceEnabled: true },
      ),
      { initialProps: { chapter: { ...fixtureChapter, audio_path: '', content_html_path: null } } },
    );

    await waitFor(() => expect(client.getChapterTranslation).toHaveBeenCalledTimes(1));
    await new Promise((resolve) => window.setTimeout(resolve, 350));
    expect(client.getChapterTranslation).toHaveBeenCalledTimes(1);

    rerender({ chapter: nextChapter });
    await waitFor(() => expect(client.getChapterTranslation).toHaveBeenCalledTimes(2));
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

  it('deduplicates current chapter loads and aborts superseded requests', async () => {
    const requests = new Map<number, ReturnType<typeof deferred<string>>>();
    const translations = new Map<number, ReturnType<typeof deferred<string | null>>>();
    const signals = new Map<number, AbortSignal | undefined>();
    const client = {
      getChapterSource: vi.fn((_bookId: number, chapterId: number, options?: { signal?: AbortSignal }) => {
        const request = deferred<string>();
        requests.set(chapterId, request);
        signals.set(chapterId, options?.signal);
        return request.promise;
      }),
      getChapterTranslation: vi.fn((_bookId: number, chapterId: number) => {
        const request = deferred<string | null>();
        translations.set(chapterId, request);
        return request.promise;
      }),
      getChapterContent: vi.fn(),
      saveChapterTranslation: vi.fn(),
    } as unknown as ApiClient;

    const { result, rerender } = renderHook(
      ({ chapter }) => useChapterText(
        client,
        true,
        chapter,
        undefined,
        [],
        { cacheOwnership: 'external', sourceEnabled: true },
      ),
      { initialProps: { chapter: { ...fixtureChapter, audio_path: '' } } },
    );

    await waitFor(() => expect(client.getChapterSource).toHaveBeenCalledTimes(1));
    void result.current.load();
    void result.current.load();
    expect(client.getChapterSource).toHaveBeenCalledTimes(1);
    expect(signals.get(4201)).toBeInstanceOf(AbortSignal);

    rerender({ chapter: { ...fixtureChapter, id: 4301, title: 'New Chapter', audio_path: '' } });
    await waitFor(() => expect(client.getChapterSource).toHaveBeenCalledTimes(2));
    expect(signals.get(4201)?.aborted).toBe(true);

    requests.get(4301)?.resolve('Nguồn mới');
    translations.get(4301)?.resolve('Bản dịch mới');
    await waitFor(() => expect(result.current.translationText).toBe('Bản dịch mới'));
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
