import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import WorkflowShell, { type WorkflowView } from './WorkflowShell';

const renderShell = (activeView: WorkflowView = 'workbench') => {
  const onViewChange = vi.fn();
  const onOpenImport = vi.fn();

  render(
    <WorkflowShell
      activeView={activeView}
      apiBaseUrl="http://127.0.0.1:7860"
      apiStatus="ready"
      onLogout={vi.fn()}
      onOpenImport={onOpenImport}
      onViewChange={onViewChange}
      renderView={() => <section aria-label="Current workflow">Workbench content</section>}
    />,
  );

  return { onOpenImport, onViewChange };
};

describe('WorkflowShell', () => {
  afterEach(() => {
    cleanup();
  });

  it('renders Vietnamese workflow navigation labels with active state', () => {
    renderShell('glossary');

    const nav = screen.getByRole('navigation', { name: 'Quy trình' });

    expect(within(nav).getByRole('button', { name: 'Bàn dịch' })).toHaveAttribute('aria-pressed', 'false');
    expect(within(nav).getByRole('button', { name: 'Raw chưa dịch' })).toHaveAttribute('aria-pressed', 'false');
    expect(within(nav).getByRole('button', { name: 'Thư viện' })).toHaveAttribute('aria-pressed', 'false');
    expect(within(nav).getByRole('button', { name: 'Đọc truyện' })).toHaveAttribute('aria-pressed', 'false');
    expect(within(nav).getByRole('button', { name: 'Nhập chương' })).toHaveAttribute('aria-pressed', 'false');
    expect(within(nav).getByRole('button', { name: 'Nguồn truyện' })).toHaveAttribute('aria-pressed', 'false');
    expect(within(nav).getByRole('button', { name: 'Thuật ngữ & Văn phong' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(nav).getByRole('button', { name: 'Model API' })).toHaveAttribute('aria-pressed', 'false');
    expect(within(nav).getByRole('button', { name: 'Tác vụ' })).toHaveAttribute('aria-pressed', 'false');
    expect(within(nav).getByRole('button', { name: 'Trạng thái' })).toHaveAttribute('aria-pressed', 'false');
    expect(within(nav).getByRole('button', { name: 'Xuất file' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('requests active view changes from workflow navigation', async () => {
    const { onViewChange } = renderShell('workbench');

    await userEvent.click(screen.getAllByRole('button', { name: 'Model API' })[0]);

    expect(onViewChange).toHaveBeenCalledWith('providers');
  });

  it('keeps mobile workflow navigation wired to the same routes', async () => {
    const { onOpenImport, onViewChange } = renderShell('workbench');
    const mobileNav = screen.getByRole('navigation', { name: 'Quy trình di động' });

    await userEvent.click(within(mobileNav).getByRole('button', { name: 'Thư viện' }));
    await userEvent.click(within(mobileNav).getByRole('button', { name: 'Raw chưa dịch' }));
    await userEvent.click(within(mobileNav).getByRole('button', { name: 'Đọc truyện' }));
    await userEvent.click(within(mobileNav).getByRole('button', { name: 'Tác vụ' }));
    await userEvent.click(within(mobileNav).getByRole('button', { name: 'Trạng thái' }));
    await userEvent.click(within(mobileNav).getByRole('button', { name: 'Nguồn truyện' }));
    await userEvent.click(within(mobileNav).getByRole('button', { name: 'Xuất file' }));
    await userEvent.click(screen.getByRole('button', { name: 'Nhập' }));

    expect(onViewChange).toHaveBeenCalledWith('library');
    expect(onViewChange).toHaveBeenCalledWith('raw');
    expect(onViewChange).toHaveBeenCalledWith('reader');
    expect(onViewChange).toHaveBeenCalledWith('jobs');
    expect(onViewChange).toHaveBeenCalledWith('status');
    expect(onViewChange).toHaveBeenCalledWith('sources');
    expect(onViewChange).toHaveBeenCalledWith('export');
    expect(onOpenImport).toHaveBeenCalledTimes(1);
  });

  it('marks the active workflow view for immersive reader layout', () => {
    renderShell('reader');

    expect(screen.getByRole('main')).toHaveAttribute('data-active-view', 'reader');
  });

  it('shows real API status labels and wires footer shortcuts', async () => {
    const { onViewChange } = renderShell('workbench');

    expect(screen.getByRole('region', { name: 'API Status' })).toHaveTextContent('Hoạt động tốt');

    await userEvent.click(screen.getByRole('button', { name: 'Mở trạng thái hệ thống' }));
    await userEvent.click(screen.getByRole('button', { name: 'Mở tác vụ' }));
    await userEvent.click(screen.getByRole('button', { name: 'Mở Model API' }));

    expect(onViewChange).toHaveBeenCalledWith('status');
    expect(onViewChange).toHaveBeenCalledWith('jobs');
    expect(onViewChange).toHaveBeenCalledWith('providers');
  });
});
