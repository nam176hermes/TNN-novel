import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ReaderAiPanel from './ReaderAiPanel';

describe('ReaderAiPanel', () => {
  afterEach(() => {
    cleanup();
  });

  it('does not render when closed', () => {
    render(
      <ReaderAiPanel
        error=""
        loading={false}
        mode="explain"
        open={false}
        result={null}
        selectedText="筑基"
        spoilerMode="no_spoiler"
        onClose={vi.fn()}
        onRetry={vi.fn()}
        onSpoilerModeChange={vi.fn()}
      />,
    );

    expect(screen.queryByRole('dialog', { name: 'AI đọc truyện' })).not.toBeInTheDocument();
  });

  it('shows explanation terms and changes spoiler mode', async () => {
    const onSpoilerModeChange = vi.fn();
    render(
      <ReaderAiPanel
        error=""
        loading={false}
        mode="translate_term"
        open
        result={{
          explanation: '筑基 là cảnh giới đặt nền móng tu luyện.',
          terms: [{ source: '筑基', target: 'Trúc Cơ', note: 'cảnh giới tu luyện' }],
        }}
        selectedText="筑基"
        spoilerMode="no_spoiler"
        onClose={vi.fn()}
        onRetry={vi.fn()}
        onSpoilerModeChange={onSpoilerModeChange}
      />,
    );

    const panel = screen.getByRole('dialog', { name: 'AI đọc truyện' });
    expect(within(panel).getByRole('heading', { name: /Dịch thuật ngữ/ })).toBeInTheDocument();
    expect(within(panel).getByText('筑基 là cảnh giới đặt nền móng tu luyện.')).toBeInTheDocument();
    expect(within(panel).getByText('Trúc Cơ')).toBeInTheDocument();

    await userEvent.click(within(panel).getByRole('button', { name: 'Cho phép spoiler' }));
    expect(onSpoilerModeChange).toHaveBeenCalledWith('allow_spoiler');
  });

  it('shows loading and retry on error', async () => {
    const onRetry = vi.fn();
    const { rerender } = render(
      <ReaderAiPanel
        error=""
        loading
        mode="explain"
        open
        result={null}
        selectedText="Hàn Lập"
        spoilerMode="no_spoiler"
        onClose={vi.fn()}
        onRetry={onRetry}
        onSpoilerModeChange={vi.fn()}
      />,
    );
    expect(screen.getByText('Đang giải thích...')).toBeInTheDocument();

    rerender(
      <ReaderAiPanel
        error="Failed to explain selected text"
        loading={false}
        mode="explain"
        open
        result={null}
        selectedText="Hàn Lập"
        spoilerMode="no_spoiler"
        onClose={vi.fn()}
        onRetry={onRetry}
        onSpoilerModeChange={vi.fn()}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: /Thử lại/ }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
