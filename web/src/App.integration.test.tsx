import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';
import { loadReaderProgressSnapshot, saveReaderProgressSnapshot } from './state/readerProgress';
import { clearToken, saveToken } from './state/session';
import {
  fixtureBook,
  fixtureChapter,
  fixtureGlossaryTerm,
  fixtureMissingKeyProvider,
  fixtureProvider,
  fixtureStyleProfile,
  fixtureUsage,
} from './test/fixtures';

function streamFromText(text: string): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();

  return new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode(text));
      controller.close();
    },
  });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });

  return { promise, resolve };
}

function defaultAssistAutoLoadResponse(target: string) {
  if (target.endsWith('/api/style-profiles')) {
    return {
      ok: true,
      json: async () => ({ profiles: [] }),
    };
  }

  if (/\/api\/glossary\?book_id=\d+&per_page=500$/.test(target)) {
    return {
      ok: true,
      json: async () => ({ items: [] }),
    };
  }

  if (/\/api\/books\/\d+\/chapters\/\d+\/qa$/.test(target)) {
    return {
      ok: false,
      status: 404,
      statusText: 'Not Found',
      json: async () => ({ detail: 'No QA report yet' }),
    };
  }

  if (/\/api\/jobs\/[^/]+\/attempts$/.test(target)) {
    return {
      ok: true,
      json: async () => ({ attempts: [] }),
    };
  }

  if (target.endsWith('/api/library/books')) {
    return {
      ok: true,
      json: async () => ({
        books: [
          {
            id: fixtureBook.id,
            title: fixtureBook.title,
            author: fixtureBook.author,
            source: fixtureBook.source,
            source_url: fixtureBook.source_url,
            total_chapters: 1,
            translated_chapters: 1,
            audio_chapters: 0,
            failed_chapters: 0,
            qa_low_chapters: 0,
            first_translated_chapter_id: fixtureChapter.id,
            latest_translated_chapter_id: fixtureChapter.id,
            latest_chapter_number: fixtureChapter.chapter_number,
            latest_chapter_title: fixtureChapter.title,
            last_activity: fixtureBook.updated_at,
          },
        ],
      }),
    };
  }

  return null;
}

async function expectNoGlobalAlert(): Promise<void> {
  await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
}

async function expectReaderPage(): Promise<void> {
  expect(
    await screen.findByRole('heading', { name: 'Đọc truyện' }, { timeout: 10_000 }),
  ).toBeInTheDocument();
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

async function openRawBacklogChapter(chapterNumber = 1, bookTitle = 'Live Book'): Promise<void> {
  await userEvent.click(
    within(screen.getByRole('navigation', { name: 'Quy trình' })).getByRole('button', { name: 'Raw chưa dịch' }),
  );
  expect(await screen.findByRole('heading', { name: 'Raw chưa dịch' })).toBeInTheDocument();

  await userEvent.click(
    await screen.findByRole('button', {
      name: new RegExp(`Mở bàn dịch\\s+${escapeRegExp(bookTitle)}\\s+chương\\s+${chapterNumber}`),
    }),
  );
}

async function openTranslatedWorkbench(bookTitle = 'Live Book'): Promise<void> {
  await userEvent.click(
    within(screen.getByRole('navigation', { name: 'Quy trình' })).getByRole('button', { name: 'Thư viện' }),
  );
  expect(await screen.findByRole('heading', { name: 'Thư viện' })).toBeInTheDocument();

  const bookHeading = await screen.findByRole('heading', { name: bookTitle });
  const row = bookHeading.closest('article');
  expect(row).not.toBeNull();
  await userEvent.click(within(row as HTMLElement).getByRole('button', { name: 'Sửa' }));
}

function installDirtyWorkbenchApiMock({ saveUnauthorized = false } = {}) {
  let logoutCalls = 0;
  const fetchMock = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const target = String(url);

    if (target.endsWith('/api/providers')) {
      return { ok: true, json: async () => ({ providers: [fixtureProvider] }) };
    }
    if (target.endsWith('/api/style-profiles')) {
      return { ok: true, json: async () => ({ profiles: [fixtureStyleProfile] }) };
    }
    if (target.endsWith('/api/books')) {
      return { ok: true, json: async () => [fixtureBook] };
    }
    if (target.endsWith('/api/books/42/chapters')) {
      return { ok: true, json: async () => [fixtureChapter] };
    }
    if (target.endsWith('/api/books/42/chapters/4201/source')) {
      return { ok: true, json: async () => ({ chapter_id: 4201, text: 'Live source text' }) };
    }
    if (target.endsWith('/api/books/42/chapters/4201/translation')) {
      if (init?.method === 'PATCH') {
        if (saveUnauthorized) {
          return {
            ok: false,
            status: 401,
            statusText: 'Unauthorized',
            json: async () => ({ detail: 'Not authenticated' }),
          };
        }
        return { ok: true, json: async () => ({ chapter_id: 4201, text: 'Dirty draft' }) };
      }
      return { ok: true, json: async () => ({ chapter_id: 4201, text: 'Saved translation' }) };
    }
    if (target.endsWith('/api/providers/estimate')) {
      return {
        ok: true,
        json: async () => ({
          provider_id: fixtureProvider.id,
          model: fixtureProvider.model,
          chapter_count: 1,
          estimated_input_tokens: 100,
          estimated_output_tokens: 100,
          estimated_cost_usd: 0.0001,
          within_budget: true,
        }),
      };
    }
    if (target.endsWith('/api/providers/usage')) {
      return { ok: true, json: async () => ({ usage: fixtureUsage }) };
    }
    if (target.endsWith('/api/system/status')) {
      return { ok: true, json: async () => ({ api_ready: true, active_jobs: 0, running_jobs: 0 }) };
    }
    if (target.endsWith('/api/auth/logout') && init?.method === 'POST') {
      logoutCalls += 1;
      return { ok: true, json: async () => ({ ok: true }) };
    }

    const assistResponse = defaultAssistAutoLoadResponse(target);
    if (assistResponse) return assistResponse;

    throw new Error(`Unexpected URL: ${target}`);
  });
  vi.stubGlobal('fetch', fetchMock);
  return { fetchMock, getLogoutCalls: () => logoutCalls };
}

async function renderDirtyWorkbench(options: { saveUnauthorized?: boolean } = {}) {
  saveToken('access');
  const api = installDirtyWorkbenchApiMock(options);
  const rendered = render(<App />);
  await openTranslatedWorkbench();
  const translation = await screen.findByLabelText('Bản dịch tiếng Việt');
  expect(translation).toHaveValue('Saved translation');
  await userEvent.clear(translation);
  await userEvent.type(translation, 'Dirty draft');
  expect(translation).toHaveValue('Dirty draft');
  return { ...api, ...rendered, translation };
}

describe('App live data wiring', () => {
  beforeEach(() => {
    clearToken();
  });

  afterEach(() => {
    cleanup();
    clearToken();
    vi.unstubAllGlobals();
  });

  it('renders honest empty states without seed books, chapters, providers, or estimates', async () => {
    saveToken('access');
    const fetchMock = vi.fn(async (url: RequestInfo | URL) => {
      const target = String(url);

      if (target.endsWith('/api/providers')) return { ok: true, json: async () => ({ providers: [] }) };
      if (target.endsWith('/api/style-profiles')) return { ok: true, json: async () => ({ profiles: [] }) };
      if (target.endsWith('/api/books')) return { ok: true, json: async () => [] };
      if (target.endsWith('/api/providers/usage')) {
        return {
          ok: true,
          json: async () => ({
            usage: fixtureUsage,
          }),
        };
      }

      const assistResponse = defaultAssistAutoLoadResponse(target);
      if (assistResponse) return assistResponse;

      throw new Error(`Unexpected URL: ${target}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);

    expect(await screen.findByRole('heading', { name: 'Chưa chọn chương' })).toBeInTheDocument();
    expect(screen.getByText('Chọn một chương trong danh sách bên trái để bắt đầu biên tập bản dịch.')).toBeInTheDocument();
    expect(screen.queryByText('Phàm Nhân Tu Tiên')).not.toBeInTheDocument();
    expect(screen.queryByText('Gemini Flash')).not.toBeInTheDocument();
    expect(screen.queryByText('gemini-2.5-flash-lite')).not.toBeInTheDocument();
    expect(screen.queryByText('Tiên hiệp')).not.toBeInTheDocument();
    expect(screen.queryByText('Estimated cost')).not.toBeInTheDocument();
    await expectNoGlobalAlert();
  });

  it('PR-2 unsaved translation guard registers beforeunload only while dirty and removes it when clean or unmounted', async () => {
    saveToken('access');
    installDirtyWorkbenchApiMock();
    const rendered = render(<App />);
    await openTranslatedWorkbench();
    const translation = await screen.findByLabelText('Bản dịch tiếng Việt');
    expect(translation).toHaveValue('Saved translation');

    const cleanEvent = new Event('beforeunload', { cancelable: true });
    expect(window.dispatchEvent(cleanEvent)).toBe(true);
    expect(cleanEvent.defaultPrevented).toBe(false);

    await userEvent.clear(translation);
    await userEvent.type(translation, 'Dirty draft');
    const dirtyEvent = new Event('beforeunload', { cancelable: true });
    expect(window.dispatchEvent(dirtyEvent)).toBe(false);
    expect(dirtyEvent.defaultPrevented).toBe(true);

    await userEvent.click(screen.getByRole('button', { name: 'Lưu' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Lưu' })).toBeDisabled());
    const savedEvent = new Event('beforeunload', { cancelable: true });
    expect(window.dispatchEvent(savedEvent)).toBe(true);
    expect(savedEvent.defaultPrevented).toBe(false);

    await userEvent.type(translation, ' changed again');
    rendered.unmount();
    const unmountedEvent = new Event('beforeunload', { cancelable: true });
    expect(window.dispatchEvent(unmountedEvent)).toBe(true);
    expect(unmountedEvent.defaultPrevented).toBe(false);
  });

  it('PR-2 unsaved translation guard skips same-view actions and cancel keeps the Workbench draft unchanged', async () => {
    const confirmLeave = vi.fn(() => false);
    vi.stubGlobal('confirm', confirmLeave);
    const { translation } = await renderDirtyWorkbench();
    const workflowNav = screen.getByRole('navigation', { name: 'Quy trình' });

    await userEvent.click(within(workflowNav).getByRole('button', { name: 'Bàn dịch' }));
    expect(confirmLeave).not.toHaveBeenCalled();
    expect(translation).toHaveValue('Dirty draft');

    await userEvent.click(within(workflowNav).getByRole('button', { name: 'Raw chưa dịch' }));
    expect(confirmLeave).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('region', { name: 'Workbench' })).toBeInTheDocument();
    expect(screen.getByLabelText('Bản dịch tiếng Việt')).toHaveValue('Dirty draft');
  });

  it('PR-2 unsaved translation guard never blocks forced 401 expiry while a draft is dirty', async () => {
    const confirmLeave = vi.fn(() => false);
    vi.stubGlobal('confirm', confirmLeave);
    await renderDirtyWorkbench({ saveUnauthorized: true });

    await userEvent.click(screen.getByRole('button', { name: 'Lưu' }));

    expect(await screen.findByRole('button', { name: 'Login' })).toBeInTheDocument();
    expect(await screen.findByText('Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.')).toBeInTheDocument();
    expect(confirmLeave).not.toHaveBeenCalled();
  });

  it('retries the last failed job from the status page', async () => {
    saveToken('access');
    const systemStatus = {
      active_jobs: 0,
      active_provider: 'gemini',
      api_ready: true,
      app_version: '0.1.0',
      asset_protection_enabled: true,
      backup_recommendation: 'System backup is separate from book export. Run scripts/backup-local.sh before upgrades or public deploy changes.',
      build: 'phase1',
      cache_count: 0,
      cache_size_bytes: 0,
      data_directory_available: true,
      data_size_bytes: 8192,
      database_available: true,
      db_size_bytes: 4096,
      last_failed_job: {
        job_id: 'job-restarted',
        job_type: 'translate',
        status: 'failed',
        progress: 1,
        total: 2,
        message: 'Server restarted during job. Please retry the job.',
        error: 'Server restarted during job',
        retry_count: 0,
      },
      ollama_host: 'http://localhost:11434/v1',
      ollama_model: 'qwen3:14b',
      storage_health: 'healthy',
      storage_label: 'Configured data storage',
      public_deploy: true,
      running_jobs: 0,
      upload_max_bytes: 104857600,
    };
    const fetchMock = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      const target = String(url);

      if (target.endsWith('/api/providers')) return { ok: true, json: async () => ({ providers: [] }) };
      if (target.endsWith('/api/style-profiles')) return { ok: true, json: async () => ({ profiles: [] }) };
      if (target.endsWith('/api/books')) return { ok: true, json: async () => [] };
      if (target.endsWith('/api/providers/usage')) {
        return { ok: true, json: async () => ({ usage: fixtureUsage }) };
      }
      if (target.endsWith('/api/system/status')) {
        return { ok: true, json: async () => systemStatus };
      }
      if (target.endsWith('/api/jobs/job-restarted/retry') && init?.method === 'POST') {
        return {
          ok: true,
          json: async () => ({ job_id: 'job-retry', status: 'pending', message: 'Retry job started' }),
        };
      }
      if (target.endsWith('/api/jobs/job-retry/events')) {
        return {
          ok: true,
          body: streamFromText('data: {"job_id":"job-retry","status":"completed","progress":1,"total":1,"message":"Retry queued"}\n\n'),
        };
      }
      if (target.endsWith('/api/jobs/job-retry/attempts')) {
        return { ok: true, json: async () => ({ attempts: [] }) };
      }

      const assistResponse = defaultAssistAutoLoadResponse(target);
      if (assistResponse) return assistResponse;

      throw new Error(`Unexpected URL: ${target}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);

    await userEvent.click(
      within(await screen.findByRole('navigation', { name: 'Quy trình' }))
        .getByRole('button', { name: 'Trạng thái' }),
    );
    expect(await screen.findByRole('heading', { name: 'Trạng thái hệ thống' })).toBeInTheDocument();
    expect(await screen.findByText('Server đã restart khi job đang chạy. Hãy chạy lại job.')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Chạy lại' }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        'http://127.0.0.1:7860/api/jobs/job-restarted/retry',
        expect.objectContaining({ method: 'POST' }),
      ),
    );
    expect(await screen.findByText('Chạy lại job đã bắt đầu: job-retry')).toBeInTheDocument();
  });

  it('saves provider API keys from the Model API page', async () => {
    saveToken('access');
    const savedProvider = { ...fixtureMissingKeyProvider, api_key_set: true };
    const fetchMock = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      const target = String(url);

      if (target.endsWith('/api/providers')) return { ok: true, json: async () => ({ providers: [fixtureMissingKeyProvider] }) };
      if (target.endsWith('/api/style-profiles')) return { ok: true, json: async () => ({ profiles: [] }) };
      if (target.endsWith('/api/books')) return { ok: true, json: async () => [] };
      if (target.endsWith('/api/providers/usage')) return { ok: true, json: async () => ({ usage: fixtureUsage }) };
      if (target.endsWith('/api/providers/missing/key') && init?.method === 'POST') {
        return { ok: true, json: async () => ({ provider: savedProvider }) };
      }

      const assistResponse = defaultAssistAutoLoadResponse(target);
      if (assistResponse) return assistResponse;

      throw new Error(`Unexpected URL: ${target}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);

    await screen.findByRole('heading', { name: 'Chưa chọn chương' });
    await userEvent.click(within(screen.getByRole('navigation', { name: 'Quy trình' })).getByRole('button', { name: 'Model API' }));
    const keyInput = await screen.findByLabelText('API key cho Missing Key Provider');
    await userEvent.type(keyInput, 'new-secret');
    await userEvent.click(screen.getByRole('button', { name: 'Lưu key cho Missing Key Provider' }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      'http://127.0.0.1:7860/api/providers/missing/key',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
        body: JSON.stringify({ api_key: 'new-secret' }),
      }),
    ));
    expect(await screen.findByText('Đã lưu API key cho Missing Key Provider.')).toBeVisible();
    expect(screen.getByLabelText('API key cho Missing Key Provider')).toHaveValue('');
    await expectNoGlobalAlert();
  });

  it('imports a translated ebook into the library from the import page', async () => {
    saveToken('access');
    const importedBook = {
      id: 101,
      title: 'Đấu Phá Thương Khung',
      author: 'Thiên Tằm Thổ Đậu',
      source: 'ebook',
      source_url: '',
      created_at: '2026-06-26T00:00:00Z',
      updated_at: '2026-06-26T00:00:00Z',
    };
    const importedChapter = {
      ...fixtureChapter,
      id: 10101,
      book_id: 101,
      chapter_number: 1,
      title: 'Vẫn Lạc Thiên Tài',
      status: 'translated',
      translated_text_path: '/tmp/translated.txt',
    };
    const fetchMock = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      const target = String(url);

      if (target.endsWith('/api/providers')) return { ok: true, json: async () => ({ providers: [] }) };
      if (target.endsWith('/api/style-profiles')) return { ok: true, json: async () => ({ profiles: [] }) };
      if (target.endsWith('/api/books')) return { ok: true, json: async () => [importedBook] };
      if (target.endsWith('/api/books/101/chapters')) return { ok: true, json: async () => [importedChapter] };
      if (target.endsWith('/api/providers/usage')) return { ok: true, json: async () => ({ usage: fixtureUsage }) };

      if (target.endsWith('/api/import/ebook/preview') && init?.method === 'POST') {
        const body = init.body as FormData;
        expect(body.get('split_mode')).toBe('auto');
        expect(body.get('file')).toBeInstanceOf(File);
        return {
          ok: true,
          json: async () => ({
            title: 'Đấu Phá Thương Khung',
            author: 'Thiên Tằm Thổ Đậu',
            language: 'vi',
            source_format: 'epub',
            cover_present: false,
            chapter_count: 1,
            chapters: [{ chapter_number: 1, title: 'Vẫn Lạc Thiên Tài', sample: 'Đấu khí, ba đoạn!' }],
            dry_run: {
              target_book_id: 101,
              target_title: 'Đấu Phá Thương Khung',
              duplicate_strategy: 'skip',
              chapter_count: 1,
              new_chapters: 0,
              duplicate_chapters: 1,
              would_import: 0,
              would_skip: 1,
              would_overwrite: 0,
              would_error: 0,
              existing_book_id: 101,
              existing_book_title: 'Đấu Phá Thương Khung',
              existing_chapter_count: 1,
              book_match_reason: 'title',
              requires_existing_book_confirmation: true,
            },
          }),
        };
      }

      if (target.endsWith('/api/import/ebook/job') && init?.method === 'POST') {
        const body = init.body as FormData;
        expect(body.get('duplicate_strategy')).toBe('skip');
        expect(body.get('split_mode')).toBe('auto');
        expect(body.get('confirmed_existing_book_id')).toBe('101');
        return {
          ok: true,
          json: async () => ({
            job_id: 'job-import-ebook',
            status: 'pending',
            message: 'Translated ebook import job started',
          }),
        };
      }

      if (target.endsWith('/api/jobs/job-import-ebook/events')) {
        return {
          ok: true,
          body: streamFromText(
            'data: {"job_id":"job-import-ebook","job_type":"import_ebook","status":"completed","progress":1,"total":1,"message":"Imported 0 translated ebook chapter(s), skipped 1."}\n\n',
          ),
        };
      }

      if (target.endsWith('/api/jobs/job-import-ebook')) {
        return {
          ok: true,
          json: async () => ({
            job_id: 'job-import-ebook',
            job_type: 'import_ebook',
            status: 'completed',
            progress: 1,
            total: 1,
            message: 'Imported 0 translated ebook chapter(s), skipped 1.',
          }),
        };
      }

      if (target.includes('/api/jobs?')) {
        return {
          ok: true,
          json: async () => ({
            jobs: [
              {
                job_id: 'job-import-ebook',
                job_type: 'import_ebook',
                status: 'completed',
                progress: 1,
                total: 1,
                message: 'Imported 0 translated ebook chapter(s), skipped 1.',
              },
            ],
          }),
        };
      }

      if (target.endsWith('/api/library/books')) {
        return {
          ok: true,
          json: async () => ({
            books: [
              {
                id: 101,
                title: importedBook.title,
                author: importedBook.author,
                source: 'ebook',
                source_url: '',
                total_chapters: 1,
                translated_chapters: 1,
                audio_chapters: 0,
                failed_chapters: 0,
                qa_low_chapters: 0,
                first_translated_chapter_id: 10101,
                latest_translated_chapter_id: 10101,
                latest_chapter_number: 1,
                latest_chapter_title: 'Vẫn Lạc Thiên Tài',
                last_activity: '2026-06-26T00:00:00Z',
              },
            ],
          }),
        };
      }

      const assistResponse = defaultAssistAutoLoadResponse(target);
      if (assistResponse) return assistResponse;

      throw new Error(`Unexpected URL: ${target}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);

    await screen.findByRole('heading', { name: 'Chưa chọn chương' });
    await userEvent.click(within(screen.getByRole('navigation', { name: 'Quy trình' })).getByRole('button', { name: 'Nhập chương' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Ebook bản dịch' }));
    await userEvent.upload(
      await screen.findByLabelText('Ebook file'),
      new File(['ebook'], 'dau-pha.epub', { type: 'application/epub+zip' }),
    );

    expect(await screen.findByRole('heading', { name: 'Đấu Phá Thương Khung' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('radio', { name: 'Bỏ qua chương trùng' }));
    const importButton = screen.getByRole('button', { name: 'Import vào Library' });
    expect(importButton).toBeDisabled();
    await userEvent.click(screen.getByLabelText('Tôi xác nhận gộp ebook này vào truyện đã có.'));
    expect(importButton).toBeEnabled();
    await userEvent.click(importButton);

    expect(await screen.findByRole('heading', { name: 'Tác vụ' })).toBeInTheDocument();
    expect(screen.getByText('Đã bắt đầu import ebook. Theo dõi tác vụ job-impo.')).toBeInTheDocument();
    expect(await screen.findAllByText('Imported 0 translated ebook chapter(s), skipped 1.')).not.toHaveLength(0);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      'http://127.0.0.1:7860/api/import/ebook/job',
      expect.objectContaining({ method: 'POST' }),
    ));
    await expectNoGlobalAlert();
  });

  it('keeps the import page and clears stale confirmation after an ebook job conflict', async () => {
    saveToken('access');
    const existingBook = {
      id: 101,
      title: 'Đấu Phá Thương Khung',
      author: 'Thiên Tằm Thổ Đậu',
      source: 'ebook',
      source_url: '',
      created_at: '2026-06-26T00:00:00Z',
      updated_at: '2026-06-26T00:00:00Z',
    };
    const safeDetail = 'Truyện này đã tồn tại trong Library. Hãy Preview và xác nhận gộp vào truyện hiện có.';
    const fetchMock = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      const target = String(url);

      if (target.endsWith('/api/providers')) return { ok: true, json: async () => ({ providers: [] }) };
      if (target.endsWith('/api/style-profiles')) return { ok: true, json: async () => ({ profiles: [] }) };
      if (target.endsWith('/api/books')) return { ok: true, json: async () => [existingBook] };
      if (target.endsWith('/api/books/101/chapters')) return { ok: true, json: async () => [] };
      if (target.endsWith('/api/providers/usage')) return { ok: true, json: async () => ({ usage: fixtureUsage }) };

      if (target.endsWith('/api/import/ebook/preview') && init?.method === 'POST') {
        return {
          ok: true,
          json: async () => ({
            title: existingBook.title,
            author: existingBook.author,
            language: 'vi',
            source_format: 'epub',
            cover_present: false,
            chapter_count: 1,
            chapters: [{ chapter_number: 1, title: 'Vẫn Lạc Thiên Tài', sample: 'Đấu khí, ba đoạn!' }],
            dry_run: {
              target_book_id: 101,
              target_title: existingBook.title,
              duplicate_strategy: 'skip',
              chapter_count: 1,
              new_chapters: 1,
              duplicate_chapters: 0,
              would_import: 1,
              would_skip: 0,
              would_overwrite: 0,
              would_error: 0,
              existing_book_id: 101,
              existing_book_title: existingBook.title,
              existing_chapter_count: 0,
              book_match_reason: 'title',
              requires_existing_book_confirmation: true,
            },
          }),
        };
      }

      if (target.endsWith('/api/import/ebook/job') && init?.method === 'POST') {
        const body = init.body as FormData;
        expect(body.get('confirmed_existing_book_id')).toBe('101');
        return {
          ok: false,
          status: 409,
          statusText: 'Conflict',
          json: async () => ({ detail: safeDetail }),
        };
      }

      const assistResponse = defaultAssistAutoLoadResponse(target);
      if (assistResponse) return assistResponse;

      throw new Error(`Unexpected URL: ${target}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);

    await screen.findByRole('heading', { name: 'Chưa chọn chương' });
    await userEvent.click(within(screen.getByRole('navigation', { name: 'Quy trình' })).getByRole('button', { name: 'Nhập chương' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Ebook bản dịch' }));
    await userEvent.upload(
      await screen.findByLabelText('Ebook file'),
      new File(['ebook'], 'dau-pha.epub', { type: 'application/epub+zip' }),
    );
    await userEvent.click(await screen.findByLabelText('Tôi xác nhận gộp ebook này vào truyện đã có.'));
    await userEvent.click(screen.getByRole('button', { name: 'Import vào Library' }));

    expect(await screen.findAllByText(new RegExp(safeDetail))).not.toHaveLength(0);
    expect(screen.getByRole('heading', { name: 'Ebook bản dịch' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Tác vụ' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Tôi xác nhận gộp ebook này vào truyện đã có.')).not.toBeInTheDocument();

    const retryButton = screen.getByRole('button', { name: 'Preview lại' });
    expect(retryButton).toBeEnabled();
    await userEvent.click(retryButton);

    expect(await screen.findByLabelText('Tôi xác nhận gộp ebook này vào truyện đã có.')).not.toBeChecked();
    expect(fetchMock.mock.calls.filter(([url, init]) => (
      String(url).endsWith('/api/import/ebook/preview') && init?.method === 'POST'
    ))).toHaveLength(2);
  });

  it('opens translated library and reader as separate workflow pages', async () => {
    saveToken('access');
    let translatedLibraryRequests = 0;
    const fetchMock = vi.fn(async (url: RequestInfo | URL) => {
      const target = String(url);

      if (target.endsWith('/api/providers')) {
        return {
          ok: true,
          json: async () => ({ providers: [{ ...fixtureProvider, notes: '' }] }),
        };
      }

      if (target.endsWith('/api/style-profiles')) {
        return {
          ok: true,
          json: async () => ({ profiles: [fixtureStyleProfile] }),
        };
      }

      if (target.endsWith('/api/books')) {
        return {
          ok: true,
          json: async () => [fixtureBook],
        };
      }

      if (target.endsWith('/api/books/42/chapters')) {
        return {
          ok: true,
          json: async () => [fixtureChapter],
        };
      }

      if (target.endsWith('/api/books/42/chapters/4201/source')) {
        return { ok: true, json: async () => ({ chapter_id: 4201, text: '原文' }) };
      }

      if (target.endsWith('/api/books/42/chapters/4201/translation')) {
        return {
          ok: true,
          json: async () => ({ chapter_id: 4201, text: 'Hắn bước vào động phủ.\n\nLinh khí cuồn cuộn.' }),
        };
      }

      if (target.endsWith('/api/library/books')) {
        translatedLibraryRequests += 1;
        return {
          ok: true,
          json: async () => ({
            books: [
              {
                id: 42,
                title: 'Live Book',
                author: '',
                source: 'manual',
                source_url: '',
                total_chapters: 1,
                translated_chapters: 1,
                audio_chapters: 0,
                failed_chapters: 0,
                qa_low_chapters: 0,
                first_translated_chapter_id: 4201,
                latest_translated_chapter_id: 4201,
                latest_chapter_number: 1,
                latest_chapter_title: 'Live Chapter',
                last_activity: '2026-06-20T00:00:00Z',
              },
            ],
          }),
        };
      }

      if (target.endsWith('/api/providers/estimate')) {
        return {
          ok: true,
          json: async () => ({
            provider_id: 'gemini',
            model: 'gemini-live',
            chapter_count: 1,
            estimated_input_tokens: 100,
            estimated_output_tokens: 200,
            estimated_cost_usd: 0.0001,
            within_budget: true,
          }),
        };
      }

      if (target.endsWith('/api/providers/usage')) {
        return {
          ok: true,
          json: async () => ({ usage: fixtureUsage }),
        };
      }

      const assistResponse = defaultAssistAutoLoadResponse(target);
      if (assistResponse) return assistResponse;

      throw new Error(`Unexpected URL: ${target}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);

    expect(await screen.findByRole('heading', { name: 'Chưa chọn chương' })).toBeInTheDocument();
    await userEvent.click(within(screen.getByRole('navigation', { name: 'Quy trình' })).getByRole('button', { name: 'Thư viện' }));

    expect(await screen.findByRole('heading', { name: 'Thư viện' })).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: 'Live Book' })).toBeInTheDocument();
    expect(screen.getByText('1/1 chương đã dịch')).toBeVisible();
    expect(translatedLibraryRequests).toBe(1);

    await userEvent.click(screen.getByRole('button', { name: 'Đọc tiếp Live Book' }));

    await expectReaderPage();
    expect(screen.getByRole('article', { name: 'Nội dung đọc tiếng Việt' })).toHaveTextContent('Hắn bước vào động phủ.');
    expect(screen.getByRole('article', { name: 'Nội dung đọc tiếng Việt' })).toHaveTextContent('Linh khí cuồn cuộn.');
    expect(
      within(screen.getByRole('navigation', { name: 'Quy trình' })).getByRole('button', { name: 'Đọc truyện' }),
    ).toHaveAttribute('aria-pressed', 'true');
    await expectNoGlobalAlert();
  });

  it('opens the newer local reader progress when backend progress is stale', async () => {
    saveToken('access');
    saveReaderProgressSnapshot(42, 4202, 80, 100, window.localStorage, {
      absoluteCharOffset: 120,
      charOffset: 12,
      mode: 'scroll',
      pageIndex: 0,
      paragraphIndex: 1,
      updatedAt: '2026-06-29T10:10:00Z',
    });
    const chapterTwo = {
      ...fixtureChapter,
      id: 4202,
      chapter_number: 2,
      title: 'Local Progress Chapter',
    };
    const fetchMock = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      const target = String(url);

      if (target.endsWith('/api/providers')) return { ok: true, json: async () => ({ providers: [{ ...fixtureProvider, notes: '' }] }) };
      if (target.endsWith('/api/style-profiles')) return { ok: true, json: async () => ({ profiles: [fixtureStyleProfile] }) };
      if (target.endsWith('/api/books')) return { ok: true, json: async () => [fixtureBook] };
      if (target.endsWith('/api/providers/usage')) return { ok: true, json: async () => ({ usage: fixtureUsage }) };
      if (target.endsWith('/api/books/42/chapters')) return { ok: true, json: async () => [fixtureChapter, chapterTwo] };
      if (target.endsWith('/api/books/42/reader/state')) {
        return {
          ok: true,
          json: async () => ({
            annotations: [],
            progress: {
              book_id: 42,
              chapter_id: 4201,
              chapter_number: 1,
              chapter_title: 'Live Chapter',
              char_offset: 3,
              absolute_char_offset: 3,
              mode: 'scroll',
              page_index: 0,
              paragraph_index: 0,
              percent: 20,
              updated_at: '2026-06-29T10:00:00Z',
            },
          }),
        };
      }
      if (target.endsWith('/api/books/42/reader/progress') && init?.method === 'PATCH') {
        return {
          ok: true,
          json: async () => ({
            progress: {
              book_id: 42,
              chapter_id: 4202,
              chapter_number: 2,
              chapter_title: 'Local Progress Chapter',
              char_offset: 12,
              absolute_char_offset: 120,
              mode: 'scroll',
              page_index: 0,
              paragraph_index: 1,
              percent: 80,
              updated_at: '2026-06-29T10:11:00Z',
            },
          }),
        };
      }
      if (target.endsWith('/api/books/42/chapters/4202/source')) {
        return { ok: true, json: async () => ({ chapter_id: 4202, text: '第二章' }) };
      }
      if (target.endsWith('/api/books/42/chapters/4202/translation')) {
        return {
          ok: true,
          json: async () => ({ chapter_id: 4202, text: 'Chương hai từ local progress.' }),
        };
      }

      const assistResponse = defaultAssistAutoLoadResponse(target);
      if (assistResponse) return assistResponse;

      throw new Error(`Unexpected URL: ${target}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);

    await userEvent.click(within(screen.getByRole('navigation', { name: 'Quy trình' })).getByRole('button', { name: 'Thư viện' }));
    expect(await screen.findByRole('heading', { name: 'Live Book' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Đọc tiếp Live Book' }));

    await expectReaderPage();
    expect(screen.getByRole('article', { name: 'Nội dung đọc tiếng Việt' })).toHaveTextContent('Chương hai từ local progress.');
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      'http://127.0.0.1:7860/api/books/42/reader/state',
      expect.anything(),
    ));
    expect(loadReaderProgressSnapshot(42, window.localStorage)).toMatchObject({
      chapterId: 4202,
      updatedAt: '2026-06-29T10:10:00Z',
    });
  });

  it('deletes a translated book from the library after confirmation', async () => {
    saveToken('access');
    let libraryDeleted = false;
    const fetchMock = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      const target = String(url);

      if (target.endsWith('/api/providers')) return { ok: true, json: async () => ({ providers: [] }) };
      if (target.endsWith('/api/style-profiles')) return { ok: true, json: async () => ({ profiles: [] }) };
      if (target.endsWith('/api/books')) return { ok: true, json: async () => [] };
      if (target.endsWith('/api/providers/usage')) return { ok: true, json: async () => ({ usage: fixtureUsage }) };
      if (target.endsWith('/api/books/42') && init?.method === 'DELETE') {
        libraryDeleted = true;
        return { ok: true, json: async () => ({ message: 'Book deleted' }) };
      }
      if (target.endsWith('/api/library/books')) {
        return {
          ok: true,
          json: async () => ({
            books: libraryDeleted
              ? []
              : [
                  {
                    id: 42,
                    title: 'Live Book',
                    author: '',
                    source: 'manual',
                    source_url: '',
                    total_chapters: 1,
                    translated_chapters: 1,
                    audio_chapters: 0,
                    failed_chapters: 0,
                    qa_low_chapters: 0,
                    first_translated_chapter_id: 4201,
                    latest_translated_chapter_id: 4201,
                    latest_chapter_number: 1,
                    latest_chapter_title: 'Live Chapter',
                    last_activity: '2026-06-20T00:00:00Z',
                  },
                ],
          }),
        };
      }

      const assistResponse = defaultAssistAutoLoadResponse(target);
      if (assistResponse) return assistResponse;

      throw new Error(`Unexpected URL: ${target}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);

    await screen.findByRole('heading', { name: 'Chưa chọn chương' });
    await userEvent.click(within(screen.getByRole('navigation', { name: 'Quy trình' })).getByRole('button', { name: 'Thư viện' }));

    expect(await screen.findByRole('heading', { name: 'Live Book' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Xóa sách Live Book' }));
    expect(screen.getByRole('dialog', { name: 'Xóa sách?' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Xóa sách' }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      'http://127.0.0.1:7860/api/books/42',
      expect.objectContaining({ method: 'DELETE' }),
    ));
    expect(await screen.findByRole('heading', { name: 'Thư viện trống' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Live Book' })).not.toBeInTheDocument();
    await expectNoGlobalAlert();
  });

  it('uploads and refreshes a translated book cover from the library', async () => {
    saveToken('access');
    let coverUploaded = false;
    const fetchMock = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      const target = String(url);

      if (target.endsWith('/api/providers')) return { ok: true, json: async () => ({ providers: [] }) };
      if (target.endsWith('/api/style-profiles')) return { ok: true, json: async () => ({ profiles: [] }) };
      if (target.endsWith('/api/books')) return { ok: true, json: async () => [] };
      if (target.endsWith('/api/providers/usage')) return { ok: true, json: async () => ({ usage: fixtureUsage }) };
      if (target.endsWith('/api/books/42/cover') && init?.method === 'POST') {
        const body = init.body as FormData;
        expect(body.get('cover')).toBeInstanceOf(File);
        coverUploaded = true;
        return {
          ok: true,
          json: async () => ({
            id: 42,
            title: 'Live Book',
            author: '',
            source: 'manual',
            source_url: '',
            cover_path: '/tmp/covers/book_42.jpg',
            cover_url: '/covers/book_42.jpg',
            created_at: '2026-06-20T00:00:00Z',
            updated_at: '2026-06-20T00:00:00Z',
          }),
        };
      }
      if (target.endsWith('/api/library/books')) {
        return {
          ok: true,
          json: async () => ({
            books: [
              {
                id: 42,
                title: 'Live Book',
                author: '',
                source: 'manual',
                source_url: '',
                cover_url: coverUploaded ? '/covers/book_42.jpg' : '',
                total_chapters: 1,
                translated_chapters: 1,
                audio_chapters: 0,
                failed_chapters: 0,
                qa_low_chapters: 0,
                first_translated_chapter_id: 4201,
                latest_translated_chapter_id: 4201,
                latest_chapter_number: 1,
                latest_chapter_title: 'Live Chapter',
                last_activity: '2026-06-20T00:00:00Z',
              },
            ],
          }),
        };
      }

      const assistResponse = defaultAssistAutoLoadResponse(target);
      if (assistResponse) return assistResponse;

      throw new Error(`Unexpected URL: ${target}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);

    await screen.findByRole('heading', { name: 'Chưa chọn chương' });
    await userEvent.click(within(screen.getByRole('navigation', { name: 'Quy trình' })).getByRole('button', { name: 'Thư viện' }));

    expect(await screen.findByRole('heading', { name: 'Live Book' })).toBeInTheDocument();
    await userEvent.upload(
      screen.getByLabelText('Thêm bìa sách Live Book'),
      new File(['cover'], 'cover.jpg', { type: 'image/jpeg' }),
    );

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      'http://127.0.0.1:7860/api/books/42/cover',
      expect.objectContaining({ method: 'POST' }),
    ));
    expect(await screen.findByRole('img', { name: 'Bìa Live Book' })).toHaveAttribute('src', '/covers/book_42.jpg');
    expect(screen.getByText('Đã cập nhật bìa sách.')).toBeInTheDocument();
    await expectNoGlobalAlert();
  });

  it('does not request seed chapter text before live chapters hydrate', async () => {
    saveToken('access');
    const fetchMock = vi.fn(async (url: RequestInfo | URL) => {
      const target = String(url);

      if (target.endsWith('/api/books/1/chapters/11/source')) {
        throw new Error('Stale seed chapter source should not be requested');
      }

      if (target.endsWith('/api/books/1/chapters/11/translation')) {
        throw new Error('Stale seed chapter translation should not be requested');
      }

      if (target.endsWith('/api/providers')) {
        return {
          ok: true,
          json: async () => ({
            providers: [{ ...fixtureProvider, notes: '' }],
          }),
        };
      }

      if (target.endsWith('/api/style-profiles')) {
        return {
          ok: true,
          json: async () => ({
            profiles: [
              fixtureStyleProfile,
              {
                ...fixtureStyleProfile,
                id: 'kiem_hiep',
                label: 'Kiếm hiệp',
                is_default: 0,
              },
            ],
          }),
        };
      }

      if (target.endsWith('/api/books')) {
        return {
          ok: true,
          json: async () => [
            {
              ...fixtureBook,
              id: 1,
              title: 'Live Book Same Id',
            },
          ],
        };
      }

      if (target.endsWith('/api/books/1/chapters')) {
        return {
          ok: true,
          json: async () => [
            {
              ...fixtureChapter,
              id: 101,
              book_id: 1,
              title: 'Live Chapter Same Book',
            },
          ],
        };
      }

      if (target.endsWith('/api/books/1/chapters/101/source')) {
        return { ok: true, json: async () => ({ chapter_id: 101, text: 'Live source text' }) };
      }

      if (target.endsWith('/api/books/1/chapters/101/translation')) {
        return { ok: true, json: async () => ({ chapter_id: 101, text: 'Live translated text' }) };
      }

      if (target.endsWith('/api/library/books')) {
        return {
          ok: true,
          json: async () => ({
            books: [
              {
                id: 1,
                title: 'Live Book Same Id',
                author: '',
                source: 'manual',
                source_url: '',
                total_chapters: 1,
                translated_chapters: 1,
                audio_chapters: 0,
                failed_chapters: 0,
                qa_low_chapters: 0,
                first_translated_chapter_id: 101,
                latest_translated_chapter_id: 101,
                latest_chapter_number: 1,
                latest_chapter_title: 'Live Chapter Same Book',
                last_activity: '2026-06-20T00:00:00Z',
              },
            ],
          }),
        };
      }

      if (target.endsWith('/api/providers/estimate')) {
        return {
          ok: true,
          json: async () => ({
            provider_id: 'gemini',
            model: 'gemini-live',
            chapter_count: 1,
            estimated_input_tokens: 12000,
            estimated_output_tokens: 16000,
            estimated_cost_usd: 0.0076,
            within_budget: true,
          }),
        };
      }

      if (target.endsWith('/api/providers/usage')) {
        return {
          ok: true,
          json: async () => ({
            usage: fixtureUsage,
          }),
        };
      }

      const assistResponse = defaultAssistAutoLoadResponse(target);
      if (assistResponse) return assistResponse;

      throw new Error(`Unexpected URL: ${target}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);

    await openTranslatedWorkbench('Live Book Same Id');
    expect(await screen.findByRole('heading', { name: 'Live Chapter Same Book' })).toBeInTheDocument();
    expect(await screen.findByText('Live source text')).toBeInTheDocument();
    expect(await screen.findByDisplayValue('Live translated text')).toBeInTheDocument();
    await expectNoGlobalAlert();
  });

  it('loads providers, books, chapters, estimate data, and assist glossary data when a token exists', async () => {
    saveToken('access');
    const fetchMock = vi.fn(async (url: RequestInfo | URL) => {
      const target = String(url);

      if (target.endsWith('/api/providers')) {
        return {
          ok: true,
          json: async () => ({
            providers: [fixtureProvider],
          }),
        };
      }

      if (target.endsWith('/api/style-profiles')) {
        return { ok: true, json: async () => ({ profiles: [fixtureStyleProfile] }) };
      }

      if (target.endsWith('/api/books')) {
        return {
          ok: true,
          json: async () => [fixtureBook],
        };
      }

      if (target.endsWith('/api/books/42/chapters')) {
        return {
          ok: true,
          json: async () => [fixtureChapter],
        };
      }

      if (target.endsWith('/api/books/42/chapters/4201/source')) {
        return {
          ok: true,
          json: async () => ({ chapter_id: 4201, text: 'Live source text with 筑基' }),
        };
      }

      if (target.endsWith('/api/books/42/chapters/4201/translation')) {
        return {
          ok: true,
          json: async () => ({ chapter_id: 4201, text: 'Live translated text' }),
        };
      }

      if (target.endsWith('/api/providers/estimate')) {
        return {
          ok: true,
          json: async () => ({
            provider_id: 'gemini',
            model: 'gemini-live',
            chapter_count: 1,
            estimated_input_tokens: 12000,
            estimated_output_tokens: 16000,
            estimated_cost_usd: 0.0076,
            within_budget: true,
          }),
        };
      }

      if (target.endsWith('/api/providers/usage')) {
        return {
          ok: true,
          json: async () => ({
            usage: {
              ...fixtureUsage,
              total_prompt_tokens: 100,
              total_completion_tokens: 50,
              total_tokens: 150,
              total_estimated_cost_usd: 0.0012,
            },
          }),
        };
      }

      if (target.endsWith('/api/providers/test')) {
        return {
          ok: true,
          json: async () => ({
            provider_id: 'gemini',
            model: 'gemini-live',
            ok: true,
            sample: 'Hắn cầm linh thạch lên.',
          }),
        };
      }

      if (target.endsWith('/api/jobs?limit=30')) {
        return {
          ok: true,
          json: async () => ({ jobs: [] }),
        };
      }

      if (target.endsWith('/api/glossary?book_id=42&per_page=500')) {
        return {
          ok: true,
          json: async () => ({ items: [fixtureGlossaryTerm] }),
        };
      }

      if (target.endsWith('/api/books/42/chapters/4201/qa')) {
        return {
          ok: false,
          status: 404,
          statusText: 'Not Found',
          json: async () => ({ detail: 'No QA report yet' }),
        };
      }

      const assistResponse = defaultAssistAutoLoadResponse(target);
      if (assistResponse) return assistResponse;

      throw new Error(`Unexpected URL: ${target}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);

    expect(await screen.findByRole('heading', { name: 'Novel-TNN' })).toBeInTheDocument();
    await openTranslatedWorkbench();
    expect(await screen.findByRole('heading', { name: 'Live Chapter' })).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'Quy trình' })).toBeInTheDocument();
    expect(screen.getByLabelText('Preset dịch')).toHaveValue('balanced');
    expect(screen.getByRole('option', { name: 'Cân bằng' })).toBeInTheDocument();
    expect(await screen.findByText('Bản gốc tiếng Trung')).toBeInTheDocument();
    expect(await screen.findByText('Live source text with 筑基')).toBeInTheDocument();
    expect(await screen.findByDisplayValue('Live translated text')).toBeInTheDocument();
    expect(await screen.findByText('Trúc Cơ')).toBeInTheDocument();
    expect(screen.getByText('Nhập đoạn nguồn để tìm ký ức dịch.')).toBeInTheDocument();
    await expectNoGlobalAlert();
    await waitFor(() => expect(screen.getByText('Chi phí: $0.0076')).toBeInTheDocument());
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        'http://127.0.0.1:7860/api/providers/estimate',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({
            provider_id: 'gemini',
            source_chars: 'Live source text with 筑基'.length,
            chapter_count: 1,
            max_cost_usd: 0.03,
          }),
        }),
      ),
    );

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        'http://127.0.0.1:7860/api/providers',
        expect.objectContaining({
          headers: expect.objectContaining({ Authorization: 'Bearer access' }),
        }),
      ),
    );

    const workflowNav = screen.getByRole('navigation', { name: 'Quy trình' });

    await userEvent.click(within(workflowNav).getByRole('button', { name: 'Thuật ngữ & Văn phong' }));
    expect(await screen.findByRole('heading', { name: 'Thuật ngữ & Văn phong' })).toBeInTheDocument();
    expect(screen.getByLabelText('Profile văn phong')).toHaveValue('tien_hiep');
    expect(screen.getByDisplayValue('Trúc Cơ')).toBeInTheDocument();
    expect(screen.queryByText('Chi tiết màn hình V2 cho thuật ngữ và văn phong đang chờ triển khai.')).not.toBeInTheDocument();

    await userEvent.click(within(workflowNav).getByRole('button', { name: 'Model API' }));
    expect(await screen.findByRole('heading', { name: 'Model API' })).toBeInTheDocument();
    expect(screen.getByText('Tổng token')).toBeInTheDocument();
    expect(screen.getByText('$0.0012')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Test model' }));
    expect(await screen.findByText('Hắn cầm linh thạch lên.')).toBeInTheDocument();
    expect(screen.queryByText('Chi tiết màn hình V2 cho cấu hình Model API đang chờ triển khai.')).not.toBeInTheDocument();

    await userEvent.click(within(workflowNav).getByRole('button', { name: 'Tác vụ' }));
    expect(await screen.findByRole('heading', { name: 'Tác vụ' })).toBeInTheDocument();
    expect(screen.getByText('Không có tác vụ đang chạy')).toBeInTheDocument();
    expect(screen.getByText('Chưa có lịch sử tác vụ')).toBeInTheDocument();
    await expectNoGlobalAlert();
  });

  it('clears an expired token and returns to login', async () => {
    saveToken('expired');
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 401,
        statusText: 'Unauthorized',
        json: async () => ({ detail: 'Not authenticated' }),
      }),
    );

    render(<App />);

    expect(await screen.findByRole('button', { name: 'Login' })).toBeInTheDocument();
    expect(await screen.findByText('Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.')).toBeInTheDocument();
  });

  it('keeps translation preset-first when the provider list contains a missing key', async () => {
    saveToken('access');
    const fetchMock = vi.fn(async (url: RequestInfo | URL) => {
      const target = String(url);

      if (target.endsWith('/api/providers')) {
        return {
          ok: true,
          json: async () => ({ providers: [fixtureMissingKeyProvider] }),
        };
      }

      if (target.endsWith('/api/style-profiles')) {
        return { ok: true, json: async () => ({ profiles: [fixtureStyleProfile] }) };
      }

      if (target.endsWith('/api/books')) {
        return { ok: true, json: async () => [fixtureBook] };
      }

      if (target.endsWith('/api/books/42/chapters')) {
        return { ok: true, json: async () => [fixtureChapter] };
      }

      if (target.endsWith('/api/books/42/chapters/4201/source')) {
        return { ok: true, json: async () => ({ chapter_id: 4201, text: '第一章 筑基' }) };
      }

      if (target.endsWith('/api/books/42/chapters/4201/translation')) {
        return { ok: true, json: async () => ({ chapter_id: 4201, text: '' }) };
      }

      if (target.endsWith('/api/providers/estimate')) {
        return {
          ok: true,
          json: async () => ({
            provider_id: 'missing',
            model: 'gemini-live',
            chapter_count: 1,
            estimated_input_tokens: 12000,
            estimated_output_tokens: 16000,
            estimated_cost_usd: 0.0076,
            within_budget: true,
          }),
        };
      }

      if (target.endsWith('/api/providers/usage')) {
        return { ok: true, json: async () => ({ usage: fixtureUsage }) };
      }

      const assistResponse = defaultAssistAutoLoadResponse(target);
      if (assistResponse) return assistResponse;

      throw new Error(`Unexpected URL: ${target}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);

    await openTranslatedWorkbench();
    expect(await screen.findByRole('heading', { name: 'Live Chapter' })).toBeInTheDocument();
    expect(await screen.findByText('第一章 筑基')).toBeInTheDocument();
    expect(screen.getByLabelText('Preset dịch')).toHaveValue('balanced');
    expect(screen.getByRole('button', { name: 'Dịch' })).not.toBeDisabled();
    expect(screen.queryByLabelText('Model')).not.toBeInTheDocument();
    expect(screen.queryByText('Model thiếu API key')).not.toBeInTheDocument();
    await expectNoGlobalAlert();
  });

  it('applies an actionable QA fix to the editable Vietnamese translation', async () => {
    saveToken('access');
    const fetchMock = vi.fn(async (url: RequestInfo | URL) => {
      const target = String(url);

      if (target.endsWith('/api/providers')) {
        return { ok: true, json: async () => ({ providers: [fixtureProvider] }) };
      }

      if (target.endsWith('/api/style-profiles')) {
        return { ok: true, json: async () => ({ profiles: [fixtureStyleProfile] }) };
      }

      if (target.endsWith('/api/books')) {
        return { ok: true, json: async () => [fixtureBook] };
      }

      if (target.endsWith('/api/books/42/chapters')) {
        return { ok: true, json: async () => [fixtureChapter] };
      }

      if (target.endsWith('/api/books/42/chapters/4201/source')) {
        return { ok: true, json: async () => ({ chapter_id: 4201, text: '陆哥，我多谢你。' }) };
      }

      if (target.endsWith('/api/books/42/chapters/4201/translation')) {
        return { ok: true, json: async () => ({ chapter_id: 4201, text: 'Lục ca, tôi cảm ơn anh.' }) };
      }

      if (target.endsWith('/api/books/42/chapters/4201/qa')) {
        return {
          ok: true,
          json: async () => ({
            book_id: 42,
            chapter_id: 4201,
            quality_score: 5,
            verdict: 'FAIL',
            issues: [
              {
                type: 'pronoun_modern',
                segment: 'tôi cảm ơn anh',
                reason: 'Xưng hô hiện đại trong thoại cổ trang',
                suggested_fix: 'ta cảm tạ huynh',
              },
            ],
          }),
        };
      }

      if (target.endsWith('/api/providers/estimate')) {
        return {
          ok: true,
          json: async () => ({
            provider_id: 'gemini',
            model: 'gemini-live',
            chapter_count: 1,
            estimated_input_tokens: 100,
            estimated_output_tokens: 100,
            estimated_cost_usd: 0.0001,
            within_budget: true,
          }),
        };
      }

      if (target.endsWith('/api/providers/usage')) {
        return { ok: true, json: async () => ({ usage: fixtureUsage }) };
      }

      const assistResponse = defaultAssistAutoLoadResponse(target);
      if (assistResponse) return assistResponse;

      throw new Error(`Unexpected URL: ${target}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);

    await openTranslatedWorkbench();
    expect(await screen.findByRole('heading', { name: 'Live Chapter' })).toBeInTheDocument();
    expect(await screen.findByText('tôi cảm ơn anh')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Apply fix pronoun_modern' }));

    expect(screen.getByLabelText('Bản dịch tiếng Việt')).toHaveValue('Lục ca, ta cảm tạ huynh.');
    expect(screen.queryByRole('region', { name: 'Chapter navigator' })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Đọc' }));

    expect(screen.getByRole('article', { name: 'Bản đọc tiếng Việt' })).toHaveTextContent('Lục ca, ta cảm tạ huynh.');
    expect(screen.queryByRole('region', { name: 'Chapter navigator' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Bản dịch tiếng Việt')).not.toBeInTheDocument();
    await expectNoGlobalAlert();
  });

  it('starts a translate job from a chapter action and streams progress', async () => {
    saveToken('access');
    let chaptersLoaded = 0;
    let translationLoaded = 0;
    let usageLoaded = 0;
    let attemptsLoaded = 0;
    let jobCompleted = false;
    const fetchMock = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      const target = String(url);

      if (target.endsWith('/api/providers')) {
        return {
          ok: true,
          json: async () => ({
            providers: [
              { ...fixtureProvider, notes: '' },
              {
                ...fixtureProvider,
                id: 'deepseek',
                label: 'Live DeepSeek',
                base_url: 'https://api.deepseek.com/v1',
                model: 'deepseek-live',
                api_key_env: 'DEEPSEEK_API_KEY',
                temperature: 0.1,
                cost_input_per_1m: 0.14,
                cost_output_per_1m: 0.28,
                notes: '',
              },
            ],
          }),
        };
      }

      if (target.endsWith('/api/style-profiles')) {
        return {
          ok: true,
          json: async () => ({
            profiles: [
              fixtureStyleProfile,
              {
                ...fixtureStyleProfile,
                id: 'kiem_hiep',
                label: 'Kiếm hiệp',
                is_default: 0,
              },
            ],
          }),
        };
      }

      if (target.endsWith('/api/books')) {
        return {
          ok: true,
          json: async () => [fixtureBook],
        };
      }

      if (target.endsWith('/api/books/42/chapters')) {
        chaptersLoaded += 1;
        return {
          ok: true,
          json: async () => {
            return [
              {
                ...fixtureChapter,
                status: jobCompleted ? 'translated' : 'cleaned',
                translated_text_path: jobCompleted ? '/tmp/translated.txt' : null,
                translated_at: jobCompleted ? '2026-06-20T00:00:00Z' : null,
              },
            ];
          },
        };
      }

      if (target.endsWith('/api/books/42/chapters/4201/source')) {
        return {
          ok: true,
          json: async () => ({ chapter_id: 4201, text: 'Live source text' }),
        };
      }

      if (target.endsWith('/api/books/42/chapters/4201/translation')) {
        translationLoaded += 1;
        return {
          ok: true,
          json: async () => ({
            chapter_id: 4201,
            text: translationLoaded > 1 ? 'Translated after job' : '',
          }),
        };
      }

      if (target.endsWith('/api/providers/estimate')) {
        return {
          ok: true,
          json: async () => ({
            provider_id: 'gemini',
            model: 'gemini-live',
            chapter_count: 1,
            estimated_input_tokens: 12000,
            estimated_output_tokens: 16000,
            estimated_cost_usd: 0.0076,
            within_budget: true,
          }),
        };
      }

      if (target.endsWith('/api/providers/usage')) {
        usageLoaded += 1;
        return {
          ok: true,
          json: async () => ({
            usage: {
              ...fixtureUsage,
              total_prompt_tokens: usageLoaded > 1 ? 100 : 0,
              total_completion_tokens: usageLoaded > 1 ? 50 : 0,
              total_tokens: usageLoaded > 1 ? 150 : 0,
              total_estimated_cost_usd: usageLoaded > 1 ? 0.0012 : 0,
            },
          }),
        };
      }

      if (target.endsWith('/api/jobs/translate') && init?.method === 'POST') {
        return {
          ok: true,
          json: async () => ({ job_id: 'job-live', status: 'pending', message: 'Translation job started' }),
        };
      }

      if (target.endsWith('/api/jobs/job-live/events')) {
        jobCompleted = true;
        return {
          ok: true,
          body: streamFromText(
            [
              'data: {"job_id":"job-live","status":"running","progress":1,"total":1,"message":"Translating Live Chapter"}',
              '',
              'data: {"job_id":"job-live","status":"completed","progress":1,"total":1,"message":"Done"}',
              '',
              '',
            ].join('\n'),
          ),
        };
      }

      if (target.endsWith('/api/jobs/job-live/attempts')) {
        attemptsLoaded += 1;
        return {
          ok: true,
          json: async () => ({
            attempts: attemptsLoaded > 1
              ? [
                  {
                    id: 1,
                    job_id: 'job-live',
                    chapter_id: 4201,
                    provider_id: 'deepseek',
                    model: 'deepseek-live',
                    status: 'success',
                    elapsed_ms: 1530,
                  },
                ]
              : [],
          }),
        };
      }

      const assistResponse = defaultAssistAutoLoadResponse(target);
      if (assistResponse) return assistResponse;

      throw new Error(`Unexpected URL: ${target}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);

    await openRawBacklogChapter();
    await screen.findByRole('heading', { name: 'Live Chapter' });
    await screen.findByRole('option', { name: 'Kiếm hiệp' });
    await userEvent.selectOptions(screen.getByLabelText('Preset dịch'), 'quality_high');
    await userEvent.selectOptions(screen.getByLabelText('Thể loại/văn phong'), 'kiem_hiep');
    await userEvent.click(screen.getByRole('button', { name: 'Dịch' }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        'http://127.0.0.1:7860/api/jobs/translate',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({
            book_id: 42,
            chapter_ids: [4201],
            limit: 15,
            params: { preset_id: 'quality_high', style_profile_id: 'kiem_hiep' },
          }),
        }),
      ),
    );
    expect(await screen.findByText('Done')).toBeInTheDocument();
    expect(await screen.findByDisplayValue('Translated after job')).toBeInTheDocument();
    await waitFor(() => expect(usageLoaded).toBeGreaterThan(1));
    await waitFor(() => expect(attemptsLoaded).toBeGreaterThan(1));
    await userEvent.click(within(screen.getByRole('navigation', { name: 'Quy trình' })).getByRole('button', { name: 'Tác vụ' }));
    expect(await screen.findByText('deepseek-live')).toBeInTheDocument();
    await expectNoGlobalAlert();
  });

  it('refreshes job attempts after a translate job fails', async () => {
    saveToken('access');
    let attemptsLoaded = 0;
    const fetchMock = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      const target = String(url);

      if (target.endsWith('/api/providers')) {
        return {
          ok: true,
          json: async () => ({ providers: [{ ...fixtureProvider, notes: '' }] }),
        };
      }

      if (target.endsWith('/api/style-profiles')) {
        return {
          ok: true,
          json: async () => ({ profiles: [fixtureStyleProfile] }),
        };
      }

      if (target.endsWith('/api/books')) {
        return {
          ok: true,
          json: async () => [fixtureBook],
        };
      }

      if (target.endsWith('/api/books/42/chapters')) {
        return {
          ok: true,
          json: async () => [{ ...fixtureChapter, status: 'cleaned', translated_text_path: null }],
        };
      }

      if (target.endsWith('/api/books/42/chapters/4201/source')) {
        return {
          ok: true,
          json: async () => ({ chapter_id: 4201, text: 'Live source text' }),
        };
      }

      if (target.endsWith('/api/books/42/chapters/4201/translation')) {
        return {
          ok: true,
          json: async () => ({ chapter_id: 4201, text: '' }),
        };
      }

      if (target.endsWith('/api/providers/usage')) {
        return {
          ok: true,
          json: async () => ({ usage: fixtureUsage }),
        };
      }

      if (target.endsWith('/api/providers/estimate')) {
        return {
          ok: true,
          json: async () => ({
            provider_id: 'gemini',
            model: 'gemini-live',
            chapter_count: 1,
            estimated_input_tokens: 1200,
            estimated_output_tokens: 1600,
            estimated_cost_usd: 0.00076,
            within_budget: true,
          }),
        };
      }

      if (target.endsWith('/api/jobs/translate') && init?.method === 'POST') {
        return {
          ok: true,
          json: async () => ({ job_id: 'job-failed', status: 'pending', message: 'Translation job started' }),
        };
      }

      if (target.endsWith('/api/jobs/job-failed/events')) {
        return {
          ok: true,
          body: streamFromText(
            [
              'data: {"job_id":"job-failed","status":"running","progress":0,"total":1,"message":"Translating Live Chapter"}',
              '',
              'data: {"job_id":"job-failed","status":"failed","progress":0,"total":1,"message":"Provider failed","error":"rate limit"}',
              '',
              '',
            ].join('\n'),
          ),
        };
      }

      if (target.endsWith('/api/jobs/job-failed/attempts')) {
        attemptsLoaded += 1;
        return {
          ok: true,
          json: async () => ({
            attempts: attemptsLoaded > 1
              ? [
                  {
                    id: 2,
                    job_id: 'job-failed',
                    chapter_id: 4201,
                    provider_id: 'gemini',
                    model: 'gemini-live',
                    status: 'failed',
                    error: 'rate limit',
                    elapsed_ms: 860,
                  },
                ]
              : [],
          }),
        };
      }

      const assistResponse = defaultAssistAutoLoadResponse(target);
      if (assistResponse) return assistResponse;

      throw new Error(`Unexpected URL: ${target}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);

    await openRawBacklogChapter();
    await screen.findByRole('heading', { name: 'Live Chapter' });
    await userEvent.selectOptions(screen.getByLabelText('Preset dịch'), 'quality_high');
    await userEvent.click(screen.getByRole('button', { name: 'Dịch' }));

    expect(await screen.findByText('Provider failed')).toBeInTheDocument();
    await waitFor(() => expect(attemptsLoaded).toBeGreaterThan(1));
    await userEvent.click(within(screen.getByRole('navigation', { name: 'Quy trình' })).getByRole('button', { name: 'Tác vụ' }));
    expect(await screen.findByText('gemini-live')).toBeInTheDocument();
    expect(screen.getByText('rate limit')).toBeVisible();
    await expectNoGlobalAlert();
  });

  it('does not enqueue duplicate translate jobs on a fast double click', async () => {
    saveToken('access');
    const translateStart = deferred<Response>();
    let translatePosts = 0;
    const fetchMock = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      const target = String(url);

      if (target.endsWith('/api/providers')) {
        return {
          ok: true,
          json: async () => ({
            providers: [{ ...fixtureProvider, notes: '' }],
          }),
        };
      }

      if (target.endsWith('/api/style-profiles')) {
        return {
          ok: true,
          json: async () => ({ profiles: [fixtureStyleProfile] }),
        };
      }

      if (target.endsWith('/api/books')) {
        return {
          ok: true,
          json: async () => [fixtureBook],
        };
      }

      if (target.endsWith('/api/books/42/chapters')) {
        return {
          ok: true,
          json: async () => [fixtureChapter],
        };
      }

      if (target.endsWith('/api/books/42/chapters/4201/source')) {
        return {
          ok: true,
          json: async () => ({ chapter_id: 4201, text: 'Live source text' }),
        };
      }

      if (target.endsWith('/api/books/42/chapters/4201/translation')) {
        return {
          ok: true,
          json: async () => ({ chapter_id: 4201, text: '' }),
        };
      }

      if (target.endsWith('/api/providers/estimate')) {
        return {
          ok: true,
          json: async () => ({
            provider_id: 'gemini',
            model: 'gemini-live',
            chapter_count: 1,
            estimated_input_tokens: 12000,
            estimated_output_tokens: 16000,
            estimated_cost_usd: 0.0076,
            within_budget: true,
          }),
        };
      }

      if (target.endsWith('/api/providers/usage')) {
        return {
          ok: true,
          json: async () => ({ usage: fixtureUsage }),
        };
      }

      if (target.endsWith('/api/jobs/translate') && init?.method === 'POST') {
        translatePosts += 1;
        return translateStart.promise;
      }

      if (target.endsWith('/api/jobs/job-double/events')) {
        return {
          ok: true,
          body: streamFromText(
            [
              'data: {"job_id":"job-double","status":"completed","progress":1,"total":1,"message":"Done"}',
              '',
              '',
            ].join('\n'),
          ),
        };
      }

      const assistResponse = defaultAssistAutoLoadResponse(target);
      if (assistResponse) return assistResponse;

      throw new Error(`Unexpected URL: ${target}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);

    await openTranslatedWorkbench();
    await screen.findByRole('heading', { name: 'Live Chapter' });
    await screen.findByText('Live source text');
    await userEvent.dblClick(screen.getByRole('button', { name: 'Dịch' }));

    await waitFor(() => expect(translatePosts).toBe(1));
    expect(screen.getByRole('button', { name: 'Dịch' })).toBeDisabled();
    expect(screen.getByText('Đang có tác vụ dịch')).toBeInTheDocument();
    await expectNoGlobalAlert();

    translateStart.resolve({
      ok: true,
      json: async () => ({ job_id: 'job-double', status: 'pending', message: 'Translation job started' }),
    } as Response);
  });

  it('retries post-job refresh after a transient chapter reload failure', async () => {
    saveToken('access');
    let chaptersLoaded = 0;
    let postJobChapterLoads = 0;
    let translationLoaded = 0;
    let jobCompleted = false;
    const fetchMock = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      const target = String(url);

      if (target.endsWith('/api/providers')) {
        return {
          ok: true,
          json: async () => ({
            providers: [{ ...fixtureProvider, notes: '' }],
          }),
        };
      }

      if (target.endsWith('/api/books')) {
        return {
          ok: true,
          json: async () => [fixtureBook],
        };
      }

      if (target.endsWith('/api/books/42/chapters')) {
        chaptersLoaded += 1;
        if (jobCompleted) {
          postJobChapterLoads += 1;
        }

        if (jobCompleted && postJobChapterLoads === 1) {
          return {
            ok: false,
            status: 503,
            statusText: 'Service Unavailable',
            json: async () => ({ detail: 'Temporary reload failure' }),
          };
        }

        return {
          ok: true,
          json: async () => [
            {
              ...fixtureChapter,
              status: jobCompleted && postJobChapterLoads > 1 ? 'translated' : 'cleaned',
              translated_text_path: jobCompleted && postJobChapterLoads > 1 ? '/tmp/translated.txt' : null,
              translated_at: jobCompleted && postJobChapterLoads > 1 ? '2026-06-20T00:00:00Z' : null,
            },
          ],
        };
      }

      if (target.endsWith('/api/books/42/chapters/4201/source')) {
        return { ok: true, json: async () => ({ chapter_id: 4201, text: 'Live source text' }) };
      }

      if (target.endsWith('/api/books/42/chapters/4201/translation')) {
        translationLoaded += 1;
        return {
          ok: true,
          json: async () => ({
            chapter_id: 4201,
            text: translationLoaded > 1 ? 'Translated after retry' : '',
          }),
        };
      }

      if (target.endsWith('/api/providers/estimate')) {
        return {
          ok: true,
          json: async () => ({
            provider_id: 'gemini',
            model: 'gemini-live',
            chapter_count: 1,
            estimated_input_tokens: 12000,
            estimated_output_tokens: 16000,
            estimated_cost_usd: 0.0076,
            within_budget: true,
          }),
        };
      }

      if (target.endsWith('/api/providers/usage')) {
        return {
          ok: true,
          json: async () => ({
            usage: {
              ...fixtureUsage,
              total_prompt_tokens: 10,
              total_completion_tokens: 5,
              total_tokens: 15,
              total_estimated_cost_usd: 0.0001,
            },
          }),
        };
      }

      if (target.endsWith('/api/jobs/translate') && init?.method === 'POST') {
        return {
          ok: true,
          json: async () => ({ job_id: 'job-retry', status: 'pending', message: 'Translation job started' }),
        };
      }

      if (target.endsWith('/api/jobs/job-retry/events')) {
        jobCompleted = true;
        return {
          ok: true,
          body: streamFromText(
            [
              'data: {"job_id":"job-retry","status":"completed","progress":1,"total":1,"message":"Done"}',
              '',
              '',
            ].join('\n'),
          ),
        };
      }

      const assistResponse = defaultAssistAutoLoadResponse(target);
      if (assistResponse) return assistResponse;

      throw new Error(`Unexpected URL: ${target}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);

    await openRawBacklogChapter();
    await screen.findByRole('heading', { name: 'Live Chapter' });
    await userEvent.click(screen.getByRole('button', { name: 'Dịch' }));

    expect(await screen.findByText('Done')).toBeInTheDocument();
    expect(await screen.findByDisplayValue('Translated after retry')).toBeInTheDocument();
    await waitFor(() => expect(chaptersLoaded).toBeGreaterThanOrEqual(3));
    await expectNoGlobalAlert();
  });

  it('reloads chapters and selects the imported chapter when paste targets the active book', async () => {
    saveToken('access');
    let chaptersLoaded = 0;
    const fetchMock = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      const target = String(url);

      if (target.endsWith('/api/providers')) {
        return {
          ok: true,
          json: async () => ({
            providers: [{ ...fixtureProvider, notes: '' }],
          }),
        };
      }

      if (target.endsWith('/api/books')) {
        return {
          ok: true,
          json: async () => [fixtureBook],
        };
      }

      if (target.endsWith('/api/books/42/chapters')) {
        chaptersLoaded += 1;
        const chapters = [
          {
            ...fixtureChapter,
            cleaned_text_path: '/tmp/cleaned-1.txt',
            translated_text_path: '/tmp/translated-1.txt',
          },
        ];

        return {
          ok: true,
          json: async () =>
            chaptersLoaded > 1
              ? [
                  ...chapters,
                  {
                    ...fixtureChapter,
                    id: 4202,
                    chapter_number: 2,
                    title: 'Imported Chapter',
                    status: 'cleaned',
                    cleaned_text_path: '/tmp/cleaned-2.txt',
                    translated_text_path: null,
                    translated_at: null,
                  },
                ]
              : chapters,
        };
      }

      if (target.endsWith('/api/books/42/chapters/4201/source')) {
        return { ok: true, json: async () => ({ chapter_id: 4201, text: 'Original source text' }) };
      }

      if (target.endsWith('/api/books/42/chapters/4201/translation')) {
        return { ok: true, json: async () => ({ chapter_id: 4201, text: 'Original translated text' }) };
      }

      if (target.endsWith('/api/books/42/chapters/4202/source')) {
        return { ok: true, json: async () => ({ chapter_id: 4202, text: 'Imported source text' }) };
      }

      if (target.endsWith('/api/books/42/chapters/4202/translation')) {
        return { status: 404, ok: false, json: async () => ({ detail: 'Not found' }) };
      }

      if (target.endsWith('/api/providers/estimate')) {
        return {
          ok: true,
          json: async () => ({
            provider_id: 'gemini',
            model: 'gemini-live',
            chapter_count: 1,
            estimated_input_tokens: 12000,
            estimated_output_tokens: 16000,
            estimated_cost_usd: 0.0076,
            within_budget: true,
          }),
        };
      }

      if (target.endsWith('/api/providers/usage')) {
        return {
          ok: true,
          json: async () => ({
            usage: fixtureUsage,
          }),
        };
      }

      if (target.endsWith('/api/import/wizard/text') && init?.method === 'POST') {
        return {
          ok: true,
          json: async () => ({
            book_id: 42,
            title: 'Live Book',
            content_kind: 'raw',
            chapter_count: 1,
            imported_chapters: 1,
            skipped_chapters: 0,
            overwritten_chapters: 0,
            chapter_ids: [4202],
            warnings: [],
            message: 'Imported reviewed text',
          }),
        };
      }

      const assistResponse = defaultAssistAutoLoadResponse(target);
      if (assistResponse) return assistResponse;

      throw new Error(`Unexpected URL: ${target}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);

    expect(await screen.findByRole('heading', { name: 'Chưa chọn chương' })).toBeInTheDocument();
    await userEvent.click(
      within(screen.getByRole('navigation', { name: 'Quy trình' })).getByRole('button', { name: 'Nhập chương' }),
    );
    await userEvent.type(
      await screen.findByPlaceholderText('Nhập tên truyện hoặc để trống nếu đã chọn từ Library'),
      'Live Book',
    );
    const chapterNumberInput = screen.getByRole('spinbutton');
    await userEvent.clear(chapterNumberInput);
    await userEvent.type(chapterNumberInput, '2');
    await userEvent.type(screen.getByPlaceholderText('Nhập tiêu đề chương'), 'Imported Chapter');
    await userEvent.type(screen.getByPlaceholderText('Dán nội dung chương vào đây...'), '第2章 Imported Chapter\\n\\n少年走入山中。');
    await userEvent.click(screen.getByRole('button', { name: 'Import chapter' }));

    expect(await screen.findByRole('heading', { name: 'Imported Chapter' })).toBeInTheDocument();
    await expectNoGlobalAlert();
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        'http://127.0.0.1:7860/api/books/42/chapters/4202/source',
        expect.any(Object),
      ),
    );
  });

  it('opens raw backlog chapters in the workbench after the V2 shell swap', async () => {
    saveToken('access');
    const fetchMock = vi.fn(async (url: RequestInfo | URL) => {
      const target = String(url);

      if (target.endsWith('/api/providers')) {
        return {
          ok: true,
          json: async () => ({
            providers: [{ ...fixtureProvider, notes: '' }],
          }),
        };
      }

      if (target.endsWith('/api/books')) {
        return {
          ok: true,
          json: async () => [fixtureBook],
        };
      }

      if (target.endsWith('/api/books/42/chapters')) {
        return {
          ok: true,
          json: async () => [
            {
              ...fixtureChapter,
              title: 'First Chapter',
              cleaned_text_path: '/tmp/cleaned-1.txt',
              translated_text_path: '/tmp/translated-1.txt',
            },
            {
              ...fixtureChapter,
              id: 4202,
              chapter_number: 2,
              title: 'Second Chapter',
              status: 'cleaned',
              cleaned_text_path: '/tmp/cleaned-2.txt',
              translated_text_path: null,
              translated_at: null,
            },
          ],
        };
      }

      if (target.endsWith('/api/books/42/chapters/4201/source')) {
        return { ok: true, json: async () => ({ chapter_id: 4201, text: 'First source text' }) };
      }

      if (target.endsWith('/api/books/42/chapters/4201/translation')) {
        return { ok: true, json: async () => ({ chapter_id: 4201, text: 'First translated text' }) };
      }

      if (target.endsWith('/api/books/42/chapters/4202/source')) {
        return { ok: true, json: async () => ({ chapter_id: 4202, text: 'Second source text' }) };
      }

      if (target.endsWith('/api/books/42/chapters/4202/translation')) {
        return { ok: false, status: 404, json: async () => ({ detail: 'No translation yet' }) };
      }

      if (target.endsWith('/api/providers/estimate')) {
        return {
          ok: true,
          json: async () => ({
            provider_id: 'gemini',
            model: 'gemini-live',
            chapter_count: 2,
            estimated_input_tokens: 12000,
            estimated_output_tokens: 16000,
            estimated_cost_usd: 0.0076,
            within_budget: true,
          }),
        };
      }

      if (target.endsWith('/api/providers/usage')) {
        return {
          ok: true,
          json: async () => ({
            usage: fixtureUsage,
          }),
        };
      }

      const assistResponse = defaultAssistAutoLoadResponse(target);
      if (assistResponse) return assistResponse;

      throw new Error(`Unexpected URL: ${target}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);

    await openTranslatedWorkbench();
    expect(await screen.findByRole('heading', { name: 'First Chapter' })).toBeInTheDocument();
    expect(await screen.findByText('First source text')).toBeInTheDocument();
    expect(await screen.findByDisplayValue('First translated text')).toBeInTheDocument();

    await openRawBacklogChapter(2);

    expect(await screen.findByRole('heading', { name: 'Second Chapter' })).toBeInTheDocument();
    expect(await screen.findByText('Second source text')).toBeInTheDocument();
    expect(screen.getByLabelText('Bản dịch tiếng Việt')).toHaveValue('');
    await expectNoGlobalAlert();
  });

  it('uses explicit confirmation dialogs before deleting translation artifacts or chapters', async () => {
    saveToken('access');
    const nativeConfirm = vi.fn(() => {
      throw new Error('native confirm should not be used for delete actions');
    });
    vi.stubGlobal('confirm', nativeConfirm);
    let chaptersDeleted = false;

    const fetchMock = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      const target = String(url);

      if (target.endsWith('/api/providers')) {
        return {
          ok: true,
          json: async () => ({
            providers: [{ ...fixtureProvider, notes: '' }],
          }),
        };
      }

      if (target.endsWith('/api/style-profiles')) return { ok: true, json: async () => ({ profiles: [] }) };
      if (target.endsWith('/api/books')) return { ok: true, json: async () => [fixtureBook] };
      if (target.endsWith('/api/books/42/chapters')) {
        return {
          ok: true,
          json: async () => (chaptersDeleted ? [] : [fixtureChapter]),
        };
      }

      if (target.endsWith('/api/books/42/chapters/4201/source')) {
        return { ok: true, json: async () => ({ chapter_id: 4201, text: 'Live source text' }) };
      }

      if (target.endsWith('/api/books/42/chapters/4201/translation')) {
        if (init?.method === 'DELETE') return { ok: true, json: async () => ({ message: 'Translation deleted' }) };
        return { ok: true, json: async () => ({ chapter_id: 4201, text: 'Live translated text' }) };
      }

      if (target.endsWith('/api/books/42/chapters/4201') && init?.method === 'DELETE') {
        chaptersDeleted = true;
        return { ok: true, json: async () => ({ message: 'Chapter deleted' }) };
      }

      if (target.endsWith('/api/providers/estimate')) {
        return {
          ok: true,
          json: async () => ({
            provider_id: 'gemini',
            model: 'gemini-live',
            chapter_count: 1,
            estimated_input_tokens: 12000,
            estimated_output_tokens: 16000,
            estimated_cost_usd: 0.0076,
            within_budget: true,
          }),
        };
      }

      if (target.endsWith('/api/providers/usage')) return { ok: true, json: async () => ({ usage: fixtureUsage }) };

      const assistResponse = defaultAssistAutoLoadResponse(target);
      if (assistResponse) return assistResponse;

      throw new Error(`Unexpected URL: ${target}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);

    await openTranslatedWorkbench();
    expect(await screen.findByRole('heading', { name: 'Live Chapter' })).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Xóa bản dịch' }));
    let dialog = screen.getByRole('dialog', { name: 'Xóa bản dịch?' });
    expect(dialog).toHaveTextContent('Bản gốc tiếng Trung sẽ được giữ lại');
    expect(fetchMock).not.toHaveBeenCalledWith(
      'http://127.0.0.1:7860/api/books/42/chapters/4201/translation',
      expect.objectContaining({ method: 'DELETE' }),
    );
    await userEvent.click(within(dialog).getByRole('button', { name: 'Xóa bản dịch' }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        'http://127.0.0.1:7860/api/books/42/chapters/4201/translation',
        expect.objectContaining({ method: 'DELETE' }),
      ),
    );

    await userEvent.click(screen.getByRole('button', { name: 'Xóa chương' }));
    dialog = screen.getByRole('dialog', { name: 'Xóa chương?' });
    expect(dialog).toHaveTextContent('Bản gốc, bản dịch, audio, QA và job liên quan sẽ bị dọn');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Xóa chương' }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        'http://127.0.0.1:7860/api/books/42/chapters/4201',
        expect.objectContaining({ method: 'DELETE' }),
      ),
    );
    expect(nativeConfirm).not.toHaveBeenCalled();
  });
});
