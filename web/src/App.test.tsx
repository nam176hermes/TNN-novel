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
});
