import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import LoginPanel from './LoginPanel';

describe('LoginPanel', () => {
  afterEach(cleanup);

  it('submits username and password', async () => {
    const onLogin = vi.fn().mockResolvedValue(undefined);
    render(<LoginPanel error="" onLogin={onLogin} />);

    await userEvent.clear(screen.getByLabelText('Username'));
    await userEvent.type(screen.getByLabelText('Username'), 'admin');
    await userEvent.type(screen.getByLabelText('Password'), 'change_me');
    await userEvent.click(screen.getByRole('button', { name: 'Login' }));

    expect(onLogin).toHaveBeenCalledWith('admin', 'change_me');
  });

  it('shows login errors', () => {
    render(<LoginPanel error="Login failed" onLogin={vi.fn()} />);

    expect(screen.getByText('Login failed')).toBeInTheDocument();
  });

  it('shows env password recovery guidance instead of a no-op forgot button', async () => {
    render(<LoginPanel error="" onLogin={vi.fn()} />);

    await userEvent.click(screen.getByRole('button', { name: 'Forgot password?' }));

    expect(screen.getByRole('status')).toHaveTextContent('MOBILE_API_ADMIN_PASSWORD');
  });
});
