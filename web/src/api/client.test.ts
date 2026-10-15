import { describe, expect, it, vi } from 'vitest';
import { ApiClient, ApiError } from './client';

describe('ApiClient', () => {
  it('loads a cancellable raw page and the complete raw ID list with authorization', async () => {
    const page = { chapters: [], total_chapters: 60, total_books: 1, book_counts: { 42: 60 }, offset: 50, limit: 50 };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => page })
      .mockResolvedValueOnce({ ok: true, json: async () => [4201, 4259] });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';
    const signal = new AbortController().signal;
    await expect(client.getRawBacklog(50, 50, { signal })).resolves.toEqual(page);
    expect(fetchMock).toHaveBeenNthCalledWith(1, 'http://test/api/library/raw?offset=50&limit=50',
      expect.objectContaining({ signal, headers: expect.objectContaining({ Authorization: 'Bearer access' }) }));
    await expect(client.getRawChapterIds(42)).resolves.toEqual([4201, 4259]);
    expect(fetchMock).toHaveBeenNthCalledWith(2, 'http://test/api/books/42/chapters/raw-ids',
      expect.objectContaining({ headers: expect.objectContaining({ Authorization: 'Bearer access' }) }));
  });

  it('binds the default browser fetch so login does not throw illegal invocation', async () => {
    const fetchMock = vi.fn(function (this: unknown) {
      if (this !== undefined) throw new TypeError('Illegal invocation');
      return Promise.resolve({
        ok: true,
        json: async () => ({
          access_token: 'access',
          token_type: 'bearer',
        }),
      });
    });
    vi.stubGlobal('fetch', fetchMock);

    try {
      const client = new ApiClient('http://test');

      await expect(client.login('admin', '123456')).resolves.toMatchObject({
        access_token: 'access',
      });
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it('stores bearer token after login', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        access_token: 'access',
        token_type: 'bearer',
      }),
    });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);

    const result = await client.login('admin', 'change_me');

    expect(result.access_token).toBe('access');
    expect(client.token).toBe('access');
    expect(fetchMock).toHaveBeenCalledWith(
      'http://test/api/auth/login',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ username: 'admin', password: 'change_me' }),
      }),
    );
  });

  it('refreshes through credentials and the double-submit csrf header', async () => {
    document.cookie = 'novel_csrf=csrf-test; path=/';
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        access_token: 'new-access',
        token_type: 'bearer',
      }),
    });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);

    const result = await client.refresh();

    expect(result.access_token).toBe('new-access');
    expect(client.token).toBe('new-access');
    expect(fetchMock).toHaveBeenCalledWith(
      'http://test/api/auth/refresh',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ 'X-CSRF-Token': 'csrf-test' }),
      }),
    );
  });

  it('adds authorization header to protected getProviders requests', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ providers: [] }) });
    const client = new ApiClient('http://test/', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    await client.getProviders();

    expect(fetchMock).toHaveBeenCalledWith(
      'http://test/api/providers',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
  });

  it('loads translated book summaries for the library page', async () => {
    const books = [
      {
        id: 42,
        title: 'Live Book',
        author: 'Author',
        source: 'manual',
        source_url: '',
        total_chapters: 3,
        translated_chapters: 2,
        audio_chapters: 1,
        failed_chapters: 0,
        qa_low_chapters: 1,
        first_translated_chapter_id: 4201,
        latest_translated_chapter_id: 4202,
        latest_chapter_number: 2,
        latest_chapter_title: 'Live Chapter 2',
        last_activity: '2026-06-20T00:00:00Z',
      },
    ];
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ books }) });
    const client = new ApiClient('http://test/', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    await expect(client.getTranslatedBooks()).resolves.toEqual(books);

    expect(fetchMock).toHaveBeenCalledWith(
      'http://test/api/library/books',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
  });

  it('loads internal system status with auth headers', async () => {
    const status = {
      public_deploy: true,
      api_ready: true,
      active_provider: 'gemini',
      upload_max_bytes: 104857600,
      asset_protection_enabled: true,
      active_jobs: 1,
      running_jobs: 1,
      last_failed_job: {
        job_id: 'job-failed',
        status: 'failed',
        message: 'Server restarted during job. Please retry the job.',
        error: 'Server restarted during job',
      },
      app_version: '0.1.0',
      build: 'phase1',
      database_available: true,
      data_directory_available: true,
      data_size_bytes: 8192,
      storage_health: 'healthy',
      storage_label: 'Configured data storage',
      backup_recommendation: 'System backup is separate from book export. Run scripts/backup-local.sh before upgrades or public deploy changes.',
    };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => status });
    const client = new ApiClient('http://test/', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    const statusClient = client as unknown as { getSystemStatus?: () => Promise<unknown> };
    expect(typeof statusClient.getSystemStatus).toBe('function');
    await expect(statusClient.getSystemStatus?.()).resolves.toEqual(status);

    expect(fetchMock).toHaveBeenCalledWith(
      'http://test/api/system/status',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
  });

  it('retries a failed job with auth headers', async () => {
    const retryResponse = { job_id: 'retry-1', status: 'pending', message: 'Retry job started' };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => retryResponse });
    const client = new ApiClient('http://test/', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    await expect(client.retryFailedJob('job failed')).resolves.toEqual(retryResponse);

    expect(fetchMock).toHaveBeenCalledWith(
      'http://test/api/jobs/job%20failed/retry',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
  });

  it('loads sanitized job logs with auth headers', async () => {
    const logs = [
      {
        id: 1,
        job_id: 'job-1',
        event_type: 'state_transition',
        state: 'TRANSLATING',
        step: 'TRANSLATING',
        message: 'Translating chapter',
        details: { chapter_id: 10 },
      },
    ];
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => logs });
    const client = new ApiClient('http://test/', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    await expect(client.getJobLogs('job-1')).resolves.toEqual(logs);

    expect(fetchMock).toHaveBeenCalledWith(
      'http://test/api/jobs/job-1/logs',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
  });

  it('throws useful errors for non-ok responses with detail', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      statusText: 'Service Unavailable',
      json: async () => ({ detail: 'provider service offline' }),
    });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);

    const request = client.getProviders();

    await expect(request).rejects.toThrow(ApiError);
    await expect(request).rejects.toMatchObject({
      message: 'Failed to load providers (503 Service Unavailable): provider service offline',
      status: 503,
    });
  });

  it('loads provider defaults, estimates cost, and gets provider usage with auth headers', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ defaults: { translate: 'gemini' } }) })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          provider_id: 'gemini',
          model: 'gemini-2.5-flash-lite',
          chapter_count: 2,
          estimated_input_tokens: 11000,
          estimated_output_tokens: 9000,
          estimated_cost_usd: 0.0047,
          within_budget: true,
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          usage: {
            total_prompt_tokens: 200,
            total_completion_tokens: 300,
            total_tokens: 500,
            total_estimated_cost_usd: 0.00014,
          },
        }),
      });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    await expect(client.getProviderDefaults()).resolves.toEqual({ translate: 'gemini' });
    await expect(client.estimateCost('gemini', 12000, 2, 0.01)).resolves.toMatchObject({
      provider_id: 'gemini',
      within_budget: true,
    });
    await expect(client.getProviderUsage()).resolves.toEqual({
      total_prompt_tokens: 200,
      total_completion_tokens: 300,
      total_tokens: 500,
      total_estimated_cost_usd: 0.00014,
    });

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      'http://test/api/providers/defaults',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      'http://test/api/providers/estimate',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          Authorization: 'Bearer access',
          'Content-Type': 'application/json',
        }),
        body: JSON.stringify({
          provider_id: 'gemini',
          source_chars: 12000,
          chapter_count: 2,
          max_cost_usd: 0.01,
        }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      'http://test/api/providers/usage',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
  });

  it('saves a provider API key with auth headers and never sends it in the URL', async () => {
    const provider = {
      id: 'gemini',
      label: 'Gemini',
      base_url: 'https://generativelanguage.googleapis.com/v1beta/openai',
      model: 'gemini-2.5-flash-lite',
      api_key_env: 'GEMINI_API_KEY',
      api_key_set: true,
      temperature: 0.3,
      timeout_seconds: 180,
      supports_streaming: 0,
      supports_batch: 0,
      cost_input_per_1m: 0.1,
      cost_output_per_1m: 0.4,
      enabled: 1,
      notes: '',
    };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ provider }) });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    await expect(client.saveProviderKey('gemini', 'new-secret')).resolves.toEqual(provider);

    expect(fetchMock).toHaveBeenCalledWith(
      'http://test/api/providers/gemini/key',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          Authorization: 'Bearer access',
          'Content-Type': 'application/json',
        }),
        body: JSON.stringify({ api_key: 'new-secret' }),
      }),
    );
    expect(fetchMock.mock.calls[0]?.[0]).not.toContain('new-secret');
  });

  it('loads audiobook playlist metadata from the backend without local audio paths', async () => {
    const playlist = {
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
    };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => playlist });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    await expect(client.getBookAudioPlaylist(42)).resolves.toEqual({
      ...playlist,
      chapters: [
        {
          ...playlist.chapters[0],
          download_url: 'http://test/api/books/42/chapters/102/audio/download',
          stream_url: 'http://test/api/books/42/chapters/102/audio',
        },
      ],
    });

    expect(fetchMock).toHaveBeenCalledWith(
      'http://test/api/books/42/audio/playlist',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
    expect(JSON.stringify(playlist)).not.toContain('audio_path');
  });

  it('previews and imports translated ebook files with multipart auth requests', async () => {
    const preview = {
      title: 'Đấu Phá Thương Khung',
      author: 'Thiên Tằm Thổ Đậu',
      language: 'vi',
      source_format: 'epub',
      cover_present: false,
      chapter_count: 1,
      chapters: [{ chapter_number: 1, title: 'Vẫn Lạc Thiên Tài', sample: 'Đấu khí, ba đoạn!' }],
    };
    const importResult = {
      book_id: 7,
      title: 'Đấu Phá Thương Khung',
      author: 'Thiên Tằm Thổ Đậu',
      source_format: 'epub',
      chapter_count: 1,
      imported_chapters: 1,
      skipped_chapters: 0,
      chapter_ids: [70],
      message: 'Imported translated ebook',
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: async () => preview })
      .mockResolvedValueOnce({ ok: true, json: async () => importResult });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';
    const file = new File(['ebook'], 'translated.epub', { type: 'application/epub+zip' });

    await expect(client.previewTranslatedEbook(file)).resolves.toEqual(preview);
    await expect(client.importTranslatedEbook({ file, duplicateStrategy: 'skip', targetBookId: 7 })).resolves.toEqual(importResult);

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      'http://test/api/import/ebook/preview',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
        body: expect.any(FormData),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      'http://test/api/import/ebook',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
        body: expect.any(FormData),
      }),
    );
    const importBody = fetchMock.mock.calls[1]?.[1]?.body as FormData;
    expect(importBody.get('duplicate_strategy')).toBe('skip');
    expect(importBody.get('target_book_id')).toBe('7');
  });

  it('imports a previewed translated ebook by upload id without reuploading the file', async () => {
    const importResult = {
      book_id: 7,
      title: 'Đấu Phá Thương Khung',
      author: 'Thiên Tằm Thổ Đậu',
      source_format: 'epub',
      chapter_count: 1,
      imported_chapters: 1,
      skipped_chapters: 0,
      chapter_ids: [70],
      message: 'Imported translated ebook',
    };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => importResult });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';
    const file = new File(['ebook'], 'translated.epub', { type: 'application/epub+zip' });

    await expect(
      client.importTranslatedEbook({
        file,
        uploadId: 'preview-upload-1',
        duplicateStrategy: 'skip',
        targetBookId: 7,
      }),
    ).resolves.toEqual(importResult);

    const body = fetchMock.mock.calls[0]?.[1]?.body as FormData;
    expect(body.get('upload_id')).toBe('preview-upload-1');
    expect(body.get('file')).toBeNull();
  });

  it('starts a translated ebook import job by upload id without reuploading the file', async () => {
    const job = {
      job_id: 'job-import-ebook',
      status: 'pending',
      message: 'Translated ebook import job started',
    };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => job });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';
    const file = new File(['ebook'], 'translated.epub', { type: 'application/epub+zip' });

    await expect(
      client.startTranslatedEbookImportJob({
        file,
        uploadId: 'preview-upload-1',
        duplicateStrategy: 'skip',
        targetBookId: 7,
        confirmedExistingBookId: 7,
      }),
    ).resolves.toEqual(job);

    expect(fetchMock).toHaveBeenCalledWith(
      'http://test/api/import/ebook/job',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
        body: expect.any(FormData),
      }),
    );
    const body = fetchMock.mock.calls[0]?.[1]?.body as FormData;
    expect(body.get('upload_id')).toBe('preview-upload-1');
    expect(body.get('file')).toBeNull();
    expect(body.get('duplicate_strategy')).toBe('skip');
    expect(body.get('target_book_id')).toBe('7');
    expect(body.get('confirmed_existing_book_id')).toBe('7');
  });

  it('loads, previews, and imports a translated ebook from the server inbox', async () => {
    const inbox = {
      directory: '/srv/novel-tnn/inbox/ebooks',
      files: [{ name: 'translated-from-inbox.epub', size: 130000000, modified_at: '2026-06-27T00:00:00Z' }],
    };
    const preview = {
      title: 'Đấu Phá Thương Khung',
      author: 'Thiên Tằm Thổ Đậu',
      language: 'vi',
      source_format: 'epub',
      cover_present: false,
      chapter_count: 1,
      chapters: [{ chapter_number: 1, title: 'Vẫn Lạc Thiên Tài', sample: 'Đấu khí, ba đoạn!' }],
      inbox_file: 'translated-from-inbox.epub',
    };
    const importResult = {
      book_id: 7,
      title: 'Đấu Phá Thương Khung',
      author: 'Thiên Tằm Thổ Đậu',
      source_format: 'epub',
      chapter_count: 1,
      imported_chapters: 1,
      skipped_chapters: 0,
      chapter_ids: [70],
      message: 'Imported translated ebook',
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: async () => inbox })
      .mockResolvedValueOnce({ ok: true, json: async () => preview })
      .mockResolvedValueOnce({ ok: true, json: async () => importResult });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    await expect(client.getEbookInboxFiles()).resolves.toEqual(inbox);
    await expect(client.previewInboxTranslatedEbook('translated-from-inbox.epub', 'auto')).resolves.toEqual(preview);
    await expect(client.importTranslatedEbook({ inboxFile: 'translated-from-inbox.epub' })).resolves.toEqual(importResult);

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      'http://test/api/import/ebook/inbox',
      expect.objectContaining({ headers: expect.objectContaining({ Authorization: 'Bearer access' }) }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      'http://test/api/import/ebook/inbox/preview',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
        body: expect.any(FormData),
      }),
    );
    const previewBody = fetchMock.mock.calls[1]?.[1]?.body as FormData;
    expect(previewBody.get('filename')).toBe('translated-from-inbox.epub');

    const importBody = fetchMock.mock.calls[2]?.[1]?.body as FormData;
    expect(importBody.get('inbox_file')).toBe('translated-from-inbox.epub');
    expect(importBody.get('file')).toBeNull();
  });

  it('sends ebook preview dry-run options and loads import history', async () => {
    const preview = {
      title: 'Đấu Phá Thương Khung',
      author: 'Thiên Tằm Thổ Đậu',
      language: 'vi',
      source_format: 'epub',
      cover_present: false,
      chapter_count: 1,
      chapters: [{ chapter_number: 1, title: 'Vẫn Lạc Thiên Tài', sample: 'Đấu khí, ba đoạn!' }],
      first_chapters: [{ chapter_number: 1, title: 'Vẫn Lạc Thiên Tài', sample: 'Đấu khí, ba đoạn!' }],
      last_chapters: [{ chapter_number: 1, title: 'Vẫn Lạc Thiên Tài', sample: 'Đấu khí, ba đoạn!' }],
      warnings: [],
      dry_run: {
        target_book_id: 7,
        target_title: 'Đấu Phá Thương Khung',
        duplicate_strategy: 'overwrite',
        chapter_count: 1,
        new_chapters: 0,
        duplicate_chapters: 1,
        would_import: 1,
        would_skip: 0,
        would_overwrite: 1,
        would_error: 0,
      },
    };
    const history = {
      runs: [
        {
          id: 1,
          book_id: 7,
          title: 'Đấu Phá Thương Khung',
          filename: 'dau-pha.epub',
          source_format: 'epub',
          duplicate_strategy: 'skip',
          split_mode: 'auto',
          chapter_count: 1,
          imported_chapters: 1,
          skipped_chapters: 0,
          overwritten_chapters: 0,
          warning_count: 0,
          warnings: [],
          created_at: '2026-06-26T00:00:00Z',
        },
      ],
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: async () => preview })
      .mockResolvedValueOnce({ ok: true, json: async () => history });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';
    const file = new File(['ebook'], 'translated.epub', { type: 'application/epub+zip' });

    await expect(
      client.previewTranslatedEbook(file, 'auto', { duplicateStrategy: 'overwrite', targetBookId: 7 }),
    ).resolves.toEqual(preview);
    await expect(client.getEbookImportHistory()).resolves.toEqual(history.runs);

    const previewBody = fetchMock.mock.calls[0]?.[1]?.body as FormData;
    expect(previewBody.get('duplicate_strategy')).toBe('overwrite');
    expect(previewBody.get('target_book_id')).toBe('7');
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      'http://test/api/import/ebook/history',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
  });

  it('defaults translated ebook duplicate handling to skip', async () => {
    const importResult = {
      book_id: 7,
      title: 'Đấu Phá Thương Khung',
      author: 'Thiên Tằm Thổ Đậu',
      source_format: 'epub',
      chapter_count: 1,
      imported_chapters: 0,
      skipped_chapters: 1,
      chapter_ids: [],
      message: 'Imported translated ebook',
    };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => importResult });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';
    const file = new File(['ebook'], 'translated.epub', { type: 'application/epub+zip' });

    await expect(client.importTranslatedEbook({ file })).resolves.toEqual(importResult);

    const body = fetchMock.mock.calls[0]?.[1]?.body as FormData;
    expect(body.get('duplicate_strategy')).toBe('skip');
    expect(body.get('confirmed_existing_book_id')).toBeNull();
  });

  it('loads books and chapters with auth headers', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => [
          {
            id: 1,
            title: 'Phàm Nhân Tu Tiên',
            author: '',
            source: 'manual',
            source_url: '',
            created_at: '2026-06-20T00:00:00Z',
            updated_at: '2026-06-20T00:00:00Z',
          },
        ],
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => [
          {
            id: 11,
            book_id: 1,
            chapter_number: 1,
            title: 'Sơn biên tiểu thôn',
            status: 'translated',
            source_url: '',
            raw_text_path: null,
            cleaned_text_path: '/tmp/cleaned.txt',
            translated_text_path: '/tmp/translated.txt',
            audio_path: null,
            translated_at: '2026-06-20T00:00:00Z',
            audio_created_at: null,
          },
        ],
      });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    await expect(client.getBooks()).resolves.toHaveLength(1);
    await expect(client.getChapters(1)).resolves.toMatchObject([{ id: 11, status: 'translated' }]);

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      'http://test/api/books',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      'http://test/api/books/1/chapters',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
  });

  it('updates book titles with auth headers', async () => {
    const updatedBook = {
      id: 1,
      title: 'Phàm Nhân Tu Tiên - bản đã sửa',
      author: '',
      source: 'manual',
      source_url: '',
      created_at: '2026-06-20T00:00:00Z',
      updated_at: '2026-06-25T00:00:00Z',
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => updatedBook,
    });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    await expect(client.updateBook(1, { title: updatedBook.title })).resolves.toEqual(updatedBook);

    expect(fetchMock).toHaveBeenCalledWith(
      'http://test/api/books/1',
      expect.objectContaining({
        method: 'PATCH',
        headers: expect.objectContaining({
          Authorization: 'Bearer access',
          'Content-Type': 'application/json',
        }),
        body: JSON.stringify({ title: updatedBook.title }),
      }),
    );
  });

  it('deletes books with auth headers', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ message: 'Book deleted' }),
    });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    await expect(client.deleteBook(42)).resolves.toBeUndefined();

    expect(fetchMock).toHaveBeenCalledWith(
      'http://test/api/books/42',
      expect.objectContaining({
        method: 'DELETE',
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
  });

  it('uploads book cover images with auth headers', async () => {
    const updatedBook = {
      id: 42,
      title: 'Phàm Nhân Tu Tiên',
      author: '',
      source: 'ebook',
      source_url: '',
      cover_path: '/data/covers/book_42.jpg',
      cover_url: '/covers/book_42.jpg',
      created_at: '2026-06-20T00:00:00Z',
      updated_at: '2026-06-25T00:00:00Z',
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => updatedBook,
    });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';
    const cover = new File(['cover-bytes'], 'cover.jpg', { type: 'image/jpeg' });

    await expect(client.updateBookCover(42, cover)).resolves.toEqual(updatedBook);

    expect(fetchMock).toHaveBeenCalledWith(
      'http://test/api/books/42/cover',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
        body: expect.any(FormData),
      }),
    );
    const body = fetchMock.mock.calls[0][1].body as FormData;
    expect(body.get('cover')).toBe(cover);
  });

  it('previews source URLs and starts URL import jobs with auth headers', async () => {
    const preview = {
      adapter_id: 'generic_html',
      adapter_label: 'Generic HTML',
      source: 'novel.example',
      source_url: 'https://novel.example/book/1',
      title: '凡人修仙传',
      author: '忘语',
      description: '',
      cover_url: '',
      chapters: [
        {
          chapter_number: 1,
          title: '第一章 山边小村',
          url: 'https://novel.example/book/1/chapter/1',
        },
      ],
      chapter_count: 1,
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: async () => preview })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          job_id: 'job-import-url',
          status: 'pending',
          message: 'URL import job started',
        }),
      });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    await expect(client.previewImportUrl('https://novel.example/book/1')).resolves.toEqual(preview);
    await expect(
      client.startImportUrlJob({
        url: preview.source_url,
        title: preview.title,
        author: preview.author,
        source: preview.source,
        chapters: preview.chapters,
        retry_limit: 2,
      }),
    ).resolves.toMatchObject({ job_id: 'job-import-url' });

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      'http://test/api/import/url/preview',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          Authorization: 'Bearer access',
          'Content-Type': 'application/json',
        }),
        body: JSON.stringify({ url: 'https://novel.example/book/1' }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      'http://test/api/import/url',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          Authorization: 'Bearer access',
          'Content-Type': 'application/json',
        }),
        body: JSON.stringify({
          url: preview.source_url,
          title: preview.title,
          author: preview.author,
          source: preview.source,
          chapters: preview.chapters,
          retry_limit: 2,
        }),
      }),
    );
  });

  it('loads import source capabilities with auth headers', async () => {
    const sources = [
      {
        source_id: '22biqu',
        label: '22biqu',
        domains: ['22biqu.com'],
        adapter_id: 'biquge',
        adapter_label: 'Biquge',
        extraction: 'selector',
        direct_import: true,
        delay_seconds: 10,
        max_concurrency: 1,
        retry_limit: 2,
        notes: 'Parser rieng cho layout hien tai.',
      },
    ];
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ sources }) });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    await expect(client.getImportSources()).resolves.toEqual(sources);

    expect(fetchMock).toHaveBeenCalledWith(
      'http://test/api/import/sources',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
  });

  it('loads source catalog with filters and auth headers', async () => {
    const catalog = {
      items: [
        {
          id: 'catalog-1',
          external_id: '100',
          catalog_source: 'yckceo',
          name: '69 Source',
          url: 'https://www.69shuba.com',
          domain: 'www.69shuba.com',
          author: 'Author',
          downloads: 12,
          version: '1',
          raw_tags: '搜',
          tags: ['search'],
          unknown_tags: [],
          supported: true,
          supported_status: 'supported',
          supported_source_id: '69shuba',
          invalid_reason: '',
          updated_label: '',
          created_at: '',
          updated_at: '',
        },
      ],
      entries: [],
      total: 1,
      page: 2,
      per_page: 25,
      page_size: 25,
    };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => catalog });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    await expect(
      client.getSourceCatalog({
        query: '69',
        tag: 'search',
        domain: 'www.69shuba.com',
        supported: 'true',
        status: 'VERIFIED',
        trust_level: 'HIGH',
        page: 2,
        page_size: 25,
      }),
    ).resolves.toEqual(catalog);

    expect(fetchMock).toHaveBeenCalledWith(
      'http://test/api/source-catalog?query=69&tag=search&domain=www.69shuba.com&supported=true&status=VERIFIED&trust_level=HIGH&page=2&page_size=25',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
  });

  it('checks one source catalog entry with auth headers', async () => {
    const result = {
      catalog_entry_id: 'catalog-1',
      domain: 'www.69shuba.com',
      status: 'reachable',
      reason: 'ok',
      checked_at: '2026-07-07T00:00:00+00:00',
      final_url: 'https://www.69shuba.com/book/1',
      http_status: 200,
    };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => result });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    await expect(client.checkSourceCatalogEntry('catalog 1')).resolves.toEqual(result);

    expect(fetchMock).toHaveBeenCalledWith(
      'http://test/api/source-catalog/catalog%201/check',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
  });

  it('imports, tests, verifies, and blocks managed sources with auth headers', async () => {
    const importSummary = {
      selected: 1,
      inserted: 1,
      duplicates: 0,
      invalid: 0,
      skipped: 0,
      items: [{ id: 'src-1', catalog_entry_id: 'catalog-1', status: 'NEEDS_REVIEW', trust_level: 'MANUAL_ONLY', can_use_in_jobs: false }],
    };
    const testResult = {
      source_id: 'src-1',
      status: 'success',
      reason: 'ok',
      tested_at: '2026-07-09T00:00:00+00:00',
      final_url: 'https://www.69shuba.com/book/1',
      http_status: 200,
    };
    const managedSource = {
      id: 'src-1',
      catalog_entry_id: 'catalog-1',
      name: '69 Source',
      base_url: 'https://www.69shuba.com/book/1',
      domain: 'www.69shuba.com',
      language: 'zh-CN',
      parser_type: 'policy_supported',
      parser_config: {},
      status: 'VERIFIED',
      trust_level: 'HIGH',
      supported_source_id: '69shuba',
      last_test_status: 'success',
      last_tested_at: '2026-07-09T00:00:00+00:00',
      last_successful_fetch_at: '2026-07-09T00:00:00+00:00',
      last_error: '',
      rate_limit_requests_per_minute: 7,
      rate_limit_delay_ms: 8000,
      max_concurrent_requests: 1,
      cooldown_after_error_seconds: 300,
      notes: '',
      created_at: '',
      updated_at: '',
      can_use_in_jobs: true,
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: async () => importSummary })
      .mockResolvedValueOnce({ ok: true, json: async () => testResult })
      .mockResolvedValueOnce({ ok: true, json: async () => managedSource })
      .mockResolvedValueOnce({ ok: true, json: async () => managedSource });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    await expect(client.importManagedSources(['catalog-1'])).resolves.toEqual(importSummary);
    await expect(client.testManagedSource('src-1')).resolves.toEqual(testResult);
    await expect(client.verifyManagedSource('src-1')).resolves.toEqual(managedSource);
    await expect(client.setManagedSourceStatus('src-1', 'BLOCKED')).resolves.toEqual(managedSource);

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      'http://test/api/sources/import-catalog',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ Authorization: 'Bearer access', 'Content-Type': 'application/json' }),
        body: JSON.stringify({ entry_ids: ['catalog-1'] }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      'http://test/api/sources/src-1/test',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      'http://test/api/sources/src-1/verify',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      'http://test/api/sources/src-1/status',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ Authorization: 'Bearer access', 'Content-Type': 'application/json' }),
        body: JSON.stringify({ status: 'BLOCKED' }),
      }),
    );
  });

  it('creates and lists source adapter candidates with auth headers', async () => {
    const candidate = {
      id: 'cand-1',
      catalog_entry_id: 'catalog-1',
      domain: 'example.com',
      sample_url: 'https://example.com/book/1',
      detected_title: 'Example Novel',
      detected_chapter_list: [{ title: 'Chapter 1', url: 'https://example.com/book/1/c1' }],
      parser_confidence: 'medium',
      failure_reason: '',
      status: 'needs_review',
      created_at: '2026-07-07T00:00:00+00:00',
      updated_at: '2026-07-07T00:00:00+00:00',
      reviewed_at: '',
      reviewed_by: '',
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: async () => candidate })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ items: [candidate], total: 1, page: 1, page_size: 50 }) })
      .mockResolvedValueOnce({ ok: true, json: async () => candidate });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    await expect(client.createSourceAdapterCandidate('catalog-1')).resolves.toEqual(candidate);
    await expect(client.getSourceAdapterCandidates()).resolves.toMatchObject({ items: [candidate], total: 1 });
    await expect(client.getSourceAdapterCandidate('cand-1')).resolves.toEqual(candidate);

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      'http://test/api/source-catalog/catalog-1/parser-candidate',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          Authorization: 'Bearer access',
          'Content-Type': 'application/json',
        }),
        body: JSON.stringify({}),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      'http://test/api/source-adapter-candidates?page=1&page_size=50',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      'http://test/api/source-adapter-candidates/cand-1',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
  });

  it('exports and downloads book files with auth headers', async () => {
    const exportResponse = {
      book_id: 1,
      book_title: 'Phàm Nhân Tu Tiên',
      format: 'txt',
      filename: 'pham_nhan_tu_tien.txt',
      path: '',
      download_url: '/api/books/1/exports/txt/download',
      media_type: 'text/plain; charset=utf-8',
      size_bytes: 1024,
      chapter_count: 2,
    };
    const exportedBlob = new Blob(['chapter text'], { type: 'text/plain' });
    const audiobookBlob = new Blob(['m4b bytes'], { type: 'audio/mp4' });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: async () => exportResponse })
      .mockResolvedValueOnce({
        ok: true,
        blob: async () => exportedBlob,
        headers: new Headers({
          'content-disposition': 'attachment; filename="pham_nhan_tu_tien.txt"',
          'content-type': 'text/plain; charset=utf-8',
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        blob: async () => audiobookBlob,
        headers: new Headers({
          'content-disposition': 'attachment; filename="pham_nhan_tu_tien.m4b"',
          'content-type': 'audio/mp4',
        }),
      });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    await expect(client.exportBook(1, 'txt')).resolves.toEqual(exportResponse);
    await expect(client.downloadBookExport(1, 'txt')).resolves.toMatchObject({
      blob: exportedBlob,
      filename: 'pham_nhan_tu_tien.txt',
      mediaType: 'text/plain; charset=utf-8',
    });
    await expect(client.downloadAudiobookExport(1, 'm4b')).resolves.toMatchObject({
      blob: audiobookBlob,
      filename: 'pham_nhan_tu_tien.m4b',
      mediaType: 'audio/mp4',
    });

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      'http://test/api/books/1/exports',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          Authorization: 'Bearer access',
          'Content-Type': 'application/json',
        }),
        body: JSON.stringify({ format: 'txt' }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      'http://test/api/books/1/exports/txt/download',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      'http://test/api/books/1/exports/audiobook/m4b/download',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
  });

  it('creates, lists, and downloads protected system backups with auth headers', async () => {
    const backupItem = {
      filename: 'novel-pipeline-backup-20260709-100000.tar.gz',
      size_bytes: 2048,
      created_at: '2026-07-09T10:00:00',
      encrypted: false,
      secrets_included: false,
      included_modules: ['database', 'uploads', 'audio'],
      excluded_modules: ['exports', 'job_logs', 'secrets'],
      manifest: {},
      download_url: '/api/system/backups/novel-pipeline-backup-20260709-100000.tar.gz/download',
    };
    const backupJob: import('./types').SystemBackupJobStart = {
      job_id: 'backup-job-1',
      status: 'queued',
      message: 'Backup queued',
    };
    const backupBlob = new Blob(['backup'], { type: 'application/octet-stream' });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ items: [backupItem] }) })
      .mockResolvedValueOnce({ ok: true, json: async () => backupJob })
      .mockResolvedValueOnce({
        ok: true,
        blob: async () => backupBlob,
        headers: new Headers({
          'content-disposition': 'attachment; filename="novel-pipeline-backup-20260709-100000.tar.gz"',
          'content-type': 'application/octet-stream',
        }),
      });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    await expect(client.listSystemBackups()).resolves.toEqual({ items: [backupItem] });
    await expect(client.createSystemBackup({ include_audio: true })).resolves.toEqual(backupJob);
    await expect(client.downloadSystemBackup(backupItem.filename)).resolves.toMatchObject({
      blob: backupBlob,
      filename: backupItem.filename,
      mediaType: 'application/octet-stream',
    });

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      'http://test/api/system/backups',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      'http://test/api/system/backups',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          Authorization: 'Bearer access',
          'Content-Type': 'application/json',
        }),
        body: JSON.stringify({ include_audio: true }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      'http://test/api/system/backups/novel-pipeline-backup-20260709-100000.tar.gz/download',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
  });

  it('looks up reader dictionary, downloads annotation exports, and builds audio URLs', async () => {
    const dictionaryResponse = {
      book_id: 1,
      chapter_id: 10,
      query: 'Hàn Lập',
      sources: [{ source: 'xray', term: 'Hàn Lập', definition: 'Nhân vật chính.' }],
      offline_count: 1,
      online: { status: 'ok', error: '', count: 0 },
    };
    const annotationBlob = new Blob(['# annotations'], { type: 'text/markdown' });
    const annotationCsvBlob = new Blob(['kind,selected_text'], { type: 'text/csv' });
    const annotationJsonBlob = new Blob(['{"annotations":[]}'], { type: 'application/json' });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: async () => dictionaryResponse })
      .mockResolvedValueOnce({
        ok: true,
        blob: async () => annotationBlob,
        headers: new Headers({
          'content-disposition': 'attachment; filename="pham.annotations.md"',
          'content-type': 'text/markdown; charset=utf-8',
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        blob: async () => annotationCsvBlob,
        headers: new Headers({
          'content-disposition': 'attachment; filename="pham.annotations.csv"',
          'content-type': 'text/csv; charset=utf-8',
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        blob: async () => annotationJsonBlob,
        headers: new Headers({
          'content-disposition': 'attachment; filename="pham.highlights.json"',
          'content-type': 'application/json; charset=utf-8',
        }),
      });
    const client = new ApiClient('http://test/', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    await expect(client.lookupReaderDictionary(1, 'Hàn Lập', { chapterId: 10, includeOnline: false }))
      .resolves.toEqual(dictionaryResponse);
    await expect(client.downloadReaderAnnotations(1, 'md')).resolves.toMatchObject({
      blob: annotationBlob,
      filename: 'pham.annotations.md',
      mediaType: 'text/markdown; charset=utf-8',
    });
    await expect(client.downloadReaderAnnotations(1, 'csv')).resolves.toMatchObject({
      blob: annotationCsvBlob,
      filename: 'pham.annotations.csv',
      mediaType: 'text/csv; charset=utf-8',
    });
    await expect(client.downloadReaderAnnotations(1, 'json', { kind: 'highlight' })).resolves.toMatchObject({
      blob: annotationJsonBlob,
      filename: 'pham.highlights.json',
      mediaType: 'application/json; charset=utf-8',
    });
    expect(client.chapterAudioUrl(1, 10)).toBe('http://test/api/books/1/chapters/10/audio');
    expect(client.chapterAudioDownloadUrl(1, 10)).toBe('http://test/api/books/1/chapters/10/audio/download');

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      'http://test/api/books/1/dictionary/lookup?q=H%C3%A0n+L%E1%BA%ADp&chapter_id=10&include_online=false',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      'http://test/api/books/1/exports/annotations/md/download',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      'http://test/api/books/1/exports/annotations/csv/download',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      'http://test/api/books/1/exports/annotations/json/download?kind=highlight',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
	  });

  it('imports reader annotations for restore and cross-device recovery', async () => {
    const importResponse = {
      summary: { imported: 1, skipped: 0, duplicates: 0, invalid: 0 },
      annotations: [],
    };
    const fetchMock = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: async () => importResponse,
    });
    const client = new ApiClient('http://test/', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    await expect(client.importReaderAnnotations(1, [
      {
        chapter_number: 1,
        client_id: 'phone-highlight-1',
        kind: 'highlight',
        paragraph_index: 3,
        selected_text: 'Hàn Lập khẽ gật đầu.',
      },
    ])).resolves.toEqual(importResponse);

    expect(fetchMock).toHaveBeenCalledWith(
      'http://test/api/books/1/annotations/import',
      expect.objectContaining({
        body: JSON.stringify({
          annotations: [
            {
              chapter_number: 1,
              client_id: 'phone-highlight-1',
              kind: 'highlight',
              paragraph_index: 3,
              selected_text: 'Hàn Lập khẽ gật đầu.',
            },
          ],
        }),
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
        method: 'POST',
      }),
    );
  });

  it('loads and enriches reader X-Ray data', async () => {
    const xrayResponse = {
      book_id: 1,
      current_chapter_number: 10,
      spoiler_mode: 'no_spoiler',
      entities: [],
      relationships: [],
      faction_tree: [],
      power_rankings: [],
      timeline: [],
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: async () => xrayResponse })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ ...xrayResponse, relationships: [{ source: 'A', target: 'B' }] }),
      });
    const client = new ApiClient('http://test/', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    await expect(client.getReaderXray(1, 10, 'no_spoiler')).resolves.toEqual(xrayResponse);
    await expect(client.enrichReaderXray(1, { chapterId: 10, spoilerMode: 'no_spoiler' }))
      .resolves.toMatchObject({ relationships: [{ source: 'A', target: 'B' }] });

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      'http://test/api/books/1/reader/xray?spoiler_mode=no_spoiler&chapter_id=10',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      'http://test/api/books/1/reader/xray/enrich',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          Authorization: 'Bearer access',
          'Content-Type': 'application/json',
        }),
        body: JSON.stringify({ chapter_id: 10, spoiler_mode: 'no_spoiler' }),
      }),
    );
  });

  it('loads reader dictionary pack for offline browser cache', async () => {
    const dictionaryPack = {
      book_id: 1,
      chapter_id: 10,
      sources: [{ source: 'builtin', term: '灵石', target: 'linh thạch' }],
      source_count: 1,
      counts: { builtin: 1, glossary: 0, offline_dictionary: 0, xray: 0 },
      online: { status: 'skipped', error: '', count: 0 },
      generated_at: '2026-06-29T10:00:00Z',
    };
    const fetchMock = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => dictionaryPack });
    const client = new ApiClient('http://test/', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    await expect(client.getReaderDictionaryPack(1, { chapterId: 10 })).resolves.toEqual(dictionaryPack);

    expect(fetchMock).toHaveBeenCalledWith(
      'http://test/api/books/1/dictionary/pack?chapter_id=10',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
  });

  it('manages reader dictionary files with authenticated requests', async () => {
    const dictionaryFile = {
      filename: 'reader_cn_vi.tsv',
      entry_count: 1,
      size_bytes: 72,
    };
    const uploadFile = new File(
      ['term\ttarget\tdefinition\n道心\tđạo tâm\tTâm cảnh tu đạo.'],
      'reader_cn_vi.tsv',
      { type: 'text/tab-separated-values' },
    );
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ dictionaries: [dictionaryFile] }) })
      .mockResolvedValueOnce({ ok: true, json: async () => dictionaryFile })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ message: 'Dictionary deleted' }) });
    const client = new ApiClient('http://test/', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    await expect(client.listReaderDictionaries()).resolves.toEqual([dictionaryFile]);
    await expect(client.uploadReaderDictionary(uploadFile)).resolves.toEqual(dictionaryFile);
    await expect(client.deleteReaderDictionary('reader_cn_vi.tsv')).resolves.toBeUndefined();

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      'http://test/api/reader/dictionaries',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      'http://test/api/reader/dictionaries',
      expect.objectContaining({
        method: 'POST',
        body: expect.any(FormData),
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      'http://test/api/reader/dictionaries/reader_cn_vi.tsv',
      expect.objectContaining({
        method: 'DELETE',
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
  });

  it('downloads reader dictionary files with authenticated requests', async () => {
    const response = new Response('term\ttarget\n道心\tđạo tâm', {
      headers: {
        'content-disposition': 'attachment; filename="reader_cn_vi.tsv"',
        'content-type': 'text/tab-separated-values; charset=utf-8',
      },
    });
    const fetchMock = vi.fn().mockResolvedValueOnce(response);
    const client = new ApiClient('http://test/', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    await expect(client.downloadReaderDictionary('reader_cn_vi.tsv')).resolves.toMatchObject({
      filename: 'reader_cn_vi.tsv',
      mediaType: 'text/tab-separated-values; charset=utf-8',
    });

    expect(fetchMock).toHaveBeenCalledWith(
      'http://test/api/reader/dictionaries/reader_cn_vi.tsv/download',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
  });

  it('syncs reader progress and annotations with conflict metadata', async () => {
    const syncResponse = {
      progress: {
        book_id: 1,
        chapter_id: 10,
        chapter_number: 2,
        chapter_title: 'Thanh Ngưu trấn',
        mode: 'scroll',
        percent: 55,
        paragraph_index: 4,
        char_offset: 8,
        absolute_char_offset: 248,
        page_index: 0,
        updated_at: '2026-06-29T12:00:00+00:00',
      },
      annotations: [],
      conflicts: [
        {
          entity: 'annotation',
          id: 12,
          client_id: null,
          resolution: 'server_won',
          reason: 'server_newer',
        },
      ],
      server_time: '2026-06-29T12:00:01+00:00',
    };
    const fetchMock = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => syncResponse });
    const client = new ApiClient('http://test/', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    await expect(client.syncReaderState(1, {
      device_id: 'phone',
      progress: {
        chapter_id: 10,
        mode: 'scroll',
        percent: 55,
        paragraph_index: 4,
        char_offset: 8,
        absolute_char_offset: 248,
        page_index: 0,
        updated_at: '2026-06-29T12:00:00+00:00',
      },
      annotations: [],
    })).resolves.toEqual(syncResponse);

    expect(fetchMock).toHaveBeenCalledWith(
      'http://test/api/books/1/reader/sync',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          Authorization: 'Bearer access',
          'Content-Type': 'application/json',
        }),
        body: JSON.stringify({
          device_id: 'phone',
          progress: {
            chapter_id: 10,
            mode: 'scroll',
            percent: 55,
            paragraph_index: 4,
            char_offset: 8,
            absolute_char_offset: 248,
            page_index: 0,
            updated_at: '2026-06-29T12:00:00+00:00',
          },
          annotations: [],
        }),
      }),
    );
  });

  it('streams import job SSE with bearer auth and a reconnect cursor', async () => {
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('id: 7\nevent: import_job_event\ndata: {"sequence":7,"job_id":"job-1",'));
        controller.enqueue(encoder.encode('"task_id":null,"type":"job_transitioned","data":{"status":"running"},"created_at":"now"}\n\n'));
        controller.close();
      },
    });
    const fetchMock = vi.fn().mockResolvedValue(new Response(body, {
      status: 200,
      headers: { 'content-type': 'text/event-stream' },
    }));
    const client = new ApiClient('http://test/', fetchMock as unknown as typeof fetch);
    client.token = 'access';
    const events: unknown[] = [];

    const stream = client.openImportJobEventStream('job 1', (event) => events.push(event), { cursor: 6 });
    await stream.done;

    expect(events).toEqual([
      {
        sequence: 7,
        job_id: 'job-1',
        task_id: null,
        type: 'job_transitioned',
        data: { status: 'running' },
        created_at: 'now',
      },
    ]);
    expect(fetchMock).toHaveBeenCalledWith(
      'http://test/api/import/jobs/job%201/events?cursor=6',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
        signal: expect.any(AbortSignal),
      }),
    );
  });

  it('aborts import job streaming without surfacing an AbortError', async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
    }));
    const client = new ApiClient('http://test/', fetchMock as unknown as typeof fetch);

    const stream = client.openImportJobEventStream('job-1', vi.fn());
    stream.abort();

    await expect(stream.done).resolves.toBeUndefined();
    const init = fetchMock.mock.calls[0]?.[1];
    expect(init?.signal?.aborted).toBe(true);
  });

  it('supports the canonical P10 retryFailedTasks method', async () => {
    const snapshot = { job_id: 'job-1', status: 'queued', tasks: [] };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => snapshot });
    const client = new ApiClient('http://test/', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    await expect(client.retryFailedTasks('job 1')).resolves.toEqual(snapshot);

    expect(fetchMock).toHaveBeenCalledWith(
      'http://test/api/import/jobs/job%201/retry-failed',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
  });

  it('creates, loads, and cancels import jobs through the P09 endpoints', async () => {
    const accepted = { job_id: 'job-1', status: 'queued', total: 1 };
    const snapshot = { job_id: 'job-1', status: 'running', tasks: [] };
    const cancelled = { job_id: 'job-1', status: 'cancelled', tasks: [] };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => accepted })
      .mockResolvedValueOnce({ ok: true, json: async () => snapshot })
      .mockResolvedValueOnce({ ok: true, json: async () => cancelled });
    const client = new ApiClient('http://test/', fetchMock as unknown as typeof fetch);
    client.token = 'access';
    const createRequest = {
      source_url: 'https://www.69shuba.com/book/1',
      title: 'Đại Đạo Triều Thiên',
      author: '',
      source: '69shuba',
      chapters: [{
        url: 'https://www.69shuba.com/book/1/1.html',
        chapter_number: 1,
        title: 'Chương 1',
      }],
    };

    await expect(client.createImportJob(createRequest)).resolves.toEqual(accepted);
    await expect(client.getImportJob('job-1')).resolves.toEqual(snapshot);
    await expect(client.cancelImportJob('job-1')).resolves.toEqual(cancelled);

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      'http://test/api/import/jobs',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          Authorization: 'Bearer access',
          'Content-Type': 'application/json',
        }),
        body: JSON.stringify(createRequest),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      'http://test/api/import/jobs/job-1',
      expect.objectContaining({ headers: expect.objectContaining({ Authorization: 'Bearer access' }) }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      'http://test/api/import/jobs/job-1/cancel',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
  });

  it('supports the canonical P10 subscribeJobEvents method with Last-Event-ID', async () => {
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.close();
      },
    });
    const fetchMock = vi.fn().mockResolvedValue(new Response(body, { status: 200 }));
    const client = new ApiClient('http://test/', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    await client.subscribeJobEvents('job-1', vi.fn(), { cursor: 7, lastEventId: 7 }).done;

    expect(fetchMock).toHaveBeenCalledWith(
      'http://test/api/import/jobs/job-1/events?cursor=7',
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: 'Bearer access',
          'Last-Event-ID': '7',
        }),
        signal: expect.any(AbortSignal),
      }),
    );
  });

  it('preserves typed import job errors without parsing the message', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      statusText: 'Not Found',
      json: async () => ({
        detail: { code: 'job_not_found', retryable: false, message: 'Import job not found' },
      }),
    });
    const client = new ApiClient('http://test/', fetchMock as unknown as typeof fetch);

    const error: unknown = await client.getImportJob('missing').then(
      () => null,
      (value: unknown) => value,
    );

    expect(error).toBeInstanceOf(ApiError);
    if (!(error instanceof ApiError)) throw new Error('Expected ApiError');
    expect(error.code).toBe('job_not_found');
    expect(error.retryable).toBe(false);
  });
});
