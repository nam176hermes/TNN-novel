import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import JobsView from './JobsView';

afterEach(cleanup);

describe('JobsView', () => {
  it('renders the active job through JobProgress and keeps history honest', async () => {
    const onCancelJob = vi.fn();
    render(
      <JobsView
        activeJob={{
          job_id: 'job-1',
          status: 'running',
          progress: 4,
          total: 10,
          message: 'Đang dịch với Gemini',
        }}
        attempts={{
          data: [
            {
              id: 1,
              job_id: 'job-1',
              chapter_id: 10,
              stage: 'translate',
              provider_id: 'gemini',
              model: 'gemini-live',
              status: 'success',
              elapsed_ms: 1234,
            },
          ],
          error: '',
          state: 'ready',
        }}
        onCancelJob={onCancelJob}
      />,
    );

    expect(screen.getByRole('heading', { name: 'Tác vụ' })).toBeInTheDocument();
    expect(screen.getByText('running')).toBeVisible();
    expect(screen.getByText('4 / 10')).toBeVisible();
    expect(screen.getByText('Đang dịch với Gemini')).toBeVisible();
    expect(
      screen.getByRole('row', {
        name: 'translate gemini gemini-live 10 success 1.2 s -',
      }),
    ).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: 'Cancel job' }));
    expect(onCancelJob).toHaveBeenCalledOnce();
  });

  it('shows the empty active-job and missing-history states', () => {
    render(<JobsView activeJob={null} attempts={{ data: [], error: '', state: 'idle' }} />);

    expect(screen.getByText('Không có tác vụ đang chạy')).toBeVisible();
    expect(screen.getByText('No active job')).toBeVisible();
    expect(screen.getByText('Chưa có lịch sử tác vụ')).toBeVisible();
  });

  it('renders real job history from the backend jobs list', () => {
    render(
      <JobsView
        activeJob={null}
        attempts={{ data: [], error: '', state: 'idle' }}
        jobs={{
          data: [
            {
              job_id: 'job-completed',
              job_type: 'translate',
              status: 'completed',
              progress: 1,
              total: 1,
              message: 'Job completed',
              created_at: '2026-07-02T01:02:25.000000+00:00',
            },
            {
              job_id: 'tts-completed',
              job_type: 'tts',
              status: 'completed',
              progress: 1,
              total: 1,
              message: 'Audio completed',
            },
          ],
          error: '',
          state: 'ready',
        }}
      />,
    );

    const history = screen.getByRole('region', { name: 'Job gần đây' });
    expect(
      within(history).getByRole('row', {
        name: /translate completed - - 1 \/ 1 - - 0 - Job completed 2026-07-02 01:02:25 -/,
      }),
    ).toBeVisible();
    expect(
      within(history).getByRole('row', {
        name: /TTS completed - - 1 \/ 1 - - 0 - Audio completed - -/,
      }),
    ).toBeVisible();
  });

  it('wires refresh and provider shortcuts instead of creating fake jobs', async () => {
    const onOpenProviders = vi.fn();
    const onRefresh = vi.fn().mockResolvedValue(undefined);
    render(
      <JobsView
        activeJob={null}
        attempts={{ data: [], error: '', state: 'idle' }}
        onOpenProviders={onOpenProviders}
        onRefresh={onRefresh}
      />,
    );

    expect(screen.queryByLabelText('Tên tác vụ')).not.toBeInTheDocument();
    await userEvent.click(screen.getAllByRole('button', { name: 'Làm mới' })[0]);
    await userEvent.click(screen.getAllByRole('button', { name: 'Mở Model API' })[0]);

    expect(onRefresh).toHaveBeenCalledOnce();
    expect(onOpenProviders).toHaveBeenCalledOnce();
  });

  it('summarizes stage timing from provider attempts', () => {
    render(
      <JobsView
        activeJob={null}
        attempts={{
          data: [
            {
              id: 1,
              job_id: 'job-1',
              chapter_id: 10,
              stage: 'translate',
              provider_id: 'deepseek',
              model: 'deepseek-chat',
              status: 'success',
              elapsed_ms: 1530,
            },
            {
              id: 2,
              job_id: 'job-1',
              chapter_id: 10,
              stage: 'polish',
              provider_id: 'gemini',
              model: 'gemini-flash',
              status: 'success',
              elapsed_ms: 2466,
            },
            {
              id: 3,
              job_id: 'job-1',
              chapter_id: 10,
              stage: 'qa',
              provider_id: 'gemini',
              model: 'gemini-flash',
              status: 'failed',
              elapsed_ms: 800,
              error: 'quota',
            },
          ],
          error: '',
          state: 'ready',
        }}
      />,
    );

    const timing = screen.getByRole('region', { name: 'Timing theo stage' });
    expect(within(timing).getByText('Tổng thời gian')).toBeVisible();
    expect(within(timing).getByText('4.8 s')).toBeVisible();
    expect(within(timing).getByText('Stage chậm nhất')).toBeVisible();
    expect(within(timing).getByText('Stage chậm nhất').parentElement).toHaveTextContent('polish');
    expect(within(timing).getByText('Stage chậm nhất').parentElement).toHaveTextContent('2.5 s');

    const breakdown = within(timing).getByRole('list', { name: 'Breakdown timing theo stage' });
    expect(within(breakdown).getByText('translate')).toBeVisible();
    expect(within(breakdown).getByText('1.5 s')).toBeVisible();
    expect(within(breakdown).getByText('polish')).toBeVisible();
    expect(within(breakdown).getByText('2.5 s')).toBeVisible();
    expect(within(breakdown).getByText('qa')).toBeVisible();
    expect(within(breakdown).getByText('800 ms')).toBeVisible();
    expect(within(breakdown).getByText(/1 lỗi/)).toBeVisible();
  });

  it('shows a TTS chunk report and retries failed chunks', async () => {
    const onRetryTtsChunks = vi.fn();
    render(
      <JobsView
        activeJob={{
          job_id: 'tts-job-1',
          job_type: 'tts',
          status: 'running',
          progress: 1,
          total: 2,
          message: 'Generating audio',
        }}
        attempts={{ data: [], error: '', state: 'idle' }}
        onRetryTtsChunks={onRetryTtsChunks}
        ttsJob={{
          data: {
            id: 'tts-job-1',
            job_id: 'tts-job-1',
            status: 'failed',
            provider: 'f5_vietnamese',
            model: 'vivioice',
            progress: 50,
            chunks: [
              {
                id: 'chunk-0',
                job_id: 'tts-job-1',
                chunk_index: 0,
                text_hash: 'hash-0',
                status: 'completed',
                duration_seconds: 3.25,
                qa_status: 'passed',
              },
              {
                id: 'chunk-1',
                job_id: 'tts-job-1',
                chunk_index: 1,
                text_hash: 'hash-1',
                status: 'failed',
                qa_status: 'failed',
                error_message: 'Audio QA failed',
              },
            ],
          },
          error: '',
          state: 'ready',
        }}
      />,
    );

    const report = screen.getByRole('region', { name: 'TTS chunk report' });
    expect(within(report).getByText('f5_vietnamese')).toBeVisible();
    expect(within(report).getByText('vivioice')).toBeVisible();
    expect(within(report).getByText('50%')).toBeVisible();
    expect(
      within(report).getByRole('row', {
        name: '2 failed failed - Audio QA failed',
      }),
    ).toBeVisible();

    await userEvent.click(within(report).getByRole('button', { name: 'Retry failed chunks' }));
    expect(onRetryTtsChunks).toHaveBeenCalledWith('tts-job-1');
  });

  it('disables TTS retry when there are no failed chunks', () => {
    render(
      <JobsView
        activeJob={{
          job_id: 'tts-job-1',
          job_type: 'tts',
          status: 'running',
          progress: 1,
          total: 1,
          message: 'Generating audio',
        }}
        attempts={{ data: [], error: '', state: 'idle' }}
        ttsJob={{
          data: {
            id: 'tts-job-1',
            status: 'running',
            provider: 'f5_vietnamese',
            model: 'vivioice',
            progress: 10,
            chunks: [
              {
                id: 'chunk-0',
                job_id: 'tts-job-1',
                chunk_index: 0,
                text_hash: 'hash-0',
                status: 'completed',
                qa_status: 'passed',
              },
            ],
          },
          error: '',
          state: 'ready',
        }}
      />,
    );

    expect(screen.getByRole('button', { name: 'Retry failed chunks' })).toBeDisabled();
  });
});
