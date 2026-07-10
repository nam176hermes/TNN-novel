import { afterEach, describe, expect, it, vi } from 'vitest';
import * as readerCacheModule from './readerCache';
import {
  READER_CACHE_STORAGE_KEY,
  cacheReaderAudio,
  cacheReaderAssetsFromHtml,
  estimateReaderCacheBytes,
  extractReaderAssetUrls,
  formatReaderCacheSize,
  getCachedReaderAudioUrl,
  getCachedChapter,
  getCachedChapterAsync,
  hasCachedChapter,
  hasCachedChapterAsync,
  hydrateCachedReaderAssetUrls,
  hydrateReaderCssAssetUrls,
  hydrateReaderElementAssetUrls,
  hydrateReaderSrcsetAssetUrls,
  loadReaderCache,
  loadReaderCacheAsync,
  putCachedChapter,
  putCachedChapterAsync,
  readerCacheStatus,
  readerCacheStatusAsync,
  readerAudioCacheKey,
  readerCacheKey,
  removeCachedBook,
  removeCachedBookAsync,
  removeCachedChapter,
  removeCachedChapterAsync,
} from './readerCache';

function createMemoryStorage(): Storage {
  const values = new Map<string, string>();
  return {
    get length() {
      return values.size;
    },
    clear: () => values.clear(),
    getItem: (key: string) => values.get(key) ?? null,
    key: (index: number) => Array.from(values.keys())[index] ?? null,
    removeItem: (key: string) => {
      values.delete(key);
    },
    setItem: (key: string, value: string) => {
      values.set(key, value);
    },
  };
}

describe('readerCache', () => {
  afterEach(() => {
    window.localStorage.clear();
  });

  it('stores translated chapter content and reports cache status', () => {
    const storage = createMemoryStorage();

    putCachedChapter({
      bookId: 42,
      cachedAt: '2026-06-28T10:00:00Z',
      chapterId: 101,
      html: '<p>Bản dịch</p>',
      sourceText: '原文',
      text: 'Bản dịch',
    }, storage);
    putCachedChapter({
      bookId: 42,
      cachedAt: '2026-06-28T10:01:00Z',
      chapterId: 102,
      html: '',
      sourceText: '',
      text: 'Chương sau',
    }, storage);

    expect(readerCacheKey(42, 101)).toBe('42:101');
    expect(hasCachedChapter(42, 101, storage)).toBe(true);
    expect(getCachedChapter(42, 101, storage)).toMatchObject({
      bookId: 42,
      chapterId: 101,
      html: '<p>Bản dịch</p>',
      sourceText: '原文',
      text: 'Bản dịch',
    });
    expect(readerCacheStatus({
      bookId: 42,
      chapterId: 101,
      nextChapterId: 102,
      storage,
    })).toMatchObject({
      currentCached: true,
      nextCached: true,
    });
    expect(estimateReaderCacheBytes(loadReaderCache(storage))).toBeGreaterThan(0);
  });

  it('ignores invalid persisted cache payloads', () => {
    const storage = createMemoryStorage();
    storage.setItem(READER_CACHE_STORAGE_KEY, '{"42:101":{"bookId":"bad"}}');

    expect(loadReaderCache(storage)).toEqual({});

    storage.setItem(READER_CACHE_STORAGE_KEY, 'not-json');
    expect(loadReaderCache(storage)).toEqual({});
  });

  it('formats cache size for the reader menu', () => {
    expect(formatReaderCacheSize(0)).toBe('0 KB');
    expect(formatReaderCacheSize(1200)).toBe('1 KB');
    expect(formatReaderCacheSize(2.4 * 1024 * 1024)).toBe('2.4 MB');
  });

  it('extracts cacheable image asset URLs from rich chapter HTML', () => {
    expect(extractReaderAssetUrls(`
      <p><img src="/book-assets/42/a.png" alt="A"/></p>
      <img src="/book-assets/42/a.png" alt="duplicate"/>
      <img src="data:image/png;base64,abc" alt="inline"/>
      <img src="blob:http://local/abc" alt="blob"/>
    `)).toEqual(['/book-assets/42/a.png']);
  });

  it('extracts EPUB-style image assets from srcset and mixed attribute quotes', () => {
    expect(extractReaderAssetUrls(`
      <picture>
        <source srcset='/book-assets/42/cover-small.webp 480w, /book-assets/42/cover.webp 960w'>
        <img src='/book-assets/42/cover.jpg'
          srcset="/book-assets/42/cover@2x.jpg 2x, data:image/png;base64,abc 3x"
          alt="Cover">
      </picture>
      <img src=/book-assets/42/map.png>
      <img src="javascript:alert(1)">
    `)).toEqual([
      '/book-assets/42/cover-small.webp',
      '/book-assets/42/cover.webp',
      '/book-assets/42/cover.jpg',
      '/book-assets/42/cover@2x.jpg',
      '/book-assets/42/map.png',
    ]);
  });

  it('resolves relative EPUB srcset asset URLs against the chapter asset base', () => {
    expect(extractReaderAssetUrls(`
      <picture>
        <source srcset="images/cover-small.webp 480w, ./images/cover.webp 960w">
        <img src="images/cover.jpg" srcset="../shared/cover@2x.jpg 2x">
      </picture>
    `, '/book-assets/42/OEBPS/chapter-1.xhtml')).toEqual([
      '/book-assets/42/OEBPS/images/cover-small.webp',
      '/book-assets/42/OEBPS/images/cover.webp',
      '/book-assets/42/OEBPS/images/cover.jpg',
      '/book-assets/42/shared/cover@2x.jpg',
    ]);
  });

  it('extracts EPUB-style SVG and CSS image assets from rich chapter HTML', () => {
    expect(extractReaderAssetUrls(`
      <svg>
        <image href="/book-assets/42/realm-map.svg"></image>
        <image xlink:href="/book-assets/42/spirit-seal.png"></image>
      </svg>
      <p style="background-image: url('/book-assets/42/bg.jpg'); border-image: url(&quot;/book-assets/42/frame.webp&quot;) 30;">
        Trận pháp sáng lên.
      </p>
      <style>
        .dropcap { background: url("/book-assets/42/dropcap.png") no-repeat; }
        .inline { background: url(data:image/png;base64,abc); }
      </style>
    `)).toEqual([
      '/book-assets/42/realm-map.svg',
      '/book-assets/42/spirit-seal.png',
      '/book-assets/42/bg.jpg',
      '/book-assets/42/frame.webp',
      '/book-assets/42/dropcap.png',
    ]);
  });

  it('extracts SVG filter image assets from rich EPUB illustrations', () => {
    expect(extractReaderAssetUrls(`
      <svg>
        <filter id="paper-texture">
          <feImage href="/book-assets/42/filter-texture.png"></feImage>
        </filter>
        <filter id="glow">
          <feImage xlink:href="/book-assets/42/glow.webp"></feImage>
        </filter>
      </svg>
    `)).toEqual([
      '/book-assets/42/filter-texture.png',
      '/book-assets/42/glow.webp',
    ]);
  });

  it('extracts external SVG sprite assets from EPUB use references without local-only fragments', () => {
    expect(extractReaderAssetUrls(`
      <svg>
        <use href="/book-assets/42/sprites.svg#sword-seal"></use>
        <use xlink:href="/book-assets/42/icons.svg#realm"></use>
        <use href="#local-symbol"></use>
      </svg>
    `)).toEqual([
      '/book-assets/42/sprites.svg',
      '/book-assets/42/icons.svg',
    ]);
  });

  it('extracts EPUB stylesheet links for offline rich chapter rendering', () => {
    expect(extractReaderAssetUrls(`
      <link rel="stylesheet" href="/book-assets/42/chapter.css">
      <link rel="preload" as="style" href="/book-assets/42/theme.css">
      <link rel="canonical" href="/books/42/chapter-1">
    `)).toEqual([
      '/book-assets/42/chapter.css',
      '/book-assets/42/theme.css',
    ]);
  });

  it('extracts EPUB object, embed, track, and preload assets for complete offline rendering', () => {
    expect(extractReaderAssetUrls(`
      <object data="/book-assets/42/formation.svg" type="image/svg+xml"></object>
      <embed src="/book-assets/42/realm-diagram.svg" type="image/svg+xml">
      <video controls>
        <track kind="subtitles" src="/book-assets/42/subtitles.vtt" srclang="vi">
      </video>
      <link rel="preload" as="font" href="/book-assets/42/reader-serif.woff2">
      <link rel="preload" as="image" href="/book-assets/42/preloaded-map.webp">
      <link rel="canonical" href="/books/42/chapter-1">
    `)).toEqual([
      '/book-assets/42/formation.svg',
      '/book-assets/42/realm-diagram.svg',
      '/book-assets/42/subtitles.vtt',
      '/book-assets/42/reader-serif.woff2',
      '/book-assets/42/preloaded-map.webp',
    ]);
  });

  it('extracts lazy image and media poster assets from EPUB-converted rich HTML', () => {
    expect(extractReaderAssetUrls(`
      <figure>
        <img data-src="/book-assets/42/lazy-cover.jpg" alt="Lazy cover">
        <img data-original='/book-assets/42/original-map.png' alt="Original map">
        <img data-lazy-src=/book-assets/42/lazy-seal.webp alt="Lazy seal">
        <img data-srcset="/book-assets/42/lazy-small.webp 480w, /book-assets/42/lazy-large.webp 960w">
      </figure>
      <video poster="/book-assets/42/trailer-poster.jpg"></video>
      <img data-src="data:image/png;base64,abc" alt="inline">
    `)).toEqual([
      '/book-assets/42/lazy-cover.jpg',
      '/book-assets/42/original-map.png',
      '/book-assets/42/lazy-seal.webp',
      '/book-assets/42/lazy-small.webp',
      '/book-assets/42/lazy-large.webp',
      '/book-assets/42/trailer-poster.jpg',
    ]);
  });

  it('extracts audio and video source assets from EPUB-converted rich HTML', () => {
    expect(extractReaderAssetUrls(`
      <audio controls src="/book-assets/42/zither.mp3" title="Tiếng đàn cổ"></audio>
      <video controls src="/book-assets/42/vision.mp4" poster="/book-assets/42/vision-poster.jpg">
        <source src="/book-assets/42/vision-720.mp4" type="video/mp4">
        <source src="/book-assets/42/vision-480.webm" type="video/webm">
      </video>
      <audio src="https://cdn.example.com/remote.mp3"></audio>
    `)).toEqual([
      '/book-assets/42/zither.mp3',
      '/book-assets/42/vision.mp4',
      '/book-assets/42/vision-poster.jpg',
      '/book-assets/42/vision-720.mp4',
      '/book-assets/42/vision-480.webm',
      'https://cdn.example.com/remote.mp3',
    ]);
  });

  it('stores reader assets in fallback storage when IndexedDB is unavailable', async () => {
    const originalIndexedDb = window.indexedDB;
    Object.defineProperty(window, 'indexedDB', { configurable: true, value: undefined });
    const fetcher = vi.fn().mockResolvedValue({
      blob: async () => new Blob(['image-bytes'], { type: 'image/png' }),
      headers: new Headers({ 'content-type': 'image/png' }),
      ok: true,
    }) as unknown as typeof fetch;

    try {
      await expect(cacheReaderAssetsFromHtml(
        42,
        101,
        '<img src="/book-assets/42/a.png" alt="A"/>',
        fetcher,
      )).resolves.toMatchObject({
        cached: 1,
        failed: 0,
        total: 1,
        urls: ['/book-assets/42/a.png'],
      });
      expect(fetcher).toHaveBeenCalledWith('/book-assets/42/a.png', { credentials: 'same-origin' });
      await expect(readerCacheStatusAsync({
        bookId: 42,
        chapterId: 101,
      })).resolves.toMatchObject({
        assetCount: 1,
        assetSizeBytes: 11,
      });
    } finally {
      Object.defineProperty(window, 'indexedDB', { configurable: true, value: originalIndexedDb });
    }
  });

  it('caches assets referenced by linked EPUB stylesheets', async () => {
    const originalIndexedDb = window.indexedDB;
    Object.defineProperty(window, 'indexedDB', { configurable: true, value: undefined });
    const fetcher = vi.fn(async (url: RequestInfo | URL) => {
      const href = String(url);
      if (href === '/book-assets/42/chapter.css') {
        return {
          blob: async () => new Blob([
            '@import "./theme.css"; .map { background-image: url("./images/map.png"); } .seal { background: url("/book-assets/42/seal.png"); }',
          ], { type: 'text/css' }),
          headers: new Headers({ 'content-type': 'text/css' }),
          ok: true,
        };
      }
      if (href === '/book-assets/42/theme.css') {
        return {
          blob: async () => new Blob([
            '.theme { color: #111; }',
          ], { type: 'text/css' }),
          headers: new Headers({ 'content-type': 'text/css' }),
          ok: true,
        };
      }
      return {
        blob: async () => new Blob([`bytes:${href}`], { type: 'image/png' }),
        headers: new Headers({ 'content-type': 'image/png' }),
        ok: true,
      };
    }) as unknown as typeof fetch;

    try {
      await expect(cacheReaderAssetsFromHtml(
        42,
        101,
        '<link rel="stylesheet" href="/book-assets/42/chapter.css">',
        fetcher,
      )).resolves.toMatchObject({
        cached: 4,
        failed: 0,
        total: 4,
        urls: [
          '/book-assets/42/chapter.css',
          '/book-assets/42/theme.css',
          '/book-assets/42/images/map.png',
          '/book-assets/42/seal.png',
        ],
      });
      expect(fetcher).toHaveBeenCalledWith('/book-assets/42/chapter.css', { credentials: 'same-origin' });
      expect(fetcher).toHaveBeenCalledWith('/book-assets/42/theme.css', { credentials: 'same-origin' });
      expect(fetcher).toHaveBeenCalledWith('/book-assets/42/images/map.png', { credentials: 'same-origin' });
      expect(fetcher).toHaveBeenCalledWith('/book-assets/42/seal.png', { credentials: 'same-origin' });
    } finally {
      Object.defineProperty(window, 'indexedDB', { configurable: true, value: originalIndexedDb });
    }
  });

  it('caches and hydrates relative EPUB style assets end-to-end', async () => {
    const originalIndexedDb = window.indexedDB;
    const originalCreateObjectUrl = URL.createObjectURL;
    Object.defineProperty(window, 'indexedDB', { configurable: true, value: undefined });
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:reader-relative-style') });
    const fetcher = vi.fn(async (url: RequestInfo | URL) => ({
      blob: async () => new Blob([`bytes:${String(url)}`], { type: 'image/jpeg' }),
      headers: new Headers({ 'content-type': 'image/jpeg' }),
      ok: true,
    })) as unknown as typeof fetch;
    const html = '<p style="background-image: url(\'./images/bg.jpg\')">Trận pháp sáng lên.</p>';

    try {
      await expect(cacheReaderAssetsFromHtml(
        42,
        101,
        html,
        fetcher,
        '/book-assets/42/OEBPS/chapter-1.xhtml',
      )).resolves.toMatchObject({
        cached: 1,
        failed: 0,
        total: 1,
        urls: ['/book-assets/42/OEBPS/images/bg.jpg'],
      });
      expect(fetcher).toHaveBeenCalledWith('/book-assets/42/OEBPS/images/bg.jpg', { credentials: 'same-origin' });

      await expect(hydrateCachedReaderAssetUrls(
        42,
        101,
        html,
        '/book-assets/42/OEBPS/chapter-1.xhtml',
      )).resolves.toBe('<p style="background-image: url(\'blob:reader-relative-style\')" data-original-style="background-image: url(\'./images/bg.jpg\')">Trận pháp sáng lên.</p>');
    } finally {
      Object.defineProperty(window, 'indexedDB', { configurable: true, value: originalIndexedDb });
      Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: originalCreateObjectUrl });
    }
  });

  it('caches and hydrates SVG filter image assets end-to-end', async () => {
    const originalIndexedDb = window.indexedDB;
    const originalCreateObjectUrl = URL.createObjectURL;
    Object.defineProperty(window, 'indexedDB', { configurable: true, value: undefined });
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn()
        .mockReturnValueOnce('blob:reader-filter-texture')
        .mockReturnValueOnce('blob:reader-filter-glow'),
    });
    const fetcher = vi.fn(async (url: RequestInfo | URL) => ({
      blob: async () => new Blob([`bytes:${String(url)}`], { type: 'image/png' }),
      headers: new Headers({ 'content-type': 'image/png' }),
      ok: true,
    })) as unknown as typeof fetch;
    const html = `
      <svg>
        <filter id="paper-texture">
          <feImage href="/book-assets/42/filter-texture.png#grain"></feImage>
        </filter>
        <filter id="glow">
          <feImage xlink:href="/book-assets/42/glow.webp"></feImage>
        </filter>
      </svg>
    `;

    try {
      await expect(cacheReaderAssetsFromHtml(42, 101, html, fetcher)).resolves.toMatchObject({
        cached: 2,
        failed: 0,
        total: 2,
        urls: [
          '/book-assets/42/filter-texture.png',
          '/book-assets/42/glow.webp',
        ],
      });
      expect(fetcher).toHaveBeenCalledWith('/book-assets/42/filter-texture.png', { credentials: 'same-origin' });
      expect(fetcher).toHaveBeenCalledWith('/book-assets/42/glow.webp', { credentials: 'same-origin' });

      await expect(hydrateCachedReaderAssetUrls(42, 101, html)).resolves.toContain(
        'href="blob:reader-filter-texture#grain"',
      );
      await expect(hydrateCachedReaderAssetUrls(42, 101, html)).resolves.toContain(
        'xlink:href="blob:reader-filter-glow"',
      );
    } finally {
      Object.defineProperty(window, 'indexedDB', { configurable: true, value: originalIndexedDb });
      Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: originalCreateObjectUrl });
    }
  });

  it('hydrates cached srcset image assets without rewriting inline or missing images', async () => {
    const resolveCachedUrl = vi.fn(async (url: string) => ({
      '/book-assets/142/cover-small.webp': 'blob:reader-asset-1',
      '/book-assets/142/cover.webp': 'blob:reader-asset-2',
    }[url] ?? ''));

    await expect(hydrateReaderSrcsetAssetUrls(
      '/book-assets/142/cover-small.webp 480w, /book-assets/142/cover.webp 960w, data:image/png;base64,abc 3x, /book-assets/142/missing.webp 2x',
      resolveCachedUrl,
    )).resolves.toEqual({
      changed: true,
      value: 'blob:reader-asset-1 480w, blob:reader-asset-2 960w, data:image/png;base64,abc 3x, /book-assets/142/missing.webp 2x',
    });
    expect(resolveCachedUrl).toHaveBeenCalledTimes(3);
    expect(resolveCachedUrl).toHaveBeenCalledWith('/book-assets/142/cover-small.webp');
    expect(resolveCachedUrl).toHaveBeenCalledWith('/book-assets/142/cover.webp');
    expect(resolveCachedUrl).toHaveBeenCalledWith('/book-assets/142/missing.webp');
  });

  it('hydrates relative EPUB srcset assets against the chapter asset base', async () => {
    const resolveCachedUrl = vi.fn(async (url: string) => ({
      '/book-assets/142/OEBPS/images/cover-small.webp': 'blob:reader-relative-1',
      '/book-assets/142/shared/cover.webp': 'blob:reader-relative-2',
    }[url] ?? ''));

    await expect(hydrateReaderSrcsetAssetUrls(
      'images/cover-small.webp 480w, ../shared/cover.webp 960w, images/missing.webp 2x',
      resolveCachedUrl,
      '/book-assets/142/OEBPS/chapter-1.xhtml',
    )).resolves.toEqual({
      changed: true,
      value: 'blob:reader-relative-1 480w, blob:reader-relative-2 960w, images/missing.webp 2x',
    });
    expect(resolveCachedUrl).toHaveBeenCalledWith('/book-assets/142/OEBPS/images/cover-small.webp');
    expect(resolveCachedUrl).toHaveBeenCalledWith('/book-assets/142/shared/cover.webp');
    expect(resolveCachedUrl).toHaveBeenCalledWith('/book-assets/142/OEBPS/images/missing.webp');
  });

  it('hydrates cached CSS url assets without rewriting inline or missing images', async () => {
    const resolveCachedUrl = vi.fn(async (url: string) => ({
      '/book-assets/142/theme.css': 'blob:reader-theme-css',
      '/book-assets/142/bg.jpg': 'blob:reader-bg',
      '/book-assets/142/mask.png': 'blob:reader-mask',
    }[url] ?? ''));

    await expect(hydrateReaderCssAssetUrls(
      '@import "/book-assets/142/theme.css"; background-image: url("/book-assets/142/bg.jpg"); mask-image: url(/book-assets/142/mask.png); border-image: url(data:image/png;base64,abc); list-style: url(/book-assets/142/missing.svg);',
      resolveCachedUrl,
    )).resolves.toEqual({
      changed: true,
      value: '@import "blob:reader-theme-css"; background-image: url("blob:reader-bg"); mask-image: url(blob:reader-mask); border-image: url(data:image/png;base64,abc); list-style: url(/book-assets/142/missing.svg);',
    });
    expect(resolveCachedUrl).toHaveBeenCalledTimes(4);
    expect(resolveCachedUrl).toHaveBeenCalledWith('/book-assets/142/theme.css');
    expect(resolveCachedUrl).toHaveBeenCalledWith('/book-assets/142/bg.jpg');
    expect(resolveCachedUrl).toHaveBeenCalledWith('/book-assets/142/mask.png');
    expect(resolveCachedUrl).toHaveBeenCalledWith('/book-assets/142/missing.svg');
  });

  it('hydrates relative EPUB CSS url assets against the stylesheet base', async () => {
    const resolveCachedUrl = vi.fn(async (url: string) => ({
      '/book-assets/142/OEBPS/styles/theme.css': 'blob:reader-theme',
      '/book-assets/142/OEBPS/styles/images/bg.jpg': 'blob:reader-bg',
      '/book-assets/142/OEBPS/shared/frame.webp': 'blob:reader-frame',
    }[url] ?? ''));

    await expect(hydrateReaderCssAssetUrls(
      '@import "./theme.css"; background-image: url("./images/bg.jpg"); border-image: url("../shared/frame.webp") 30; list-style: url("./missing.svg");',
      resolveCachedUrl,
      '/book-assets/142/OEBPS/styles/chapter.css',
    )).resolves.toEqual({
      changed: true,
      value: '@import "blob:reader-theme"; background-image: url("blob:reader-bg"); border-image: url("blob:reader-frame") 30; list-style: url("./missing.svg");',
    });
    expect(resolveCachedUrl).toHaveBeenCalledWith('/book-assets/142/OEBPS/styles/theme.css');
    expect(resolveCachedUrl).toHaveBeenCalledWith('/book-assets/142/OEBPS/styles/images/bg.jpg');
    expect(resolveCachedUrl).toHaveBeenCalledWith('/book-assets/142/OEBPS/shared/frame.webp');
    expect(resolveCachedUrl).toHaveBeenCalledWith('/book-assets/142/OEBPS/styles/missing.svg');
  });

  it('hydrates cached lazy image and poster assets for offline rich HTML', async () => {
    const documentRef = new DOMParser().parseFromString(`
      <img data-src="/book-assets/42/lazy-cover.jpg" alt="Lazy cover">
      <video poster="/book-assets/42/poster.jpg"></video>
    `, 'text/html');
    const image = documentRef.querySelector('img');
    const video = documentRef.querySelector('video');
    const resolveCachedUrl = vi.fn(async (url: string) => ({
      '/book-assets/42/lazy-cover.jpg': 'blob:reader-lazy-1',
      '/book-assets/42/poster.jpg': 'blob:reader-lazy-2',
    }[url] ?? ''));

    expect(image).not.toBeNull();
    expect(video).not.toBeNull();
    await expect(hydrateReaderElementAssetUrls(image as Element, resolveCachedUrl)).resolves.toBe(true);
    await expect(hydrateReaderElementAssetUrls(video as Element, resolveCachedUrl)).resolves.toBe(true);

    expect(image?.getAttribute('data-original-data-src')).toBe('/book-assets/42/lazy-cover.jpg');
    expect(image?.getAttribute('data-src')).toBe('blob:reader-lazy-1');
    expect(image?.getAttribute('src')).toBe('blob:reader-lazy-1');
    expect(video?.getAttribute('data-original-poster')).toBe('/book-assets/42/poster.jpg');
    expect(video?.getAttribute('poster')).toBe('blob:reader-lazy-2');
  });

  it('hydrates relative EPUB element style assets against the chapter base', async () => {
    const documentRef = new DOMParser().parseFromString(`
      <p style="background-image: url('./images/bg.jpg'); border-image: url('../shared/frame.webp') 30;">
        Trận pháp sáng lên.
      </p>
    `, 'text/html');
    const paragraph = documentRef.querySelector('p');
    const resolveCachedUrl = vi.fn(async (url: string) => ({
      '/book-assets/42/OEBPS/images/bg.jpg': 'blob:reader-style-bg',
      '/book-assets/42/shared/frame.webp': 'blob:reader-style-frame',
    }[url] ?? ''));

    expect(paragraph).not.toBeNull();
    await expect(hydrateReaderElementAssetUrls(
      paragraph as Element,
      resolveCachedUrl,
      '/book-assets/42/OEBPS/chapter-1.xhtml',
    )).resolves.toBe(true);

    expect(resolveCachedUrl).toHaveBeenCalledWith('/book-assets/42/OEBPS/images/bg.jpg');
    expect(resolveCachedUrl).toHaveBeenCalledWith('/book-assets/42/shared/frame.webp');
    expect(paragraph?.getAttribute('data-original-style')).toContain('./images/bg.jpg');
    expect(paragraph?.getAttribute('style')).toBe(
      'background-image: url(\'blob:reader-style-bg\'); border-image: url(\'blob:reader-style-frame\') 30;',
    );
  });

  it('hydrates cached audio and video source assets for offline rich HTML', async () => {
    const documentRef = new DOMParser().parseFromString(`
      <audio controls src="/book-assets/42/zither.mp3"></audio>
      <video controls src="/book-assets/42/vision.mp4">
        <source src="/book-assets/42/vision-720.mp4" type="video/mp4">
      </video>
    `, 'text/html');
    const audio = documentRef.querySelector('audio');
    const video = documentRef.querySelector('video');
    const source = documentRef.querySelector('source');
    const resolveCachedUrl = vi.fn(async (url: string) => ({
      '/book-assets/42/zither.mp3': 'blob:reader-audio-rich',
      '/book-assets/42/vision.mp4': 'blob:reader-video-rich',
      '/book-assets/42/vision-720.mp4': 'blob:reader-source-rich',
    }[url] ?? ''));

    expect(audio).not.toBeNull();
    expect(video).not.toBeNull();
    expect(source).not.toBeNull();
    await expect(hydrateReaderElementAssetUrls(audio as Element, resolveCachedUrl)).resolves.toBe(true);
    await expect(hydrateReaderElementAssetUrls(video as Element, resolveCachedUrl)).resolves.toBe(true);
    await expect(hydrateReaderElementAssetUrls(source as Element, resolveCachedUrl)).resolves.toBe(true);

    expect(audio?.getAttribute('data-original-src')).toBe('/book-assets/42/zither.mp3');
    expect(audio?.getAttribute('src')).toBe('blob:reader-audio-rich');
    expect(video?.getAttribute('data-original-src')).toBe('/book-assets/42/vision.mp4');
    expect(video?.getAttribute('src')).toBe('blob:reader-video-rich');
    expect(source?.getAttribute('data-original-src')).toBe('/book-assets/42/vision-720.mp4');
    expect(source?.getAttribute('src')).toBe('blob:reader-source-rich');
  });

  it('hydrates cached linked stylesheets and embedded EPUB resource assets', async () => {
    const documentRef = new DOMParser().parseFromString(`
      <link rel="stylesheet" href="/book-assets/42/chapter.css">
      <object data="/book-assets/42/formation.svg" type="image/svg+xml"></object>
      <embed src="/book-assets/42/realm-diagram.svg" type="image/svg+xml">
      <track kind="subtitles" src="/book-assets/42/subtitles.vtt" srclang="vi">
    `, 'text/html');
    const link = documentRef.querySelector('link');
    const object = documentRef.querySelector('object');
    const embed = documentRef.querySelector('embed');
    const track = documentRef.querySelector('track');
    const resolveCachedUrl = vi.fn(async (url: string) => ({
      '/book-assets/42/chapter.css': 'blob:reader-css',
      '/book-assets/42/formation.svg': 'blob:reader-object',
      '/book-assets/42/realm-diagram.svg': 'blob:reader-embed',
      '/book-assets/42/subtitles.vtt': 'blob:reader-track',
    }[url] ?? ''));

    expect(link).not.toBeNull();
    expect(object).not.toBeNull();
    expect(embed).not.toBeNull();
    expect(track).not.toBeNull();
    await expect(hydrateReaderElementAssetUrls(link as Element, resolveCachedUrl)).resolves.toBe(true);
    await expect(hydrateReaderElementAssetUrls(object as Element, resolveCachedUrl)).resolves.toBe(true);
    await expect(hydrateReaderElementAssetUrls(embed as Element, resolveCachedUrl)).resolves.toBe(true);
    await expect(hydrateReaderElementAssetUrls(track as Element, resolveCachedUrl)).resolves.toBe(true);

    expect(link?.getAttribute('data-original-href')).toBe('/book-assets/42/chapter.css');
    expect(link?.getAttribute('href')).toBe('blob:reader-css');
    expect(object?.getAttribute('data-original-data')).toBe('/book-assets/42/formation.svg');
    expect(object?.getAttribute('data')).toBe('blob:reader-object');
    expect(embed?.getAttribute('data-original-src')).toBe('/book-assets/42/realm-diagram.svg');
    expect(embed?.getAttribute('src')).toBe('blob:reader-embed');
    expect(track?.getAttribute('data-original-src')).toBe('/book-assets/42/subtitles.vtt');
    expect(track?.getAttribute('src')).toBe('blob:reader-track');
  });

  it('hydrates external SVG use references while preserving their symbol fragments', async () => {
    const documentRef = new DOMParser().parseFromString(`
      <svg>
        <use href="/book-assets/42/sprites.svg#sword-seal"></use>
        <use xlink:href="/book-assets/42/icons.svg#realm"></use>
        <use href="#local-symbol"></use>
      </svg>
    `, 'text/html');
    const uses = Array.from(documentRef.querySelectorAll('use'));
    const resolveCachedUrl = vi.fn(async (url: string) => ({
      '/book-assets/42/sprites.svg': 'blob:reader-sprites',
      '/book-assets/42/icons.svg': 'blob:reader-icons',
    }[url] ?? ''));

    expect(uses).toHaveLength(3);
    await expect(hydrateReaderElementAssetUrls(uses[0] as Element, resolveCachedUrl)).resolves.toBe(true);
    await expect(hydrateReaderElementAssetUrls(uses[1] as Element, resolveCachedUrl)).resolves.toBe(true);
    await expect(hydrateReaderElementAssetUrls(uses[2] as Element, resolveCachedUrl)).resolves.toBe(false);

    expect(resolveCachedUrl).toHaveBeenCalledWith('/book-assets/42/sprites.svg');
    expect(resolveCachedUrl).toHaveBeenCalledWith('/book-assets/42/icons.svg');
    expect(resolveCachedUrl).not.toHaveBeenCalledWith('/#local-symbol');
    expect(uses[0]?.getAttribute('data-original-href')).toBe('/book-assets/42/sprites.svg#sword-seal');
    expect(uses[0]?.getAttribute('href')).toBe('blob:reader-sprites#sword-seal');
    expect(uses[1]?.getAttribute('data-original-xlink-href')).toBe('/book-assets/42/icons.svg#realm');
    expect(uses[1]?.getAttribute('xlink:href')).toBe('blob:reader-icons#realm');
    expect(uses[2]?.getAttribute('href')).toBe('#local-symbol');
  });

  it('hydrates SVG filter image assets while preserving fragments', async () => {
    const documentRef = new DOMParser().parseFromString(`
      <svg>
        <filter id="paper-texture">
          <feImage href="/book-assets/42/filter-texture.png#grain"></feImage>
        </filter>
        <filter id="glow">
          <feImage xlink:href="/book-assets/42/glow.webp"></feImage>
        </filter>
      </svg>
    `, 'text/html');
    const filterImages = Array.from(documentRef.querySelectorAll('feImage'));
    const resolveCachedUrl = vi.fn(async (url: string) => ({
      '/book-assets/42/filter-texture.png': 'blob:reader-filter-texture',
      '/book-assets/42/glow.webp': 'blob:reader-filter-glow',
    }[url] ?? ''));

    expect(filterImages).toHaveLength(2);
    await expect(hydrateReaderElementAssetUrls(filterImages[0] as Element, resolveCachedUrl)).resolves.toBe(true);
    await expect(hydrateReaderElementAssetUrls(filterImages[1] as Element, resolveCachedUrl)).resolves.toBe(true);

    expect(resolveCachedUrl).toHaveBeenCalledWith('/book-assets/42/filter-texture.png');
    expect(resolveCachedUrl).toHaveBeenCalledWith('/book-assets/42/glow.webp');
    expect(filterImages[0]?.getAttribute('data-original-href')).toBe('/book-assets/42/filter-texture.png#grain');
    expect(filterImages[0]?.getAttribute('href')).toBe('blob:reader-filter-texture#grain');
    expect(filterImages[1]?.getAttribute('data-original-xlink-href')).toBe('/book-assets/42/glow.webp');
    expect(filterImages[1]?.getAttribute('xlink:href')).toBe('blob:reader-filter-glow');
  });

  it('removes stale chapter cache entries', () => {
    const storage = createMemoryStorage();
    putCachedChapter({
      bookId: 42,
      chapterId: 101,
      html: '',
      sourceText: '',
      text: 'Bản dịch cũ',
    }, storage);

    removeCachedChapter(42, 101, storage);

    expect(hasCachedChapter(42, 101, storage)).toBe(false);
  });

  it('removes all cached chapters for a deleted book', () => {
    const storage = createMemoryStorage();
    putCachedChapter({
      bookId: 42,
      chapterId: 101,
      html: '',
      sourceText: '',
      text: 'Sách 42',
    }, storage);
    putCachedChapter({
      bookId: 43,
      chapterId: 201,
      html: '',
      sourceText: '',
      text: 'Sách 43',
    }, storage);

    removeCachedBook(42, storage);

    expect(hasCachedChapter(42, 101, storage)).toBe(false);
    expect(hasCachedChapter(43, 201, storage)).toBe(true);
  });

  it('supports the async IndexedDB-facing API with localStorage fallback', async () => {
    await putCachedChapterAsync({
      bookId: 42,
      cachedAt: '2026-06-28T10:00:00Z',
      chapterId: 101,
      html: '',
      sourceText: '原文',
      text: 'Bản dịch',
    });

    expect(await hasCachedChapterAsync(42, 101)).toBe(true);
    expect(await getCachedChapterAsync(42, 101)).toMatchObject({
      bookId: 42,
      chapterId: 101,
      sourceText: '原文',
      text: 'Bản dịch',
    });
    expect(await loadReaderCacheAsync()).toMatchObject({
      '42:101': {
        text: 'Bản dịch',
      },
    });
    expect(await readerCacheStatusAsync({
      bookId: 42,
      chapterId: 101,
      nextChapterId: null,
    })).toMatchObject({
      currentCached: true,
      nextCached: null,
    });

    await removeCachedChapterAsync(42, 101);
    expect(await hasCachedChapterAsync(42, 101)).toBe(false);

    await putCachedChapterAsync({
      bookId: 42,
      chapterId: 101,
      html: '',
      sourceText: '',
      text: 'Sách 42',
    });
    await putCachedChapterAsync({
      bookId: 43,
      chapterId: 201,
      html: '',
      sourceText: '',
      text: 'Sách 43',
    });
    await removeCachedBookAsync(42);
    expect(await hasCachedChapterAsync(42, 101)).toBe(false);
    expect(await hasCachedChapterAsync(43, 201)).toBe(true);
  });

  it('caches chapter audio blobs and returns an offline object URL', async () => {
    const originalCreateObjectUrl = URL.createObjectURL;
    const originalRevokeObjectUrl = URL.revokeObjectURL;
    const createObjectUrl = vi.fn(() => 'blob:reader-audio-101');
    const revokeObjectUrl = vi.fn();
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectUrl });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revokeObjectUrl });
    const fetcher = vi.fn().mockResolvedValue({
      blob: async () => new Blob(['audio-bytes'], { type: 'audio/mpeg' }),
      headers: new Headers({ 'content-type': 'audio/mpeg' }),
      ok: true,
    }) as unknown as typeof fetch;

    try {
      await expect(cacheReaderAudio(
        42,
        101,
        '/api/books/42/chapters/101/audio',
        fetcher,
      )).resolves.toMatchObject({
        cached: true,
        failed: false,
        sizeBytes: 11,
      });
      expect(fetcher).toHaveBeenCalledWith('/api/books/42/chapters/101/audio', { credentials: 'include' });
      expect(readerAudioCacheKey(42, 101, '/api/books/42/chapters/101/audio')).toBe(
        '42:101:/api/books/42/chapters/101/audio',
      );

      await expect(getCachedReaderAudioUrl(
        42,
        101,
        '/api/books/42/chapters/101/audio',
      )).resolves.toBe('blob:reader-audio-101');
      expect(createObjectUrl).toHaveBeenCalledTimes(1);

      await expect(readerCacheStatusAsync({
        bookId: 42,
        chapterId: 101,
        nextChapterId: null,
      })).resolves.toMatchObject({
        audioCount: 1,
        audioSizeBytes: 11,
        audioSizeLabel: '1 KB',
      });

      await removeCachedChapterAsync(42, 101);
      expect(await getCachedReaderAudioUrl(42, 101, '/api/books/42/chapters/101/audio')).toBe('');
      expect(revokeObjectUrl).toHaveBeenCalledWith('blob:reader-audio-101');
    } finally {
      Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: originalCreateObjectUrl });
      Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: originalRevokeObjectUrl });
    }
  });

  it('falls back to the cached chapter audio when playlist and API URLs differ', async () => {
    const originalCreateObjectUrl = URL.createObjectURL;
    const createObjectUrl = vi.fn(() => 'blob:reader-audio-variant');
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectUrl });
    const fetcher = vi.fn().mockResolvedValue({
      blob: async () => new Blob(['audio-bytes'], { type: 'audio/mpeg' }),
      headers: new Headers({ 'content-type': 'audio/mpeg' }),
      ok: true,
    }) as unknown as typeof fetch;

    try {
      await cacheReaderAudio(
        42,
        101,
        'http://test/api/books/42/chapters/101/audio',
        fetcher,
      );

      await expect(getCachedReaderAudioUrl(
        42,
        101,
        '/api/books/42/chapters/101/audio',
      )).resolves.toBe('blob:reader-audio-variant');
    } finally {
      await removeCachedChapterAsync(42, 101);
      Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: originalCreateObjectUrl });
    }
  });

  it('returns cached book-level cover asset object URLs for offline chrome', async () => {
    const originalCreateObjectUrl = URL.createObjectURL;
    const originalRevokeObjectUrl = URL.revokeObjectURL;
    const createObjectUrl = vi.fn(() => 'blob:reader-cover-42');
    const revokeObjectUrl = vi.fn();
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectUrl });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revokeObjectUrl });
    const fetcher = vi.fn().mockResolvedValue({
      blob: async () => new Blob(['cover-bytes'], { type: 'image/jpeg' }),
      headers: new Headers({ 'content-type': 'image/jpeg' }),
      ok: true,
    }) as unknown as typeof fetch;
    const getCachedReaderAssetUrl = (
      readerCacheModule as unknown as {
        getCachedReaderAssetUrl?: (bookId: number, chapterId: number, url: string) => Promise<string>;
      }
    ).getCachedReaderAssetUrl;

    try {
      await expect(cacheReaderAssetsFromHtml(
        42,
        0,
        '<img src="/covers/42.jpg" alt="Book cover">',
        fetcher,
      )).resolves.toMatchObject({
        cached: 1,
        failed: 0,
        total: 1,
      });

      expect(typeof getCachedReaderAssetUrl).toBe('function');
      await expect(getCachedReaderAssetUrl?.(42, 0, '/covers/42.jpg')).resolves.toBe('blob:reader-cover-42');
      expect(createObjectUrl).toHaveBeenCalledTimes(1);

      await removeCachedBookAsync(42);
      await expect(getCachedReaderAssetUrl?.(42, 0, '/covers/42.jpg')).resolves.toBe('');
      expect(revokeObjectUrl).toHaveBeenCalledWith('blob:reader-cover-42');
    } finally {
      Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: originalCreateObjectUrl });
      Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: originalRevokeObjectUrl });
    }
  });
});
