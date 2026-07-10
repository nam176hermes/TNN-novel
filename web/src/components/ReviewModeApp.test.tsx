import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ReviewModeApp from './ReviewModeApp';

describe('ReviewModeApp', () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('renders a no-login sanitized review shell without calling the backend', () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);

    render(<ReviewModeApp apiBaseUrl="https://review.example" />);

    expect(screen.getByText('Public review mode')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Bàn dịch' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Login' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Username')).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('lets reviewers inspect representative app screens', async () => {
    render(<ReviewModeApp apiBaseUrl="https://review.example" />);

    await userEvent.click(screen.getAllByRole('button', { name: 'Thư viện' })[0]);
    expect(await screen.findByRole('heading', { name: 'Thư viện đã dịch' })).toBeInTheDocument();
    expect(screen.getByText('Độc Tu')).toBeInTheDocument();

    await userEvent.click(screen.getAllByRole('button', { name: 'Trạng thái' })[0]);
    const statusPage = screen.getByRole('heading', { name: 'Trạng thái hệ thống' }).closest('.review-page');
    expect(statusPage).toBeTruthy();
    expect(within(statusPage as HTMLElement).getByText('API Readiness')).toBeInTheDocument();
  });
});
