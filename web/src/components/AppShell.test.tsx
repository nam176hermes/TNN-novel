import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import AppShell from './AppShell';

const props = {
  activeBookId: 1,
  backendError: '',
  backendLoading: false,
  books: [
    {
      id: 1,
      title: 'Live Book',
      translated: 0,
      audio: 0,
      failed: 0,
      total: 1,
    },
  ],
  chapters: [
    {
      id: 10,
      book_id: 1,
      chapter_number: 1,
      title: 'Live Chapter',
      status: 'cleaned',
      audio_path: null,
    },
  ],
  importOpen: false,
  importPanel: <section>Import panel</section>,
  insights: <section aria-label="Operator insights">Usage panel</section>,
  onCloseImport: vi.fn(),
  onLogout: vi.fn(),
  onOpenImport: vi.fn(),
  onSelectBook: vi.fn(),
  onSelectChapter: vi.fn(),
  selectedChapterId: 10,
  workbench: <section aria-label="Workbench content">Workbench</section>,
};

describe('AppShell', () => {
  afterEach(() => {
    cleanup();
  });

  it('switches mobile panel tabs with accessible selected state', async () => {
    render(<AppShell {...props} />);

    const workspace = screen.getByLabelText('Translator workspace');
    const tabs = screen.getByRole('tablist', { name: 'Mobile panels' });

    expect(workspace).toHaveAttribute('data-mobile-panel', 'editor');
    expect(within(tabs).getByRole('tab', { name: 'Editor' })).toHaveAttribute('aria-selected', 'true');

    await userEvent.click(within(tabs).getByRole('tab', { name: 'QA' }));

    expect(workspace).toHaveAttribute('data-mobile-panel', 'qa');
    expect(within(tabs).getByRole('tab', { name: 'QA' })).toHaveAttribute('aria-selected', 'true');
    expect(within(tabs).getByRole('tab', { name: 'Editor' })).toHaveAttribute('aria-selected', 'false');

    await userEvent.click(within(tabs).getByRole('tab', { name: 'Assist' }));

    expect(workspace).toHaveAttribute('data-mobile-panel', 'assist');
    expect(within(tabs).getByRole('tab', { name: 'Assist' })).toHaveAttribute('aria-selected', 'true');
  });

  it('exposes a logout action from the authenticated shell', async () => {
    const onLogout = vi.fn();
    render(<AppShell {...props} onLogout={onLogout} />);

    await userEvent.click(screen.getByRole('button', { name: 'Logout' }));

    expect(onLogout).toHaveBeenCalledOnce();
  });
});
