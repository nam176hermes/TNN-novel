import { describe, expect, it, vi } from 'vitest';
import { ApiClient } from './client';

function streamFromText(text: string): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();

  return new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode(text));
      controller.close();
    },
  });
}

describe('job API methods', () => {
  it('lists recent jobs with auth headers', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        jobs: [
          {
            job_id: 'job-1',
            job_type: 'translate',
            status: 'completed',
            progress: 1,
            total: 1,
            message: 'Job completed',
          },
        ],
      }),
    });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    await expect(client.listJobs(20)).resolves.toEqual([
      expect.objectContaining({ job_id: 'job-1', status: 'completed' }),
    ]);

    expect(fetchMock).toHaveBeenCalledWith(
      'http://test/api/jobs?limit=20',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
  });

  it('starts a translate job with book id, chapter ids, preset id, and style profile id', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ job_id: 'job-1', status: 'pending', message: 'started' }),
    });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    const job = await client.startTranslateJob(1, [10], 'balanced', 'kiem_hiep');

    expect(job.job_id).toBe('job-1');
    expect(fetchMock).toHaveBeenCalledWith(
      'http://test/api/jobs/translate',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          Authorization: 'Bearer access',
          'Content-Type': 'application/json',
        }),
        body: JSON.stringify({
          book_id: 1,
          chapter_ids: [10],
          limit: 15,
          params: { preset_id: 'balanced', style_profile_id: 'kiem_hiep' },
        }),
      }),
    );
  });

  it('starts a fast draft translate job with explicit chunk size', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ job_id: 'job-fast', status: 'pending', message: 'started' }),
    });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    const job = await client.startTranslateJob(1, [10], 'fast_draft', 'huyen_huyen', 3500);

    expect(job.job_id).toBe('job-fast');
    expect(fetchMock).toHaveBeenCalledWith(
      'http://test/api/jobs/translate',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          book_id: 1,
          chapter_ids: [10],
          limit: 15,
          params: { preset_id: 'fast_draft', style_profile_id: 'huyen_huyen', chunk_size: '3500' },
        }),
      }),
    );
  });

  it('starts a book translate job for batch raw chapters', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ job_id: 'job-batch', status: 'pending', message: 'started' }),
    });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    const job = await client.startBookTranslateJob(1, 'fast_draft', 'huyen_huyen', 3500, {
      chapterIds: [10, 11],
      limit: 123,
    });

    expect(job.job_id).toBe('job-batch');
    expect(fetchMock).toHaveBeenCalledWith(
      'http://test/api/jobs/translate',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          Authorization: 'Bearer access',
          'Content-Type': 'application/json',
        }),
        body: JSON.stringify({
          book_id: 1,
          chapter_ids: [10, 11],
          limit: 123,
          params: { preset_id: 'fast_draft', style_profile_id: 'huyen_huyen', chunk_size: '3500' },
        }),
      }),
    );
  });

  it('starts QA and TTS jobs', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ job_id: 'qa-1', status: 'pending', message: 'QA job started' }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ job_id: 'tts-1', status: 'pending', message: 'TTS job started' }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ job_id: 'tts-book-1', status: 'pending', message: 'Audiobook TTS job started' }),
      });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    await expect(client.startQaJob(1, [10])).resolves.toMatchObject({ job_id: 'qa-1' });
    await expect(client.startTtsJob(1, [10])).resolves.toMatchObject({ job_id: 'tts-1' });
    await expect(client.startBookTtsJob(1, { limit: 200 })).resolves.toMatchObject({ job_id: 'tts-book-1' });

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      'http://test/api/jobs/qa',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ book_id: 1, chapter_ids: [10], limit: 15, params: {} }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      'http://test/api/jobs/tts',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ book_id: 1, chapter_ids: [10], limit: 15, params: {} }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      'http://test/api/jobs/tts',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ book_id: 1, chapter_ids: [], limit: 200, params: {} }),
      }),
    );
  });

  it('streams authenticated job events from fetch SSE', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      body: streamFromText(
        [
          'data: {"job_id":"job-1","status":"running","progress":1,"total":2,"message":"Translating"}',
          '',
          'data: {"job_id":"job-1","status":"completed","progress":2,"total":2,"message":"Done"}',
          '',
          '',
        ].join('\n'),
      ),
    });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    const controller = new AbortController();
    const events = vi.fn();
    client.token = 'access';

    await client.streamJob('job-1', events, controller.signal);

    expect(fetchMock).toHaveBeenCalledWith(
      'http://test/api/jobs/job-1/events',
      expect.objectContaining({
        headers: expect.objectContaining({
          Accept: 'text/event-stream',
          Authorization: 'Bearer access',
          'Cache-Control': 'no-cache',
        }),
        signal: controller.signal,
      }),
    );
    expect(events).toHaveBeenCalledTimes(2);
    expect(events).toHaveBeenLastCalledWith(
      expect.objectContaining({ job_id: 'job-1', status: 'completed', progress: 2 }),
    );
  });

  it('cancels jobs with auth headers', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ message: 'Job cancelled' }),
    });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    await expect(client.cancelJob('job-1')).resolves.toBeUndefined();

    expect(fetchMock).toHaveBeenCalledWith(
      'http://test/api/jobs/job-1/cancel',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
  });

  it('loads and retries TTS jobs with auth headers', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          id: 'tts-1',
          status: 'failed',
          provider: 'f5_vietnamese',
          model: 'vivioice',
          progress: 50,
          chunks: [],
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ job_id: 'tts-1', status: 'retrying', message: 'Retry queued' }),
      });
    const client = new ApiClient('http://test', fetchMock as unknown as typeof fetch);
    client.token = 'access';

    await expect(client.getTtsJob('tts-1')).resolves.toMatchObject({
      id: 'tts-1',
      provider: 'f5_vietnamese',
      model: 'vivioice',
    });
    await expect(client.retryTtsJob('tts-1')).resolves.toMatchObject({ status: 'retrying' });

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      'http://test/api/tts/jobs/tts-1',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      'http://test/api/tts/jobs/tts-1/retry',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
  });
});
