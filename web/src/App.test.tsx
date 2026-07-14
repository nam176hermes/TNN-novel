import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';
import { clearToken, loadRefreshToken, saveSessionTokens } from './state/session';
import { fixtureUsage } from './test/fixtures';

describe('App', () => {
  beforeEach(() => {
    clearToken();
  });

  afterEach(() => {
    cleanup();
    clearToken();
    window.localStorage.removeItem('novel-pwa-install-dismissed-v1');
    window.sessionStorage.removeItem('novel-pwa-install-later-session-v1');
    Object.defineProperty(navigator, 'onLine', { configurable: true, value: true });
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('shows login when no session token exists', () => {
    render(<App />);

    expect(screen.getByRole('heading', { name: 'Novel-TNN Translator' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Login' })).toBeInTheDocument();
    expect(screen.queryByRole('navigation', { name: 'Primary' })).not.toBeInTheDocument();
  });

  it('shows an install prompt when the browser offers PWA installation', async () => {
    const prompt = vi.fn().mockResolvedValue(undefined);
    const installEvent = new Event('beforeinstallprompt') as Event & {
      prompt: () => Promise<void>;
      userChoice: Promise<{ outcome: string; platform: string }>;
    };
    Object.defineProperty(installEvent, 'prompt', { value: prompt });
    Object.defineProperty(installEvent, 'userChoice', {
      value: Promise.resolve({ outcome: 'accepted', platform: 'web' }),
    });
    const preventDefault = vi.spyOn(installEvent, 'preventDefault');

    render(<App />);
    window.dispatchEvent(installEvent);

    const promptRegion = await screen.findByRole(
      'region',
      { name: 'Cài đặt Novel-TNN như app' },
      { timeout: 2500 },
    );
    expect(preventDefault).toHaveBeenCalled();
    expect(within(promptRegion).getByText(/đọc các chương đã lưu khi mất mạng/)).toBeInTheDocument();

    await userEvent.click(within(promptRegion).getByRole('button', { name: 'Cài đặt ngay' }));

    expect(prompt).toHaveBeenCalledTimes(1);
  });

  it('lets the operator dismiss the PWA install prompt', async () => {
    const installEvent = new Event('beforeinstallprompt');
    Object.defineProperty(installEvent, 'prompt', { value: vi.fn().mockResolvedValue(undefined) });
    Object.defineProperty(installEvent, 'userChoice', {
      value: Promise.resolve({ outcome: 'dismissed', platform: 'web' }),
    });

    render(<App />);
    window.dispatchEvent(installEvent);

    const promptRegion = await screen.findByRole('region', { name: 'Cài đặt Novel-TNN như app' });
    await userEvent.click(within(promptRegion).getByRole('button', { name: 'Để sau' }));

    expect(screen.queryByRole('region', { name: 'Cài đặt Novel-TNN như app' })).not.toBeInTheDocument();
    expect(window.sessionStorage.getItem('novel-pwa-install-later-session-v1')).toBe('1');
    expect(window.localStorage.getItem('novel-pwa-install-dismissed-v1')).toBeNull();
  });

  it('shows manual PWA install guidance when the browser does not emit installprompt', async () => {
    render(<App />);

    const promptRegion = await screen.findByRole('region', { name: 'Cài đặt Novel-TNN như app' });
    expect(within(promptRegion).getByText(/Thêm vào màn hình chính/)).toBeInTheDocument();
    expect(within(promptRegion).queryByRole('button', { name: 'Cài đặt ngay' })).not.toBeInTheDocument();
  });

  it('shows a safe offline indicator without exposing private cached API data', () => {
    Object.defineProperty(navigator, 'onLine', { configurable: true, value: false });

    render(<App />);

    const status = screen.getByRole('status', { name: 'Trạng thái offline' });
    expect(within(status).getByText('Bạn đang offline')).toBeInTheDocument();
    expect(within(status).getByText(/nội dung đã cache thủ công/)).toBeInTheDocument();
    expect(within(status).getByText(/Import, dịch, TTS và export cần kết nối/)).toBeInTheDocument();
  });

  it('logs in and opens the V2 workflow shell', async () => {
    const fetchMock = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      const target = String(url);

      if (target.endsWith('/api/auth/login') && init?.method === 'POST') {
        return {
          ok: true,
          json: async () => ({
            access_token: 'access',
            refresh_token: 'refresh',
            token_type: 'bearer',
          }),
        };
      }

      if (target.endsWith('/api/providers')) {
        return { ok: true, json: async () => ({ providers: [] }) };
      }

      if (target.endsWith('/api/style-profiles')) {
        return { ok: true, json: async () => ({ profiles: [] }) };
      }

      if (target.endsWith('/api/books')) {
        return { ok: true, json: async () => [] };
      }

      if (target.endsWith('/api/providers/usage')) {
        return {
          ok: true,
          json: async () => ({
            usage: fixtureUsage,
          }),
        };
      }

      throw new Error(`Unexpected URL: ${target}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);

    await userEvent.type(screen.getByLabelText('Password'), 'password');
    await userEvent.click(screen.getByRole('button', { name: 'Login' }));

    expect(await screen.findByRole('heading', { name: 'Novel-TNN' })).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'Quy trình' })).toBeInTheDocument();
    expect(loadRefreshToken()).toBe('refresh');
    expect(fetchMock).toHaveBeenCalledWith(
      'http://127.0.0.1:7860/api/auth/login',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ username: 'admin', password: 'password' }),
      }),
    );
  });

  it('restores an existing session with a refresh token instead of showing login', async () => {
    saveSessionTokens('old-access', 'stored-refresh');
    const fetchMock = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      const target = String(url);

      if (target.endsWith('/api/auth/refresh') && init?.method === 'POST') {
        return {
          ok: true,
          json: async () => ({
            access_token: 'fresh-access',
            refresh_token: 'fresh-refresh',
            token_type: 'bearer',
          }),
        };
      }

      if (target.endsWith('/api/providers')) {
        return { ok: true, json: async () => ({ providers: [] }) };
      }

      if (target.endsWith('/api/style-profiles')) {
        return { ok: true, json: async () => ({ profiles: [] }) };
      }

      if (target.endsWith('/api/books')) {
        return { ok: true, json: async () => [] };
      }

      if (target.endsWith('/api/providers/usage')) {
        return {
          ok: true,
          json: async () => ({
            usage: fixtureUsage,
          }),
        };
      }

      throw new Error(`Unexpected URL: ${target}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);

    expect(screen.queryByRole('button', { name: 'Login' })).not.toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: 'Novel-TNN' })).toBeInTheDocument();
    expect(loadRefreshToken()).toBe('fresh-refresh');
    expect(fetchMock).toHaveBeenCalledWith(
      'http://127.0.0.1:7860/api/auth/refresh',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ refresh_token: 'stored-refresh' }),
      }),
    );
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        'http://127.0.0.1:7860/api/providers',
        expect.objectContaining({
          headers: expect.objectContaining({ Authorization: 'Bearer fresh-access' }),
        }),
      );
    });
  });

  it('logs out locally and returns to the login screen', async () => {
    const fetchMock = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      const target = String(url);

      if (target.endsWith('/api/auth/login') && init?.method === 'POST') {
        return {
          ok: true,
          json: async () => ({
            access_token: 'access',
            refresh_token: 'refresh',
            token_type: 'bearer',
          }),
        };
      }

      if (target.endsWith('/api/auth/logout') && init?.method === 'POST') {
        return { ok: true, json: async () => ({ message: 'Logged out' }) };
      }

      if (target.endsWith('/api/providers')) {
        return { ok: true, json: async () => ({ providers: [] }) };
      }

      if (target.endsWith('/api/style-profiles')) {
        return { ok: true, json: async () => ({ profiles: [] }) };
      }

      if (target.endsWith('/api/books')) {
        return { ok: true, json: async () => [] };
      }

      if (target.endsWith('/api/providers/usage')) {
        return {
          ok: true,
          json: async () => ({
            usage: fixtureUsage,
          }),
        };
      }

      throw new Error(`Unexpected URL: ${target}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);

    await userEvent.type(screen.getByLabelText('Password'), 'password');
    await userEvent.click(screen.getByRole('button', { name: 'Login' }));
    expect(await screen.findByRole('button', { name: 'Đăng xuất' })).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Đăng xuất' }));

    expect(await screen.findByRole('button', { name: 'Login' })).toBeInTheDocument();
    expect(window.localStorage.getItem('novel-operator-token')).toBeNull();
    expect(window.localStorage.getItem('novel-operator-refresh-token')).toBeNull();
    expect(fetchMock).toHaveBeenCalledWith(
      'http://127.0.0.1:7860/api/auth/logout',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      }),
    );
  });

  it('reloads backups once after polled completion without retaining the passphrase', async () => {
    const passphrase = 'correct horse app secret';
    const backupFilename = 'novel-pipeline-backup-20260713-120000.tar.gz.enc';
    let backupListCalls = 0;
    const fetchMock = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      const target = String(url);

      if (target.endsWith('/api/auth/login') && init?.method === 'POST') {
        return {
          ok: true,
          json: async () => ({
            access_token: 'access',
            refresh_token: 'refresh',
            token_type: 'bearer',
          }),
        };
      }
      if (target.endsWith('/api/providers')) {
        return { ok: true, json: async () => ({ providers: [] }) };
      }
      if (target.endsWith('/api/style-profiles')) {
        return { ok: true, json: async () => ({ profiles: [] }) };
      }
      if (target.endsWith('/api/books')) {
        return { ok: true, json: async () => [] };
      }
      if (target.endsWith('/api/providers/usage')) {
        return { ok: true, json: async () => ({ usage: fixtureUsage }) };
      }
      if (target.endsWith('/api/system/status')) {
        return {
          ok: true,
          json: async () => ({
            active_jobs: 0,
            active_provider: '',
            api_ready: true,
            app_version: '0.1.0',
            asset_protection_enabled: true,
            backup_recommendation: 'Create a system backup before upgrades.',
            build: 'test',
            cache_count: 0,
            cache_size_bytes: 0,
            data_directory_available: true,
            data_size_bytes: 0,
            database_available: true,
            db_size_bytes: 0,
            last_failed_job: null,
            ollama_host: '',
            ollama_model: '',
            public_deploy: false,
            queued_jobs: 0,
            recent_operational_errors: [],
            retrying_jobs: 0,
            running_jobs: 0,
            interrupted_jobs: 0,
            failed_jobs: 0,
            upload_max_bytes: 1024,
            storage_health: 'healthy',
            storage_label: 'Test storage',
          }),
        };
      }
      if (target.endsWith('/api/system/backups') && init?.method === 'POST') {
        expect(init.body).toBe(JSON.stringify({
          include_audio: true,
          include_exports: false,
          include_job_logs: false,
          include_secrets: true,
          passphrase,
        }));
        return {
          ok: true,
          json: async () => ({ job_id: 'backup-job-1', status: 'queued', message: 'Backup queued' }),
        };
      }
      if (target.endsWith('/api/system/backups')) {
        backupListCalls += 1;
        return {
          ok: true,
          json: async () => ({
            items: backupListCalls > 1
              ? [{
                archive_available: true,
                created_at: '2026-07-13T12:00:00Z',
                download_url: `/api/system/backups/${backupFilename}/download`,
                encrypted: true,
                excluded_modules: [],
                filename: backupFilename,
                included_modules: ['database', 'secrets'],
                manifest: {},
                manifest_available: true,
                metadata_status: 'READY',
                repair_needed: false,
                secrets_included: true,
                size_bytes: 4096,
                warning: '',
              }]
              : [],
          }),
        };
      }
      if (target.endsWith('/api/jobs/backup-job-1/events')) {
        return {
          ok: false,
          status: 503,
          statusText: 'Unavailable',
          json: async () => ({ detail: 'stream unavailable' }),
          text: async () => '',
        };
      }
      if (target.endsWith('/api/jobs/backup-job-1')) {
        return {
          ok: true,
          json: async () => ({
            job_id: 'backup-job-1',
            job_type: 'backup',
            status: 'completed',
            state: 'COMPLETED',
            progress: 6,
            total: 6,
            message: `Backup completed: ${backupFilename}`,
          }),
        };
      }
      if (target.endsWith('/api/jobs/backup-job-1/attempts')) {
        return { ok: true, json: async () => ({ attempts: [] }) };
      }
      if (target.endsWith('/api/jobs/backup-job-1/logs')) {
        return { ok: true, json: async () => [] };
      }
      if (target.includes('/api/jobs?limit=')) {
        return { ok: true, json: async () => ({ jobs: [] }) };
      }

      throw new Error(`Unexpected URL: ${target}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    vi.spyOn(window, 'prompt').mockReturnValue(passphrase);

    render(<App />);
    await userEvent.type(screen.getByLabelText('Password'), 'password');
    await userEvent.click(screen.getByRole('button', { name: 'Login' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Trạng thái' }));
    expect(await screen.findByRole('heading', { name: 'Trạng thái hệ thống' })).toBeInTheDocument();
    await waitFor(() => expect(backupListCalls).toBe(1));

    await userEvent.click(screen.getByText('Sao lưu hệ thống'));
    await userEvent.click(screen.getByRole('button', { name: 'Backup mã hóa' }));

    await waitFor(() => expect(backupListCalls).toBe(2));
    expect(screen.getByText(`Backup completed: ${backupFilename}`)).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent(passphrase);
    expect(window.localStorage.getItem('novel-operator-token') ?? '').not.toContain(passphrase);
    expect(window.sessionStorage.getItem('novel-pwa-install-later-session-v1') ?? '').not.toContain(passphrase);
    expect(backupListCalls).toBe(2);
  });
});
