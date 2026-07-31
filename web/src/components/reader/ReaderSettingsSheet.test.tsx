import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import ReaderSettingsSheet from './ReaderSettingsSheet';
import type { ReaderSettings } from './types';

const settings: ReaderSettings = {
  characterSpacing: 0,
  fontFamily: 'serif',
  fontSize: 18,
  fontWeight: 400,
  fullscreen: false,
  instantMode: false,
  lineHeight: 1.9,
  marginScale: 1,
  paragraphSpacing: 1.05,
  readingMode: 'scroll',
  theme: 'light',
  width: 'medium',
};

describe('ReaderSettingsSheet', () => {
  it('does not render when closed', () => {
    render(
      <ReaderSettingsSheet
        open={false}
        settings={settings}
        onClose={vi.fn()}
        onUpdate={vi.fn()}
      />,
    );

    expect(screen.queryByRole('dialog', { name: 'Cài đặt đọc' })).not.toBeInTheDocument();
  });

  it('emits premium typography, layout, theme, and fullscreen patches', async () => {
    const onUpdate = vi.fn();
    render(
      <ReaderSettingsSheet
        open
        settings={settings}
        onClose={vi.fn()}
        onUpdate={onUpdate}
      />,
    );
    const sheet = screen.getByRole('dialog', { name: 'Cài đặt đọc' });

    await userEvent.click(within(sheet).getByRole('button', { name: 'Tối' }));
    expect(onUpdate).toHaveBeenCalledWith({ theme: 'dark' });

    await userEvent.click(within(sheet).getByRole('button', { name: 'E-ink' }));
    expect(onUpdate).toHaveBeenCalledWith({ theme: 'eink' });

    await userEvent.click(within(sheet).getByRole('button', { name: 'Tăng cỡ chữ' }));
    expect(onUpdate).toHaveBeenCalledWith({ fontSize: 19 });

    await userEvent.click(within(sheet).getByRole('button', { name: 'Giảm cỡ chữ' }));
    expect(onUpdate).toHaveBeenCalledWith({ fontSize: 17 });

    fireEvent.change(within(sheet).getByLabelText('Giãn đoạn'), { target: { value: '1.4' } });
    expect(onUpdate).toHaveBeenCalledWith({ paragraphSpacing: 1.4 });

    fireEvent.change(within(sheet).getByLabelText('Lề đọc'), { target: { value: '1.2' } });
    expect(onUpdate).toHaveBeenCalledWith({ marginScale: 1.2 });

    fireEvent.change(within(sheet).getByLabelText('Giãn chữ'), { target: { value: '0.35' } });
    expect(onUpdate).toHaveBeenCalledWith({ characterSpacing: 0.35 });

    fireEvent.change(within(sheet).getByLabelText('Độ đậm'), { target: { value: '550' } });
    expect(onUpdate).toHaveBeenCalledWith({ fontWeight: 550 });

    await userEvent.click(within(sheet).getByRole('checkbox', { name: 'Toàn màn hình' }));
    expect(onUpdate).toHaveBeenCalledWith({ fullscreen: true });
  });
});
