import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ReaderDictionaryPack } from '../api/types';
import { getCachedChapterAsync, getCachedReaderAssetUrl } from './readerCache';
import { loadCachedReaderDictionaryPack } from './readerDictionaryCache';
import {
  cacheBookForOffline,
  cacheChapterForOffline,
  loadReaderOfflineManifest,
  removeReaderOfflineManifest,
  removeReaderOfflineManifestChapter,
} from './readerOfflineCache';

describe('readerOfflineCache', () => {
  afterEach(() => {
    window.localStorage.clear();
  });

  it('caches translated chapters, rich assets, audio, and dictionary pack for a whole book', async () => {
    const dictionaryPack: ReaderDictionaryPack = {
      book_id: 42,
      chapter_id: null,
      sources: [{ source: 'offline_dictionary', term: '筑基', target: 'Trúc Cơ' }],
      source_count: 1,
      counts: { builtin: 0, glossary: 0, offline_dictionary: 1, xray: 0 },
      online: { status: 'skipped', error: '', count: 0 },
      generated_at: '2026-06-29T10:00:00Z',
    };
    const client = {
      chapterAudioUrl: vi.fn((bookId: number, chapterId: number) => `/api/books/${bookId}/chapters/${chapterId}/audio`),
      getChapterContent: vi.fn(async (_bookId: number, chapterId: number) => (
        chapterId === 102
          ? { text: 'Rich chapter', html: '<p>Rich chapter</p><img src="/book-assets/42/sword.png" alt="Sword"/>' }
          : null
      )),
      getChapterSource: vi.fn(async (_bookId: number, chapterId: number) => `Raw chapter ${chapterId}`),
      getChapterTranslation: vi.fn(async (_bookId: number, chapterId: number) => (
        chapterId === 101 ? 'Plain chapter' : null
      )),
      getReaderDictionaryPack: vi.fn(async () => dictionaryPack),
    };
    const cacheAssets = vi.fn(async () => ({ cached: 1, failed: 0, sizeBytes: 123, total: 1, urls: ['/book-assets/42/sword.png'] }));
    const cacheAudio = vi.fn(async () => ({ cached: true, failed: false, sizeBytes: 456, url: '/api/books/42/chapters/101/audio' }));

    const summary = await cacheBookForOffline({
      bookId: 42,
      cacheAssets,
      cacheAudio,
      chapters: [
        { audio_path: '/audio/101.mp3', book_id: 42, content_html_path: '', has_translation: true, id: 101 },
        { audio_path: '', book_id: 42, content_html_path: '/content/102.html', has_translation: true, id: 102 },
        { audio_path: '', book_id: 42, content_html_path: '', has_translation: false, id: 103 },
      ],
      client,
    });

    expect(summary).toEqual({
      assetsCached: 1,
      assetsFailed: 0,
      assetsTotal: 1,
      audioCached: 1,
      audioFailed: 0,
      audioTotal: 1,
      chaptersCached: 2,
      chaptersFailed: 0,
      chaptersTotal: 2,
      dictionaryCached: true,
    });
    await expect(getCachedChapterAsync(42, 101)).resolves.toMatchObject({ sourceText: 'Raw chapter 101', text: 'Plain chapter' });
    await expect(getCachedChapterAsync(42, 102)).resolves.toMatchObject({
      html: expect.stringContaining('sword.png'),
      sourceText: 'Raw chapter 102',
    });
    expect(loadCachedReaderDictionaryPack(42, null)).toMatchObject({ source_count: 1 });
    expect(cacheAssets).toHaveBeenCalledWith(42, 102, expect.stringContaining('sword.png'));
    expect(cacheAudio).toHaveBeenCalledWith(42, 101, '/api/books/42/chapters/101/audio');
  });

  it('caches one selected chapter text, assets, audio, and manifest metadata', async () => {
    const chapterPack: ReaderDictionaryPack = {
      book_id: 42,
      chapter_id: 102,
      sources: [{ source: 'xray', term: '韓立', target: 'Hàn Lập' }],
      source_count: 1,
      counts: { builtin: 0, glossary: 0, offline_dictionary: 0, xray: 1 },
      online: { status: 'skipped', error: '', count: 0 },
      generated_at: '2026-06-29T10:30:00Z',
    };
    const client = {
      chapterAudioUrl: vi.fn((bookId: number, chapterId: number) => `/api/books/${bookId}/chapters/${chapterId}/audio`),
      getChapterContent: vi.fn(async () => ({
        html: '<p>Hàn Lập khẽ gật đầu.</p><img src="/book-assets/42/cover.png" alt="cover">',
        text: 'Hàn Lập khẽ gật đầu.',
      })),
      getChapterSource: vi.fn(async () => '韓立微微點頭。'),
      getChapterTranslation: vi.fn(async () => 'fallback translation'),
      getReaderDictionaryPack: vi.fn(async () => chapterPack),
    };
    const cacheAssets = vi.fn(async () => ({ cached: 1, failed: 0, sizeBytes: 321, total: 1, urls: ['/book-assets/42/cover.png'] }));
    const cacheAudio = vi.fn(async () => ({ cached: true, failed: false, sizeBytes: 654, url: '/api/books/42/chapters/102/audio' }));

    const summary = await cacheChapterForOffline({
      audioUrl: '/api/books/42/chapters/102/audio',
      bookId: 42,
      cacheAssets,
      cacheAudio,
      chapter: { audio_path: '/audio/102.mp3', book_id: 42, content_html_path: '/book-assets/42/chapter_102.html', has_translation: true, id: 102 },
      client,
    });

    expect(summary).toEqual({
      assetsCached: 1,
      assetsFailed: 0,
      assetsTotal: 1,
      audioCached: 1,
      audioFailed: 0,
      audioTotal: 1,
      chaptersCached: 1,
      chaptersFailed: 0,
      chaptersTotal: 1,
      dictionaryCached: true,
    });
    await expect(getCachedChapterAsync(42, 102)).resolves.toMatchObject({
      html: expect.stringContaining('cover.png'),
      sourceText: '韓立微微點頭。',
      text: 'Hàn Lập khẽ gật đầu.',
    });
    expect(loadCachedReaderDictionaryPack(42, 102)).toMatchObject({ source_count: 1 });
    expect(cacheAssets).toHaveBeenCalledWith(
      42,
      102,
      expect.stringContaining('cover.png'),
      '/book-assets/42/chapter_102.html',
    );
    expect(cacheAudio).toHaveBeenCalledWith(42, 102, '/api/books/42/chapters/102/audio');
    expect(loadReaderOfflineManifest(42)).toMatchObject({
      bookId: 42,
      chapterIds: [102],
      chapters: [{ cached: true, failed: false, htmlCached: true, id: 102, textCached: true }],
      audio: [{ cached: true, chapterId: 102, failed: false, sizeBytes: 654 }],
      summary: {
        assetsCached: 1,
        assetsFailed: 0,
        assetsTotal: 1,
        audioCached: 1,
        audioFailed: 0,
        audioTotal: 1,
        chaptersCached: 1,
        chaptersFailed: 0,
        chaptersTotal: 1,
        dictionaryCached: true,
      },
    });
  });

  it('keeps translated offline content available when optional source loading fails', async () => {
    const client = {
      chapterAudioUrl: vi.fn(),
      getChapterContent: vi.fn(async () => null),
      getChapterSource: vi.fn(async () => { throw new TypeError('offline'); }),
      getChapterTranslation: vi.fn(async () => 'Bản dịch vẫn được lưu.'),
      getReaderDictionaryPack: vi.fn(async () => { throw new TypeError('offline'); }),
    };

    const summary = await cacheChapterForOffline({
      bookId: 42,
      chapter: { book_id: 42, has_translation: true, id: 104 },
      client,
    });

    expect(summary.chaptersCached).toBe(1);
    expect(summary.chaptersFailed).toBe(0);
    await expect(getCachedChapterAsync(42, 104)).resolves.toMatchObject({
      sourceText: '',
      text: 'Bản dịch vẫn được lưu.',
    });
  });

  it('writes a book-level offline manifest with per-resource coverage and a stable checksum', async () => {
    const dictionaryPack: ReaderDictionaryPack = {
      book_id: 42,
      chapter_id: null,
      sources: [{ source: 'offline_dictionary', term: '筑基', target: 'Trúc Cơ' }],
      source_count: 1,
      counts: { builtin: 0, glossary: 0, offline_dictionary: 1, xray: 0 },
      online: { status: 'skipped', error: '', count: 0 },
      generated_at: '2026-06-29T10:00:00Z',
    };
    const client = {
      chapterAudioUrl: vi.fn((bookId: number, chapterId: number) => `/api/books/${bookId}/chapters/${chapterId}/audio`),
      getChapterContent: vi.fn(async () => ({ text: 'Rich chapter', html: '<p>Rich chapter</p><img src="/book-assets/42/sword.png" alt="Sword"/>' })),
      getChapterTranslation: vi.fn(async () => null),
      getReaderDictionaryPack: vi.fn(async () => dictionaryPack),
    };
    const cacheAssets = vi.fn(async () => ({ cached: 1, failed: 0, sizeBytes: 123, total: 1, urls: ['/book-assets/42/sword.png'] }));
    const cacheAudio = vi.fn(async () => ({ cached: true, failed: false, sizeBytes: 456, url: '/api/books/42/chapters/101/audio' }));

    await cacheBookForOffline({
      bookId: 42,
      cacheAssets,
      cacheAudio,
      chapters: [
        { audio_path: '/audio/101.mp3', book_id: 42, content_html_path: '/content/101.html', has_translation: true, id: 101 },
        { audio_path: '', book_id: 42, content_html_path: '/content/102.html', has_translation: true, id: 102 },
      ],
      client,
    });
    const firstStore = JSON.parse(window.localStorage.getItem('novel-reader-offline-manifest-v1') ?? '{}');

    await cacheBookForOffline({
      bookId: 42,
      cacheAssets,
      cacheAudio,
      chapters: [
        { audio_path: '/audio/101.mp3', book_id: 42, content_html_path: '/content/101.html', has_translation: true, id: 101 },
        { audio_path: '', book_id: 42, content_html_path: '/content/102.html', has_translation: true, id: 102 },
      ],
      client,
    });
    const secondStore = JSON.parse(window.localStorage.getItem('novel-reader-offline-manifest-v1') ?? '{}');

    expect(firstStore['42']).toMatchObject({
      bookId: 42,
      version: 3,
      chapterIds: [101, 102],
      cover: null,
      chapters: [
        { cached: true, failed: false, htmlCached: true, id: 101, textCached: true },
        { cached: true, failed: false, htmlCached: true, id: 102, textCached: true },
      ],
      dictionary: {
        cached: true,
        counts: { builtin: 0, glossary: 0, offline_dictionary: 1, xray: 0 },
        generatedAt: '2026-06-29T10:00:00Z',
        sourceCount: 1,
      },
      assets: [
        {
          cached: 1,
          chapterId: 101,
          failed: 0,
          sizeBytes: 123,
          total: 1,
          urls: ['/book-assets/42/sword.png'],
        },
        {
          cached: 1,
          chapterId: 102,
          failed: 0,
          sizeBytes: 123,
          total: 1,
          urls: ['/book-assets/42/sword.png'],
        },
      ],
      audio: [
        {
          cached: true,
          chapterId: 101,
          failed: false,
          sizeBytes: 456,
          url: '/api/books/42/chapters/101/audio',
        },
      ],
      summary: {
        assetsCached: 2,
        assetsFailed: 0,
        assetsTotal: 2,
        audioCached: 1,
        audioFailed: 0,
        audioTotal: 1,
        chaptersCached: 2,
        chaptersFailed: 0,
        chaptersTotal: 2,
        dictionaryCached: true,
      },
    });
    expect(firstStore['42'].checksum).toMatch(/^[a-f0-9]{8}$/);
    expect(secondStore['42'].checksum).toBe(firstStore['42'].checksum);
  });

  it('removes only the requested book offline manifest', async () => {
    const manifest = {
      assets: [],
      audio: [],
      bookId: 42,
      cachedAt: '2026-06-29T10:00:00Z',
      chapterIds: [101],
      chapters: [{ cached: true, failed: false, htmlCached: true, id: 101, textCached: true }],
      checksum: 'abc12345',
      cover: null,
      dictionary: {
        cached: true,
        counts: { builtin: 1, glossary: 0, offline_dictionary: 0, xray: 0 },
        generatedAt: '2026-06-29T09:59:00Z',
        sourceCount: 1,
      },
      summary: {
        assetsCached: 0,
        assetsFailed: 0,
        assetsTotal: 0,
        audioCached: 0,
        audioFailed: 0,
        audioTotal: 0,
        chaptersCached: 1,
        chaptersFailed: 0,
        chaptersTotal: 1,
        dictionaryCached: true,
      },
      version: 3,
    };
    window.localStorage.setItem('novel-reader-offline-manifest-v1', JSON.stringify({
      42: manifest,
      43: { ...manifest, bookId: 43, checksum: 'def67890' },
    }));

    removeReaderOfflineManifest(42);

    expect(loadReaderOfflineManifest(42)).toBeNull();
    expect(loadReaderOfflineManifest(43)).toMatchObject({ bookId: 43, checksum: 'def67890' });
  });

  it('removes only one chapter from the offline manifest', () => {
    window.localStorage.setItem('novel-reader-offline-manifest-v1', JSON.stringify({
      42: {
        assets: [
          { cached: 1, chapterId: 101, failed: 0, sizeBytes: 10, total: 1, urls: ['/book-assets/42/a.png'] },
          { cached: 1, chapterId: 102, failed: 0, sizeBytes: 20, total: 1, urls: ['/book-assets/42/b.png'] },
        ],
        audio: [
          { cached: true, chapterId: 101, failed: false, sizeBytes: 10, url: '/api/books/42/chapters/101/audio' },
          { cached: true, chapterId: 102, failed: false, sizeBytes: 20, url: '/api/books/42/chapters/102/audio' },
        ],
        bookId: 42,
        cachedAt: '2026-06-29T10:00:00Z',
        chapterIds: [101, 102],
        chapters: [
          { cached: true, failed: false, htmlCached: true, id: 101, textCached: true },
          { cached: true, failed: false, htmlCached: true, id: 102, textCached: true },
        ],
        checksum: 'abc12345',
        cover: null,
        dictionary: {
          cached: true,
          chapterPacks: [
            { cached: true, chapterId: 101, counts: { builtin: 0, glossary: 1, offline_dictionary: 0, xray: 0 }, failed: false, generatedAt: 'now', sourceCount: 1 },
            { cached: true, chapterId: 102, counts: { builtin: 0, glossary: 0, offline_dictionary: 0, xray: 1 }, failed: false, generatedAt: 'now', sourceCount: 1 },
          ],
          counts: { builtin: 0, glossary: 0, offline_dictionary: 0, xray: 0 },
          files: [],
          generatedAt: '',
          sourceCount: 0,
        },
        summary: {
          assetsCached: 2,
          assetsFailed: 0,
          assetsTotal: 2,
          audioCached: 2,
          audioFailed: 0,
          audioTotal: 2,
          chaptersCached: 2,
          chaptersFailed: 0,
          chaptersTotal: 2,
          dictionaryCached: true,
        },
        version: 3,
      },
    }));

    removeReaderOfflineManifestChapter(42, 102);

    expect(loadReaderOfflineManifest(42)).toMatchObject({
      chapterIds: [101],
      chapters: [{ id: 101 }],
      assets: [{ chapterId: 101 }],
      audio: [{ chapterId: 101 }],
      dictionary: { chapterPacks: [{ chapterId: 101 }] },
      summary: {
        assetsCached: 1,
        assetsFailed: 0,
        assetsTotal: 1,
        audioCached: 1,
        audioFailed: 0,
        audioTotal: 1,
        chaptersCached: 1,
        chaptersFailed: 0,
        chaptersTotal: 1,
        dictionaryCached: true,
      },
    });
  });

  it('caches audiobook files from the backend playlist even when chapter rows omit local audio paths', async () => {
    const dictionaryPack: ReaderDictionaryPack = {
      book_id: 42,
      chapter_id: null,
      sources: [],
      source_count: 0,
      counts: { builtin: 0, glossary: 0, offline_dictionary: 0, xray: 0 },
      online: { status: 'skipped', error: '', count: 0 },
      generated_at: '2026-06-29T10:00:00Z',
    };
    const client = {
      chapterAudioUrl: vi.fn((bookId: number, chapterId: number) => `/api/books/${bookId}/chapters/${chapterId}/audio`),
      getBookAudioPlaylist: vi.fn(async () => ({
        book_id: 42,
        chapters: [
          {
            chapter_id: 101,
            chapter_number: 1,
            title: 'Sơn biên tiểu thôn',
            duration_seconds: 120,
            download_url: '/api/books/42/chapters/101/audio/download',
            filename: 'chapter_0001.mp3',
            order: 0,
            size_bytes: 456,
            stream_url: '/api/books/42/chapters/101/audio',
          },
        ],
      })),
      getChapterContent: vi.fn(async () => null),
      getChapterTranslation: vi.fn(async () => 'Plain chapter'),
      getReaderDictionaryPack: vi.fn(async () => dictionaryPack),
    };
    const cacheAudio = vi.fn(async (_bookId: number, chapterId: number, url: string) => ({
      cached: true,
      failed: false,
      sizeBytes: 456,
      url,
    }));

    const summary = await cacheBookForOffline({
      bookId: 42,
      cacheAudio,
      chapters: [
        { audio_path: '', book_id: 42, content_html_path: '', has_translation: true, id: 101 },
      ],
      client,
    });
    const store = JSON.parse(window.localStorage.getItem('novel-reader-offline-manifest-v1') ?? '{}');

    expect(client.getBookAudioPlaylist).toHaveBeenCalledWith(42);
    expect(cacheAudio).toHaveBeenCalledWith(42, 101, '/api/books/42/chapters/101/audio');
    expect(summary).toMatchObject({
      audioCached: 1,
      audioFailed: 0,
      audioTotal: 1,
    });
    expect(store['42']).toMatchObject({
      audio: [
        {
          cached: true,
          chapterId: 101,
          failed: false,
          sizeBytes: 456,
          url: '/api/books/42/chapters/101/audio',
        },
      ],
    });
  });

  it('pre-caches chapter-level dictionary packs for offline per-chapter lookup', async () => {
    const bookDictionaryPack: ReaderDictionaryPack = {
      book_id: 42,
      chapter_id: null,
      sources: [{ source: 'glossary', term: '筑基', target: 'Trúc Cơ' }],
      source_count: 1,
      counts: { builtin: 0, glossary: 1, offline_dictionary: 0, xray: 0 },
      online: { status: 'skipped', error: '', count: 0 },
      generated_at: '2026-06-29T10:00:00Z',
    };
    const chapterDictionaryPack: ReaderDictionaryPack = {
      book_id: 42,
      chapter_id: 101,
      sources: [
        { source: 'xray', term: 'Thanh Ngưu trấn', target: 'Thanh Ngưu trấn', definition: 'Địa danh xuất hiện trong chương 1.' },
      ],
      source_count: 1,
      counts: { builtin: 0, glossary: 0, offline_dictionary: 0, xray: 1 },
      online: { status: 'skipped', error: '', count: 0 },
      generated_at: '2026-06-29T10:01:00Z',
    };
    const client = {
      chapterAudioUrl: vi.fn((bookId: number, chapterId: number) => `/api/books/${bookId}/chapters/${chapterId}/audio`),
      getChapterContent: vi.fn(async () => null),
      getChapterTranslation: vi.fn(async () => 'Plain chapter'),
      getReaderDictionaryPack: vi.fn(async (_bookId: number, options?: { chapterId?: number | null }) => (
        options?.chapterId === 101 ? chapterDictionaryPack : bookDictionaryPack
      )),
    };

    await cacheBookForOffline({
      bookId: 42,
      chapters: [
        { audio_path: '', book_id: 42, content_html_path: '', has_translation: true, id: 101 },
      ],
      client,
    });
    const store = JSON.parse(window.localStorage.getItem('novel-reader-offline-manifest-v1') ?? '{}');

    expect(client.getReaderDictionaryPack).toHaveBeenCalledWith(42, { chapterId: null });
    expect(client.getReaderDictionaryPack).toHaveBeenCalledWith(42, { chapterId: 101 });
    expect(loadCachedReaderDictionaryPack(42, 101)).toMatchObject({
      chapter_id: 101,
      source_count: 1,
      sources: [
        expect.objectContaining({ term: 'Thanh Ngưu trấn' }),
      ],
    });
    expect(store['42']).toMatchObject({
      dictionary: {
        chapterPacks: [
          {
            cached: true,
            chapterId: 101,
            failed: false,
            sourceCount: 1,
          },
        ],
      },
    });
  });

  it('uses the EPUB content path as the asset base when caching rich chapters offline', async () => {
    const dictionaryPack: ReaderDictionaryPack = {
      book_id: 42,
      chapter_id: null,
      sources: [],
      source_count: 0,
      counts: { builtin: 0, glossary: 0, offline_dictionary: 0, xray: 0 },
      online: { status: 'skipped', error: '', count: 0 },
      generated_at: '2026-06-29T10:00:00Z',
    };
    const client = {
      chapterAudioUrl: vi.fn((bookId: number, chapterId: number) => `/api/books/${bookId}/chapters/${chapterId}/audio`),
      getChapterContent: vi.fn(async () => ({
        text: 'Rich chapter',
        html: '<p style="background-image: url(\'./images/bg.jpg\')">Rich chapter</p>',
      })),
      getChapterTranslation: vi.fn(async () => null),
      getReaderDictionaryPack: vi.fn(async () => dictionaryPack),
    };
    const cacheAssets = vi.fn(async () => ({
      cached: 1,
      failed: 0,
      sizeBytes: 123,
      total: 1,
      urls: ['/book-assets/42/OEBPS/images/bg.jpg'],
    }));

    await cacheBookForOffline({
      bookId: 42,
      cacheAssets,
      chapters: [
        {
          audio_path: '',
          book_id: 42,
          content_html_path: '/book-assets/42/OEBPS/chapter-1.xhtml',
          has_translation: true,
          id: 101,
        },
      ],
      client,
    });

    expect(cacheAssets).toHaveBeenCalledWith(
      42,
      101,
      expect.stringContaining('./images/bg.jpg'),
      '/book-assets/42/OEBPS/chapter-1.xhtml',
    );
  });

  it('pre-caches the book cover as a book-level offline asset', async () => {
    const dictionaryPack: ReaderDictionaryPack = {
      book_id: 42,
      chapter_id: null,
      sources: [],
      source_count: 0,
      counts: { builtin: 0, glossary: 0, offline_dictionary: 0, xray: 0 },
      online: { status: 'skipped', error: '', count: 0 },
      generated_at: '2026-06-29T10:00:00Z',
    };
    const client = {
      chapterAudioUrl: vi.fn((bookId: number, chapterId: number) => `/api/books/${bookId}/chapters/${chapterId}/audio`),
      getChapterContent: vi.fn(async () => null),
      getChapterTranslation: vi.fn(async () => 'Plain chapter'),
      getReaderDictionaryPack: vi.fn(async () => dictionaryPack),
    };
    const cacheAssets = vi.fn(async (_bookId: number, chapterId: number, html: string) => ({
      cached: html.includes('/covers/42.jpg') ? 1 : 0,
      failed: 0,
      sizeBytes: html.includes('/covers/42.jpg') ? 321 : 0,
      total: html.includes('/covers/42.jpg') ? 1 : 0,
      urls: html.includes('/covers/42.jpg') ? ['/covers/42.jpg'] : [],
    }));

    const summary = await cacheBookForOffline({
      bookId: 42,
      cacheAssets,
      chapters: [
        { audio_path: '', book_id: 42, content_html_path: '', has_translation: true, id: 101 },
      ],
      client,
      coverUrl: '/covers/42.jpg',
    });
    const store = JSON.parse(window.localStorage.getItem('novel-reader-offline-manifest-v1') ?? '{}');

    expect(cacheAssets).toHaveBeenCalledWith(
      42,
      0,
      '<img src="/covers/42.jpg" alt="Book cover">',
    );
    expect(summary).toMatchObject({
      assetsCached: 1,
      assetsFailed: 0,
      assetsTotal: 1,
    });
    expect(store['42']).toMatchObject({
      cover: {
        cached: true,
        failed: false,
        sizeBytes: 321,
        url: '/covers/42.jpg',
      },
    });
  });

  it('pre-caches uploaded reader dictionary files for offline dictionary restore', async () => {
    const originalCreateObjectUrl = URL.createObjectURL;
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:reader-dictionary') });
    const dictionaryPack: ReaderDictionaryPack = {
      book_id: 42,
      chapter_id: null,
      sources: [{ source: 'offline_dictionary', term: '道心', target: 'đạo tâm' }],
      source_count: 1,
      counts: { builtin: 0, glossary: 0, offline_dictionary: 1, xray: 0 },
      online: { status: 'skipped', error: '', count: 0 },
      generated_at: '2026-06-29T10:00:00Z',
    };
    const client = {
      chapterAudioUrl: vi.fn((bookId: number, chapterId: number) => `/api/books/${bookId}/chapters/${chapterId}/audio`),
      downloadReaderDictionary: vi.fn(async () => ({
        blob: new Blob(['term\ttarget\n道心\tđạo tâm'], { type: 'text/tab-separated-values' }),
        filename: 'reader_cn_vi.tsv',
        mediaType: 'text/tab-separated-values',
      })),
      getChapterContent: vi.fn(async () => null),
      getChapterTranslation: vi.fn(async () => 'Plain chapter'),
      getReaderDictionaryPack: vi.fn(async () => dictionaryPack),
      listReaderDictionaries: vi.fn(async () => [
        { filename: 'reader_cn_vi.tsv', entry_count: 1, size_bytes: 29 },
      ]),
      readerDictionaryDownloadUrl: vi.fn(() => '/api/reader/dictionaries/reader_cn_vi.tsv/download'),
    };

    try {
      await cacheBookForOffline({
        bookId: 42,
        chapters: [
          { audio_path: '', book_id: 42, content_html_path: '', has_translation: true, id: 101 },
        ],
        client,
      });
      const store = JSON.parse(window.localStorage.getItem('novel-reader-offline-manifest-v1') ?? '{}');

      await expect(getCachedReaderAssetUrl(
        42,
        0,
        '/api/reader/dictionaries/reader_cn_vi.tsv/download',
      )).resolves.toBe('blob:reader-dictionary');
      expect(client.listReaderDictionaries).toHaveBeenCalledOnce();
      expect(client.downloadReaderDictionary).toHaveBeenCalledWith('reader_cn_vi.tsv');
      expect(store['42']).toMatchObject({
        dictionary: {
          cached: true,
          files: [
            {
              cached: true,
              failed: false,
              filename: 'reader_cn_vi.tsv',
              sizeBytes: 29,
              url: '/api/reader/dictionaries/reader_cn_vi.tsv/download',
            },
          ],
        },
      });
    } finally {
      Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: originalCreateObjectUrl });
    }
  });
});
