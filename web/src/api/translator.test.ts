import { describe, expect, it, vi } from 'vitest';
import { ApiClient } from './client';
import type { ImportFileRequest, ImportPasteRequest } from './types';

describe('translator API methods', () => {
  it('posts pasted import JSON and returns the import response', async () => {
    const request: ImportPasteRequest = {
      title: 'Phàm Nhân Tu Tiên',
      chapter_number: 1,
      chapter_title: 'Sơn biên tiểu thôn',
      text: 'Chapter source text',
    };
    const importResponse = {
      book_id: 1,
      chapter_id: 10,
      path: '/tmp/chapter.txt',
      message: 'Imported',
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => importResponse,
    });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    await expect(client.importPaste(request)).resolves.toEqual(importResponse);

    expect(fetchMock).toHaveBeenCalledWith(
      'http://test/api/import/paste',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          Authorization: 'Bearer access',
          'Content-Type': 'application/json',
        }),
        body: JSON.stringify(request),
      }),
    );
  });

  it('posts imported files as multipart form data without overriding content type', async () => {
    const file = new File(['章节正文'], 'chapter-1.txt', { type: 'text/plain' });
    const request: ImportFileRequest = {
      title: 'Phàm Nhân Tu Tiên',
      chapter_number: 1,
      chapter_title: 'Sơn biên tiểu thôn',
      file,
    };
    const importResponse = {
      book_id: 1,
      chapter_id: 10,
      path: '/tmp/chapter-1.txt',
      message: 'Imported',
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => importResponse,
    });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    await expect(client.importFile(request)).resolves.toEqual(importResponse);

    expect(fetchMock).toHaveBeenCalledWith(
      'http://test/api/import/file',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          Authorization: 'Bearer access',
        }),
      }),
    );
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.headers).not.toHaveProperty('Content-Type');
    expect(init.body).toBeInstanceOf(FormData);
    const formData = init.body as FormData;
    expect(formData.get('title')).toBe('Phàm Nhân Tu Tiên');
    expect(formData.get('chapter_number')).toBe('1');
    expect(formData.get('chapter_title')).toBe('Sơn biên tiểu thôn');
    expect(formData.get('file')).toBe(file);
  });

  it('gets chapter source text', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ chapter_id: 10, text: 'Source text' }),
    });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    await expect(client.getChapterSource(1, 10)).resolves.toBe('Source text');

    expect(fetchMock).toHaveBeenCalledWith(
      'http://test/api/books/1/chapters/10/source',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
  });

  it('gets chapter rich content with text and sanitized HTML', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        chapter_id: 10,
        text: 'Kiếm khí nổi lên.',
        html: '<p>Kiếm khí nổi lên.</p><img src="/book-assets/1/sword.png" alt="Kiếm"/>',
      }),
    });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    await expect(client.getChapterContent(1, 10)).resolves.toEqual({
      text: 'Kiếm khí nổi lên.',
      html: '<p>Kiếm khí nổi lên.</p><img src="/book-assets/1/sword.png" alt="Kiếm"/>',
    });

    expect(fetchMock).toHaveBeenCalledWith(
      'http://test/api/books/1/chapters/10/content',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
  });

  it('returns empty source text for translated-only chapters without raw text', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      statusText: 'Not Found',
      json: async () => ({ detail: 'Source text not found' }),
    });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);

    await expect(client.getChapterSource(1, 10)).resolves.toBe('');
  });

  it('still throws when chapter source lookup cannot find the chapter', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      statusText: 'Not Found',
      json: async () => ({ detail: 'Chapter not found' }),
    });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);

    await expect(client.getChapterSource(1, 10)).rejects.toMatchObject({
      message: 'Failed to load chapter source (404 Not Found): Chapter not found',
      status: 404,
    });
  });

  it('returns null for missing chapter translation without throwing', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      statusText: 'Not Found',
      json: vi.fn(),
      text: vi.fn(),
    });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);

    await expect(client.getChapterTranslation(1, 10)).resolves.toBeNull();
  });

  it('patches chapter translation JSON', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    await expect(client.saveChapterTranslation(1, 10, 'Translated text')).resolves.toBeUndefined();

    expect(fetchMock).toHaveBeenCalledWith(
      'http://test/api/books/1/chapters/10/translation',
      expect.objectContaining({
        method: 'PATCH',
        headers: expect.objectContaining({
          Authorization: 'Bearer access',
          'Content-Type': 'application/json',
        }),
        body: JSON.stringify({ text: 'Translated text' }),
      }),
    );
  });

  it('deletes only chapter translation artifacts', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    await expect(client.deleteChapterTranslation(1, 10)).resolves.toBeUndefined();

    expect(fetchMock).toHaveBeenCalledWith(
      'http://test/api/books/1/chapters/10/translation',
      expect.objectContaining({
        method: 'DELETE',
        headers: expect.objectContaining({
          Authorization: 'Bearer access',
        }),
      }),
    );
  });

  it('deletes a chapter', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    await expect(client.deleteChapter(1, 10)).resolves.toBeUndefined();

    expect(fetchMock).toHaveBeenCalledWith(
      'http://test/api/books/1/chapters/10',
      expect.objectContaining({
        method: 'DELETE',
        headers: expect.objectContaining({
          Authorization: 'Bearer access',
        }),
      }),
    );
  });

  it('gets chapter translation text when present', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ chapter_id: 10, text: 'Translated text' }),
    });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    await expect(client.getChapterTranslation(1, 10)).resolves.toBe('Translated text');

    expect(fetchMock).toHaveBeenCalledWith(
      'http://test/api/books/1/chapters/10/translation',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
  });

  it('gets a saved QA report when present', async () => {
    const report = {
      book_id: 1,
      chapter_id: 10,
      quality_score: 8.5,
      fidelity_score: 9,
      style_score: 8,
      glossary_score: 8,
      audiobook_score: 9,
      verdict: 'PASS',
      report_json: { issues: [{ type: 'style', message: 'Tighten phrasing' }] },
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => report,
    });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    await expect(client.getQaReport(1, 10)).resolves.toEqual(report);

    expect(fetchMock).toHaveBeenCalledWith(
      'http://test/api/books/1/chapters/10/qa',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
  });

  it('returns null when a QA report has not been saved yet', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
      statusText: 'No Content',
      json: vi.fn(),
      text: vi.fn(),
    });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);

    await expect(client.getQaReport(1, 10)).resolves.toBeNull();
  });

  it('gets job attempts and returns the attempts array', async () => {
    const attempts = [
      {
        id: 1,
        job_id: 'job-1',
        chapter_id: 10,
        provider_id: 'gemini',
        model: 'gemini-2.5-flash-lite',
        status: 'completed',
        elapsed_ms: 1200,
        created_at: '2026-06-20T00:00:00Z',
      },
    ];
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ attempts }),
    });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    await expect(client.getJobAttempts('job-1')).resolves.toEqual(attempts);

    expect(fetchMock).toHaveBeenCalledWith(
      'http://test/api/jobs/job-1/attempts',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
  });

  it('tests a provider with a short prompt', async () => {
    const result = {
      provider_id: 'gemini',
      model: 'gemini-live',
      ok: true,
      sample: 'Hắn cầm linh thạch lên.',
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => result,
    });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    await expect(client.testProvider('gemini', '他拿起灵石。')).resolves.toEqual(result);

    expect(fetchMock).toHaveBeenCalledWith(
      'http://test/api/providers/test',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          Authorization: 'Bearer access',
          'Content-Type': 'application/json',
        }),
        body: JSON.stringify({ provider_id: 'gemini', prompt: '他拿起灵石。' }),
      }),
    );
  });
});
