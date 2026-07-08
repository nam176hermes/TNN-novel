import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import JobProgress from './JobProgress';

describe('JobProgress', () => {
  it('shows progress, total, and provider message', () => {
    render(
      <JobProgress
        job={{
          job_id: 'job-1',
          status: 'running',
          progress: 3,
          total: 10,
          message: 'Translating with gemini',
        }}
      />,
    );

    expect(screen.getByText('running')).toBeInTheDocument();
    expect(screen.getByText('3 / 10')).toBeInTheDocument();
    expect(screen.getByText('Translating with gemini')).toBeInTheDocument();
  });

  it('shows preset, chunk size, and stage timing metadata', () => {
    render(
      <JobProgress
        job={{
          job_id: 'job-fast',
          status: 'running',
          progress: 0,
          total: 1,
          message: 'Translating chapter 10',
          preset_id: 'fast_draft',
          chunk_size: 3500,
          stage_timings: [
            {
              stage: 'translate',
              status: 'running',
              provider_id: 'deepseek',
              model: 'deepseek-chat',
              elapsed_ms: 1250,
            },
            {
              stage: 'polish',
              status: 'skipped',
              elapsed_ms: 0,
            },
          ],
        }}
      />,
    );

    expect(screen.getByText('Preset fast_draft')).toBeInTheDocument();
    expect(screen.getByText('Chunk 3500 ký tự')).toBeInTheDocument();
    expect(screen.getByRole('list', { name: 'Timing theo stage hiện tại' })).toBeInTheDocument();
    expect(screen.getByText('translate')).toBeInTheDocument();
    expect(screen.getByText('running · deepseek · deepseek-chat')).toBeInTheDocument();
    expect(screen.getByText('1.3 s')).toBeInTheDocument();
    expect(screen.getByText('polish')).toBeInTheDocument();
    expect(screen.getByText('skipped')).toBeInTheDocument();
  });

  it('shows durable state, step, chunk progress, provider, and cancel request', () => {
    render(
      <JobProgress
        job={{
          job_id: 'job-stable',
          status: 'running',
          state: 'TRANSLATING',
          progress: 1,
          total: 3,
          current_chapter_id: 144,
          current_chunk_index: 2,
          total_chunks: 5,
          current_step: 'TRANSLATING',
          provider: 'gemini',
          model: 'gemini-live',
          retry_count: 1,
          cancel_requested: true,
          message: 'Translating chapter 144',
        }}
      />,
    );

    expect(screen.getByText('State TRANSLATING')).toBeInTheDocument();
    expect(screen.getByText('Step TRANSLATING')).toBeInTheDocument();
    expect(screen.getByText('Chapter 144')).toBeInTheDocument();
    expect(screen.getByText('Chunk 2/5')).toBeInTheDocument();
    expect(screen.getByText('gemini / gemini-live')).toBeInTheDocument();
    expect(screen.getByText('Retry 1')).toBeInTheDocument();
    expect(screen.getByText('Cancel requested. Job will stop at the next safe checkpoint.')).toBeInTheDocument();
  });

  it('shows a cancel action for running jobs', async () => {
    const onCancel = vi.fn();
    render(
      <JobProgress
        job={{
          job_id: 'job-1',
          status: 'running',
          progress: 3,
          total: 10,
          message: 'Translating with gemini',
        }}
        onCancel={onCancel}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Cancel job' }));

    expect(onCancel).toHaveBeenCalledOnce();
  });

  it('shows an idle state without an active job', () => {
    render(<JobProgress job={null} />);

    expect(screen.getByText('No active job')).toBeInTheDocument();
  });
});
