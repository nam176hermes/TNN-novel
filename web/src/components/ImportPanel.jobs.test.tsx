import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, type ApiClient } from '../api/client';
import type {
  ChapterTask,
  ImportJob,
  ImportJobAcceptedResponse,
  JobEvent,
  JobEventSubscription,
  SourcePreview,
} from '../api/types';
import { IMPORT_JOB_STORAGE_KEY } from '../state/useImportJob';
import ImportPanel from './ImportPanel';

function sourcePreview(chapterCount = 3): SourcePreview {
  return {
    adapter_id: '69shuba',
    adapter_label: '69shuba',
    source: 'www.69shuba.com',
    source_url: 'https://www.69shuba.com/book/1',
    title: 'Phàm Nhân Tu Tiên',
    author: 'Vong Ngữ',
    description: '',
    cover_url: '',
    chapter_count: chapterCount,
    chapters: Array.from({ length: chapterCount }, (_, index) => ({
      chapter_number: index + 1,
      title: `Chương ${index + 1}`,
      url: `https://www.69shuba.com/book/1/${index + 1}.html`,
    })),
    policy: {
      source_id: '69shuba',
      label: '69shuba',
      delay_seconds: 8,
      max_concurrency: 1,
      retry_limit: 2,
    },
    managed_source_id: 'source-1',
    managed_source_status: 'VERIFIED',
    managed_source_trust_level: 'HIGH',
    automation_allowed: true,
    automation_reason: '',
    bypass_used: true,
    bypass_method: 'browser_session',
    fetch_method: 'browser_session',
    fetch_status_code: 200,
    fetch_attempts: 1,
    fetch_elapsed_ms: 12,
    fetch_bytes_received: 1024,
    fetch_final_url: 'https://www.69shuba.com/book/1',
    fetch_cookies_refreshed: false,
    fetch_cache_hit: false,
  };
}

function chapterTask(overrides: Partial<ChapterTask> = {}): ChapterTask {
  return {
    id: 1,
    chapter_number: 1,
    title: 'Chương 1',
    status: 'queued',
    stage: 'queued',
    attempts: 0,
    next_attempt_at: '',
    error_code: '',
    error_message: '',
    retryable: false,
    fetch_method: '',
    text_length: 0,
    content_hash: '',
    elapsed_ms: 0,
    started_at: '',
    finished_at: '',
    book_id: null,
    chapter_id: null,
    ...overrides,
  };
}

function jobSnapshot(overrides: Partial<ImportJob> = {}): ImportJob {
  const tasks = overrides.tasks ?? [chapterTask()];
  return {
    job_id: 'import-job-1',
    status: 'queued',
    source: 'www.69shuba.com',
    book_id: null,
    total: tasks.length,
    queued_count: tasks.length,
    running_count: 0,
    succeeded_count: 0,
    failed_count: 0,
    cancelled_count: 0,
    waiting_retry_count: 0,
    verification_required_count: 0,
    created_at: '2026-07-15T00:00:00Z',
    started_at: '',
    finished_at: '',
    cancel_requested_at: '',
    error_summary: '',
    tasks,
    ...overrides,
  };
}

type FakeJobClient = {
  client: ApiClient;
  emit: (event: JobEvent) => void;
  setSnapshot: (snapshot: ImportJob) => void;
  createImportJob: ReturnType<typeof vi.fn>;
  getImportJob: ReturnType<typeof vi.fn>;
  cancelImportJob: ReturnType<typeof vi.fn>;
  retryFailedTasks: ReturnType<typeof vi.fn>;
};

function fakeJobClient(initialSnapshot = jobSnapshot()): FakeJobClient {
  let snapshot = initialSnapshot;
  let listener: ((event: JobEvent) => void) | null = null;
  const createImportJob = vi.fn(async (): Promise<ImportJobAcceptedResponse> => ({
    job_id: snapshot.job_id,
    status: snapshot.status,
    total: snapshot.total,
  }));
  const getImportJob = vi.fn(async () => snapshot);
  const cancelImportJob = vi.fn(async () => {
    snapshot = jobSnapshot({
      ...snapshot,
      status: 'cancelled',
      queued_count: 0,
      cancelled_count: snapshot.total,
      finished_at: '2026-07-15T00:00:03Z',
      tasks: snapshot.tasks.map((task) => ({ ...task, status: 'cancelled', stage: 'cancelled' })),
    });
    return snapshot;
  });
  const retryFailedTasks = vi.fn(async () => {
    snapshot = jobSnapshot({
      ...snapshot,
      status: 'queued',
      queued_count: snapshot.failed_count,
      failed_count: 0,
      finished_at: '',
      tasks: snapshot.tasks.map((task) => (
        task.status === 'failed' ? { ...task, status: 'queued', stage: 'queued' } : task
      )),
    });
    return snapshot;
  });
  const subscribeJobEvents = vi.fn((
    _jobId: string,
    onEvent: (event: JobEvent) => void,
  ): JobEventSubscription => {
    listener = onEvent;
    return { abort: vi.fn(), done: new Promise<void>(() => undefined) };
  });
  const client = {
    createImportJob,
    getImportJob,
    cancelImportJob,
    retryFailedTasks,
    subscribeJobEvents,
  } as unknown as ApiClient;

  return {
    client,
    createImportJob,
    getImportJob,
    cancelImportJob,
    retryFailedTasks,
    emit: (event) => listener?.(event),
    setSnapshot: (nextSnapshot) => {
      snapshot = nextSnapshot;
    },
  };
}

async function previewUrl(preview: SourcePreview): Promise<void> {
  await userEvent.click(screen.getByRole('button', { name: 'URL' }));
  await userEvent.type(screen.getByLabelText('Source URL'), preview.source_url);
  await userEvent.click(screen.getByRole('button', { name: 'Preview URL' }));
  await screen.findByRole('heading', { name: preview.title });
}

describe('ImportPanel durable URL job UX', () => {
  afterEach(() => {
    cleanup();
    window.localStorage.clear();
    vi.useRealTimers();
  });

  it('creates a non-blocking job from the selected chapters and renders its summary', async () => {
    const preview = sourcePreview();
    const fake = fakeJobClient(jobSnapshot({ total: 1, queued_count: 1 }));
    render(
      <ImportPanel
        importJobClient={fake.client}
        onCancel={() => undefined}
        onImportPaste={() => undefined}
        onPreviewImportUrl={vi.fn().mockResolvedValue(preview)}
      />,
    );

    await previewUrl(preview);
    expect(screen.getByText(/Auto-bypass: browser_session/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('checkbox', { name: 'Chọn Chương 1' }));
    await userEvent.click(screen.getByRole('button', { name: 'Tạo job 1 chương' }));

    expect(fake.createImportJob).toHaveBeenCalledWith(expect.objectContaining({
      source_url: preview.source_url,
      title: preview.title,
      chapters: [preview.chapters[0]],
    }));
    const summary = await screen.findByRole('region', { name: 'Tiến độ import URL' });
    expect(within(summary).getByText('1', { selector: '[data-count="total"]' })).toBeInTheDocument();
    expect(within(summary).getByRole('heading', { name: 'Job đang chờ xử lý' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Tạo job 1 chương' })).not.toBeInTheDocument();
  });

  it('reconciles progress events and shows partial success with fetch method and operation badges', async () => {
    const running = jobSnapshot({
      status: 'running',
      queued_count: 0,
      running_count: 2,
      started_at: '2026-07-15T00:00:00Z',
      tasks: [
        chapterTask({ id: 1, status: 'running', stage: 'fetching', fetch_method: 'direct_http' }),
        chapterTask({ id: 2, chapter_number: 2, title: 'Chương 2', status: 'running', stage: 'fetching' }),
      ],
    });
    const fake = fakeJobClient(running);
    window.localStorage.setItem(IMPORT_JOB_STORAGE_KEY, running.job_id);
    render(
      <ImportPanel
        importJobClient={fake.client}
        onCancel={() => undefined}
        onImportPaste={() => undefined}
      />,
    );

    expect(await screen.findByText('Kết nối trực tiếp')).toBeInTheDocument();
    fake.setSnapshot(jobSnapshot({
      ...running,
      status: 'partially_succeeded',
      running_count: 0,
      succeeded_count: 1,
      failed_count: 1,
      finished_at: '2026-07-15T00:00:05Z',
      tasks: [
        {
          ...chapterTask({
            id: 1,
            status: 'succeeded',
            stage: 'succeeded',
            attempts: 1,
            fetch_method: 'browser_session',
            text_length: 1234,
            elapsed_ms: 400,
          }),
          operation: 'created',
        } as ChapterTask,
        chapterTask({
          id: 2,
          chapter_number: 2,
          title: 'Chương 2',
          status: 'failed',
          stage: 'failed',
          attempts: 2,
          fetch_method: 'user_verification_required',
          error_code: 'user_verification_required',
          retryable: false,
        }),
      ],
    }));
    await act(async () => {
      fake.emit({
        sequence: 2,
        job_id: running.job_id,
        task_id: 1,
        type: 'task_transitioned',
        data: {},
        created_at: '2026-07-15T00:00:05Z',
      });
    });

    expect(await screen.findByText('Hoàn tất một phần')).toBeInTheDocument();
    expect(screen.getByText('Phiên trình duyệt')).toBeInTheDocument();
    expect(screen.getByText('Cần xác minh thủ công')).toBeInTheDocument();
    expect(screen.getByText('Tạo mới')).toBeInTheDocument();
    expect(screen.getByText('1.234 ký tự')).toBeInTheDocument();
    expect(screen.getAllByText(/Nguồn yêu cầu xác minh người dùng/).length).toBeGreaterThanOrEqual(1);
  });

  it('cancels an active job and retries failed tasks without losing the job view', async () => {
    const running = jobSnapshot({
      status: 'running',
      queued_count: 0,
      running_count: 1,
      tasks: [chapterTask({ status: 'running', stage: 'fetching' })],
    });
    const fake = fakeJobClient(running);
    window.localStorage.setItem(IMPORT_JOB_STORAGE_KEY, running.job_id);
    const view = render(
      <ImportPanel importJobClient={fake.client} onCancel={() => undefined} onImportPaste={() => undefined} />,
    );

    await userEvent.click(await screen.findByRole('button', { name: 'Hủy job' }));
    expect(fake.cancelImportJob).toHaveBeenCalledWith(running.job_id);
    expect((await screen.findAllByText('Đã hủy')).length).toBeGreaterThanOrEqual(1);

    view.unmount();
    const failed = jobSnapshot({
      status: 'partially_succeeded',
      queued_count: 0,
      succeeded_count: 1,
      failed_count: 1,
      tasks: [
        chapterTask({ status: 'succeeded', stage: 'succeeded' }),
        chapterTask({
          id: 2,
          chapter_number: 2,
          status: 'failed',
          stage: 'failed',
          error_code: 'connect_timeout',
          retryable: true,
        }),
      ],
    });
    const retryFake = fakeJobClient(failed);
    window.localStorage.setItem(IMPORT_JOB_STORAGE_KEY, failed.job_id);
    render(
      <ImportPanel importJobClient={retryFake.client} onCancel={() => undefined} onImportPaste={() => undefined} />,
    );
    await userEvent.click(await screen.findByRole('button', { name: 'Thử lại chương lỗi' }));
    expect(retryFake.retryFailedTasks).toHaveBeenCalledWith(failed.job_id);
    expect(await screen.findByRole('heading', { name: 'Job đang chờ xử lý' })).toBeInTheDocument();
  });

  it('resumes after reload, exposes reconnecting as a live non-failure state, and returns to Library', async () => {
    const terminal = jobSnapshot({
      status: 'succeeded',
      queued_count: 0,
      succeeded_count: 1,
      finished_at: '2026-07-15T00:00:02Z',
      tasks: [chapterTask({ status: 'succeeded', stage: 'succeeded' })],
    });
    const fake = fakeJobClient(terminal);
    const onReturnToLibrary = vi.fn();
    window.localStorage.setItem(IMPORT_JOB_STORAGE_KEY, terminal.job_id);
    render(
      <ImportPanel
        importJobClient={fake.client}
        onCancel={() => undefined}
        onImportPaste={() => undefined}
        onReturnToLibrary={onReturnToLibrary}
      />,
    );

    const progress = screen.getByRole('region', { name: 'Tiến độ import URL' });
    expect(within(progress).getAllByText('Đang kết nối lại…')).toHaveLength(2);
    expect(within(progress).queryByRole('alert')).not.toBeInTheDocument();
    const returnButton = await screen.findByRole('button', { name: 'Về Thư viện' });
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Import hoàn tất' })).toHaveFocus());
    await userEvent.click(returnButton);
    expect(onReturnToLibrary).toHaveBeenCalledOnce();
    expect(fake.getImportJob).toHaveBeenCalledWith(terminal.job_id);
  });

  it('paginates large chapter lists, selects only the visible page, and supports a chapter range', async () => {
    const preview = sourcePreview(60);
    const fake = fakeJobClient(jobSnapshot({ total: 31, queued_count: 31 }));
    render(
      <ImportPanel
        importJobClient={fake.client}
        onCancel={() => undefined}
        onImportPaste={() => undefined}
        onPreviewImportUrl={vi.fn().mockResolvedValue(preview)}
      />,
    );
    await previewUrl(preview);

    expect(screen.getByText('Chương 1')).toBeInTheDocument();
    expect(screen.getByText('Chương 25')).toBeInTheDocument();
    expect(screen.queryByText('Chương 26')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('checkbox', { name: 'Chọn tất cả chương đang hiển thị' }));
    expect(screen.getByText('Đã chọn 25/60 chương')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Trang sau' }));
    expect(screen.getByText('Chương 26')).toBeInTheDocument();
    expect(screen.queryByText('Chương 1')).not.toBeInTheDocument();
    await userEvent.clear(screen.getByLabelText('Từ chương'));
    await userEvent.type(screen.getByLabelText('Từ chương'), '40');
    await userEvent.clear(screen.getByLabelText('Đến chương'));
    await userEvent.type(screen.getByLabelText('Đến chương'), '45');
    await userEvent.click(screen.getByRole('button', { name: 'Chọn khoảng chương' }));
    expect(screen.getByText('Đã chọn 31/60 chương')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Tạo job 31 chương' }));
    expect(fake.createImportJob.mock.calls[0][0].chapters).toHaveLength(31);
  });

  it('uses accessible live progress, labelled controls, and paginates task rows', async () => {
    const tasks = Array.from({ length: 30 }, (_, index) => chapterTask({
      id: index + 1,
      chapter_number: index + 1,
      title: `Chương ${index + 1}`,
      status: 'running',
      stage: 'validating',
      attempts: 1,
      fetch_method: 'stealth_browser_headed',
    }));
    const running = jobSnapshot({
      status: 'running',
      total: 30,
      queued_count: 0,
      running_count: 30,
      tasks,
    });
    const fake = fakeJobClient(running);
    window.localStorage.setItem(IMPORT_JOB_STORAGE_KEY, running.job_id);
    render(
      <ImportPanel importJobClient={fake.client} onCancel={() => undefined} onImportPaste={() => undefined} />,
    );

    const progress = await screen.findByRole('region', { name: 'Tiến độ import URL' });
    expect(progress).toHaveAttribute('aria-live', 'polite');
    expect(screen.getAllByText('Trình duyệt ẩn danh')).toHaveLength(20);
    expect(screen.queryByText('Chương 21')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Trang tác vụ sau' }));
    expect(screen.getByText('Chương 21')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Hủy job' })).toBeEnabled();
  });

  it('focuses a safe typed error and lets the operator return to chapter selection', async () => {
    const preview = sourcePreview(1);
    const fake = fakeJobClient(jobSnapshot());
    fake.createImportJob.mockRejectedValueOnce(new ApiError(
      'unsafe provider detail',
      400,
      'invalid_url',
      false,
    ));
    render(
      <ImportPanel
        importJobClient={fake.client}
        onCancel={() => undefined}
        onImportPaste={() => undefined}
        onPreviewImportUrl={vi.fn().mockResolvedValue(preview)}
      />,
    );
    await previewUrl(preview);
    await userEvent.click(screen.getByRole('checkbox', { name: 'Chọn Chương 1' }));
    await userEvent.click(screen.getByRole('button', { name: 'Tạo job 1 chương' }));

    const heading = await screen.findByRole('heading', { name: 'Không thể theo dõi job' });
    await waitFor(() => expect(heading).toHaveFocus());
    expect(screen.getByRole('alert')).toHaveTextContent('URL nguồn không hợp lệ');
    expect(screen.queryByText('unsafe provider detail')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Quay lại chọn chương' }));
    expect(await screen.findByRole('heading', { name: preview.title })).toBeInTheDocument();
  });
});
