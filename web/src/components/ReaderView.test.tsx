import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ReaderAnnotation } from '../api/types';
import type { Chapter, TranslatedBookSummary } from '../api/types';
import { cacheReaderAudio, getCachedChapterAsync, putCachedChapter } from '../state/readerCache';
import { saveCachedReaderDictionaryResult } from '../state/readerDictionaryCache';
import { chapterMarksKey, loadReaderMarks, saveReaderMarks } from '../state/readerMarks';
import { loadReaderProgressSnapshot, saveReaderProgressSnapshot } from '../state/readerProgress';
import { buildReaderProgressTextAnchor } from '../state/readerProgressAnchor';
import ReaderView, { type ReaderApiClient } from './ReaderView';
import { loadReaderSettings, loadReaderTextMode } from './reader/readerSettings';

const books: TranslatedBookSummary[] = [
  {
    id: 42,
    title: 'Phàm Nhân Tu Tiên',
    author: 'Vong Ngữ',
    source: 'manual',
    source_url: '',
    cover_url: '/covers/pham-nhan.jpg',
    total_chapters: 5,
    translated_chapters: 3,
    audio_chapters: 0,
    failed_chapters: 0,
    qa_low_chapters: 0,
    first_translated_chapter_id: 101,
    latest_translated_chapter_id: 103,
    latest_chapter_number: 3,
    latest_chapter_title: 'Thất Huyền Môn',
    last_activity: '2026-06-20T00:00:00Z',
  },
];

const chapters: Chapter[] = [
  { id: 101, book_id: 42, chapter_number: 1, title: 'Sơn biên tiểu thôn', status: 'translated', audio_path: null, has_translation: true },
  { id: 102, book_id: 42, chapter_number: 2, title: 'Thanh Ngưu trấn', status: 'translated', audio_path: null, has_translation: true },
  { id: 103, book_id: 42, chapter_number: 3, title: 'Thất Huyền Môn', status: 'translated', audio_path: null, has_translation: true },
  { id: 104, book_id: 42, chapter_number: 4, title: 'Chưa dịch', status: 'cleaned', audio_path: null, has_translation: false },
];

const remoteHighlight: ReaderAnnotation = {
  id: 700,
  book_id: 42,
  chapter_id: 102,
  chapter_number: 2,
  chapter_title: 'Thanh Ngưu trấn',
  kind: 'highlight',
  paragraph_index: 0,
  char_start: 0,
  char_end: 22,
  selected_text: 'Hàn Lập khẽ gật đầu.',
  note: '',
  color: 'yellow',
  created_at: '2026-06-28T10:00:00Z',
  updated_at: '2026-06-28T10:00:00Z',
  deleted_at: null,
};

function mockReaderApiClient(overrides: Partial<ReaderApiClient> = {}): ReaderApiClient {
  return {
    chapterAudioDownloadUrl: vi.fn((bookId: number, chapterId: number) => (
      `http://test/api/books/${bookId}/chapters/${chapterId}/audio/download`
    )),
    chapterAudioUrl: vi.fn((bookId: number, chapterId: number) => (
      `http://test/api/books/${bookId}/chapters/${chapterId}/audio`
    )),
    cancelJob: vi.fn().mockResolvedValue(undefined),
    createReaderAnnotation: vi.fn().mockResolvedValue(remoteHighlight),
    deleteReaderAnnotation: vi.fn().mockResolvedValue(undefined),
    deleteReaderDictionary: vi.fn().mockResolvedValue(undefined),
    downloadReaderAnnotations: vi.fn().mockResolvedValue({
      blob: new Blob(['# notes'], { type: 'text/markdown' }),
      filename: 'pham_nhan.annotations.md',
      mediaType: 'text/markdown',
    }),
    downloadAudiobookExport: vi.fn().mockResolvedValue({
      blob: new Blob(['m4b'], { type: 'audio/mp4' }),
      filename: 'pham_nhan.m4b',
      mediaType: 'audio/mp4',
    }),
    enrichReaderXray: vi.fn().mockResolvedValue({
      book_id: 42,
      current_chapter_number: 2,
      spoiler_mode: 'no_spoiler',
      entities: [
        {
          id: 1,
          book_id: 42,
          type: 'character',
          name: 'Hàn Lập',
          aliases: ['韓立'],
          description: 'Nhân vật chính sau khi AI cập nhật.',
          first_chapter_number: 1,
          importance: 100,
          metadata: {},
          mention_count: 1,
          mentions: [],
        },
      ],
      relationships: [
        {
          source: 'Hàn Lập',
          target: 'Thất Huyền Môn',
          relation: 'đệ tử',
          evidence: 'AI xác nhận quan hệ tông môn.',
          chapter_number: 2,
          strength: 0.85,
          source_type: 'ai',
        },
      ],
      faction_tree: [],
      power_rankings: [],
      timeline: [],
    }),
    explainReaderSelection: vi.fn().mockResolvedValue({
      explanation: '筑基 là cảnh giới đặt nền móng tu luyện.',
      terms: [{ source: '筑基', target: 'Trúc Cơ', note: 'cảnh giới tu luyện' }],
    }),
    getChapterContent: vi.fn().mockResolvedValue(null),
    getChapterTranslation: vi.fn((bookId: number, chapterId: number) => Promise.resolve(
      `Bản dịch ${bookId}:${chapterId}`,
    )),
    getQaReport: vi.fn().mockResolvedValue(null),
    getReaderXray: vi.fn().mockResolvedValue({
      book_id: 42,
      current_chapter_number: 2,
      spoiler_mode: 'no_spoiler',
      entities: [
        {
          id: 1,
          book_id: 42,
          type: 'character',
          name: 'Hàn Lập',
          aliases: ['韓立'],
          description: 'Nhân vật chính.',
          first_chapter_number: 1,
          importance: 100,
          metadata: {},
          mention_count: 1,
          mentions: [
            {
              id: 11,
              chapter_id: 101,
              chapter_number: 1,
              paragraph_index: 0,
              mention_text: 'Hàn Lập',
              context: 'Hàn Lập rời thôn.',
              spoiler_level: 0,
            },
          ],
        },
	      ],
	      relationships: [],
	      faction_tree: [],
	      power_rankings: [],
	      timeline: [
        {
          id: 21,
          chapter_id: 101,
          chapter_number: 1,
          event_order: 1,
          title: 'Hàn Lập rời thôn',
          summary: 'Hàn Lập bắt đầu rời Sơn biên tiểu thôn.',
          spoiler_level: 0,
          entities: ['Hàn Lập'],
        },
      ],
    }),
    getReaderDictionaryPack: vi.fn().mockResolvedValue({
      book_id: 42,
      chapter_id: 102,
      sources: [
        {
          source: 'xray',
          term: 'Hàn Lập',
          target: 'Hàn Lập',
          definition: 'Nhân vật chính.',
          category: 'character',
        },
      ],
      source_count: 1,
      counts: {
        builtin: 0,
        glossary: 0,
        offline_dictionary: 0,
        xray: 1,
      },
      online: { status: 'skipped', error: '', count: 0 },
      generated_at: '2026-06-29T10:00:00Z',
    }),
    getBookAudioPlaylist: vi.fn().mockResolvedValue({
      book_id: 42,
      book_title: 'Phàm Nhân Tu Tiên',
      chapters: [],
    }),
    getReaderState: vi.fn().mockResolvedValue({ annotations: [], progress: null }),
    importReaderAnnotations: vi.fn().mockResolvedValue({
      annotations: [],
      summary: { imported: 0, skipped: 0, duplicates: 0, invalid: 0 },
    }),
    listReaderDictionaries: vi.fn().mockResolvedValue([]),
    lookupReaderDictionary: vi.fn().mockResolvedValue({
      book_id: 42,
      chapter_id: 102,
      query: 'Hàn Lập',
      sources: [
        {
          source: 'xray',
          term: 'Hàn Lập',
          target: 'Hàn Lập',
          definition: 'Nhân vật chính.',
          category: 'character',
        },
      ],
      offline_count: 1,
      online: { status: 'ok', error: '', count: 0 },
    }),
    saveReaderProgress: vi.fn().mockResolvedValue({
      book_id: 42,
      chapter_id: 102,
      chapter_number: 2,
      chapter_title: 'Thanh Ngưu trấn',
      mode: 'scroll',
      percent: 67,
      paragraph_index: 0,
      char_offset: 0,
      absolute_char_offset: 0,
      page_index: 0,
      updated_at: '2026-06-28T10:00:00Z',
    }),
    searchBook: vi.fn().mockResolvedValue([]),
    getJobStatus: vi.fn().mockResolvedValue({
      job_id: 'tts-reader-123456',
      job_type: 'tts',
      status: 'running',
      progress: 0,
      total: 1,
      message: 'TTS job queued',
    }),
    getTtsJob: vi.fn().mockResolvedValue({
      job_id: 'tts-reader-123456',
      status: 'running',
      progress: 0,
      chunks: [],
    }),
    retryTtsJob: vi.fn().mockResolvedValue({
      job_id: 'tts-retry-123456',
      status: 'queued',
      message: 'Retry queued',
    }),
    startTtsJob: vi.fn().mockResolvedValue({
      job_id: 'tts-reader-123456',
      status: 'pending',
      message: 'TTS job started',
    }),
    startBookTtsJob: vi.fn().mockResolvedValue({
      job_id: 'tts-book-123456',
      status: 'pending',
      message: 'Audiobook TTS job started',
    }),
    syncReaderState: vi.fn().mockResolvedValue({
      annotations: [],
      conflicts: [],
      progress: null,
      server_time: '2026-06-29T10:12:00Z',
    }),
    updateReaderAnnotation: vi.fn().mockResolvedValue(remoteHighlight),
    uploadReaderDictionary: vi.fn().mockResolvedValue({
      entry_count: 1,
      filename: 'reader_cn_vi.tsv',
      size_bytes: 72,
    }),
    ...overrides,
  };
}

function renderReader(overrides: Partial<Parameters<typeof ReaderView>[0]> = {}) {
  const props = {
    activeBookId: 42,
    books,
    chapters,
    selectedChapter: chapters[1],
    selectedChapterId: 102,
    contentHtml: '',
    textError: '',
    textState: 'ready' as const,
    translationText: 'Hàn Lập khẽ gật đầu.\n\nLục ca, ta cảm tạ huynh.',
    onBackToLibrary: vi.fn(),
    onOpenWorkbench: vi.fn(),
    onSelectBook: vi.fn(),
    onSelectChapter: vi.fn(),
    ...overrides,
  };

  render(<ReaderView {...props} />);
  return props;
}

function latestProgressSyncPayload(apiClient: ReturnType<typeof mockReaderApiClient>) {
  const calls = vi.mocked(apiClient.syncReaderState).mock.calls
    .filter(([, request]) => Boolean(request.progress));
  const lastCall = calls[calls.length - 1];
  return lastCall?.[1].progress;
}

type TestIdleWindow = Window & {
  cancelIdleCallback?: (handle: number) => void;
  requestIdleCallback?: (callback: () => void, options?: { timeout?: number }) => number;
};

type TestResizeObserverConstructor = typeof ResizeObserver;

describe('ReaderView', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    window.localStorage.clear();
  });

  it('opens in immersive mode with reader chrome instead of dashboard panels', async () => {
    renderReader();

    const reader = screen.getByRole('region', { name: 'Trang đọc truyện' });
    expect(reader).toHaveAttribute('data-chrome-visible', 'true');
    expect(screen.getByRole('button', { name: 'Quay lại thư viện' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Mục lục' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Tìm kiếm' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Đánh dấu trang' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cài đặt chữ' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Thêm tùy chọn' })).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Điều khiển đọc' })).not.toBeInTheDocument();
    expect(reader.querySelectorAll('.reader-top-bar')).toHaveLength(1);
    expect(reader.querySelectorAll('.reader-bottom-bar')).toHaveLength(1);
    expect(reader.querySelectorAll('.reader-reference-chapter-nav')).toHaveLength(1);
    expect(reader.querySelectorAll('.reader-text-mode-switcher')).toHaveLength(1);
    expect(reader.querySelectorAll('.reader-reference-actions')).toHaveLength(1);
    expect(screen.getByRole('button', { name: 'Quay lại thư viện' })).toHaveClass('reader-icon-button');
    expect(screen.getByRole('button', { name: 'Chương trước' })).toHaveClass('reader-chapter-nav-button');

    await userEvent.click(screen.getByRole('article', { name: 'Nội dung đọc tiếng Việt' }));
    expect(reader).toHaveAttribute('data-chrome-visible', 'false');

    await userEvent.click(screen.getByRole('article', { name: 'Nội dung đọc tiếng Việt' }));
    expect(reader).toHaveAttribute('data-chrome-visible', 'true');
  });

  it('routes the reference chapter navigation to real reader actions', async () => {
    const props = renderReader();

    await userEvent.click(screen.getByRole('button', { name: 'Chương sau ›' }));
    expect(props.onSelectChapter).toHaveBeenCalledWith(103);

    await userEvent.click(screen.getByRole('button', { name: '‹ Chương trước' }));
    expect(props.onSelectChapter).toHaveBeenCalledWith(101);

    await userEvent.click(screen.getByRole('button', { name: 'Chương 2 / 3' }));
    expect(screen.getByRole('dialog', { name: 'Mục lục' })).toBeInTheDocument();
  });

  it('toggles auto-scroll as a real reader control', async () => {
    renderReader();

    const autoScrollButton = screen.getByRole('button', { name: 'Tự động cuộn' });
    expect(autoScrollButton).not.toBeDisabled();
    expect(autoScrollButton).toHaveAttribute('aria-pressed', 'false');

    await userEvent.click(autoScrollButton);
    expect(autoScrollButton).toHaveAttribute('aria-pressed', 'true');

    await userEvent.click(autoScrollButton);
    expect(autoScrollButton).toHaveAttribute('aria-pressed', 'false');
  });

  it('opens a table of contents drawer with chapter search', async () => {
    const props = renderReader();

    await userEvent.click(screen.getByRole('button', { name: 'Mục lục' }));

    const drawer = screen.getByRole('dialog', { name: 'Mục lục' });
    expect(within(drawer).getByText('Phàm Nhân Tu Tiên')).toBeInTheDocument();
    expect(within(drawer).getByText('Vong Ngữ')).toBeInTheDocument();
    expect(within(drawer).getByText('3 chương đã dịch')).toBeInTheDocument();

    await userEvent.type(within(drawer).getByLabelText('Tìm trong mục lục'), 'thất');
    expect(within(drawer).queryByRole('button', { name: 'Ch. 1 Sơn biên tiểu thôn' })).not.toBeInTheDocument();
    await userEvent.click(within(drawer).getByRole('button', { name: 'Ch. 3 Thất Huyền Môn' }));

    expect(props.onSelectChapter).toHaveBeenCalledWith(103);
    expect(screen.queryByRole('dialog', { name: 'Mục lục' })).not.toBeInTheDocument();
  });

  it('opens an Aa settings sheet and persists reading preferences', async () => {
    renderReader();

    await userEvent.click(screen.getByRole('button', { name: 'Cài đặt chữ' }));
    const sheet = screen.getByRole('dialog', { name: 'Cài đặt đọc' });

    await userEvent.click(within(sheet).getByRole('button', { name: 'Tối' }));
    await userEvent.click(within(sheet).getByRole('button', { name: 'Sans' }));
    fireEvent.change(within(sheet).getByLabelText('Cỡ chữ'), { target: { value: '20' } });
    fireEvent.change(within(sheet).getByLabelText('Giãn dòng'), { target: { value: '2' } });
    fireEvent.change(within(sheet).getByLabelText('Giãn đoạn'), { target: { value: '1.4' } });
    fireEvent.change(within(sheet).getByLabelText('Lề đọc'), { target: { value: '1.2' } });
    fireEvent.change(within(sheet).getByLabelText('Giãn chữ'), { target: { value: '0.35' } });
    fireEvent.change(within(sheet).getByLabelText('Độ đậm'), { target: { value: '550' } });
    await userEvent.click(within(sheet).getByRole('button', { name: 'E-ink' }));
    await userEvent.click(within(sheet).getByRole('checkbox', { name: 'Toàn màn hình' }));

    const article = screen.getByRole('article', { name: 'Nội dung đọc tiếng Việt' });
    expect(screen.getByRole('region', { name: 'Trang đọc truyện' })).toHaveAttribute('data-fullscreen', 'true');
    expect(article).toHaveAttribute('data-theme', 'eink');
    expect(article).toHaveAttribute('data-font', 'sans');
    expect(article).toHaveStyle({
      '--reader-character-spacing': '0.35px',
      '--reader-font-size': '20px',
      '--reader-font-weight': '550',
      '--reader-line-height': '2',
      '--reader-margin-scale': '1.2',
      '--reader-paragraph-spacing': '1.4em',
    });
    expect(loadReaderSettings(window.localStorage)).toMatchObject({
      characterSpacing: 0.35,
      fontFamily: 'sans',
      fontSize: 20,
      fontWeight: 550,
      fullscreen: true,
      lineHeight: 2,
      marginScale: 1.2,
      paragraphSpacing: 1.4,
      theme: 'eink',
    });
  });

  it('renders Vietnamese, raw, and split reading modes without duplicating the default text block', async () => {
    renderReader({
      contentHtml: '<p>原文第一段。</p><p>原文第二段。</p>',
      translationText: 'Hàn Lập khẽ gật đầu.\n\nLục ca, ta cảm tạ huynh.',
    });

    expect(screen.getByRole('button', { name: 'Bản dịch' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Raw' })).not.toBeDisabled();
    expect(screen.getByRole('button', { name: 'Song song' })).not.toBeDisabled();
    expect(screen.getAllByText('Hàn Lập khẽ gật đầu.')).toHaveLength(1);
    expect(screen.queryByText('原文第一段。')).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Raw' }));
    expect(screen.getByRole('article', { name: 'Nội dung raw tiếng Trung' })).toBeInTheDocument();
    expect(screen.getByText('原文第一段。')).toBeInTheDocument();
    expect(screen.queryByText('Hàn Lập khẽ gật đầu.')).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Song song' }));
    expect(screen.getByRole('article', { name: 'Nội dung raw tiếng Trung' })).toBeInTheDocument();
    expect(screen.getByRole('article', { name: 'Nội dung bản dịch tiếng Việt' })).toBeInTheDocument();
    expect(screen.getByText('原文第二段。')).toBeInTheDocument();
    expect(screen.getByText('Lục ca, ta cảm tạ huynh.')).toBeInTheDocument();
  });

  it('persists the selected reader text mode across reader mounts', async () => {
    renderReader({
      contentHtml: '<p>原文第一段。</p>',
      translationText: 'Hàn Lập khẽ gật đầu.',
    });

    await userEvent.click(screen.getByRole('button', { name: 'Raw' }));
    expect(loadReaderTextMode(window.localStorage)).toBe('raw');

    cleanup();
    renderReader({
      contentHtml: '<p>原文第一段。</p>',
      translationText: 'Hàn Lập khẽ gật đầu.',
    });

    expect(screen.getByRole('button', { name: 'Raw' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('article', { name: 'Nội dung raw tiếng Trung' })).toBeInTheDocument();
  });

  it('renders raw-collapsed mode without exposing raw paragraphs until expanded', async () => {
    renderReader({
      contentHtml: '<p>原文第一段。</p><p>原文第二段。</p>',
      translationText: 'Hàn Lập khẽ gật đầu.\n\nLục ca, ta cảm tạ huynh.',
    });

    await userEvent.click(screen.getByRole('button', { name: 'Raw gọn' }));

    expect(screen.getByRole('article', { name: 'Bản dịch tiếng Việt kèm raw gọn' })).toBeInTheDocument();
    expect(screen.getByText('Hàn Lập khẽ gật đầu.')).toBeInTheDocument();
    expect(screen.queryByText('原文第一段。')).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Mở raw đoạn 1' }));

    expect(screen.getByText('原文第一段。')).toBeInTheDocument();
    expect(screen.queryByText('原文第二段。')).not.toBeInTheDocument();
  });

  it('renders QA overlay summary and paragraph badges from the chapter QA report', async () => {
    const apiClient = mockReaderApiClient({
      getQaReport: vi.fn().mockResolvedValue({
        book_id: 42,
        chapter_id: 102,
        overall_status: 'WARNING',
        chinese_leakage_count: 1,
        glossary_violations: [
          {
            paragraph_index: 0,
            source_term: '灵石',
            expected_translation: 'linh thạch',
            reason: 'Locked glossary term was not followed.',
          },
        ],
        quality_score: 6.4,
        repetition_warning: true,
        term_consistency_status: 'FAIL',
        report_json: {
          internal_debug: '<script>alert(1)</script>',
        },
      }),
    });

    renderReader({
      apiClient,
      contentHtml: '<p>青云宗弟子取出灵石。</p><p>他进入筑基境。</p>',
      translationText: 'Đệ tử lấy ra 灵石.\n\nĐệ tử lấy ra 灵石.',
    });

    await waitFor(() => expect(apiClient.getQaReport).toHaveBeenCalledWith(42, 102));
    await userEvent.click(screen.getByRole('button', { name: 'QA' }));

    const summary = screen.getByRole('region', { name: 'Tóm tắt QA chương' });
    expect(within(summary).getByText('WARNING')).toBeInTheDocument();
    expect(within(summary).getByText('Rò chữ Trung: 1')).toBeInTheDocument();
    expect(within(summary).getByText('Vi phạm thuật ngữ: 1')).toBeInTheDocument();
    expect(screen.getAllByText('Rò chữ Trung')).toHaveLength(1);
    expect(screen.getAllByText('Vi phạm thuật ngữ')).toHaveLength(1);
    expect(screen.queryByText(/internal_debug/)).not.toBeInTheDocument();
    expect(screen.queryByText(/<script>/)).not.toBeInTheDocument();
  });

  it('switches between scrolling and paginated reading modes', async () => {
    const props = renderReader({
      translationText: [
        'Đoạn một mở đầu.',
        'Đoạn hai giữ nhịp.',
        'Đoạn ba triển khai.',
        'Đoạn bốn kết cảnh.',
        'Đoạn năm sang trang.',
      ].join('\n\n'),
    });

    await userEvent.click(screen.getByRole('button', { name: 'Cài đặt chữ' }));
    const sheet = screen.getByRole('dialog', { name: 'Cài đặt đọc' });
    await userEvent.click(within(sheet).getByRole('button', { name: 'Trang' }));

    const article = screen.getByRole('article', { name: 'Nội dung đọc tiếng Việt' });
    expect(article).toHaveAttribute('data-reading-mode', 'paginated');
    expect(screen.getByText('Đoạn một mở đầu.')).toBeInTheDocument();
    expect(screen.queryByText('Đoạn năm sang trang.')).not.toBeInTheDocument();
    expect(screen.getByText('Trang 1/2')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Chương sau' }));
    expect(props.onSelectChapter).not.toHaveBeenCalled();
    expect(screen.queryByText('Đoạn một mở đầu.')).not.toBeInTheDocument();
    expect(screen.getByText('Đoạn năm sang trang.')).toBeInTheDocument();
    expect(screen.getByText('Trang 2/2')).toBeInTheDocument();
    await waitFor(() => expect(JSON.parse(window.localStorage.getItem('novel-reader-progress-v1') ?? '{}')).toMatchObject({
      42: {
        chapterId: 102,
        mode: 'paginated',
        pageIndex: 1,
        paragraphIndex: 4,
      },
    }));

    await userEvent.click(within(sheet).getByRole('button', { name: 'Cuộn' }));
    expect(article).toHaveAttribute('data-reading-mode', 'scroll');
    expect(screen.getByText('Đoạn một mở đầu.')).toBeInTheDocument();
    expect(screen.getByText('Đoạn năm sang trang.')).toBeInTheDocument();
  });

  it('uses rich EPUB page-break hints for fallback pagination before viewport measurement is available', async () => {
    const originalResizeObserver = window.ResizeObserver;
    Object.defineProperty(window, 'ResizeObserver', { configurable: true, value: undefined });
    window.localStorage.setItem('novel-reader-settings-v1', JSON.stringify({ readingMode: 'paginated' }));

    try {
      renderReader({
        contentHtml: `
          <p>Trang trước.</p>
          <p style="break-before: page">Trang riêng mở.</p>
          <p>Đoạn giữa.</p>
          <p data-page-break="after">Kết trang.</p>
          <figure data-keep-together="true">
            <img src="/book-assets/42/map.png" alt="Bản đồ cấm địa">
            <figcaption>Bản đồ cấm địa</figcaption>
          </figure>
          <p>Sau hình.</p>
        `,
        translationText: '',
      });

      expect(screen.getByText('Trang 1/4')).toBeInTheDocument();
      expect(screen.getByText('Trang trước.')).toBeInTheDocument();
      expect(screen.queryByText('Trang riêng mở.')).not.toBeInTheDocument();

      await userEvent.click(screen.getByRole('button', { name: 'Chương sau' }));
      expect(screen.getByText('Trang 2/4')).toBeInTheDocument();
      expect(screen.getByText('Trang riêng mở.')).toBeInTheDocument();
      expect(screen.getByText('Kết trang.')).toBeInTheDocument();
      expect(screen.queryByText('Bản đồ cấm địa')).not.toBeInTheDocument();

      await userEvent.click(screen.getByRole('button', { name: 'Chương sau' }));
      expect(screen.getByText('Trang 3/4')).toBeInTheDocument();
      expect(screen.getByText('Bản đồ cấm địa')).toBeInTheDocument();
      expect(screen.queryByText('Sau hình.')).not.toBeInTheDocument();
    } finally {
      Object.defineProperty(window, 'ResizeObserver', { configurable: true, value: originalResizeObserver });
    }
  });

  it('syncs paginated progress percent at the first visible character', async () => {
    window.localStorage.setItem('novel-reader-settings-v1', JSON.stringify({ readingMode: 'paginated' }));
    const apiClient = mockReaderApiClient({
      getReaderState: vi.fn().mockResolvedValue({ annotations: [], progress: null }),
    });
    const pageParagraphs = [
      'Đoạn một mở đầu.',
      'Đoạn hai giữ nhịp.',
      'Đoạn ba triển khai.',
      'Đoạn bốn kết cảnh.',
      'Đoạn năm sang trang.',
    ];
    renderReader({
      apiClient,
      translationText: pageParagraphs.join('\n\n'),
    });

    await waitFor(() => expect(screen.getByText('Trang 1/2')).toBeInTheDocument());
    await waitFor(() => expect(latestProgressSyncPayload(apiClient)).toMatchObject({
      absolute_char_offset: 0,
      char_offset: 0,
      chapter_id: 102,
      mode: 'paginated',
      page_index: 0,
      paragraph_index: 0,
      percent: 0,
    }));
  });

  it('uses measured viewport boundaries for paginated pages when layout is available', async () => {
    const originalResizeObserver = window.ResizeObserver;
    const originalClientHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientHeight');
    const originalGetBoundingClientRect = HTMLElement.prototype.getBoundingClientRect;

    class ImmediateResizeObserver {
      constructor(private readonly callback: ResizeObserverCallback) {}
      disconnect() {}
      observe() {
        this.callback([], this as unknown as ResizeObserver);
      }
      unobserve() {}
    }

    Object.defineProperty(window, 'ResizeObserver', {
      configurable: true,
      value: ImmediateResizeObserver as unknown as TestResizeObserverConstructor,
    });
    Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
      configurable: true,
      get() {
        return this.classList.contains('reader-immersive-main') ? 360 : 0;
      },
    });
    Object.defineProperty(HTMLElement.prototype, 'getBoundingClientRect', {
      configurable: true,
      value() {
        if (this.classList?.contains('reader-paragraph-block')) {
          const index = Number(this.dataset.paragraphIndex ?? 0);
          const top = index * 140;
          return {
            bottom: top + 120,
            height: 120,
            left: 0,
            right: 300,
            top,
            width: 300,
            x: 0,
            y: top,
            toJSON: () => ({}),
          } as DOMRect;
        }
        return {
          bottom: 0,
          height: 0,
          left: 0,
          right: 300,
          top: 0,
          width: 300,
          x: 0,
          y: 0,
          toJSON: () => ({}),
        } as DOMRect;
      },
    });
    Object.defineProperty(document, 'caretPositionFromPoint', {
      configurable: true,
      value: () => {
        const textNode = document
          .querySelector<HTMLElement>('article[aria-label="Nội dung đọc tiếng Việt"] .reader-paragraph-text')
          ?.firstChild;
        return textNode ? { offsetNode: textNode, offset: 12 } : null;
      },
    });
    window.localStorage.setItem('novel-reader-settings-v1', JSON.stringify({ readingMode: 'paginated' }));

    try {
      renderReader({
        translationText: [
          'Đoạn một mở đầu.',
          'Đoạn hai giữ nhịp.',
          'Đoạn ba triển khai.',
          'Đoạn bốn kết cảnh.',
          'Đoạn năm sang trang.',
        ].join('\n\n'),
      });

      await waitFor(() => expect(screen.getByText('Trang 1/3')).toBeInTheDocument());
      const article = screen.getByRole('article', { name: 'Nội dung đọc tiếng Việt' });
      expect(within(article).getByText('Đoạn một mở đầu.')).toBeInTheDocument();
      expect(within(article).getByText('Đoạn hai giữ nhịp.')).toBeInTheDocument();
      expect(within(article).queryByText('Đoạn ba triển khai.')).not.toBeInTheDocument();
    } finally {
      Object.defineProperty(window, 'ResizeObserver', {
        configurable: true,
        value: originalResizeObserver,
      });
      if (originalClientHeight) {
        Object.defineProperty(HTMLElement.prototype, 'clientHeight', originalClientHeight);
      }
      Object.defineProperty(HTMLElement.prototype, 'getBoundingClientRect', {
        configurable: true,
        value: originalGetBoundingClientRect,
      });
    }
  });

  it('splits an oversized paginated paragraph into visible character slices', async () => {
    const originalResizeObserver = window.ResizeObserver;
    const originalClientHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientHeight');
    const originalGetBoundingClientRect = HTMLElement.prototype.getBoundingClientRect;
    const firstPageText = 'a'.repeat(300);
    const secondPageText = 'b'.repeat(300);
    const thirdPageText = 'c'.repeat(300);

    class ImmediateResizeObserver {
      constructor(private readonly callback: ResizeObserverCallback) {}
      disconnect() {}
      observe() {
        this.callback([], this as unknown as ResizeObserver);
      }
      unobserve() {}
    }

    Object.defineProperty(window, 'ResizeObserver', {
      configurable: true,
      value: ImmediateResizeObserver as unknown as TestResizeObserverConstructor,
    });
    Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
      configurable: true,
      get() {
        return this.classList.contains('reader-immersive-main') ? 300 : 0;
      },
    });
    Object.defineProperty(HTMLElement.prototype, 'getBoundingClientRect', {
      configurable: true,
      value() {
        if (this.classList?.contains('reader-paragraph-block')) {
          return {
            bottom: 900,
            height: 900,
            left: 0,
            right: 300,
            top: 0,
            width: 300,
            x: 0,
            y: 0,
            toJSON: () => ({}),
          } as DOMRect;
        }
        return {
          bottom: 0,
          height: 0,
          left: 0,
          right: 300,
          top: 0,
          width: 300,
          x: 0,
          y: 0,
          toJSON: () => ({}),
        } as DOMRect;
      },
    });
    window.localStorage.setItem('novel-reader-settings-v1', JSON.stringify({ readingMode: 'paginated' }));

    try {
      renderReader({
        translationText: firstPageText + secondPageText + thirdPageText,
      });

      await waitFor(() => expect(screen.getByText('Trang 1/3')).toBeInTheDocument());
      const article = screen.getByRole('article', { name: 'Nội dung đọc tiếng Việt' });
      expect(within(article).getByText(firstPageText)).toBeInTheDocument();
      expect(within(article).queryByText(secondPageText)).not.toBeInTheDocument();

      await userEvent.click(screen.getByRole('button', { name: 'Chương sau' }));
      expect(screen.getByText('Trang 2/3')).toBeInTheDocument();
      expect(within(article).getByText(secondPageText)).toBeInTheDocument();
      expect(within(article).queryByText(firstPageText)).not.toBeInTheDocument();
    } finally {
      Object.defineProperty(window, 'ResizeObserver', {
        configurable: true,
        value: originalResizeObserver,
      });
      if (originalClientHeight) {
        Object.defineProperty(HTMLElement.prototype, 'clientHeight', originalClientHeight);
      }
      Object.defineProperty(HTMLElement.prototype, 'getBoundingClientRect', {
        configurable: true,
        value: originalGetBoundingClientRect,
      });
    }
  });

  it('jumps to the exact character-ranged page for marks inside a split paginated paragraph', async () => {
    const originalResizeObserver = window.ResizeObserver;
    const originalClientHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientHeight');
    const originalGetBoundingClientRect = HTMLElement.prototype.getBoundingClientRect;
    const firstPageText = 'a'.repeat(300);
    const secondPageText = 'b'.repeat(300);
    const thirdPageText = 'c'.repeat(300);
    const apiClient = mockReaderApiClient({
      getReaderState: vi.fn().mockResolvedValue({
        progress: null,
        annotations: [
          {
            ...remoteHighlight,
            paragraph_index: 0,
            char_start: firstPageText.length + 12,
            char_end: firstPageText.length + 24,
            selected_text: secondPageText.slice(12, 24),
          },
        ],
      }),
    });

    class ImmediateResizeObserver {
      constructor(private readonly callback: ResizeObserverCallback) {}
      disconnect() {}
      observe() {
        this.callback([], this as unknown as ResizeObserver);
      }
      unobserve() {}
    }

    Object.defineProperty(window, 'ResizeObserver', {
      configurable: true,
      value: ImmediateResizeObserver as unknown as TestResizeObserverConstructor,
    });
    Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
      configurable: true,
      get() {
        return this.classList.contains('reader-immersive-main') ? 300 : 0;
      },
    });
    Object.defineProperty(HTMLElement.prototype, 'getBoundingClientRect', {
      configurable: true,
      value() {
        if (this.classList?.contains('reader-paragraph-block')) {
          return {
            bottom: 900,
            height: 900,
            left: 0,
            right: 300,
            top: 0,
            width: 300,
            x: 0,
            y: 0,
            toJSON: () => ({}),
          } as DOMRect;
        }
        return {
          bottom: 0,
          height: 0,
          left: 0,
          right: 300,
          top: 0,
          width: 300,
          x: 0,
          y: 0,
          toJSON: () => ({}),
        } as DOMRect;
      },
    });
    window.localStorage.setItem('novel-reader-settings-v1', JSON.stringify({ readingMode: 'paginated' }));

    try {
      renderReader({
        apiClient,
        translationText: firstPageText + secondPageText + thirdPageText,
      });

      await waitFor(() => expect(screen.getByText('Trang 1/3')).toBeInTheDocument());
      await userEvent.click(screen.getByRole('button', { name: 'Thêm tùy chọn' }));
      await waitFor(() => expect(screen.getByRole('button', { name: 'Mở dấu đọc' })).not.toBeDisabled());
      await userEvent.click(screen.getByRole('button', { name: 'Mở dấu đọc' }));
      const panel = screen.getByRole('dialog', { name: 'Dấu đọc' });
      await userEvent.click(within(panel).getByRole('button', { name: 'Highlights' }));
      await userEvent.click(within(panel).getByRole('button', { name: 'Đến Ch. 2 đoạn 1' }));

      await waitFor(() => expect(screen.getByText('Trang 2/3')).toBeInTheDocument());
      const article = screen.getByRole('article', { name: 'Nội dung đọc tiếng Việt' });
      expect(within(article).getByText(secondPageText)).toBeInTheDocument();
      expect(within(article).queryByText(firstPageText)).not.toBeInTheDocument();
    } finally {
      Object.defineProperty(window, 'ResizeObserver', {
        configurable: true,
        value: originalResizeObserver,
      });
      if (originalClientHeight) {
        Object.defineProperty(HTMLElement.prototype, 'clientHeight', originalClientHeight);
      }
      Object.defineProperty(HTMLElement.prototype, 'getBoundingClientRect', {
        configurable: true,
        value: originalGetBoundingClientRect,
      });
    }
  });

  it('syncs the exact start character when a paginated page begins inside one block', async () => {
    const originalResizeObserver = window.ResizeObserver;
    const originalClientHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientHeight');
    const originalGetBoundingClientRect = HTMLElement.prototype.getBoundingClientRect;
    const apiClient = mockReaderApiClient({
      getReaderState: vi.fn().mockResolvedValue({ annotations: [], progress: null }),
    });
    const firstPageText = 'a'.repeat(300);
    const secondPageText = 'b'.repeat(300);
    const thirdPageText = 'c'.repeat(300);

    class ImmediateResizeObserver {
      constructor(private readonly callback: ResizeObserverCallback) {}
      disconnect() {}
      observe() {
        this.callback([], this as unknown as ResizeObserver);
      }
      unobserve() {}
    }

    Object.defineProperty(window, 'ResizeObserver', {
      configurable: true,
      value: ImmediateResizeObserver as unknown as TestResizeObserverConstructor,
    });
    Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
      configurable: true,
      get() {
        return this.classList.contains('reader-immersive-main') ? 300 : 0;
      },
    });
    Object.defineProperty(HTMLElement.prototype, 'getBoundingClientRect', {
      configurable: true,
      value() {
        if (this.classList?.contains('reader-paragraph-block')) {
          return {
            bottom: 900,
            height: 900,
            left: 0,
            right: 300,
            top: 0,
            width: 300,
            x: 0,
            y: 0,
            toJSON: () => ({}),
          } as DOMRect;
        }
        return {
          bottom: 0,
          height: 0,
          left: 0,
          right: 300,
          top: 0,
          width: 300,
          x: 0,
          y: 0,
          toJSON: () => ({}),
        } as DOMRect;
      },
    });
    window.localStorage.setItem('novel-reader-settings-v1', JSON.stringify({ readingMode: 'paginated' }));

    try {
      renderReader({
        apiClient,
        translationText: firstPageText + secondPageText + thirdPageText,
      });

      await waitFor(() => expect(screen.getByText('Trang 1/3')).toBeInTheDocument());
      await userEvent.click(screen.getByRole('button', { name: 'Chương sau' }));
      await waitFor(() => expect(screen.getByText('Trang 2/3')).toBeInTheDocument());
      await waitFor(() => expect(latestProgressSyncPayload(apiClient)).toMatchObject({
        absolute_char_offset: 300,
        char_offset: 300,
        chapter_id: 102,
        mode: 'paginated',
        page_index: 1,
        paragraph_index: 0,
      }));
    } finally {
      Object.defineProperty(window, 'ResizeObserver', {
        configurable: true,
        value: originalResizeObserver,
      });
      if (originalClientHeight) {
        Object.defineProperty(HTMLElement.prototype, 'clientHeight', originalClientHeight);
      }
      Object.defineProperty(HTMLElement.prototype, 'getBoundingClientRect', {
        configurable: true,
        value: originalGetBoundingClientRect,
      });
    }
  });

  it('syncs the exact viewport character inside a split paginated page', async () => {
    const originalResizeObserver = window.ResizeObserver;
    const originalClientHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientHeight');
    const originalGetBoundingClientRect = HTMLElement.prototype.getBoundingClientRect;
    const apiClient = mockReaderApiClient({
      getReaderState: vi.fn().mockResolvedValue({ annotations: [], progress: null }),
    });
    const firstPageText = 'a'.repeat(300);
    const secondPageText = 'b'.repeat(300);
    const thirdPageText = 'c'.repeat(300);

    class ImmediateResizeObserver {
      constructor(private readonly callback: ResizeObserverCallback) {}
      disconnect() {}
      observe() {
        this.callback([], this as unknown as ResizeObserver);
      }
      unobserve() {}
    }

    Object.defineProperty(window, 'ResizeObserver', {
      configurable: true,
      value: ImmediateResizeObserver as unknown as TestResizeObserverConstructor,
    });
    Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
      configurable: true,
      get() {
        return this.classList.contains('reader-immersive-main') ? 300 : 0;
      },
    });
    Object.defineProperty(HTMLElement.prototype, 'getBoundingClientRect', {
      configurable: true,
      value() {
        if (this.classList?.contains('reader-immersive-main')) {
          return {
            bottom: 300,
            height: 300,
            left: 0,
            right: 300,
            top: 0,
            width: 300,
            x: 0,
            y: 0,
            toJSON: () => ({}),
          } as DOMRect;
        }
        if (this.classList?.contains('reader-paragraph-block')) {
          return {
            bottom: 900,
            height: 900,
            left: 0,
            right: 300,
            top: 0,
            width: 300,
            x: 0,
            y: 0,
            toJSON: () => ({}),
          } as DOMRect;
        }
        if (this.classList?.contains('reader-paragraph-text')) {
          return {
            bottom: 280,
            height: 280,
            left: 24,
            right: 280,
            top: 0,
            width: 256,
            x: 24,
            y: 0,
            toJSON: () => ({}),
          } as DOMRect;
        }
        return {
          bottom: 0,
          height: 0,
          left: 0,
          right: 300,
          top: 0,
          width: 300,
          x: 0,
          y: 0,
          toJSON: () => ({}),
        } as DOMRect;
      },
    });
    Object.defineProperty(document, 'caretPositionFromPoint', {
      configurable: true,
      value: () => {
        const textNode = document
          .querySelector<HTMLElement>('article[aria-label="Nội dung đọc tiếng Việt"] .reader-paragraph-text')
          ?.firstChild;
        return textNode ? { offsetNode: textNode, offset: 12 } : null;
      },
    });
    window.localStorage.setItem('novel-reader-settings-v1', JSON.stringify({ readingMode: 'paginated' }));

    try {
      renderReader({
        apiClient,
        translationText: firstPageText + secondPageText + thirdPageText,
      });

      await waitFor(() => expect(screen.getByText('Trang 1/3')).toBeInTheDocument());
      await userEvent.click(screen.getByRole('button', { name: 'Chương sau' }));
      await waitFor(() => expect(screen.getByText('Trang 2/3')).toBeInTheDocument());

      await waitFor(() => expect(latestProgressSyncPayload(apiClient)).toMatchObject({
        absolute_char_offset: 312,
        char_offset: 312,
        chapter_id: 102,
        mode: 'paginated',
        page_index: 1,
        paragraph_index: 0,
        percent: 35,
      }));
    } finally {
      Reflect.deleteProperty(document, 'caretPositionFromPoint');
      Object.defineProperty(window, 'ResizeObserver', {
        configurable: true,
        value: originalResizeObserver,
      });
      if (originalClientHeight) {
        Object.defineProperty(HTMLElement.prototype, 'clientHeight', originalClientHeight);
      }
      Object.defineProperty(HTMLElement.prototype, 'getBoundingClientRect', {
        configurable: true,
        value: originalGetBoundingClientRect,
      });
    }
  });

  it('uses geometry fallback for exact split paginated progress when native caret APIs are unavailable', async () => {
    const originalResizeObserver = window.ResizeObserver;
    const originalClientHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientHeight');
    const originalGetBoundingClientRect = HTMLElement.prototype.getBoundingClientRect;
    const originalGetClientRects = Range.prototype.getClientRects;
    const originalRangeGetBoundingClientRect = Range.prototype.getBoundingClientRect;
    const originalCaretPositionFromPoint = (document as Document & {
      caretPositionFromPoint?: (x: number, y: number) => { offsetNode: Node; offset: number } | null;
    }).caretPositionFromPoint;
    const originalCaretRangeFromPoint = (document as Document & {
      caretRangeFromPoint?: (x: number, y: number) => Range | null;
    }).caretRangeFromPoint;
    const apiClient = mockReaderApiClient({
      getReaderState: vi.fn().mockResolvedValue({ annotations: [], progress: null }),
    });
    const firstPageText = 'a'.repeat(300);
    const secondPageText = 'b'.repeat(300);
    const thirdPageText = 'c'.repeat(300);

    class ImmediateResizeObserver {
      constructor(private readonly callback: ResizeObserverCallback) {}
      disconnect() {}
      observe() {
        this.callback([], this as unknown as ResizeObserver);
      }
      unobserve() {}
    }

    Object.defineProperty(window, 'ResizeObserver', {
      configurable: true,
      value: ImmediateResizeObserver as unknown as TestResizeObserverConstructor,
    });
    Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
      configurable: true,
      get() {
        return this.classList.contains('reader-immersive-main') ? 300 : 0;
      },
    });
    Object.defineProperty(HTMLElement.prototype, 'getBoundingClientRect', {
      configurable: true,
      value() {
        if (this.classList?.contains('reader-immersive-main')) {
          return {
            bottom: 300,
            height: 300,
            left: 0,
            right: 300,
            top: 0,
            width: 300,
            x: 0,
            y: 0,
            toJSON: () => ({}),
          } as DOMRect;
        }
        if (this.classList?.contains('reader-paragraph-block')) {
          return {
            bottom: 900,
            height: 900,
            left: 0,
            right: 300,
            top: 0,
            width: 300,
            x: 0,
            y: 0,
            toJSON: () => ({}),
          } as DOMRect;
        }
        if (this.classList?.contains('reader-paragraph-text')) {
          return {
            bottom: 280,
            height: 280,
            left: 24,
            right: 280,
            top: 0,
            width: 256,
            x: 24,
            y: 0,
            toJSON: () => ({}),
          } as DOMRect;
        }
        return {
          bottom: 0,
          height: 0,
          left: 0,
          right: 300,
          top: 0,
          width: 300,
          x: 0,
          y: 0,
          toJSON: () => ({}),
        } as DOMRect;
      },
    });
    Object.defineProperty(Range.prototype, 'getClientRects', {
      configurable: true,
      value(this: Range) {
        const left = 20 + this.startOffset;
        return [{
          bottom: 20,
          height: 20,
          left,
          right: left + 1,
          top: 0,
          width: 1,
          x: left,
          y: 0,
          toJSON: () => ({}),
        }] as unknown as DOMRectList;
      },
    });
    Object.defineProperty(Range.prototype, 'getBoundingClientRect', {
      configurable: true,
      value(this: Range) {
        const left = 20 + this.startOffset;
        return {
          bottom: 20,
          height: 20,
          left,
          right: left + 1,
          top: 0,
          width: 1,
          x: left,
          y: 0,
          toJSON: () => ({}),
        } as DOMRect;
      },
    });
    Reflect.deleteProperty(document, 'caretPositionFromPoint');
    Reflect.deleteProperty(document, 'caretRangeFromPoint');
    window.localStorage.setItem('novel-reader-settings-v1', JSON.stringify({ readingMode: 'paginated' }));

    try {
      renderReader({
        apiClient,
        translationText: firstPageText + secondPageText + thirdPageText,
      });

      await waitFor(() => expect(screen.getByText('Trang 1/3')).toBeInTheDocument());
      await userEvent.click(screen.getByRole('button', { name: 'Chương sau' }));
      await waitFor(() => expect(screen.getByText('Trang 2/3')).toBeInTheDocument());

      await waitFor(() => expect(latestProgressSyncPayload(apiClient)).toMatchObject({
        absolute_char_offset: 312,
        char_offset: 312,
        chapter_id: 102,
        mode: 'paginated',
        page_index: 1,
        paragraph_index: 0,
        percent: 35,
      }));
    } finally {
      Object.defineProperty(window, 'ResizeObserver', {
        configurable: true,
        value: originalResizeObserver,
      });
      if (originalClientHeight) {
        Object.defineProperty(HTMLElement.prototype, 'clientHeight', originalClientHeight);
      }
      Object.defineProperty(HTMLElement.prototype, 'getBoundingClientRect', {
        configurable: true,
        value: originalGetBoundingClientRect,
      });
      Object.defineProperty(Range.prototype, 'getClientRects', {
        configurable: true,
        value: originalGetClientRects,
      });
      Object.defineProperty(Range.prototype, 'getBoundingClientRect', {
        configurable: true,
        value: originalRangeGetBoundingClientRect,
      });
      if (originalCaretPositionFromPoint) {
        Object.defineProperty(document, 'caretPositionFromPoint', {
          configurable: true,
          value: originalCaretPositionFromPoint,
        });
      } else {
        Reflect.deleteProperty(document, 'caretPositionFromPoint');
      }
      if (originalCaretRangeFromPoint) {
        Object.defineProperty(document, 'caretRangeFromPoint', {
          configurable: true,
          value: originalCaretRangeFromPoint,
        });
      } else {
        Reflect.deleteProperty(document, 'caretRangeFromPoint');
      }
    }
  });

  it('saves selected highlight ranges with absolute character offsets on split paginated pages', async () => {
    const originalResizeObserver = window.ResizeObserver;
    const originalClientHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientHeight');
    const originalGetBoundingClientRect = HTMLElement.prototype.getBoundingClientRect;
    const apiClient = mockReaderApiClient({
      getReaderState: vi.fn().mockResolvedValue({ annotations: [], progress: null }),
    });
    const firstPageText = 'a'.repeat(300);
    const secondPageText = 'b'.repeat(300);
    const thirdPageText = 'c'.repeat(300);

    class ImmediateResizeObserver {
      constructor(private readonly callback: ResizeObserverCallback) {}
      disconnect() {}
      observe() {
        this.callback([], this as unknown as ResizeObserver);
      }
      unobserve() {}
    }

    Object.defineProperty(window, 'ResizeObserver', {
      configurable: true,
      value: ImmediateResizeObserver as unknown as TestResizeObserverConstructor,
    });
    Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
      configurable: true,
      get() {
        return this.classList.contains('reader-immersive-main') ? 300 : 0;
      },
    });
    Object.defineProperty(HTMLElement.prototype, 'getBoundingClientRect', {
      configurable: true,
      value() {
        if (this.classList?.contains('reader-paragraph-block')) {
          return {
            bottom: 900,
            height: 900,
            left: 0,
            right: 300,
            top: 0,
            width: 300,
            x: 0,
            y: 0,
            toJSON: () => ({}),
          } as DOMRect;
        }
        return {
          bottom: 0,
          height: 0,
          left: 0,
          right: 300,
          top: 0,
          width: 300,
          x: 0,
          y: 0,
          toJSON: () => ({}),
        } as DOMRect;
      },
    });
    window.localStorage.setItem('novel-reader-settings-v1', JSON.stringify({ readingMode: 'paginated' }));

    try {
      renderReader({
        apiClient,
        translationText: firstPageText + secondPageText + thirdPageText,
      });

      await waitFor(() => expect(screen.getByText('Trang 1/3')).toBeInTheDocument());
      await userEvent.click(screen.getByRole('button', { name: 'Chương sau' }));
      await waitFor(() => expect(screen.getByText('Trang 2/3')).toBeInTheDocument());

      const textNode = screen.getByText(secondPageText).firstChild as Text;
      const startOffset = 7;
      const endOffset = 19;
      const selectedText = secondPageText.slice(startOffset, endOffset);
      vi.spyOn(window, 'getSelection').mockReturnValue({
        anchorNode: textNode,
        focusNode: textNode,
        getRangeAt: () => ({
          commonAncestorContainer: textNode,
          endContainer: textNode,
          endOffset,
          getBoundingClientRect: () => ({
            bottom: 198,
            height: 18,
            left: 120,
            right: 180,
            top: 180,
            width: 60,
            x: 120,
            y: 180,
            toJSON: () => ({}),
          } as DOMRect),
          startContainer: textNode,
          startOffset,
        } as unknown as Range),
        isCollapsed: false,
        rangeCount: 1,
        removeAllRanges: vi.fn(),
        toString: () => selectedText,
      } as unknown as Selection);

      fireEvent.mouseUp(screen.getByRole('article', { name: 'Nội dung đọc tiếng Việt' }));
      await userEvent.click(screen.getByRole('button', { name: 'Highlight đoạn chọn' }));

      expect(apiClient.createReaderAnnotation).toHaveBeenCalledWith(42, 102, expect.objectContaining({
        char_end: 300 + endOffset,
        char_start: 300 + startOffset,
        kind: 'highlight',
        paragraph_index: 0,
        selected_text: selectedText,
      }));
    } finally {
      Object.defineProperty(window, 'ResizeObserver', {
        configurable: true,
        value: originalResizeObserver,
      });
      if (originalClientHeight) {
        Object.defineProperty(HTMLElement.prototype, 'clientHeight', originalClientHeight);
      }
      Object.defineProperty(HTMLElement.prototype, 'getBoundingClientRect', {
        configurable: true,
        value: originalGetBoundingClientRect,
      });
    }
  });

  it('keeps large rich media blocks on standalone paginated pages', async () => {
    const originalResizeObserver = window.ResizeObserver;
    const originalClientHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientHeight');
    const originalGetBoundingClientRect = HTMLElement.prototype.getBoundingClientRect;

    class ImmediateResizeObserver {
      constructor(private readonly callback: ResizeObserverCallback) {}
      disconnect() {}
      observe() {
        this.callback([], this as unknown as ResizeObserver);
      }
      unobserve() {}
    }

    Object.defineProperty(window, 'ResizeObserver', {
      configurable: true,
      value: ImmediateResizeObserver as unknown as TestResizeObserverConstructor,
    });
    Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
      configurable: true,
      get() {
        return this.classList.contains('reader-immersive-main') ? 500 : 0;
      },
    });
    Object.defineProperty(HTMLElement.prototype, 'getBoundingClientRect', {
      configurable: true,
      value() {
        if (this.classList?.contains('reader-paragraph-block')) {
          const index = Number(this.dataset.paragraphIndex ?? 0);
          const top = index === 0 ? 0 : index === 1 ? 132 : 372;
          const bottom = index === 0 ? 120 : index === 1 ? 360 : 460;
          return {
            bottom,
            height: bottom - top,
            left: 0,
            right: 300,
            top,
            width: 300,
            x: 0,
            y: top,
            toJSON: () => ({}),
          } as DOMRect;
        }
        return {
          bottom: 0,
          height: 0,
          left: 0,
          right: 300,
          top: 0,
          width: 300,
          x: 0,
          y: 0,
          toJSON: () => ({}),
        } as DOMRect;
      },
    });
    window.localStorage.setItem('novel-reader-settings-v1', JSON.stringify({ readingMode: 'paginated' }));

    try {
      renderReader({
        contentHtml: [
          '<p>Trước tranh.</p>',
          '<figure><img src="/book-assets/42/sword.png" alt="Kiếm quang"/></figure>',
          '<p>Sau tranh.</p>',
        ].join(''),
        translationText: ['Trước tranh.', 'Kiếm quang', 'Sau tranh.'].join('\n\n'),
      });

      await waitFor(() => expect(screen.getByText('Trang 1/3')).toBeInTheDocument());
      const article = screen.getByRole('article', { name: 'Nội dung đọc tiếng Việt' });
      expect(within(article).getByText('Trước tranh.')).toBeInTheDocument();
      expect(within(article).queryByRole('img', { name: 'Kiếm quang' })).not.toBeInTheDocument();

      await userEvent.click(screen.getByRole('button', { name: 'Chương sau' }));
      expect(screen.getByText('Trang 2/3')).toBeInTheDocument();
      expect(within(article).getByRole('img', { name: 'Kiếm quang' })).toHaveAttribute(
        'src',
        '/book-assets/42/sword.png',
      );
      expect(within(article).queryByText('Sau tranh.')).not.toBeInTheDocument();

      await userEvent.click(screen.getByRole('button', { name: 'Chương sau' }));
      expect(screen.getByText('Trang 3/3')).toBeInTheDocument();
      expect(within(article).getByText('Sau tranh.')).toBeInTheDocument();
    } finally {
      Object.defineProperty(window, 'ResizeObserver', {
        configurable: true,
        value: originalResizeObserver,
      });
      if (originalClientHeight) {
        Object.defineProperty(HTMLElement.prototype, 'clientHeight', originalClientHeight);
      }
      Object.defineProperty(HTMLElement.prototype, 'getBoundingClientRect', {
        configurable: true,
        value: originalGetBoundingClientRect,
      });
    }
  });

  it('keeps oversized rich media blocks on one paginated page instead of duplicating image slices', async () => {
    const originalResizeObserver = window.ResizeObserver;
    const originalClientHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientHeight');
    const originalGetBoundingClientRect = HTMLElement.prototype.getBoundingClientRect;

    class ImmediateResizeObserver {
      constructor(private readonly callback: ResizeObserverCallback) {}
      disconnect() {}
      observe() {
        this.callback([], this as unknown as ResizeObserver);
      }
      unobserve() {}
    }

    Object.defineProperty(window, 'ResizeObserver', {
      configurable: true,
      value: ImmediateResizeObserver as unknown as TestResizeObserverConstructor,
    });
    Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
      configurable: true,
      get() {
        return this.classList.contains('reader-immersive-main') ? 300 : 0;
      },
    });
    Object.defineProperty(HTMLElement.prototype, 'getBoundingClientRect', {
      configurable: true,
      value() {
        if (this.classList?.contains('reader-paragraph-block')) {
          const index = Number(this.dataset.paragraphIndex ?? 0);
          const top = index === 0 ? 0 : index === 1 ? 132 : 1044;
          const bottom = index === 0 ? 120 : index === 1 ? 1032 : 1120;
          return {
            bottom,
            height: bottom - top,
            left: 0,
            right: 300,
            top,
            width: 300,
            x: 0,
            y: top,
            toJSON: () => ({}),
          } as DOMRect;
        }
        return {
          bottom: 0,
          height: 0,
          left: 0,
          right: 300,
          top: 0,
          width: 300,
          x: 0,
          y: 0,
          toJSON: () => ({}),
        } as DOMRect;
      },
    });
    window.localStorage.setItem('novel-reader-settings-v1', JSON.stringify({ readingMode: 'paginated' }));

    try {
      renderReader({
        contentHtml: [
          '<p>Trước tranh dài.</p>',
          '<figure><img src="/book-assets/42/map.png" alt="Bản đồ cấm địa"/></figure>',
          '<p>Sau tranh dài.</p>',
        ].join(''),
        translationText: ['Trước tranh dài.', 'Bản đồ cấm địa', 'Sau tranh dài.'].join('\n\n'),
      });

      await waitFor(() => expect(screen.getByText('Trang 1/3')).toBeInTheDocument());
      const article = screen.getByRole('article', { name: 'Nội dung đọc tiếng Việt' });
      expect(within(article).getByText('Trước tranh dài.')).toBeInTheDocument();

      await userEvent.click(screen.getByRole('button', { name: 'Chương sau' }));
      expect(screen.getByText('Trang 2/3')).toBeInTheDocument();
      expect(within(article).getByRole('img', { name: 'Bản đồ cấm địa' })).toHaveAttribute(
        'src',
        '/book-assets/42/map.png',
      );

      await userEvent.click(screen.getByRole('button', { name: 'Chương sau' }));
      expect(screen.getByText('Trang 3/3')).toBeInTheDocument();
      expect(within(article).getByText('Sau tranh dài.')).toBeInTheDocument();
      expect(within(article).queryByRole('img', { name: 'Bản đồ cấm địa' })).not.toBeInTheDocument();
    } finally {
      Object.defineProperty(window, 'ResizeObserver', {
        configurable: true,
        value: originalResizeObserver,
      });
      if (originalClientHeight) {
        Object.defineProperty(HTMLElement.prototype, 'clientHeight', originalClientHeight);
      }
      Object.defineProperty(HTMLElement.prototype, 'getBoundingClientRect', {
        configurable: true,
        value: originalGetBoundingClientRect,
      });
    }
  });

  it('honors explicit rich HTML page breaks in paginated mode', async () => {
    const originalResizeObserver = window.ResizeObserver;
    const originalClientHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientHeight');
    const originalGetBoundingClientRect = HTMLElement.prototype.getBoundingClientRect;

    class ImmediateResizeObserver {
      constructor(private readonly callback: ResizeObserverCallback) {}
      disconnect() {}
      observe() {
        this.callback([], this as unknown as ResizeObserver);
      }
      unobserve() {}
    }

    Object.defineProperty(window, 'ResizeObserver', {
      configurable: true,
      value: ImmediateResizeObserver as unknown as TestResizeObserverConstructor,
    });
    Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
      configurable: true,
      get() {
        return this.classList.contains('reader-immersive-main') ? 500 : 0;
      },
    });
    Object.defineProperty(HTMLElement.prototype, 'getBoundingClientRect', {
      configurable: true,
      value() {
        if (this.classList?.contains('reader-paragraph-block')) {
          const index = Number(this.dataset.paragraphIndex ?? 0);
          const top = index * 100;
          return {
            bottom: top + 80,
            height: 80,
            left: 0,
            right: 300,
            top,
            width: 300,
            x: 0,
            y: top,
            toJSON: () => ({}),
          } as DOMRect;
        }
        return {
          bottom: 0,
          height: 0,
          left: 0,
          right: 300,
          top: 0,
          width: 300,
          x: 0,
          y: 0,
          toJSON: () => ({}),
        } as DOMRect;
      },
    });
    window.localStorage.setItem('novel-reader-settings-v1', JSON.stringify({ readingMode: 'paginated' }));

    try {
      renderReader({
        contentHtml: [
          '<p>Trước ngắt trang.</p>',
          '<p style="break-before: page">Sau ngắt trang.</p>',
          '<p>Vẫn cùng trang sau.</p>',
        ].join(''),
        translationText: ['Trước ngắt trang.', 'Sau ngắt trang.', 'Vẫn cùng trang sau.'].join('\n\n'),
      });

      await waitFor(() => expect(screen.getByText('Trang 1/2')).toBeInTheDocument());
      const article = screen.getByRole('article', { name: 'Nội dung đọc tiếng Việt' });
      expect(within(article).getByText('Trước ngắt trang.')).toBeInTheDocument();
      expect(within(article).queryByText('Sau ngắt trang.')).not.toBeInTheDocument();

      await userEvent.click(screen.getByRole('button', { name: 'Chương sau' }));
      expect(screen.getByText('Trang 2/2')).toBeInTheDocument();
      expect(within(article).getByText('Sau ngắt trang.')).toBeInTheDocument();
      expect(within(article).getByText('Vẫn cùng trang sau.')).toBeInTheDocument();
    } finally {
      Object.defineProperty(window, 'ResizeObserver', {
        configurable: true,
        value: originalResizeObserver,
      });
      if (originalClientHeight) {
        Object.defineProperty(HTMLElement.prototype, 'clientHeight', originalClientHeight);
      }
      Object.defineProperty(HTMLElement.prototype, 'getBoundingClientRect', {
        configurable: true,
        value: originalGetBoundingClientRect,
      });
    }
  });

  it('keeps EPUB break-inside avoid structures on standalone paginated pages', async () => {
    const originalResizeObserver = window.ResizeObserver;
    const originalClientHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientHeight');
    const originalGetBoundingClientRect = HTMLElement.prototype.getBoundingClientRect;

    class ImmediateResizeObserver {
      constructor(private readonly callback: ResizeObserverCallback) {}
      disconnect() {}
      observe() {
        this.callback([], this as unknown as ResizeObserver);
      }
      unobserve() {}
    }

    Object.defineProperty(window, 'ResizeObserver', {
      configurable: true,
      value: ImmediateResizeObserver as unknown as TestResizeObserverConstructor,
    });
    Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
      configurable: true,
      get() {
        return this.classList.contains('reader-immersive-main') ? 500 : 0;
      },
    });
    Object.defineProperty(HTMLElement.prototype, 'getBoundingClientRect', {
      configurable: true,
      value() {
        if (this.classList?.contains('reader-paragraph-block')) {
          const index = Number(this.dataset.paragraphIndex ?? 0);
          const top = index * 100;
          return {
            bottom: top + 80,
            height: 80,
            left: 0,
            right: 300,
            top,
            width: 300,
            x: 0,
            y: top,
            toJSON: () => ({}),
          } as DOMRect;
        }
        return {
          bottom: 0,
          height: 0,
          left: 0,
          right: 300,
          top: 0,
          width: 300,
          x: 0,
          y: 0,
          toJSON: () => ({}),
        } as DOMRect;
      },
    });
    window.localStorage.setItem('novel-reader-settings-v1', JSON.stringify({ readingMode: 'paginated' }));

    try {
      renderReader({
        contentHtml: [
          '<p>Trước bảng.</p>',
          '<table style="page-break-inside: avoid"><tr><td>Cảnh giới</td><td>Trúc Cơ</td></tr></table>',
          '<p>Sau bảng.</p>',
        ].join(''),
        translationText: ['Trước bảng.', 'Cảnh giới Trúc Cơ', 'Sau bảng.'].join('\n\n'),
      });

      await waitFor(() => expect(screen.getByText('Trang 1/3')).toBeInTheDocument());
      const article = screen.getByRole('article', { name: 'Nội dung đọc tiếng Việt' });
      expect(within(article).getByText('Trước bảng.')).toBeInTheDocument();
      expect(within(article).queryByText('Cảnh giới')).not.toBeInTheDocument();

      await userEvent.click(screen.getByRole('button', { name: 'Chương sau' }));
      expect(screen.getByText('Trang 2/3')).toBeInTheDocument();
      expect(within(article).getByText('Cảnh giới')).toBeInTheDocument();
      expect(within(article).getByText('Trúc Cơ')).toBeInTheDocument();
      expect(within(article).queryByText('Sau bảng.')).not.toBeInTheDocument();

      await userEvent.click(screen.getByRole('button', { name: 'Chương sau' }));
      expect(screen.getByText('Trang 3/3')).toBeInTheDocument();
      expect(within(article).getByText('Sau bảng.')).toBeInTheDocument();
    } finally {
      Object.defineProperty(window, 'ResizeObserver', {
        configurable: true,
        value: originalResizeObserver,
      });
      if (originalClientHeight) {
        Object.defineProperty(HTMLElement.prototype, 'clientHeight', originalClientHeight);
      }
      Object.defineProperty(HTMLElement.prototype, 'getBoundingClientRect', {
        configurable: true,
        value: originalGetBoundingClientRect,
      });
    }
  });

  it('shows offline cache status in the more menu', async () => {
    window.localStorage.setItem('novel-reader-offline-manifest-v1', JSON.stringify({
      42: {
        assets: [
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
            chapterId: 102,
            failed: false,
            sizeBytes: 456,
            url: '/api/books/42/chapters/102/audio',
          },
        ],
        bookId: 42,
        cachedAt: '2026-06-29T10:00:00Z',
        chapterIds: [102, 103],
        chapters: [
          { cached: true, failed: false, htmlCached: true, id: 102, textCached: true },
          { cached: true, failed: false, htmlCached: false, id: 103, textCached: true },
        ],
        checksum: 'abc12345',
        cover: null,
        dictionary: {
          cached: true,
          counts: { builtin: 2, glossary: 4, offline_dictionary: 5, xray: 1 },
          generatedAt: '2026-06-29T09:59:00Z',
          sourceCount: 12,
        },
        summary: {
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
        },
        version: 3,
      },
    }));
    putCachedChapter({
      bookId: 42,
      chapterId: 102,
      html: '',
      sourceText: '',
      text: 'Hàn Lập khẽ gật đầu.',
    });
    putCachedChapter({
      bookId: 42,
      chapterId: 103,
      html: '',
      sourceText: '',
      text: 'Chương sau.',
    });
    renderReader();

    await userEvent.click(screen.getByRole('button', { name: 'Thêm tùy chọn' }));
    const menu = screen.getByRole('dialog', { name: 'Tùy chọn đọc' });

    await waitFor(() => expect(within(menu).getByText('Chương hiện tại đã cache')).toBeInTheDocument());
    expect(within(menu).getByText(/có thể vẫn còn trên thiết bị sau khi đăng xuất/)).toBeInTheDocument();
    expect(within(menu).getByText(/Dùng các nút xóa cache bên dưới/)).toBeInTheDocument();
    expect(within(menu).getByText('Chương sau đã cache')).toBeInTheDocument();
    expect(within(menu).getByText(/^Cache \d+ KB$/)).toBeInTheDocument();
    expect(within(menu).getByText('Manifest 2 chương · abc12345')).toBeInTheDocument();
    expect(within(menu).getByText('Coverage 2/2 chương · 0 lỗi')).toBeInTheDocument();
    expect(within(menu).getByText('Resources 1/1 asset · 1/1 audio · 12 mục từ điển')).toBeInTheDocument();
  });

  it('caches the whole translated book for offline reading from the more menu', async () => {
    const apiClient = mockReaderApiClient();
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      blob: async () => new Blob(['cover'], { type: 'image/jpeg' }),
      headers: new Headers({ 'content-type': 'image/jpeg' }),
      ok: true,
    } as Response);
    renderReader({ apiClient });

    await userEvent.click(screen.getByRole('button', { name: 'Thêm tùy chọn' }));
    await userEvent.click(screen.getByRole('button', { name: 'Cache toàn bộ truyện offline' }));

    expect(await screen.findByText(/Đã cache offline 3\/3 chương · 1\/1 asset/)).toBeInTheDocument();
    expect(globalThis.fetch).toHaveBeenCalledWith('/covers/pham-nhan.jpg', { credentials: 'same-origin' });
    expect(apiClient.getChapterTranslation).toHaveBeenCalledTimes(3);
    expect(apiClient.getReaderDictionaryPack).toHaveBeenCalledWith(42, { chapterId: null });
  });

  it('caches the current chapter and audio for offline reading from the more menu', async () => {
    const apiClient = mockReaderApiClient();
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      blob: async () => new Blob(['audio-bytes'], { type: 'audio/mpeg' }),
      headers: new Headers({ 'content-type': 'audio/mpeg' }),
      ok: true,
    } as Response);
    const audioChapters = chapters.map((chapter) => (
      chapter.id === 103 ? { ...chapter, audio_path: '/tmp/chapter-103.mp3' } : chapter
    ));
    renderReader({
      apiClient,
      chapters: audioChapters,
      selectedChapter: audioChapters[2],
      selectedChapterId: 103,
    });

    await userEvent.click(screen.getByRole('button', { name: 'Thêm tùy chọn' }));
    await userEvent.click(screen.getByRole('button', { name: 'Tải chương hiện tại offline' }));

    expect(await screen.findByText('Đã tải Chương 3 offline · 0/0 asset · 1/1 audio')).toBeInTheDocument();
    expect(apiClient.getChapterTranslation).toHaveBeenCalledWith(42, 103);
    expect(apiClient.getReaderDictionaryPack).toHaveBeenCalledWith(42, { chapterId: 103 });
    expect(globalThis.fetch).toHaveBeenCalledWith('http://test/api/books/42/chapters/103/audio', { credentials: 'include' });
    await expect(getCachedChapterAsync(42, 103)).resolves.toMatchObject({ text: 'Bản dịch 42:103' });
    expect(await screen.findByLabelText('Có sẵn offline')).toBeInTheDocument();
  });

  it('removes the current book offline cache and manifest from the more menu', async () => {
    window.localStorage.setItem('novel-reader-offline-manifest-v1', JSON.stringify({
      42: {
        assets: [],
        audio: [],
        bookId: 42,
        cachedAt: '2026-06-29T10:00:00Z',
        chapterIds: [102],
        chapters: [
          { cached: true, failed: false, htmlCached: true, id: 102, textCached: true },
        ],
        checksum: 'abc12345',
        cover: null,
        dictionary: {
          cached: true,
          counts: { builtin: 2, glossary: 0, offline_dictionary: 0, xray: 0 },
          generatedAt: '2026-06-29T09:59:00Z',
          sourceCount: 2,
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
      },
    }));
    putCachedChapter({
      bookId: 42,
      chapterId: 102,
      html: '',
      sourceText: '',
      text: 'Hàn Lập khẽ gật đầu.',
    });
    renderReader();

    await userEvent.click(screen.getByRole('button', { name: 'Thêm tùy chọn' }));
    const menu = screen.getByRole('dialog', { name: 'Tùy chọn đọc' });
    await waitFor(() => expect(within(menu).getByText('Chương hiện tại đã cache')).toBeInTheDocument());
    expect(within(menu).getByText('Manifest 1 chương · abc12345')).toBeInTheDocument();

    await userEvent.click(within(menu).getByRole('button', { name: 'Xóa cache offline truyện này' }));

    await waitFor(() => expect(within(menu).getByText('Chương hiện tại chưa cache')).toBeInTheDocument());
    expect(within(menu).queryByText('Manifest 1 chương · abc12345')).not.toBeInTheDocument();
    expect(within(menu).getByText('Đã xóa cache offline của truyện này.')).toBeInTheDocument();
    expect(window.localStorage.getItem('novel-reader-offline-manifest-v1')).not.toContain('"42"');
  });

  it('removes only the current chapter offline cache from the more menu', async () => {
    window.localStorage.setItem('novel-reader-offline-manifest-v1', JSON.stringify({
      42: {
        assets: [],
        audio: [],
        bookId: 42,
        cachedAt: '2026-06-29T10:00:00Z',
        chapterIds: [102, 103],
        chapters: [
          { cached: true, failed: false, htmlCached: false, id: 102, textCached: true },
          { cached: true, failed: false, htmlCached: false, id: 103, textCached: true },
        ],
        checksum: 'abc12345',
        cover: null,
        dictionary: {
          cached: true,
          chapterPacks: [],
          counts: { builtin: 2, glossary: 0, offline_dictionary: 0, xray: 0 },
          files: [],
          generatedAt: '2026-06-29T09:59:00Z',
          sourceCount: 2,
        },
        summary: {
          assetsCached: 0,
          assetsFailed: 0,
          assetsTotal: 0,
          audioCached: 0,
          audioFailed: 0,
          audioTotal: 0,
          chaptersCached: 2,
          chaptersFailed: 0,
          chaptersTotal: 2,
          dictionaryCached: true,
        },
        version: 3,
      },
    }));
    putCachedChapter({
      bookId: 42,
      chapterId: 102,
      html: '',
      sourceText: '',
      text: 'Hàn Lập khẽ gật đầu.',
    });
    putCachedChapter({
      bookId: 42,
      chapterId: 103,
      html: '',
      sourceText: '',
      text: 'Chương sau.',
    });
    renderReader();

    await userEvent.click(screen.getByRole('button', { name: 'Thêm tùy chọn' }));
    const menu = screen.getByRole('dialog', { name: 'Tùy chọn đọc' });
    await waitFor(() => expect(within(menu).getByText('Chương hiện tại đã cache')).toBeInTheDocument());
    expect(screen.getByLabelText('Có sẵn offline')).toBeInTheDocument();

    await userEvent.click(within(menu).getByRole('button', { name: 'Xóa cache chương hiện tại' }));

    expect(await within(menu).findByText('Đã xóa cache offline Chương 2.')).toBeInTheDocument();
    await waitFor(() => expect(within(menu).getByText('Chương hiện tại chưa cache')).toBeInTheDocument());
    expect(screen.queryByLabelText('Có sẵn offline')).not.toBeInTheDocument();
    expect(window.localStorage.getItem('novel-reader-offline-manifest-v1')).toContain('"chapterIds":[103]');
    expect(window.localStorage.getItem('novel-reader-cache-v1')).toContain('"chapterId":103');
    expect(window.localStorage.getItem('novel-reader-cache-v1')).not.toContain('"chapterId":102');
  });

  it('uploads an offline reader dictionary from the more menu', async () => {
    const apiClient = mockReaderApiClient({
      getReaderDictionaryPack: vi.fn().mockResolvedValue({
        book_id: 42,
        chapter_id: 102,
        sources: [
          {
            source: 'offline_dictionary',
            provider: 'reader_cn_vi.tsv',
            term: '道心',
            target: 'đạo tâm',
          },
        ],
        source_count: 1,
        counts: {
          builtin: 0,
          glossary: 0,
          offline_dictionary: 1,
          xray: 0,
        },
        online: { status: 'skipped', error: '', count: 0 },
        generated_at: '2026-06-29T10:00:00Z',
      }),
      uploadReaderDictionary: vi.fn().mockResolvedValue({
        entry_count: 1,
        filename: 'reader_cn_vi.tsv',
        size_bytes: 72,
      }),
    });
    renderReader({ apiClient });

    await userEvent.click(screen.getByRole('button', { name: 'Thêm tùy chọn' }));
    const dictionaryFile = new File(
      ['term\ttarget\tdefinition\n道心\tđạo tâm\tTâm cảnh tu đạo.'],
      'reader_cn_vi.tsv',
      { type: 'text/tab-separated-values' },
    );
    const dictionaryInput = screen.getByLabelText('Chọn file từ điển offline');
    expect(dictionaryInput.getAttribute('accept')?.split(',')).toEqual(expect.arrayContaining(['.dsl', '.zip']));
    await userEvent.upload(dictionaryInput, dictionaryFile);

    await waitFor(() => expect(apiClient.uploadReaderDictionary).toHaveBeenCalledWith(dictionaryFile));
    expect(apiClient.getReaderDictionaryPack).toHaveBeenLastCalledWith(42, { chapterId: 102 });
    expect(await screen.findByText('Đã nạp từ điển reader_cn_vi.tsv · 1 mục')).toBeInTheDocument();
  });

  it('lists and deletes offline reader dictionaries from the more menu', async () => {
    const listReaderDictionaries = vi.fn()
      .mockResolvedValueOnce([
        {
          entry_count: 12,
          filename: 'reader_cn_vi.csv',
          size_bytes: 2048,
        },
      ])
      .mockResolvedValueOnce([]);
    const deleteReaderDictionary = vi.fn().mockResolvedValue(undefined);
    const apiClient = {
      ...mockReaderApiClient(),
      deleteReaderDictionary,
      listReaderDictionaries,
    } as ReaderApiClient & {
      deleteReaderDictionary(filename: string): Promise<void>;
      listReaderDictionaries(): Promise<Array<{ entry_count: number; filename: string; size_bytes: number }>>;
    };
    renderReader({ apiClient });

    await userEvent.click(screen.getByRole('button', { name: 'Thêm tùy chọn' }));

    expect(await screen.findByText('reader_cn_vi.csv')).toBeInTheDocument();
    expect(screen.getByText('12 mục · 2 KB')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Xóa từ điển reader_cn_vi.csv' }));

    await waitFor(() => expect(deleteReaderDictionary).toHaveBeenCalledWith('reader_cn_vi.csv'));
    expect(await screen.findByText('Đã xóa từ điển reader_cn_vi.csv')).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText('reader_cn_vi.csv')).not.toBeInTheDocument());
  });

  it('renders long scrolling chapters in chunks and expands near the scroll edge', () => {
    const idleWindow = window as TestIdleWindow;
    const originalRequestIdleCallback = idleWindow.requestIdleCallback;
    const originalCancelIdleCallback = idleWindow.cancelIdleCallback;
    Object.defineProperty(idleWindow, 'requestIdleCallback', {
      configurable: true,
      value: vi.fn(() => 1),
    });
    Object.defineProperty(idleWindow, 'cancelIdleCallback', {
      configurable: true,
      value: vi.fn(),
    });

    try {
      renderReader({
        translationText: Array.from(
          { length: 180 },
          (_, index) => `Đoạn ${index + 1}. Nội dung luyện khí.`,
        ).join('\n\n'),
      });

      expect(screen.getByText('Đoạn 1. Nội dung luyện khí.')).toBeInTheDocument();
      expect(screen.queryByText('Đoạn 120. Nội dung luyện khí.')).not.toBeInTheDocument();
      expect(screen.getByText('Đang nạp thêm đoạn 80/180')).toBeInTheDocument();

      const main = screen.getByRole('main', { name: 'Vùng đọc chính' });
      Object.defineProperty(main, 'scrollHeight', { configurable: true, value: 1600 });
      Object.defineProperty(main, 'clientHeight', { configurable: true, value: 600 });
      Object.defineProperty(main, 'scrollTop', { configurable: true, value: 940 });

      fireEvent.scroll(main);

      expect(screen.getByText('Đoạn 120. Nội dung luyện khí.')).toBeInTheDocument();
    } finally {
      Object.defineProperty(idleWindow, 'requestIdleCallback', {
        configurable: true,
        value: originalRequestIdleCallback,
      });
      Object.defineProperty(idleWindow, 'cancelIdleCallback', {
        configurable: true,
        value: originalCancelIdleCallback,
      });
    }
  });

  it('persists bookmarks, highlights, and notes from instant mode', async () => {
    renderReader();

    await userEvent.click(screen.getByRole('button', { name: 'Đánh dấu trang' }));
    expect(JSON.parse(window.localStorage.getItem('novel-reader-marks-v1') ?? '{}')).toMatchObject({
      '42:102': {
        bookmarked: true,
      },
    });

    await userEvent.click(screen.getByRole('button', { name: 'Cài đặt chữ' }));
    const sheet = screen.getByRole('dialog', { name: 'Cài đặt đọc' });
    await userEvent.click(within(sheet).getByRole('checkbox', { name: 'Instant mode' }));
    await userEvent.click(screen.getByRole('button', { name: 'Đóng cài đặt đọc' }));

    await userEvent.click(screen.getByRole('button', { name: 'Đánh dấu đoạn 1' }));
    expect(screen.getByText('Hàn Lập khẽ gật đầu.').closest('.reader-paragraph-block')).toHaveAttribute(
      'data-highlighted',
      'true',
    );

    await userEvent.click(screen.getByRole('button', { name: 'Ghi chú đoạn 1' }));
    const noteDialog = screen.getByRole('dialog', { name: 'Ghi chú đoạn đọc' });
    await userEvent.type(within(noteDialog).getByLabelText('Nội dung ghi chú'), 'Cần giữ xưng hô cổ trang.');
    await userEvent.click(within(noteDialog).getByRole('button', { name: 'Lưu ghi chú' }));

    expect(JSON.parse(window.localStorage.getItem('novel-reader-marks-v1') ?? '{}')).toMatchObject({
      '42:102': {
        bookmarked: true,
        highlights: [
          {
            paragraphIndex: 0,
            text: 'Hàn Lập khẽ gật đầu.',
          },
        ],
        notes: [
          {
            paragraphIndex: 0,
            note: 'Cần giữ xưng hô cổ trang.',
            text: 'Hàn Lập khẽ gật đầu.',
          },
        ],
      },
    });
    expect(screen.getByRole('button', { name: 'Mở ghi chú đoạn 1' })).toHaveTextContent(
      'Cần giữ xưng hô cổ trang.',
    );
  });

  it('syncs instant highlight character range to the backend', async () => {
    const apiClient = mockReaderApiClient();
    renderReader({ apiClient });

    await userEvent.click(screen.getByRole('button', { name: 'Cài đặt chữ' }));
    const sheet = screen.getByRole('dialog', { name: 'Cài đặt đọc' });
    await userEvent.click(within(sheet).getByRole('checkbox', { name: 'Instant mode' }));
    await userEvent.click(screen.getByRole('button', { name: 'Đóng cài đặt đọc' }));

    await userEvent.click(screen.getByRole('button', { name: 'Đánh dấu đoạn 1' }));

    expect(apiClient.createReaderAnnotation).toHaveBeenCalledWith(42, 102, expect.objectContaining({
      char_end: 'Hàn Lập khẽ gật đầu.'.length,
      char_start: 0,
      kind: 'highlight',
      paragraph_index: 0,
      selected_text: 'Hàn Lập khẽ gật đầu.',
    }));
  });

  it('keeps multiple selected highlights in the same paragraph when their ranges differ', async () => {
    renderReader({
      translationText: 'Hàn Lập khẽ gật đầu rồi nhìn về Thanh Ngưu trấn.',
    });
    const textNode = screen.getByText('Hàn Lập khẽ gật đầu rồi nhìn về Thanh Ngưu trấn.').firstChild as Text;
    const selectText = (selectedText: string) => {
      const startOffset = textNode.textContent?.indexOf(selectedText) ?? 0;
      const endOffset = startOffset + selectedText.length;
      vi.spyOn(window, 'getSelection').mockReturnValue({
        anchorNode: textNode,
        focusNode: textNode,
        getRangeAt: () => ({
          commonAncestorContainer: textNode,
          endContainer: textNode,
          endOffset,
          getBoundingClientRect: () => ({
            bottom: 160,
            height: 20,
            left: 40,
            right: 120,
            top: 140,
            width: 80,
            x: 40,
            y: 140,
            toJSON: () => ({}),
          } as DOMRect),
          startContainer: textNode,
          startOffset,
        } as unknown as Range),
        isCollapsed: false,
        rangeCount: 1,
        removeAllRanges: vi.fn(),
        toString: () => selectedText,
      } as unknown as Selection);
      return { endOffset, startOffset };
    };

    const firstRange = selectText('Hàn Lập');
    fireEvent.mouseUp(screen.getByRole('article', { name: 'Nội dung đọc tiếng Việt' }));
    await userEvent.click(screen.getByRole('button', { name: 'Highlight đoạn chọn' }));

    const secondRange = selectText('Thanh Ngưu trấn');
    fireEvent.mouseUp(screen.getByRole('article', { name: 'Nội dung đọc tiếng Việt' }));
    await userEvent.click(screen.getByRole('button', { name: 'Highlight đoạn chọn' }));

    const marks = JSON.parse(window.localStorage.getItem('novel-reader-marks-v1') ?? '{}');
    expect(marks['42:102'].highlights).toEqual([
      expect.objectContaining({
        charEnd: firstRange.endOffset,
        charStart: firstRange.startOffset,
        paragraphIndex: 0,
        text: 'Hàn Lập',
      }),
      expect.objectContaining({
        charEnd: secondRange.endOffset,
        charStart: secondRange.startOffset,
        paragraphIndex: 0,
        text: 'Thanh Ngưu trấn',
      }),
    ]);
  });

  it('keeps selected text character range when saving a note', async () => {
    const apiClient = mockReaderApiClient();
    renderReader({
      apiClient,
      translationText: 'Hắn đang 筑基.\n\nLinh khí trong động phủ hội tụ.',
    });
    const textNode = screen.getByText('Hắn đang 筑基.').firstChild as Text;
    const selectedText = '筑基';
    const startOffset = textNode.textContent?.indexOf(selectedText) ?? 0;
    const endOffset = startOffset + selectedText.length;
    vi.spyOn(window, 'getSelection').mockReturnValue({
      anchorNode: textNode,
      focusNode: textNode,
      getRangeAt: () => ({
        commonAncestorContainer: textNode,
        endContainer: textNode,
        endOffset,
        getBoundingClientRect: () => ({
          bottom: 198,
          height: 18,
          left: 120,
          right: 160,
          top: 180,
          width: 40,
          x: 120,
          y: 180,
          toJSON: () => ({}),
        } as DOMRect),
        startContainer: textNode,
        startOffset,
      } as unknown as Range),
      isCollapsed: false,
      rangeCount: 1,
      removeAllRanges: vi.fn(),
      toString: () => selectedText,
    } as unknown as Selection);

    fireEvent.mouseUp(screen.getByRole('article', { name: 'Nội dung đọc tiếng Việt' }));
    await userEvent.click(screen.getByRole('button', { name: 'Ghi chú đoạn chọn' }));
    const noteDialog = screen.getByRole('dialog', { name: 'Ghi chú đoạn đọc' });
    await userEvent.type(within(noteDialog).getByLabelText('Nội dung ghi chú'), 'Cảnh giới quan trọng.');
    await userEvent.click(within(noteDialog).getByRole('button', { name: 'Lưu ghi chú' }));

    expect(apiClient.createReaderAnnotation).toHaveBeenCalledWith(42, 102, expect.objectContaining({
      char_end: endOffset,
      char_start: startOffset,
      kind: 'note',
      note: 'Cảnh giới quan trọng.',
      paragraph_index: 0,
      selected_text: selectedText,
    }));
    expect(JSON.parse(window.localStorage.getItem('novel-reader-marks-v1') ?? '{}')).toMatchObject({
      '42:102': {
        notes: [
          {
            charEnd: endOffset,
            charStart: startOffset,
            note: 'Cảnh giới quan trọng.',
            text: selectedText,
          },
        ],
      },
    });
  });

  it('loads DB-backed reader annotations and lists them in the marks panel', async () => {
    const apiClient = mockReaderApiClient({
      getReaderState: vi.fn().mockResolvedValue({
        progress: null,
        annotations: [
          { ...remoteHighlight, id: 699, kind: 'bookmark', paragraph_index: 0, selected_text: 'Chương 2' },
          remoteHighlight,
          { ...remoteHighlight, id: 701, kind: 'note', paragraph_index: 1, note: 'Giữ xưng hô cổ trang.' },
        ],
      }),
    });
    renderReader({ apiClient });

    await waitFor(() => expect(apiClient.getReaderState).toHaveBeenCalledWith(42));
    expect(screen.getByText('Hàn Lập khẽ gật đầu.').closest('.reader-paragraph-block')).toHaveAttribute(
      'data-highlighted',
      'true',
    );

    await userEvent.click(screen.getByRole('button', { name: 'Thêm tùy chọn' }));
    await userEvent.click(screen.getByRole('button', { name: 'Mở dấu đọc' }));
    const panel = screen.getByRole('dialog', { name: 'Dấu đọc' });

    expect(within(panel).getByText('Thanh Ngưu trấn')).toBeInTheDocument();
    await userEvent.click(within(panel).getByRole('button', { name: 'Highlights' }));
    expect(within(panel).getByText('Hàn Lập khẽ gật đầu.')).toBeInTheDocument();
    await userEvent.click(within(panel).getByRole('button', { name: 'Notes' }));
    expect(within(panel).getByText('Giữ xưng hô cổ trang.')).toBeInTheDocument();
  });

  it('keeps failed remote-backed note edits pending for the next reader sync', async () => {
    const remoteNote: ReaderAnnotation = {
      ...remoteHighlight,
      id: 701,
      kind: 'note',
      paragraph_index: 0,
      note: 'Ghi chú cũ.',
      selected_text: 'Hàn Lập khẽ gật đầu.',
      updated_at: '2026-06-28T10:00:00Z',
    };
    const apiClient = mockReaderApiClient({
      getReaderState: vi.fn().mockResolvedValue({
        progress: null,
        annotations: [remoteNote],
      }),
      updateReaderAnnotation: vi.fn().mockRejectedValue(new Error('offline')),
    });
    renderReader({ apiClient });

    await waitFor(() => expect(apiClient.getReaderState).toHaveBeenCalledWith(42));
    await userEvent.click(screen.getByRole('button', { name: 'Cài đặt chữ' }));
    const sheet = screen.getByRole('dialog', { name: 'Cài đặt đọc' });
    await userEvent.click(within(sheet).getByRole('checkbox', { name: 'Instant mode' }));
    await userEvent.click(screen.getByRole('button', { name: 'Đóng cài đặt đọc' }));

    await userEvent.click(screen.getByRole('button', { name: 'Ghi chú đoạn 1' }));
    const noteDialog = screen.getByRole('dialog', { name: 'Ghi chú đoạn đọc' });
    const noteField = within(noteDialog).getByLabelText('Nội dung ghi chú');
    await userEvent.clear(noteField);
    await userEvent.type(noteField, 'Ghi chú sửa khi offline.');
    await userEvent.click(within(noteDialog).getByRole('button', { name: 'Lưu ghi chú' }));

    await waitFor(() => expect(apiClient.updateReaderAnnotation).toHaveBeenCalledWith(42, 701, expect.objectContaining({
      kind: 'note',
      note: 'Ghi chú sửa khi offline.',
      paragraph_index: 0,
    })));
    expect(loadReaderMarks(window.localStorage)[chapterMarksKey(42, 102)].notes[0]).toMatchObject({
      annotationId: 701,
      note: 'Ghi chú sửa khi offline.',
      syncPending: true,
      updatedAt: expect.any(String),
    });
  });

  it('exports the selected reader mark kind from the marks panel', async () => {
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:panel-highlights') });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    const apiClient = mockReaderApiClient({
      downloadReaderAnnotations: vi.fn().mockResolvedValue({
        blob: new Blob(['{"annotation_count":1}'], { type: 'application/json' }),
        filename: 'pham_nhan.highlights.json',
        mediaType: 'application/json',
      }),
      getReaderState: vi.fn().mockResolvedValue({
        progress: null,
        annotations: [remoteHighlight],
      }),
    });
    renderReader({ apiClient });
    await waitFor(() => expect(apiClient.getReaderState).toHaveBeenCalledWith(42));

    await userEvent.click(screen.getByRole('button', { name: 'Thêm tùy chọn' }));
    await userEvent.click(screen.getByRole('button', { name: 'Mở dấu đọc' }));
    const panel = screen.getByRole('dialog', { name: 'Dấu đọc' });
    await userEvent.click(within(panel).getByRole('button', { name: 'Highlights' }));
    await userEvent.click(within(panel).getByRole('button', { name: 'Xuất JSON highlights' }));

    await waitFor(() => expect(apiClient.downloadReaderAnnotations).toHaveBeenCalledWith(
      42,
      'json',
      { kind: 'highlight' },
    ));
    expect(screen.getByText('Đã xuất pham_nhan.highlights.json')).toBeInTheDocument();
  });

  it('syncs local-only reader marks to the backend when loading reader state', async () => {
    window.localStorage.setItem('novel-reader-device-id-v1', 'reader-web-test-device');
    saveReaderMarks({
      [chapterMarksKey(42, 102)]: {
        bookmarked: false,
        highlights: [
          {
            charEnd: 22,
            charStart: 0,
            color: 'green',
            id: 'offline-highlight-1',
            paragraphIndex: 0,
            text: 'Hàn Lập khẽ gật đầu.',
          },
        ],
        notes: [],
      },
    }, window.localStorage);

    const syncedHighlight = {
      ...remoteHighlight,
      id: 777,
      color: 'green',
      updated_at: '2026-06-29T12:00:00Z',
    };
    const apiClient = mockReaderApiClient({
      getReaderState: vi.fn().mockResolvedValue({ annotations: [], progress: null }),
      syncReaderState: vi.fn().mockResolvedValue({
        annotations: [syncedHighlight],
        conflicts: [],
        progress: null,
        server_time: '2026-06-29T12:00:00Z',
      }),
    });

    renderReader({ apiClient });

    await waitFor(() => expect(apiClient.syncReaderState).toHaveBeenCalledWith(42, {
      annotations: [
        expect.objectContaining({
          chapter_id: 102,
          char_end: 22,
          char_start: 0,
          client_id: 'offline-highlight-1',
          color: 'green',
          kind: 'highlight',
          paragraph_index: 0,
          selected_text: 'Hàn Lập khẽ gật đầu.',
        }),
      ],
      device_id: 'reader-web-test-device',
      last_sync_at: null,
    }));

    await waitFor(() => expect(loadReaderMarks(window.localStorage)[chapterMarksKey(42, 102)].highlights[0]).toMatchObject({
      annotationId: 777,
      color: 'green',
      paragraphIndex: 0,
      text: 'Hàn Lập khẽ gật đầu.',
    }));
  });

  it('syncs reader progress with timestamp and a browser device id', async () => {
    window.localStorage.setItem('novel-reader-device-id-v1', 'reader-web-test-device');
    window.localStorage.setItem('novel-reader-sync-v1', JSON.stringify({
      42: '2026-06-29T10:00:00Z',
    }));
    const apiClient = mockReaderApiClient({
      getReaderState: vi.fn().mockResolvedValue({ annotations: [], progress: null }),
    });
    renderReader({ apiClient });

    const syncMock = apiClient.syncReaderState as unknown as ReturnType<typeof vi.fn>;
    await waitFor(() => {
      const progressCall = syncMock.mock.calls.find(([, request]) => Boolean(request.progress));
      expect(progressCall).toBeTruthy();
      expect(progressCall?.[0]).toBe(42);
      expect(progressCall?.[1]).toMatchObject({
        device_id: 'reader-web-test-device',
        last_sync_at: '2026-06-29T10:00:00Z',
        progress: {
          absolute_char_offset: 0,
          chapter_id: 102,
          char_offset: 0,
          mode: 'scroll',
          page_index: 0,
          paragraph_index: 0,
          percent: 100,
          updated_at: expect.any(String),
        },
      });
    });
    expect(apiClient.saveReaderProgress).not.toHaveBeenCalled();
    expect(JSON.parse(window.localStorage.getItem('novel-reader-sync-v1') ?? '{}')).toMatchObject({
      42: '2026-06-29T10:12:00Z',
    });
  });

  it('shows a local remote choice when ongoing reader progress sync reports a server conflict', async () => {
    window.localStorage.setItem('novel-reader-device-id-v1', 'reader-web-test-device');
    window.localStorage.setItem('novel-reader-sync-v1', JSON.stringify({
      42: '2026-06-29T10:00:00Z',
    }));
    const apiClient = mockReaderApiClient({
      getReaderState: vi.fn().mockResolvedValue({ annotations: [], progress: null }),
      syncReaderState: vi.fn().mockResolvedValue({
        annotations: [],
        conflicts: [
          {
            entity: 'progress',
            id: null,
            client_id: 'reader-web-test-device',
            resolution: 'server_won',
            reason: 'server_newer',
          },
        ],
        progress: {
          book_id: 42,
          chapter_id: 103,
          chapter_number: 3,
          chapter_title: 'Thất Huyền Môn',
          absolute_char_offset: 512,
          char_offset: 12,
          mode: 'scroll',
          page_index: 0,
          paragraph_index: 5,
          percent: 64,
          updated_at: '2026-06-29T10:11:00Z',
        },
        server_time: '2026-06-29T10:12:00Z',
      }),
    });
    const props = renderReader({ apiClient });

    await waitFor(() => expect(apiClient.syncReaderState).toHaveBeenCalledWith(42, expect.objectContaining({
      device_id: 'reader-web-test-device',
      progress: expect.objectContaining({ chapter_id: 102 }),
    })));
    await userEvent.click(screen.getByRole('button', { name: 'Thêm tùy chọn' }));
    const menu = screen.getByRole('dialog', { name: 'Tùy chọn đọc' });

    expect(await within(menu).findByText('Sync: tiến độ server mới hơn local')).toBeInTheDocument();
    expect(within(menu).getByRole('group', { name: 'Xử lý xung đột tiến độ' })).toBeInTheDocument();
    await userEvent.click(within(menu).getByRole('button', { name: 'Dùng remote' }));

    expect(loadReaderProgressSnapshot(42, window.localStorage)).toMatchObject({
      absoluteCharOffset: 512,
      chapterId: 103,
      charOffset: 12,
      paragraphIndex: 5,
      percent: 64,
      updatedAt: '2026-06-29T10:11:00Z',
    });
    expect(props.onSelectChapter).toHaveBeenCalledWith(103);
  });

  it('shows reader annotation sync conflict details in the more menu', async () => {
    window.localStorage.setItem('novel-reader-device-id-v1', 'reader-web-test-device');
    saveReaderMarks({
      [chapterMarksKey(42, 102)]: {
        bookmarked: false,
        highlights: [
          {
            charEnd: 22,
            charStart: 0,
            color: 'yellow',
            id: 'local-highlight-1',
            paragraphIndex: 0,
            text: 'Hàn Lập khẽ gật đầu.',
          },
        ],
        notes: [],
      },
    }, window.localStorage);
    const apiClient = mockReaderApiClient({
      getReaderState: vi.fn().mockResolvedValue({ annotations: [], progress: null }),
      syncReaderState: vi.fn().mockResolvedValue({
        annotations: [],
        conflicts: [
          {
            entity: 'annotation',
            id: null,
            client_id: 'local-highlight-1',
            resolution: 'server_won',
            reason: 'server_newer',
            server_annotation: {
              id: 88,
              book_id: 42,
              chapter_id: 102,
              chapter_number: 2,
              chapter_title: 'Thanh Ngưu trấn',
              kind: 'highlight',
              paragraph_index: 0,
              char_start: 0,
              char_end: 24,
              selected_text: 'Server newer highlight',
              note: '',
              color: 'yellow',
              created_at: '2026-06-29T10:00:00Z',
              updated_at: '2026-06-29T10:11:00Z',
              deleted_at: null,
            },
            client_annotation: {
              client_id: 'local-highlight-1',
              chapter_id: 102,
              kind: 'highlight',
              paragraph_index: 0,
              char_start: 0,
              char_end: 22,
              selected_text: 'Hàn Lập khẽ gật đầu.',
              color: 'yellow',
              updated_at: '2026-06-29T10:10:00Z',
            },
          },
        ],
        progress: null,
        server_time: '2026-06-29T10:12:00Z',
      }),
    });
    renderReader({ apiClient });

    await waitFor(() => expect(apiClient.syncReaderState).toHaveBeenCalledWith(42, expect.objectContaining({
      annotations: expect.arrayContaining([
        expect.objectContaining({ client_id: 'local-highlight-1', kind: 'highlight' }),
      ]),
      device_id: 'reader-web-test-device',
    })));
    await userEvent.click(screen.getByRole('button', { name: 'Thêm tùy chọn' }));
    const menu = screen.getByRole('dialog', { name: 'Tùy chọn đọc' });

    expect(within(menu).getByText('Sync: 1 xung đột dấu đọc')).toBeInTheDocument();
    expect(within(menu).getByText('local-highlight-1 · server_newer · server_won')).toBeInTheDocument();
    expect(within(menu).getByText('Server: Server newer highlight')).toBeInTheDocument();
    expect(within(menu).getByText('Local: Hàn Lập khẽ gật đầu.')).toBeInTheDocument();
  });

  it('resolves a reader annotation sync conflict by resending the local mark', async () => {
    window.localStorage.setItem('novel-reader-device-id-v1', 'reader-web-test-device');
    saveReaderMarks({
      [chapterMarksKey(42, 102)]: {
        bookmarked: false,
        highlights: [
          {
            charEnd: 22,
            charStart: 0,
            color: 'yellow',
            id: 'local-highlight-1',
            paragraphIndex: 0,
            text: 'Hàn Lập khẽ gật đầu.',
          },
        ],
        notes: [],
      },
    }, window.localStorage);
    const apiClient = mockReaderApiClient({
      getReaderState: vi.fn().mockResolvedValue({ annotations: [], progress: null }),
      syncReaderState: vi.fn()
        .mockResolvedValue({
          annotations: [],
          conflicts: [],
          progress: null,
          server_time: '2026-06-29T10:13:00Z',
        })
        .mockResolvedValueOnce({
          annotations: [],
          conflicts: [
            {
              entity: 'annotation',
              id: null,
              client_id: 'local-highlight-1',
              resolution: 'server_won',
              reason: 'server_newer',
            },
          ],
          progress: null,
          server_time: '2026-06-29T10:12:00Z',
        })
        .mockResolvedValueOnce({
          annotations: [
            {
              ...remoteHighlight,
              id: 778,
              client_id: 'local-highlight-1',
              updated_at: '2026-06-29T10:13:00Z',
            },
          ],
          conflicts: [],
          progress: null,
          server_time: '2026-06-29T10:13:00Z',
        }),
    });
    renderReader({ apiClient });

    await waitFor(() => expect(apiClient.syncReaderState).toHaveBeenCalledWith(42, expect.objectContaining({
      annotations: expect.arrayContaining([
        expect.objectContaining({ client_id: 'local-highlight-1', kind: 'highlight' }),
      ]),
    })));
    await userEvent.click(screen.getByRole('button', { name: 'Thêm tùy chọn' }));
    const menu = screen.getByRole('dialog', { name: 'Tùy chọn đọc' });
    await userEvent.click(within(menu).getByRole('button', { name: 'Dùng local cho local-highlight-1' }));

    await waitFor(() => {
      const annotationSyncCalls = vi.mocked(apiClient.syncReaderState).mock.calls
        .filter(([, request]) => request.annotations?.some((annotation) => annotation.client_id === 'local-highlight-1'));
      expect(annotationSyncCalls).toHaveLength(2);
      expect(annotationSyncCalls[1]?.[1]).toMatchObject({
        annotations: [
          expect.objectContaining({
            client_id: 'local-highlight-1',
            kind: 'highlight',
            selected_text: 'Hàn Lập khẽ gật đầu.',
            updated_at: expect.any(String),
          }),
        ],
        device_id: 'reader-web-test-device',
        last_sync_at: expect.any(String),
      });
    });
    expect(await within(menu).findByText('Sync: đã dùng local cho dấu đọc')).toBeInTheDocument();
  });

  it('resolves a reader annotation sync conflict by accepting the server mark', async () => {
    window.localStorage.setItem('novel-reader-device-id-v1', 'reader-web-test-device');
    saveReaderMarks({
      [chapterMarksKey(42, 102)]: {
        bookmarked: false,
        highlights: [
          {
            charEnd: 22,
            charStart: 0,
            clientId: 'local-highlight-1',
            color: 'yellow',
            id: 'local-highlight-1',
            paragraphIndex: 0,
            syncPending: true,
            text: 'Hàn Lập khẽ gật đầu.',
          },
        ],
        notes: [],
      },
    }, window.localStorage);
    const apiClient = mockReaderApiClient({
      getReaderState: vi.fn().mockResolvedValue({ annotations: [], progress: null }),
      syncReaderState: vi.fn().mockResolvedValue({
        annotations: [],
        conflicts: [
          {
            entity: 'annotation',
            id: null,
            client_id: 'local-highlight-1',
            resolution: 'server_won',
            reason: 'server_newer',
            server_annotation: {
              id: 88,
              book_id: 42,
              chapter_id: 102,
              chapter_number: 2,
              chapter_title: 'Thanh Ngưu trấn',
              kind: 'highlight',
              paragraph_index: 0,
              char_start: 0,
              char_end: 24,
              selected_text: 'Server newer highlight',
              note: '',
              color: 'green',
              created_at: '2026-06-29T10:00:00Z',
              updated_at: '2026-06-29T10:11:00Z',
              deleted_at: null,
            },
            client_annotation: {
              client_id: 'local-highlight-1',
              chapter_id: 102,
              kind: 'highlight',
              paragraph_index: 0,
              char_start: 0,
              char_end: 22,
              selected_text: 'Hàn Lập khẽ gật đầu.',
              color: 'yellow',
              updated_at: '2026-06-29T10:10:00Z',
            },
          },
        ],
        progress: null,
        server_time: '2026-06-29T10:12:00Z',
      }),
    });
    renderReader({ apiClient });

    await waitFor(() => expect(apiClient.syncReaderState).toHaveBeenCalledWith(42, expect.objectContaining({
      annotations: expect.arrayContaining([
        expect.objectContaining({ client_id: 'local-highlight-1', kind: 'highlight' }),
      ]),
    })));
    await userEvent.click(screen.getByRole('button', { name: 'Thêm tùy chọn' }));
    const menu = screen.getByRole('dialog', { name: 'Tùy chọn đọc' });
    await userEvent.click(within(menu).getByRole('button', { name: 'Dùng server cho local-highlight-1' }));

    expect(await within(menu).findByText('Sync: đã dùng server cho dấu đọc')).toBeInTheDocument();
    expect(within(menu).queryByText('local-highlight-1 · server_newer · server_won')).not.toBeInTheDocument();
    expect(loadReaderMarks(window.localStorage)[chapterMarksKey(42, 102)]?.highlights).toEqual([
      expect.objectContaining({
        annotationId: 88,
        color: 'green',
        text: 'Server newer highlight',
        updatedAt: '2026-06-29T10:11:00Z',
      }),
    ]);
  });

  it('keeps newer local reader progress when remote state is stale', async () => {
    saveReaderProgressSnapshot(42, 103, 78, 100, window.localStorage, {
      absoluteCharOffset: 442,
      charOffset: 42,
      mode: 'scroll',
      pageIndex: 0,
      paragraphIndex: 4,
      updatedAt: '2026-06-29T10:10:00Z',
    });
    const apiClient = mockReaderApiClient({
      getReaderState: vi.fn().mockResolvedValue({
        annotations: [],
        progress: {
          book_id: 42,
          chapter_id: 101,
          chapter_number: 1,
          chapter_title: 'Sơn biên tiểu thôn',
          char_offset: 7,
          absolute_char_offset: 32,
          mode: 'scroll',
          page_index: 0,
          paragraph_index: 1,
          percent: 20,
          updated_at: '2026-06-29T10:00:00Z',
        },
      }),
    });

    const props = renderReader({ apiClient });

    await waitFor(() => expect(apiClient.getReaderState).toHaveBeenCalledWith(42));
    expect(loadReaderProgressSnapshot(42, window.localStorage)).toMatchObject({
      absoluteCharOffset: 442,
      chapterId: 103,
      charOffset: 42,
      paragraphIndex: 4,
      percent: 78,
      updatedAt: '2026-06-29T10:10:00Z',
    });

    await userEvent.click(screen.getByRole('button', { name: 'Thêm tùy chọn' }));
    const menu = screen.getByRole('dialog', { name: 'Tùy chọn đọc' });
    expect(within(menu).getByText('Sync: giữ tiến độ local mới hơn remote')).toBeInTheDocument();
    expect(within(menu).getByRole('button', { name: 'Dùng local' })).toBeInTheDocument();
    await userEvent.click(within(menu).getByRole('button', { name: 'Dùng remote' }));

    expect(loadReaderProgressSnapshot(42, window.localStorage)).toMatchObject({
      absoluteCharOffset: 32,
      chapterId: 101,
      charOffset: 7,
      paragraphIndex: 1,
      percent: 20,
      updatedAt: '2026-06-29T10:00:00Z',
    });
    expect(props.onSelectChapter).toHaveBeenCalledWith(101);
  });

  it('syncs newer local reader progress when the user resolves the conflict with local', async () => {
    window.localStorage.setItem('novel-reader-device-id-v1', 'reader-web-test-device');
    saveReaderProgressSnapshot(42, 103, 78, 100, window.localStorage, {
      absoluteCharOffset: 442,
      charOffset: 42,
      mode: 'scroll',
      pageIndex: 0,
      paragraphIndex: 4,
      updatedAt: '2026-06-29T10:10:00Z',
    });
    const apiClient = mockReaderApiClient({
      getReaderState: vi.fn().mockResolvedValue({
        annotations: [],
        progress: {
          book_id: 42,
          chapter_id: 101,
          chapter_number: 1,
          chapter_title: 'Sơn biên tiểu thôn',
          char_offset: 7,
          absolute_char_offset: 32,
          mode: 'scroll',
          page_index: 0,
          paragraph_index: 1,
          percent: 20,
          updated_at: '2026-06-29T10:00:00Z',
        },
      }),
    });

    renderReader({ apiClient });

    await waitFor(() => expect(apiClient.getReaderState).toHaveBeenCalledWith(42));
    await userEvent.click(screen.getByRole('button', { name: 'Thêm tùy chọn' }));
    const menu = screen.getByRole('dialog', { name: 'Tùy chọn đọc' });
    await userEvent.click(within(menu).getByRole('button', { name: 'Dùng local' }));

    await waitFor(() => expect(apiClient.syncReaderState).toHaveBeenCalledWith(42, {
      device_id: 'reader-web-test-device',
      last_sync_at: '2026-06-29T10:12:00Z',
      progress: {
        absolute_char_offset: 442,
        chapter_id: 103,
        char_offset: 42,
        mode: 'scroll',
        page_index: 0,
        paragraph_index: 4,
        percent: 78,
        updated_at: '2026-06-29T10:10:00Z',
      },
    }));
    expect(await within(menu).findByText('Sync: đã dùng tiến độ local')).toBeInTheDocument();
  });

  it('explains selected text from the reader without changing translation text', async () => {
    const apiClient = mockReaderApiClient();
    renderReader({
      apiClient,
      translationText: 'Hắn đang 筑基.\n\nLinh khí trong động phủ hội tụ.',
    });
    const textNode = screen.getByText('Hắn đang 筑基.').firstChild as Text;
    const removeAllRanges = vi.fn();
    vi.spyOn(window, 'getSelection').mockReturnValue({
      anchorNode: textNode,
      focusNode: textNode,
      getRangeAt: () => ({
        commonAncestorContainer: textNode,
        getBoundingClientRect: () => ({
          bottom: 198,
          height: 18,
          left: 120,
          right: 160,
          top: 180,
          width: 40,
          x: 120,
          y: 180,
          toJSON: () => ({}),
        } as DOMRect),
      } as unknown as Range),
      isCollapsed: false,
      rangeCount: 1,
      removeAllRanges,
      toString: () => '筑基',
    } as unknown as Selection);

    fireEvent.mouseUp(screen.getByRole('article', { name: 'Nội dung đọc tiếng Việt' }));
    await userEvent.click(screen.getByRole('button', { name: 'Giải thích đoạn chọn' }));

    expect(apiClient.explainReaderSelection).toHaveBeenCalledWith(42, 102, {
      context_after: 'Linh khí trong động phủ hội tụ.',
      context_before: '',
      spoiler_mode: 'no_spoiler',
      text: '筑基',
    });
    expect(removeAllRanges).toHaveBeenCalled();
    expect(await screen.findByRole('dialog', { name: 'AI đọc truyện' })).toBeInTheDocument();
    expect(screen.getByText('Trúc Cơ')).toBeInTheDocument();
    expect(screen.getByText('Hắn đang 筑基.')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Đóng AI đọc truyện' }));
    fireEvent.mouseUp(screen.getByRole('article', { name: 'Nội dung đọc tiếng Việt' }));
    await userEvent.click(screen.getByRole('button', { name: 'Giải thích đoạn chọn' }));

    expect(apiClient.explainReaderSelection).toHaveBeenCalledTimes(1);
    expect(await screen.findByText('Kết quả đã lưu trong cache.')).toBeInTheDocument();
  });

  it('looks up selected text in the reader dictionary offline-first', async () => {
    const apiClient = mockReaderApiClient();
    renderReader({
      apiClient,
      translationText: 'Hàn Lập bước vào Thất Huyền Môn.\n\nLinh khí lạnh thấm qua thềm đá.',
    });
    const textNode = screen.getByText('Hàn Lập bước vào Thất Huyền Môn.').firstChild as Text;
    vi.spyOn(window, 'getSelection').mockReturnValue({
      anchorNode: textNode,
      focusNode: textNode,
      getRangeAt: () => ({
        commonAncestorContainer: textNode,
        getBoundingClientRect: () => ({
          bottom: 198,
          height: 18,
          left: 120,
          right: 174,
          top: 180,
          width: 54,
          x: 120,
          y: 180,
          toJSON: () => ({}),
        } as DOMRect),
        startContainer: textNode,
        startOffset: 0,
        endContainer: textNode,
        endOffset: 6,
      } as unknown as Range),
      isCollapsed: false,
      rangeCount: 1,
      removeAllRanges: vi.fn(),
      toString: () => 'Hàn Lập',
    } as unknown as Selection);

    fireEvent.mouseUp(screen.getByRole('article', { name: 'Nội dung đọc tiếng Việt' }));
    await userEvent.click(screen.getByRole('button', { name: 'Tra từ điển' }));

    expect(apiClient.lookupReaderDictionary).toHaveBeenCalledWith(42, 'Hàn Lập', {
      chapterId: 102,
      includeOnline: false,
    });
    const panel = await screen.findByRole('dialog', { name: 'Từ điển đọc truyện' });
    expect(within(panel).getAllByText('Hàn Lập').length).toBeGreaterThan(0);
    expect(within(panel).getByText('Nhân vật chính.')).toBeInTheDocument();

    await userEvent.click(within(panel).getByLabelText('Online fallback'));
    await waitFor(() => expect(apiClient.lookupReaderDictionary).toHaveBeenLastCalledWith(42, 'Hàn Lập', {
      chapterId: 102,
      includeOnline: true,
    }));
  });

  it('uses cached reader dictionary results when the API lookup fails', async () => {
    saveCachedReaderDictionaryResult({
      book_id: 42,
      cache: {
        hit: false,
        scope: 'online',
        stored: false,
      },
      chapter_id: 102,
      offline_count: 1,
      online: {
        count: 0,
        error: '',
        status: 'skipped',
      },
      query: 'Hàn Lập',
      sources: [
        {
          category: 'character',
          definition: 'Kết quả từ cache browser.',
          provider: 'reader-cache',
          source: 'offline_dictionary',
          target: 'Hàn Lập',
          term: 'Hàn Lập',
        },
      ],
    }, window.localStorage, '2026-06-29T10:00:00Z');
    const apiClient = mockReaderApiClient({
      lookupReaderDictionary: vi.fn().mockRejectedValue(new Error('network down')),
    });
    renderReader({
      apiClient,
      translationText: 'Hàn Lập bước vào Thất Huyền Môn.\n\nLinh khí lạnh thấm qua thềm đá.',
    });
    const textNode = screen.getByText('Hàn Lập bước vào Thất Huyền Môn.').firstChild as Text;
    vi.spyOn(window, 'getSelection').mockReturnValue({
      anchorNode: textNode,
      focusNode: textNode,
      getRangeAt: () => ({
        commonAncestorContainer: textNode,
        getBoundingClientRect: () => ({
          bottom: 198,
          height: 18,
          left: 120,
          right: 174,
          top: 180,
          width: 54,
          x: 120,
          y: 180,
          toJSON: () => ({}),
        } as DOMRect),
        startContainer: textNode,
        startOffset: 0,
        endContainer: textNode,
        endOffset: 6,
      } as unknown as Range),
      isCollapsed: false,
      rangeCount: 1,
      removeAllRanges: vi.fn(),
      toString: () => 'Hàn Lập',
    } as unknown as Selection);

    fireEvent.mouseUp(screen.getByRole('article', { name: 'Nội dung đọc tiếng Việt' }));
    await userEvent.click(screen.getByRole('button', { name: 'Tra từ điển' }));

    const panel = await screen.findByRole('dialog', { name: 'Từ điển đọc truyện' });
    expect(apiClient.lookupReaderDictionary).toHaveBeenCalledWith(42, 'Hàn Lập', {
      chapterId: 102,
      includeOnline: false,
    });
    expect(within(panel).getByText('Kết quả từ cache browser.')).toBeInTheDocument();
    expect(within(panel).queryByText('network down')).not.toBeInTheDocument();
    expect(within(panel).getByText('1 offline · online skipped · cache hit')).toBeInTheDocument();
  });

  it('opens chapter audio playback when audio exists', async () => {
    const apiClient = mockReaderApiClient();
    const audioChapters = chapters.map((chapter) => (
      chapter.id === 102 ? { ...chapter, audio_path: '/tmp/chapter-102.mp3' } : chapter
    ));
    renderReader({
      apiClient,
      chapters: audioChapters,
      selectedChapter: audioChapters[1],
    });

    await userEvent.click(screen.getByRole('button', { name: 'Thêm tùy chọn' }));
    await userEvent.click(screen.getByRole('button', { name: 'Nghe audio chương' }));

    const audioBar = await screen.findByRole('region', { name: 'Audio chương' });
    expect(within(audioBar).getByLabelText('Audio Chương 2 · Thanh Ngưu trấn')).toHaveAttribute(
      'src',
      'http://test/api/books/42/chapters/102/audio',
    );
    expect(within(audioBar).getByRole('link', { name: /MP3/ })).toHaveAttribute(
      'href',
      'http://test/api/books/42/chapters/102/audio/download',
    );
  });

  it('offers a direct MP3 download action when chapter audio exists', async () => {
    const apiClient = mockReaderApiClient();
    const audioChapters = chapters.map((chapter) => (
      chapter.id === 102 ? { ...chapter, audio_path: '/tmp/chapter-102.mp3' } : chapter
    ));
    renderReader({
      apiClient,
      chapters: audioChapters,
      selectedChapter: audioChapters[1],
    });

    await userEvent.click(screen.getByRole('button', { name: 'Thêm tùy chọn' }));

    expect(screen.getByRole('link', { name: 'Tải MP3 chương' })).toHaveAttribute(
      'href',
      'http://test/api/books/42/chapters/102/audio/download',
    );
  });

  it('opens chapter audio playback from the backend playlist without relying on local audio paths', async () => {
    const apiClient = mockReaderApiClient({
      getBookAudioPlaylist: vi.fn().mockResolvedValue({
        book_id: 42,
        chapters: [
          {
            chapter_id: 102,
            chapter_number: 2,
            title: 'Thanh Ngưu trấn',
            duration_seconds: 183.5,
            download_url: '/api/books/42/chapters/102/audio/download',
            filename: 'chapter_0002.mp3',
            order: 0,
            size_bytes: 2048,
            stream_url: '/api/books/42/chapters/102/audio',
          },
        ],
      }),
    });
    renderReader({ apiClient });

    await userEvent.click(screen.getByRole('button', { name: 'Thêm tùy chọn' }));

    await waitFor(() => expect(apiClient.getBookAudioPlaylist).toHaveBeenCalledWith(42));
    await userEvent.click(await screen.findByRole('button', { name: 'Nghe audio chương' }));

    const audioBar = await screen.findByRole('region', { name: 'Audio chương' });
    expect(within(audioBar).getByLabelText('Audio Chương 2 · Thanh Ngưu trấn')).toHaveAttribute(
      'src',
      '/api/books/42/chapters/102/audio',
    );
    expect(within(audioBar).getByRole('link', { name: /MP3/ })).toHaveAttribute(
      'href',
      '/api/books/42/chapters/102/audio/download',
    );
  });

  it('plays cached offline audio when chapter audio has been cached', async () => {
    const originalCreateObjectUrl = URL.createObjectURL;
    const originalRevokeObjectUrl = URL.revokeObjectURL;
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:reader-audio-102') });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
    const fetcher = vi.fn().mockResolvedValue({
      blob: async () => new Blob(['audio-bytes'], { type: 'audio/mpeg' }),
      headers: new Headers({ 'content-type': 'audio/mpeg' }),
      ok: true,
    }) as unknown as typeof fetch;

    try {
      await cacheReaderAudio(42, 102, 'http://test/api/books/42/chapters/102/audio', fetcher);
      const apiClient = mockReaderApiClient();
      const audioChapters = chapters.map((chapter) => (
        chapter.id === 102 ? { ...chapter, audio_path: '/tmp/chapter-102.mp3' } : chapter
      ));
      renderReader({
        apiClient,
        chapters: audioChapters,
        selectedChapter: audioChapters[1],
      });

      await userEvent.click(screen.getByRole('button', { name: 'Thêm tùy chọn' }));
      await userEvent.click(screen.getByRole('button', { name: 'Nghe audio chương' }));

      const audioBar = await screen.findByRole('region', { name: 'Audio chương' });
      await waitFor(() => expect(within(audioBar).getByLabelText('Audio Chương 2 · Thanh Ngưu trấn')).toHaveAttribute(
        'src',
        'blob:reader-audio-102',
      ));
    } finally {
      Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: originalCreateObjectUrl });
      Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: originalRevokeObjectUrl });
    }
  });

  it('supports audiobook auto-next to the next chapter with audio', async () => {
    const apiClient = mockReaderApiClient();
    const audioChapters = chapters.map((chapter) => (
      chapter.id === 102 || chapter.id === 103
        ? { ...chapter, audio_path: `/tmp/chapter-${chapter.id}.mp3` }
        : chapter
    ));
    const props = renderReader({
      apiClient,
      chapters: audioChapters,
      selectedChapter: audioChapters[1],
    });

    await userEvent.click(screen.getByRole('button', { name: 'Thêm tùy chọn' }));
    await userEvent.click(screen.getByRole('button', { name: 'Nghe audio chương' }));
    await userEvent.click(screen.getByRole('checkbox', { name: 'Tự phát chương kế tiếp' }));

    fireEvent.ended(screen.getByLabelText('Audio Chương 2 · Thanh Ngưu trấn'));

    expect(props.onSelectChapter).toHaveBeenCalledWith(103);
  });

  it('starts a TTS job for the current chapter when audio is missing', async () => {
    const apiClient = mockReaderApiClient();
    renderReader({ apiClient });

    await userEvent.click(screen.getByRole('button', { name: 'Thêm tùy chọn' }));
    await userEvent.click(screen.getByRole('button', { name: 'Tạo audio chương' }));

    expect(apiClient.startTtsJob).toHaveBeenCalledWith(42, [102]);
    expect(await screen.findByText(/Đã tạo job audio tts-read/)).toBeInTheDocument();
  });

  it('shows a compact reader audio panel for chapters with and without audio', async () => {
    const apiClient = mockReaderApiClient();
    const audioChapters = chapters.map((chapter) => (
      chapter.id === 102 ? { ...chapter, audio_path: '/tmp/chapter-102.mp3' } : chapter
    ));
    renderReader({
      apiClient,
      chapters: audioChapters,
      selectedChapter: audioChapters[1],
    });

    const panel = screen.getByRole('region', { name: 'Audio và TTS chương' });
    expect(within(panel).getByText('Audio có sẵn')).toBeInTheDocument();
    expect(within(panel).getByRole('button', { name: 'Nghe audio' })).toBeInTheDocument();
    expect(within(panel).getByRole('link', { name: 'Tải MP3' })).toHaveAttribute(
      'href',
      'http://test/api/books/42/chapters/102/audio/download',
    );

    await userEvent.click(within(panel).getByRole('button', { name: 'Nghe audio' }));

    expect(await screen.findByRole('region', { name: 'Audio chương' })).toBeInTheDocument();
  });

  it('warns about QA FAIL and Chinese leakage before starting reader TTS', async () => {
    const apiClient = mockReaderApiClient({
      getQaReport: vi.fn().mockResolvedValue({
        book_id: 42,
        chapter_id: 102,
        overall_status: 'FAIL',
        chinese_leakage_count: 2,
        glossary_violations: [],
        quality_score: 3,
        repetition_warning: false,
      }),
    });
    renderReader({
      apiClient,
      translationText: 'Đệ tử lấy ra 灵石.\n\nHắn đi tiếp.',
    });

    const panel = await screen.findByRole('region', { name: 'Audio và TTS chương' });
    expect(within(panel).getByText(/QA đang FAIL/)).toBeInTheDocument();
    expect(within(panel).getByText(/Còn 2 dấu hiệu rò chữ Trung/)).toBeInTheDocument();

    await userEvent.click(within(panel).getByRole('button', { name: 'Tạo audio chương' }));

    expect(apiClient.startTtsJob).toHaveBeenCalledWith(42, [102]);
  });

  it('shows missing translation warning and blocks chapter TTS when text is empty', () => {
    const apiClient = mockReaderApiClient();
    renderReader({
      apiClient,
      translationText: '',
    });

    const panel = screen.getByRole('region', { name: 'Audio và TTS chương' });
    expect(within(panel).getByText(/Chưa có bản dịch tiếng Việt/)).toBeInTheDocument();
    expect(within(panel).getByRole('button', { name: 'Tạo audio chương' })).toBeDisabled();
  });

  it('shows TTS progress, failed chunks, friendly errors, and retry without leaking secrets', async () => {
    const apiClient = mockReaderApiClient({
      startTtsJob: vi.fn().mockResolvedValue({
        job_id: 'tts-failed-123456',
        status: 'pending',
        message: 'TTS job started',
      }),
      getJobStatus: vi.fn().mockResolvedValue({
        job_id: 'tts-failed-123456',
        job_type: 'tts',
        status: 'failed',
        progress: 1,
        total: 3,
        message: 'chunk failed with sk-live-secret GEMINI_API_KEY /home/thenam176/private',
        error: 'ffmpeg missing at /home/thenam176/private with sk-live-secret GEMINI_API_KEY',
      }),
      getTtsJob: vi.fn().mockResolvedValue({
        job_id: 'tts-failed-123456',
        status: 'failed',
        progress: 33,
        error_message: 'ffmpeg missing at /home/thenam176/private with sk-live-secret GEMINI_API_KEY',
        audio_summary: {
          warnings: ['1 completed chunk file is missing', 'Audio QA reported 2 warning(s)'],
        },
        chunks: [
          { id: 'chunk-1', job_id: 'tts-failed-123456', chunk_index: 0, text_hash: 'a', status: 'completed' },
          {
            id: 'chunk-2',
            job_id: 'tts-failed-123456',
            chunk_index: 1,
            text_hash: 'b',
            status: 'failed',
            error_message: 'sk-live-secret',
          },
          {
            id: 'chunk-3',
            job_id: 'tts-failed-123456',
            chunk_index: 2,
            text_hash: 'c',
            status: 'failed',
            error_message: 'GEMINI_API_KEY',
          },
        ],
      }),
      retryTtsJob: vi.fn().mockResolvedValue({
        job_id: 'tts-retry-654321',
        status: 'queued',
        message: 'Retry queued',
      }),
    });
    renderReader({ apiClient });

    await userEvent.click(screen.getByRole('button', { name: 'Thêm tùy chọn' }));
    await userEvent.click(screen.getByRole('button', { name: 'Tạo audio chương' }));

    const audioStatus = await screen.findByRole('status', { name: 'Trạng thái audio' });
    expect(apiClient.getJobStatus).toHaveBeenCalledWith('tts-failed-123456');
    expect(apiClient.getTtsJob).toHaveBeenCalledWith('tts-failed-123456');
    expect(within(audioStatus).getByText('Job audio tts-fail')).toBeInTheDocument();
    expect(within(audioStatus).getByText('33%')).toBeInTheDocument();
    expect(within(audioStatus).getByText('2 chunk lỗi')).toBeInTheDocument();
    expect(within(audioStatus).getByText('1 completed chunk file is missing')).toBeInTheDocument();
    expect(within(audioStatus).getByText('Audio QA reported 2 warning(s)')).toBeInTheDocument();
    expect(within(audioStatus).getByText(/Thiếu ffmpeg/)).toBeInTheDocument();
    expect(audioStatus).not.toHaveTextContent('sk-live-secret');
    expect(audioStatus).not.toHaveTextContent('GEMINI_API_KEY');
    expect(audioStatus).not.toHaveTextContent('/home/thenam176');

    await userEvent.click(within(audioStatus).getByRole('button', { name: 'Chạy lại chunk lỗi' }));

    expect(apiClient.retryTtsJob).toHaveBeenCalledWith('tts-failed-123456');
    expect(await screen.findByText(/Đã gửi retry TTS tts-retr/)).toBeInTheDocument();
  });

  it('shows running TTS progress in the reader audio panel and cancels through the existing job API', async () => {
    const apiClient = mockReaderApiClient({
      startTtsJob: vi.fn().mockResolvedValue({
        job_id: 'tts-running-123456',
        status: 'pending',
        message: 'TTS job started',
      }),
      getJobStatus: vi.fn().mockResolvedValue({
        job_id: 'tts-running-123456',
        job_type: 'tts',
        status: 'running',
        progress: 1,
        total: 4,
        current_chapter_id: 102,
        current_chunk_index: 1,
        total_chunks: 4,
        provider: 'f5_vietnamese',
        model: 'vivioice',
        retry_count: 0,
        message: 'Generating chunk 2',
      }),
      getTtsJob: vi.fn().mockResolvedValue({
        job_id: 'tts-running-123456',
        status: 'running',
        progress: 25,
        chunks: [
          { id: 'chunk-1', job_id: 'tts-running-123456', chunk_index: 0, text_hash: 'a', status: 'completed' },
          { id: 'chunk-2', job_id: 'tts-running-123456', chunk_index: 1, text_hash: 'b', status: 'running' },
        ],
      }),
    });
    renderReader({ apiClient });

    const panel = screen.getByRole('region', { name: 'Audio và TTS chương' });
    await userEvent.click(within(panel).getByRole('button', { name: 'Tạo audio chương' }));

    const status = await screen.findByRole('status', { name: 'Trạng thái audio' });
    expect(within(status).getByText('running')).toBeInTheDocument();
    expect(within(status).getByText('25%')).toBeInTheDocument();
    expect(within(status).getByText('1/2 chunks')).toBeInTheDocument();

    await userEvent.click(within(status).getByRole('button', { name: 'Hủy job audio' }));

    expect(apiClient.cancelJob).toHaveBeenCalledWith('tts-running-123456');
    expect(await screen.findByText(/Đã yêu cầu hủy job audio/)).toBeInTheDocument();
  });

  it('starts a book TTS job for missing audiobook chapters', async () => {
    const apiClient = mockReaderApiClient();
    renderReader({ apiClient });

    await userEvent.click(screen.getByRole('button', { name: 'Thêm tùy chọn' }));
    await userEvent.click(screen.getByRole('button', { name: 'Tạo audiobook còn thiếu' }));

    const dialog = screen.getByRole('dialog', { name: 'Xác nhận tạo audiobook' });
    expect(within(dialog).getByText('3 chương đã dịch')).toBeInTheDocument();
    expect(within(dialog).getByText('0 chương đã có audio')).toBeInTheDocument();
    expect(within(dialog).getByText('1 chương thiếu bản dịch')).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole('button', { name: 'Tạo audiobook' }));

    expect(apiClient.startBookTtsJob).toHaveBeenCalledWith(42, { limit: 200 });
    expect(await screen.findByText(/Đã tạo job audiobook tts-book/)).toBeInTheDocument();
  });

  it('downloads an M4B audiobook export from the more menu', async () => {
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:m4b') });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    const apiClient = mockReaderApiClient();
    renderReader({ apiClient });

    await userEvent.click(screen.getByRole('button', { name: 'Thêm tùy chọn' }));
    await userEvent.click(screen.getByRole('button', { name: 'Tải audiobook M4B' }));

    expect(apiClient.downloadAudiobookExport).toHaveBeenCalledWith(42, 'm4b');
    expect(await screen.findByText('Đã tải pham_nhan.m4b')).toBeInTheDocument();
  });

  it('exports reader bookmarks, highlights, and notes from the more menu', async () => {
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:annotations') });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    const apiClient = mockReaderApiClient({
      downloadReaderAnnotations: vi.fn().mockImplementation((bookId: number, format: string) => Promise.resolve({
        blob: new Blob([`${bookId}:${format}`], { type: format === 'json' ? 'application/json' : 'text/plain' }),
        filename: `pham_nhan.annotations.${format}`,
        mediaType: format === 'json' ? 'application/json' : 'text/plain',
      })),
      getReaderState: vi.fn().mockResolvedValue({
        progress: null,
        annotations: [remoteHighlight],
      }),
    });
    renderReader({ apiClient });
    await waitFor(() => expect(apiClient.getReaderState).toHaveBeenCalledWith(42));

    await userEvent.click(screen.getByRole('button', { name: 'Thêm tùy chọn' }));
    await userEvent.click(screen.getByRole('button', { name: 'Xuất Markdown' }));
    await userEvent.click(screen.getByRole('button', { name: 'Xuất JSON' }));
    await userEvent.click(screen.getByRole('button', { name: 'Xuất CSV' }));

    await waitFor(() => expect(apiClient.downloadReaderAnnotations).toHaveBeenCalledTimes(3));
    expect(apiClient.downloadReaderAnnotations).toHaveBeenNthCalledWith(1, 42, 'md');
    expect(apiClient.downloadReaderAnnotations).toHaveBeenNthCalledWith(2, 42, 'json');
    expect(apiClient.downloadReaderAnnotations).toHaveBeenNthCalledWith(3, 42, 'csv');
    expect(screen.getByText('Đã xuất pham_nhan.annotations.csv')).toBeInTheDocument();
  });

  it('exports local reader marks when the API is unavailable', async () => {
    const createObjectUrl = vi.fn((blob: Blob | MediaSource) => {
      void blob;
      return 'blob:local-reader-marks';
    });
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectUrl });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    saveReaderMarks({
      [chapterMarksKey(42, 102)]: {
        bookmarked: true,
        highlights: [
          {
            charEnd: 22,
            charStart: 0,
            color: 'yellow',
            id: 'local-highlight-1',
            paragraphIndex: 0,
            text: 'Hàn Lập khẽ gật đầu.',
          },
        ],
        notes: [
          {
            charEnd: 14,
            charStart: 7,
            color: 'blue',
            id: 'local-note-1',
            note: 'Giữ xưng hô cổ trang.',
            paragraphIndex: 1,
            text: 'ta cảm tạ huynh',
          },
        ],
      },
    });
    renderReader({ apiClient: undefined });

    await userEvent.click(screen.getByRole('button', { name: 'Thêm tùy chọn' }));
    await userEvent.click(screen.getByRole('button', { name: 'Xuất JSON' }));

    expect(createObjectUrl).toHaveBeenCalledTimes(1);
    const blob = createObjectUrl.mock.calls[0][0] as Blob;
    const payload = JSON.parse(await blob.text()) as {
      annotations: Array<{ kind: string; selected_text: string }>;
      format: string;
      kind_counts: Record<string, number>;
      version: number;
    };
    expect(payload).toMatchObject({
      format: 'novel_tnn_reader_annotations',
      kind_counts: { bookmark: 1, highlight: 1, note: 1 },
      version: 2,
    });
    expect(payload.annotations).toEqual(expect.arrayContaining([
      expect.objectContaining({ chapter_title: 'Thanh Ngưu trấn', kind: 'bookmark' }),
      expect.objectContaining({ kind: 'highlight', selected_text: 'Hàn Lập khẽ gật đầu.' }),
      expect.objectContaining({ kind: 'note', note: 'Giữ xưng hô cổ trang.' }),
    ]));
    expect(screen.getByText('Đã xuất local pham-nhan-tu-tien.reader-marks.json')).toBeInTheDocument();
  });

  it('exports local reader marks CSV with stable client ids and exact character ranges', async () => {
    const createObjectUrl = vi.fn((blob: Blob | MediaSource) => {
      void blob;
      return 'blob:local-reader-marks-csv';
    });
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectUrl });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    saveReaderMarks({
      [chapterMarksKey(42, 102)]: {
        bookmarked: true,
        highlights: [
          {
            charEnd: 22,
            charStart: 0,
            color: 'yellow',
            id: 'local-highlight-1',
            paragraphIndex: 0,
            text: 'Hàn Lập khẽ gật đầu.',
          },
        ],
        notes: [
          {
            charEnd: 14,
            charStart: 7,
            color: 'blue',
            id: 'local-note-1',
            note: 'Giữ xưng hô cổ trang.',
            paragraphIndex: 1,
            text: 'ta cảm tạ huynh',
          },
        ],
      },
    });
    renderReader({ apiClient: undefined });

    await userEvent.click(screen.getByRole('button', { name: 'Thêm tùy chọn' }));
    await userEvent.click(screen.getByRole('button', { name: 'Xuất CSV' }));

    expect(createObjectUrl).toHaveBeenCalledTimes(1);
    const blob = createObjectUrl.mock.calls[0][0] as Blob;
    const csv = await blob.text();
    const [headers] = csv.split('\n');
    expect(headers.split(',')).toEqual(expect.arrayContaining([
      'client_id',
      'char_start',
      'char_end',
    ]));
    expect(csv).toContain('"local-highlight-1"');
    expect(csv).toContain('"local-note-1"');
    expect(csv).toContain('"0","22"');
    expect(csv).toContain('"7","14"');
  });

  it('imports reader annotation JSON from the more menu', async () => {
    const apiClient = mockReaderApiClient({
      importReaderAnnotations: vi.fn().mockResolvedValue({
        summary: { imported: 1, skipped: 0, duplicates: 0, invalid: 0 },
        annotations: [remoteHighlight],
      }),
    });
    renderReader({ apiClient });

    await userEvent.click(screen.getByRole('button', { name: 'Thêm tùy chọn' }));
    await userEvent.upload(
      screen.getByLabelText('Chọn file dấu đọc JSON'),
      new File([
        JSON.stringify({
          annotations: [
            {
              chapter_number: 2,
              client_id: 'phone-highlight-1',
              kind: 'highlight',
              paragraph_index: 0,
              selected_text: 'Hàn Lập khẽ gật đầu.',
            },
          ],
        }),
      ], 'reader.annotations.json', { type: 'application/json' }),
    );

    await waitFor(() => expect(apiClient.importReaderAnnotations).toHaveBeenCalledWith(42, [
      {
        chapter_number: 2,
        client_id: 'phone-highlight-1',
        kind: 'highlight',
        paragraph_index: 0,
        selected_text: 'Hàn Lập khẽ gật đầu.',
      },
    ]));
    expect(await screen.findByText('Đã nhập 1 dấu đọc · bỏ qua 0')).toBeInTheDocument();
  });

  it('exports a selected reader annotation kind from the more menu', async () => {
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:highlights') });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    const apiClient = mockReaderApiClient({
      downloadReaderAnnotations: vi.fn().mockResolvedValue({
        blob: new Blob(['{"annotation_count":1}'], { type: 'application/json' }),
        filename: 'pham_nhan.highlights.json',
        mediaType: 'application/json',
      }),
      getReaderState: vi.fn().mockResolvedValue({
        progress: null,
        annotations: [remoteHighlight],
      }),
    });
    renderReader({ apiClient });
    await waitFor(() => expect(apiClient.getReaderState).toHaveBeenCalledWith(42));

    await userEvent.click(screen.getByRole('button', { name: 'Thêm tùy chọn' }));
    await userEvent.click(screen.getByRole('button', { name: 'Highlights' }));
    await userEvent.click(screen.getByRole('button', { name: 'Xuất JSON' }));

    await waitFor(() => expect(apiClient.downloadReaderAnnotations).toHaveBeenCalledWith(
      42,
      'json',
      { kind: 'highlight' },
    ));
    expect(screen.getByText('Đã xuất pham_nhan.highlights.json')).toBeInTheDocument();
  });

  it('shows KOReader-style progress and chapter navigation', async () => {
    const props = renderReader();

    expect(screen.getByRole('heading', { name: 'Thanh Ngưu trấn' })).toBeInTheDocument();
    expect(screen.getByText('Chương 2/3')).toBeInTheDocument();
    expect(screen.getByText('Chương 2 · 100%')).toBeInTheDocument();
    expect(screen.getByText('Sách 67%')).toBeInTheDocument();
    expect(screen.getByText('0 từ còn lại')).toBeInTheDocument();
    expect(screen.getByText('0 phút còn lại')).toBeInTheDocument();
    expect(screen.getByRole('progressbar', { name: 'Tiến độ đọc' })).toHaveAttribute('value', '100');

    await userEvent.click(screen.getByRole('button', { name: 'Chương trước' }));
    expect(props.onSelectChapter).toHaveBeenCalledWith(101);

    await userEvent.click(screen.getByRole('button', { name: 'Chương sau' }));
    expect(props.onSelectChapter).toHaveBeenCalledWith(103);
  });

  it('updates reader progress from scroll position inside the chapter', () => {
    renderReader();
    const main = screen.getByRole('main', { name: 'Vùng đọc chính' });

    Object.defineProperty(main, 'scrollHeight', { configurable: true, value: 1000 });
    Object.defineProperty(main, 'clientHeight', { configurable: true, value: 400 });
    Object.defineProperty(main, 'scrollTop', { configurable: true, value: 300, writable: true });

    fireEvent.scroll(main);

    expect(screen.getByText('Location 300 of 600')).toBeInTheDocument();
    expect(screen.getByText('Chương 2 · 50%')).toBeInTheDocument();
    expect(screen.getByText('Sách 50%')).toBeInTheDocument();
    expect(screen.getByText('6 từ còn lại')).toBeInTheDocument();
    expect(screen.getByText('1 phút còn lại')).toBeInTheDocument();
    expect(screen.getByRole('progressbar', { name: 'Tiến độ đọc' })).toHaveAttribute('value', '50');
    expect(JSON.parse(window.localStorage.getItem('novel-reader-progress-v1') ?? '{}')).toMatchObject({
      42: {
        chapterId: 102,
        percent: 50,
      },
    });
  });

  it('saves exact char offset from browser caret APIs when available', async () => {
    const apiClient = mockReaderApiClient();
    renderReader({ apiClient });
    const main = screen.getByRole('main', { name: 'Vùng đọc chính' });
    const paragraph = screen.getByText('Hàn Lập khẽ gật đầu.');
    const textNode = paragraph.firstChild as Text;
    const range = document.createRange();
    range.setStart(textNode, 4);
    range.collapse(true);
    Object.defineProperty(main, 'scrollHeight', { configurable: true, value: 1000 });
    Object.defineProperty(main, 'clientHeight', { configurable: true, value: 400 });
    Object.defineProperty(main, 'scrollTop', { configurable: true, value: 300, writable: true });
    vi.spyOn(main, 'getBoundingClientRect').mockReturnValue({
      bottom: 600,
      height: 400,
      left: 0,
      right: 360,
      top: 200,
      width: 360,
      x: 0,
      y: 200,
      toJSON: () => ({}),
    } as DOMRect);
    vi.spyOn(paragraph, 'getBoundingClientRect').mockReturnValue({
      bottom: 240,
      height: 24,
      left: 40,
      right: 320,
      top: 216,
      width: 280,
      x: 40,
      y: 216,
      toJSON: () => ({}),
    } as DOMRect);
    const blocks = Array.from(main.querySelectorAll<HTMLElement>('.reader-paragraph-block[data-paragraph-index]'));
    vi.spyOn(blocks[0], 'getBoundingClientRect').mockReturnValue({
      bottom: 242,
      height: 42,
      left: 30,
      right: 330,
      top: 200,
      width: 300,
      x: 30,
      y: 200,
      toJSON: () => ({}),
    } as DOMRect);
    vi.spyOn(blocks[1], 'getBoundingClientRect').mockReturnValue({
      bottom: 322,
      height: 42,
      left: 30,
      right: 330,
      top: 280,
      width: 300,
      x: 30,
      y: 280,
      toJSON: () => ({}),
    } as DOMRect);
    Object.defineProperty(document, 'caretRangeFromPoint', {
      configurable: true,
      value: vi.fn(() => range),
    });

    vi.mocked(apiClient.syncReaderState).mockClear();
    fireEvent.scroll(main);

    await waitFor(() => expect(latestProgressSyncPayload(apiClient)).toMatchObject({
      absolute_char_offset: 4,
      char_offset: 4,
      paragraph_index: 0,
    }));
    expect(apiClient.saveReaderProgress).not.toHaveBeenCalled();
  });

  it('prefers the freshly measured caret location when saving scroll progress', async () => {
    const apiClient = mockReaderApiClient();
    renderReader({
      apiClient,
      translationText: 'abcdef\n\nghijkl',
    });
    const main = screen.getByRole('main', { name: 'Vùng đọc chính' });
    const paragraph = screen.getByText('abcdef');
    const textNode = paragraph.firstChild as Text;
    const staleRange = document.createRange();
    staleRange.setStart(textNode, 1);
    staleRange.collapse(true);
    const freshRange = document.createRange();
    freshRange.setStart(textNode, 4);
    freshRange.collapse(true);
    Object.defineProperty(main, 'scrollHeight', { configurable: true, value: 1000 });
    Object.defineProperty(main, 'clientHeight', { configurable: true, value: 400 });
    Object.defineProperty(main, 'scrollTop', { configurable: true, value: 300, writable: true });
    vi.spyOn(main, 'getBoundingClientRect').mockReturnValue({
      bottom: 600,
      height: 400,
      left: 0,
      right: 360,
      top: 200,
      width: 360,
      x: 0,
      y: 200,
      toJSON: () => ({}),
    } as DOMRect);
    vi.spyOn(paragraph, 'getBoundingClientRect').mockReturnValue({
      bottom: 240,
      height: 24,
      left: 40,
      right: 320,
      top: 216,
      width: 280,
      x: 40,
      y: 216,
      toJSON: () => ({}),
    } as DOMRect);
    const blocks = Array.from(main.querySelectorAll<HTMLElement>('.reader-paragraph-block[data-paragraph-index]'));
    vi.spyOn(blocks[0], 'getBoundingClientRect').mockReturnValue({
      bottom: 242,
      height: 42,
      left: 30,
      right: 330,
      top: 200,
      width: 300,
      x: 30,
      y: 200,
      toJSON: () => ({}),
    } as DOMRect);
    vi.spyOn(blocks[1], 'getBoundingClientRect').mockReturnValue({
      bottom: 322,
      height: 42,
      left: 30,
      right: 330,
      top: 280,
      width: 300,
      x: 30,
      y: 280,
      toJSON: () => ({}),
    } as DOMRect);
    Object.defineProperty(document, 'caretRangeFromPoint', {
      configurable: true,
      value: vi.fn()
        .mockReturnValueOnce(staleRange)
        .mockReturnValue(freshRange),
    });

    vi.mocked(apiClient.syncReaderState).mockClear();
    fireEvent.scroll(main);

    await waitFor(() => expect(latestProgressSyncPayload(apiClient)).toMatchObject({
      absolute_char_offset: 4,
      char_offset: 4,
      paragraph_index: 0,
    }));
    expect(apiClient.saveReaderProgress).not.toHaveBeenCalled();
  });

  it('uses exact character offset rather than pixel scroll ratio for chapter percent', async () => {
    const apiClient = mockReaderApiClient();
    renderReader({
      apiClient,
      translationText: 'abcdef\n\nghijkl',
    });
    const main = screen.getByRole('main', { name: 'Vùng đọc chính' });
    const paragraph = screen.getByText('abcdef');
    const textNode = paragraph.firstChild as Text;
    const range = document.createRange();
    range.setStart(textNode, 3);
    range.collapse(true);
    Object.defineProperty(main, 'scrollHeight', { configurable: true, value: 1000 });
    Object.defineProperty(main, 'clientHeight', { configurable: true, value: 400 });
    Object.defineProperty(main, 'scrollTop', { configurable: true, value: 300, writable: true });
    vi.spyOn(main, 'getBoundingClientRect').mockReturnValue({
      bottom: 600,
      height: 400,
      left: 0,
      right: 360,
      top: 200,
      width: 360,
      x: 0,
      y: 200,
      toJSON: () => ({}),
    } as DOMRect);
    vi.spyOn(paragraph, 'getBoundingClientRect').mockReturnValue({
      bottom: 240,
      height: 24,
      left: 40,
      right: 320,
      top: 216,
      width: 280,
      x: 40,
      y: 216,
      toJSON: () => ({}),
    } as DOMRect);
    const blocks = Array.from(main.querySelectorAll<HTMLElement>('.reader-paragraph-block[data-paragraph-index]'));
    vi.spyOn(blocks[0], 'getBoundingClientRect').mockReturnValue({
      bottom: 242,
      height: 42,
      left: 30,
      right: 330,
      top: 200,
      width: 300,
      x: 30,
      y: 200,
      toJSON: () => ({}),
    } as DOMRect);
    vi.spyOn(blocks[1], 'getBoundingClientRect').mockReturnValue({
      bottom: 322,
      height: 42,
      left: 30,
      right: 330,
      top: 280,
      width: 300,
      x: 30,
      y: 280,
      toJSON: () => ({}),
    } as DOMRect);
    Object.defineProperty(document, 'caretRangeFromPoint', {
      configurable: true,
      value: vi.fn(() => range),
    });

    vi.mocked(apiClient.syncReaderState).mockClear();
    fireEvent.scroll(main);

    await waitFor(() => {
      expect(screen.getByText('Chương 2 · 21%')).toBeInTheDocument();
      expect(latestProgressSyncPayload(apiClient)).toMatchObject({
        absolute_char_offset: 3,
        anchor: {
          offset: 3,
          text: 'abcdef\n\nghijkl',
          version: 1,
        },
        char_offset: 3,
        paragraph_index: 0,
        percent: 21,
      });
    });
    expect(loadReaderProgressSnapshot(42)).toMatchObject({
      anchor: {
        offset: 3,
        text: 'abcdef\n\nghijkl',
        version: 1,
      },
    });
    expect(apiClient.saveReaderProgress).not.toHaveBeenCalled();
  });

  it('saves the first visible paragraph when the previous paragraph has scrolled past the viewport', async () => {
    const apiClient = mockReaderApiClient();
    const hiddenParagraph = 'Đoạn đã khuất hoàn toàn.';
    const visibleParagraph = 'Đoạn đang hiện trong viewport.';
    renderReader({
      apiClient,
      translationText: `${hiddenParagraph}\n\n${visibleParagraph}`,
    });
    const main = screen.getByRole('main', { name: 'Vùng đọc chính' });
    const blocks = Array.from(main.querySelectorAll<HTMLElement>('.reader-paragraph-block[data-paragraph-index]'));

    Object.defineProperty(main, 'scrollHeight', { configurable: true, value: 1000 });
    Object.defineProperty(main, 'clientHeight', { configurable: true, value: 400 });
    Object.defineProperty(main, 'scrollTop', { configurable: true, value: 300, writable: true });
    vi.spyOn(main, 'getBoundingClientRect').mockReturnValue({
      bottom: 600,
      height: 400,
      left: 0,
      right: 360,
      top: 200,
      width: 360,
      x: 0,
      y: 200,
      toJSON: () => ({}),
    } as DOMRect);
    vi.spyOn(blocks[0], 'getBoundingClientRect').mockReturnValue({
      bottom: 190,
      height: 70,
      left: 30,
      right: 330,
      top: 120,
      width: 300,
      x: 30,
      y: 120,
      toJSON: () => ({}),
    } as DOMRect);
    vi.spyOn(blocks[1], 'getBoundingClientRect').mockReturnValue({
      bottom: 280,
      height: 50,
      left: 30,
      right: 330,
      top: 230,
      width: 300,
      x: 30,
      y: 230,
      toJSON: () => ({}),
    } as DOMRect);

    vi.mocked(apiClient.syncReaderState).mockClear();
    fireEvent.scroll(main);

    await waitFor(() => expect(latestProgressSyncPayload(apiClient)).toMatchObject({
      absolute_char_offset: hiddenParagraph.length + 2,
      char_offset: 0,
      paragraph_index: 1,
    }));
    expect(apiClient.saveReaderProgress).not.toHaveBeenCalled();
  });

  it('restores the saved paginated page index for the selected chapter', async () => {
    window.localStorage.setItem('novel-reader-settings-v1', JSON.stringify({ readingMode: 'paginated' }));
    window.localStorage.setItem('novel-reader-progress-v1', JSON.stringify({
      42: {
        chapterId: 102,
        mode: 'paginated',
        pageIndex: 1,
        paragraphIndex: 4,
        percent: 100,
        position: 2,
        totalChapters: 2,
      },
    }));

    renderReader({
      translationText: [
        'Đoạn một mở đầu.',
        'Đoạn hai giữ nhịp.',
        'Đoạn ba triển khai.',
        'Đoạn bốn kết cảnh.',
        'Đoạn năm sang trang.',
      ].join('\n\n'),
    });

    expect(await screen.findByText('Đoạn năm sang trang.')).toBeInTheDocument();
    expect(screen.queryByText('Đoạn một mở đầu.')).not.toBeInTheDocument();
    expect(screen.getByText('Trang 2/2')).toBeInTheDocument();
  });

  it('restores saved scroll position and paragraph locator for the selected chapter', async () => {
    const scrollIntoView = vi.fn();
    const originalScrollIntoView = HTMLElement.prototype.scrollIntoView;
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: scrollIntoView,
    });
    window.localStorage.setItem('novel-reader-progress-v1', JSON.stringify({
      42: {
        chapterId: 102,
        charOffset: 0,
        mode: 'scroll',
        paragraphIndex: 1,
        percent: 50,
        position: 240,
        totalChapters: 480,
      },
    }));

    try {
      renderReader();

      const main = screen.getByRole('main', { name: 'Vùng đọc chính' });
      await waitFor(() => expect(scrollIntoView).toHaveBeenCalledTimes(1));
      expect(scrollIntoView.mock.contexts[0]).toHaveAttribute('data-paragraph-index', '1');
      expect(main.scrollTop).toBe(240);
    } finally {
      Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
        configurable: true,
        value: originalScrollIntoView,
      });
    }
  });

  it('restores saved scroll position when scrollIntoView is unavailable', async () => {
    const originalScrollIntoView = HTMLElement.prototype.scrollIntoView;
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: undefined,
    });
    window.localStorage.setItem('novel-reader-progress-v1', JSON.stringify({
      42: {
        chapterId: 102,
        charOffset: 0,
        mode: 'scroll',
        paragraphIndex: 1,
        percent: 50,
        position: 240,
        totalChapters: 480,
      },
    }));

    try {
      renderReader();

      const main = screen.getByRole('main', { name: 'Vùng đọc chính' });
      await waitFor(() => expect(main.scrollTop).toBe(240));
    } finally {
      Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
        configurable: true,
        value: originalScrollIntoView,
      });
    }
  });

  it('restores progress through a text anchor when content was inserted before the saved offset', async () => {
    const originalScrollIntoView = HTMLElement.prototype.scrollIntoView;
    const scrollIntoView = vi.fn();
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: scrollIntoView,
    });
    const originalBlocks = [
      'Lục ca khẽ gật đầu.',
      'Nàng thu kiếm, chậm rãi bước qua thềm đá.',
      'Gió đêm lặng xuống.',
    ];
    const insertedParagraph = 'Đoạn mới được biên tập thêm ở đầu chương.';
    const charOffset = 'Nàng thu kiếm, '.length;
    const absoluteCharOffset = originalBlocks[0].length + 2 + charOffset;
    saveReaderProgressSnapshot(42, 102, 240, 480, window.localStorage, {
      absoluteCharOffset,
      anchor: buildReaderProgressTextAnchor(originalBlocks, 1, charOffset),
      charOffset,
      mode: 'scroll',
      paragraphIndex: 1,
      percent: 40,
    });

    try {
      renderReader({
        translationText: [insertedParagraph, ...originalBlocks].join('\n\n'),
      });

      await waitFor(() => expect(scrollIntoView).toHaveBeenCalled());
      expect(scrollIntoView.mock.contexts[0]).toHaveAttribute('data-paragraph-index', '2');
    } finally {
      Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
        configurable: true,
        value: originalScrollIntoView,
      });
    }
  });

  it('restores rich media from the current block offset when the saved pixel position is stale', async () => {
    const originalScrollIntoView = HTMLElement.prototype.scrollIntoView;
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: undefined,
    });
    const firstText = 'Trước ảnh.';
    window.localStorage.setItem('novel-reader-progress-v1', JSON.stringify({
      42: {
        absoluteCharOffset: firstText.length + 2,
        chapterId: 102,
        charOffset: 0,
        mode: 'scroll',
        paragraphIndex: 0,
        percent: 50,
        position: 24,
        totalChapters: 480,
      },
    }));

    try {
      renderReader({
        contentHtml: '<p>Trước ảnh.</p><figure><img src="/book-assets/42/map.png"></figure><p>Sau ảnh.</p>',
        translationText: '',
      });

      const main = screen.getByRole('main', { name: 'Vùng đọc chính' });
      const mediaBlock = main.querySelector<HTMLElement>('.reader-paragraph-block[data-paragraph-index="1"]');
      expect(mediaBlock).toBeTruthy();
      Object.defineProperty(mediaBlock, 'offsetTop', { configurable: true, value: 360 });

      await waitFor(() => expect(main.scrollTop).toBe(360));
    } finally {
      Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
        configurable: true,
        value: originalScrollIntoView,
      });
    }
  });

  it('restores deep paragraph character offsets from block geometry when offsetTop is unavailable', async () => {
    const originalScrollIntoView = HTMLElement.prototype.scrollIntoView;
    const originalGetClientRects = Range.prototype.getClientRects;
    const originalGetBoundingClientRect = Range.prototype.getBoundingClientRect;
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: undefined,
    });
    Object.defineProperty(Range.prototype, 'getClientRects', {
      configurable: true,
      value: () => [] as unknown as DOMRectList,
    });
    Object.defineProperty(Range.prototype, 'getBoundingClientRect', {
      configurable: true,
      value: () => ({
        bottom: 0,
        height: 0,
        left: 0,
        right: 0,
        top: 0,
        width: 0,
        x: 0,
        y: 0,
        toJSON: () => ({}),
      }) as DOMRect,
    });
    const firstParagraph = 'Đoạn mở đầu.';
    const secondParagraph = 'x'.repeat(100);
    saveReaderProgressSnapshot(42, 102, 24, 480, window.localStorage, {
      absoluteCharOffset: firstParagraph.length + 2 + 50,
      charOffset: 50,
      mode: 'scroll',
      paragraphIndex: 1,
      percent: 50,
    });

    try {
      renderReader({
        translationText: `${firstParagraph}\n\n${secondParagraph}`,
      });

      const main = screen.getByRole('main', { name: 'Vùng đọc chính' });
      const block = main.querySelector<HTMLElement>('.reader-paragraph-block[data-paragraph-index="1"]');
      expect(block).toBeTruthy();
      Object.defineProperty(main, 'getBoundingClientRect', {
        configurable: true,
        value: () => ({
          bottom: 500,
          height: 400,
          left: 0,
          right: 360,
          top: 100,
          width: 360,
          x: 0,
          y: 100,
          toJSON: () => ({}),
        }) as DOMRect,
      });
      Object.defineProperty(block, 'offsetTop', { configurable: true, value: 0 });
      Object.defineProperty(block, 'getBoundingClientRect', {
        configurable: true,
        value: () => ({
          bottom: 720,
          height: 200,
          left: 24,
          right: 336,
          top: 520,
          width: 312,
          x: 24,
          y: 520,
          toJSON: () => ({}),
        }) as DOMRect,
      });

      await waitFor(() => expect(main.scrollTop).toBe(520));
    } finally {
      Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
        configurable: true,
        value: originalScrollIntoView,
      });
      Object.defineProperty(Range.prototype, 'getClientRects', {
        configurable: true,
        value: originalGetClientRects,
      });
      Object.defineProperty(Range.prototype, 'getBoundingClientRect', {
        configurable: true,
        value: originalGetBoundingClientRect,
      });
    }
  });

  it('shows the selected book cover in reader status', () => {
    renderReader();

    expect(screen.getByRole('img', { name: 'Bìa Phàm Nhân Tu Tiên' })).toHaveAttribute(
      'src',
      '/covers/pham-nhan.jpg',
    );
  });

  it('renders rich chapter HTML with inline illustrations when available', () => {
    renderReader({
      contentHtml: '<p>Kiếm khí nổi lên.</p><img src="/book-assets/42/sword.png" alt="Kiếm quang"/>',
      translationText: 'Kiếm khí nổi lên.',
    });

    const article = screen.getByRole('article', { name: 'Nội dung đọc tiếng Việt' });
    expect(within(article).getByRole('img', { name: 'Kiếm quang' })).toHaveAttribute(
      'src',
      '/book-assets/42/sword.png',
    );
    expect(article).toHaveTextContent('Kiếm khí nổi lên.');
  });

  it('keeps rich HTML images when switching paginated pages', async () => {
    window.localStorage.setItem('novel-reader-settings-v1', JSON.stringify({ readingMode: 'paginated' }));
    renderReader({
      contentHtml: [
        '<p>Đoạn một.</p>',
        '<p>Đoạn hai.</p>',
        '<p>Đoạn ba.</p>',
        '<p>Đoạn bốn.</p>',
        '<figure><img src="/book-assets/42/sword.png" alt="Kiếm quang"/></figure>',
      ].join(''),
      translationText: ['Đoạn một.', 'Đoạn hai.', 'Đoạn ba.', 'Đoạn bốn.', 'Kiếm quang'].join('\n\n'),
    });

    const article = screen.getByRole('article', { name: 'Nội dung đọc tiếng Việt' });
    expect(article).toHaveAttribute('data-reading-mode', 'paginated');
    expect(screen.getByText('Trang 1/2')).toBeInTheDocument();
    expect(within(article).queryByRole('img', { name: 'Kiếm quang' })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Chương sau' }));

    expect(screen.getByText('Trang 2/2')).toBeInTheDocument();
    expect(within(article).getByRole('img', { name: 'Kiếm quang' })).toHaveAttribute(
      'src',
      '/book-assets/42/sword.png',
    );
  });

  it('warns when an imported ebook chapter only has a title or decorative image', () => {
    renderReader({
      selectedChapter: { ...chapters[1], title: 'Man Khải' },
      selectedChapterId: 102,
      contentHtml: '<p><img src="/book-assets/42/ch2.png" alt="Image"/></p>',
      translationText: 'Chương 2 Man Khải',
    });

    const article = screen.getByRole('article', { name: 'Nội dung đọc tiếng Việt' });
    expect(article).toHaveTextContent('File import của chương này chỉ có tiêu đề/ảnh, chưa có nội dung chữ để đọc.');
    expect(within(article).getByRole('img', { name: 'Image' })).toHaveAttribute(
      'src',
      '/book-assets/42/ch2.png',
    );
  });

  it('uses the TOC drawer for direct chapter jumps instead of a fixed book map', async () => {
    const props = renderReader();
    expect(screen.queryByRole('navigation', { name: 'Bản đồ chương' })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Mục lục' }));
    const drawer = screen.getByRole('dialog', { name: 'Mục lục' });

    expect(within(drawer).getAllByRole('button', { name: /^Ch\. \d/ })).toHaveLength(3);
    const currentChapterButton = within(drawer).getByRole('button', { name: 'Ch. 2 Thanh Ngưu trấn' });
    expect(currentChapterButton).toHaveAttribute('aria-current', 'true');
    expect(within(currentChapterButton).getByText('11 từ')).toBeInTheDocument();
    expect(within(currentChapterButton).getByText('1 phút đọc')).toBeInTheDocument();
    expect(within(currentChapterButton).getByText('Đã đọc')).toBeInTheDocument();

    await userEvent.click(within(drawer).getByRole('button', { name: 'Ch. 3 Thất Huyền Môn' }));
    expect(props.onSelectChapter).toHaveBeenCalledWith(103);
  });

  it('keeps book switching and workbench access in the more menu', async () => {
    const props = renderReader();
    expect(screen.queryByRole('complementary', { name: 'Mục lục sách' })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Thêm tùy chọn' }));
    const menu = screen.getByRole('dialog', { name: 'Tùy chọn đọc' });

    await userEvent.click(within(menu).getByRole('button', { name: 'Mở bàn dịch' }));
    expect(props.onOpenWorkbench).toHaveBeenCalledTimes(1);
  });

  it('opens X-Ray with no-spoiler data for the current chapter', async () => {
    const apiClient = mockReaderApiClient();
    renderReader({ apiClient });

    await userEvent.click(screen.getByRole('button', { name: 'Thêm tùy chọn' }));
    await userEvent.click(screen.getByRole('button', { name: 'Mở X-Ray' }));

    expect(apiClient.getReaderXray).toHaveBeenCalledWith(42, 102, 'no_spoiler');
    const panel = await screen.findByRole('dialog', { name: 'X-Ray truyện' });
    expect(within(panel).getByText('No spoiler · tới Ch. 2')).toBeInTheDocument();
    expect(within(panel).getByText('Hàn Lập')).toBeInTheDocument();
    expect(within(panel).queryByText('Lệ Phi Vũ')).not.toBeInTheDocument();
  });

  it('manually enriches X-Ray with AI for the current chapter', async () => {
    const apiClient = mockReaderApiClient();
    renderReader({ apiClient });

    await userEvent.click(screen.getByRole('button', { name: 'Thêm tùy chọn' }));
    await userEvent.click(screen.getByRole('button', { name: 'Mở X-Ray' }));

    const panel = await screen.findByRole('dialog', { name: 'X-Ray truyện' });
    await userEvent.click(within(panel).getByRole('button', { name: 'Làm giàu chương' }));

    await waitFor(() => {
      expect(apiClient.enrichReaderXray).toHaveBeenCalledWith(42, {
        chapterId: 102,
        spoilerMode: 'no_spoiler',
      });
    });
    await userEvent.click(within(panel).getByRole('tab', { name: /Relations/ }));
    expect(within(panel).getByText('Hàn Lập -> Thất Huyền Môn')).toBeInTheDocument();
    expect(within(panel).getByText('AI xác nhận quan hệ tông môn.')).toBeInTheDocument();
  });

  it('manually enriches X-Ray with AI for the whole book', async () => {
    const apiClient = mockReaderApiClient();
    renderReader({ apiClient });

    await userEvent.click(screen.getByRole('button', { name: 'Thêm tùy chọn' }));
    await userEvent.click(screen.getByRole('button', { name: 'Mở X-Ray' }));

    const panel = await screen.findByRole('dialog', { name: 'X-Ray truyện' });
    await userEvent.click(within(panel).getByRole('button', { name: 'Làm giàu toàn sách' }));

    await waitFor(() => {
      expect(apiClient.enrichReaderXray).toHaveBeenCalledWith(42, {
        chapterId: null,
        spoilerMode: 'no_spoiler',
      });
    });
  });

  it('lets the more menu switch translated books', async () => {
    const props = renderReader();

    await userEvent.click(screen.getByRole('button', { name: 'Thêm tùy chọn' }));
    await userEvent.selectOptions(screen.getByLabelText('Chọn truyện'), '42');

    expect(props.onSelectBook).toHaveBeenCalledWith(42);
  });

  it('filters chapters by number or title from the TOC drawer', async () => {
    const props = renderReader();
    await userEvent.click(screen.getByRole('button', { name: 'Mục lục' }));

    const drawer = screen.getByRole('dialog', { name: 'Mục lục' });
    const search = within(drawer).getByLabelText('Tìm trong mục lục');

    await userEvent.type(search, 'thất');

    expect(within(drawer).queryByRole('button', { name: 'Ch. 1 Sơn biên tiểu thôn' })).not.toBeInTheDocument();
    expect(within(drawer).getByRole('button', { name: 'Ch. 3 Thất Huyền Môn' })).toBeInTheDocument();

    await userEvent.clear(search);
    await userEvent.type(search, '1');
    expect(within(drawer).getByRole('button', { name: 'Ch. 1 Sơn biên tiểu thôn' })).toBeInTheDocument();
    expect(within(drawer).queryByRole('button', { name: 'Ch. 2 Thanh Ngưu trấn' })).not.toBeInTheDocument();

    await userEvent.click(within(drawer).getByRole('button', { name: 'Ch. 1 Sơn biên tiểu thôn' }));
    expect(props.onSelectChapter).toHaveBeenCalledWith(101);
  });

  it('searches the current chapter instantly and debounces full-book search', async () => {
    const apiClient = mockReaderApiClient({
      searchBook: vi.fn().mockResolvedValue([
        {
          chapter_id: 103,
          chapter_number: 3,
          chapter_title: 'Thất Huyền Môn',
          paragraph_index: 4,
          score: 85,
          snippet: 'Giữ xưng hô cổ trang.',
          source: 'note',
        },
      ]),
    });
    const props = renderReader({ apiClient });

    await userEvent.click(screen.getByRole('button', { name: 'Tìm kiếm' }));
    const panel = screen.getByRole('dialog', { name: 'Tìm trong truyện' });
    await userEvent.type(within(panel).getByLabelText('Từ khóa'), 'Lục');

    expect(within(panel).getByText('Lục ca, ta cảm tạ huynh.')).toBeInTheDocument();
    await waitFor(() => expect(apiClient.searchBook).toHaveBeenCalledWith(42, 'Lục', {
      caseSensitive: undefined,
      regex: undefined,
      scopes: ['translation', 'notes', 'highlights'],
      wholeWord: undefined,
    }));
    expect(await within(panel).findByText('Giữ xưng hô cổ trang.')).toBeInTheDocument();

    await userEvent.click(within(panel).getByRole('button', { name: 'Đến Ch. 3 đoạn 5' }));
    expect(props.onSelectChapter).toHaveBeenCalledWith(103);
    expect(screen.queryByRole('dialog', { name: 'Tìm trong truyện' })).not.toBeInTheDocument();
  });

  it('lets the reader tune theme, type size, line height, width, and hide chrome', async () => {
    renderReader();
    const article = screen.getByRole('article', { name: 'Nội dung đọc tiếng Việt' });

    await userEvent.click(screen.getByRole('button', { name: 'Cài đặt chữ' }));
    const sheet = screen.getByRole('dialog', { name: 'Cài đặt đọc' });

    await userEvent.click(within(sheet).getByRole('button', { name: 'Tối' }));
    expect(article).toHaveAttribute('data-theme', 'dark');

    fireEvent.change(within(sheet).getByLabelText('Cỡ chữ'), { target: { value: '20' } });
    expect(article).toHaveStyle({ '--reader-font-size': '20px' });

    fireEvent.change(within(sheet).getByLabelText('Giãn dòng'), { target: { value: '2' } });
    expect(article).toHaveStyle({ '--reader-line-height': '2' });

    await userEvent.click(within(sheet).getByRole('button', { name: 'Rộng' }));
    expect(article).toHaveAttribute('data-width', 'wide');

    await userEvent.click(article);
    expect(screen.getByRole('region', { name: 'Trang đọc truyện' })).toHaveAttribute('data-chrome-visible', 'false');
  });
});
