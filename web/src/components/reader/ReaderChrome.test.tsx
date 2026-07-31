import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ReaderChrome, { type ReaderChromeProps } from './ReaderChrome';

function chromeProps(overrides: Partial<ReaderChromeProps> = {}): ReaderChromeProps {
  return {
    visible: true,
    title: {
      bookTitle: 'Phàm Nhân Tu Tiên',
      chapterTitle: 'Chương 2: Thanh Ngưu trấn',
      cover: {
        alt: 'Bìa Phàm Nhân Tu Tiên',
        src: '/covers/pham-nhan.png',
      },
      offlineAvailable: true,
    },
    navigation: {
      bookProgressLabel: 'Đã đọc 33% truyện',
      canGoNext: true,
      canGoPrevious: true,
      chapterCount: 3,
      chapterNumber: 2,
      chapterPositionLabel: '2 / 3',
      locationLabel: 'Trang 1/2',
      progressLabel: '33% chương',
      progressPercent: 33,
      timeRemainingLabel: '2 phút còn lại',
      wordsRemainingLabel: '420 từ còn lại',
    },
    actions: {
      bookmarked: false,
      onExit: vi.fn(),
      onNext: vi.fn(),
      onOpenSearch: vi.fn(),
      onOpenSettings: vi.fn(),
      onOpenToc: vi.fn(),
      onPrevious: vi.fn(),
      onToggleBookmark: vi.fn(),
      onToggleMore: vi.fn(),
    },
    ...overrides,
  };
}

describe('ReaderChrome', () => {
  afterEach(cleanup);

  it('renders the existing title and 44px semantic control contracts and routes callbacks', async () => {
    const props = chromeProps();
    const { container } = render(<ReaderChrome {...props} />);

    const topBar = container.querySelector('.reader-top-bar');
    const title = container.querySelector('.reader-top-title');
    const quickNavigation = screen.getByLabelText('Điều hướng chương nhanh');
    const bottomBar = container.querySelector('.reader-bottom-bar');

    expect(topBar).toHaveAttribute('data-visible', 'true');
    expect(title).toHaveTextContent('Phàm Nhân Tu Tiên');
    expect(title).toHaveTextContent('Chương 2: Thanh Ngưu trấn');
    expect(title?.querySelector('strong')).toHaveTextContent('Phàm Nhân Tu Tiên');
    expect(title?.querySelector('div')).toBeInTheDocument();
    expect(screen.getByAltText('Bìa Phàm Nhân Tu Tiên')).toHaveClass('reader-top-cover');
    expect(screen.getByLabelText('Có sẵn offline')).toHaveClass('reader-offline-badge');
    expect(quickNavigation).toHaveAttribute('data-visible', 'true');
    expect(bottomBar).toHaveAttribute('data-visible', 'true');

    const exitButton = screen.getByRole('button', { name: 'Quay lại thư viện' });
    const topTocButton = screen.getByRole('button', { name: 'Mở mục lục từ thanh trên' });
    const settingsButton = screen.getByRole('button', { name: 'Cài đặt chữ' });
    expect(exitButton).toHaveTextContent('Thư viện');
    expect(exitButton).toHaveClass('reader-icon-button', 'reader-back-button');
    expect(topTocButton).toHaveClass('reader-icon-button');
    expect(settingsButton).toHaveClass('reader-icon-button', 'reader-type-button');

    const quickPrevious = within(quickNavigation).getByRole('button', { name: '‹ Chương trước' });
    const quickCurrent = within(quickNavigation).getByRole('button', { name: 'Chương 2 / 3' });
    const quickNext = within(quickNavigation).getByRole('button', { name: 'Chương sau ›' });
    expect(quickPrevious).toBeEnabled();
    expect(quickCurrent).toBeEnabled();
    expect(quickNext).toBeEnabled();

    const bottomPrevious = screen.getByRole('button', { name: 'Chương trước' });
    const bottomCurrent = screen.getByRole('button', { name: 'Mục lục' });
    const bottomNext = screen.getByRole('button', { name: 'Chương sau' });
    expect(bottomPrevious).toHaveClass('reader-chapter-nav-button');
    expect(bottomCurrent).toHaveClass('reader-progress-panel');
    expect(bottomNext).toHaveClass('reader-chapter-nav-button');

    await userEvent.click(exitButton);
    await userEvent.click(topTocButton);
    await userEvent.click(settingsButton);
    await userEvent.click(quickPrevious);
    await userEvent.click(quickCurrent);
    await userEvent.click(quickNext);
    await userEvent.click(bottomPrevious);
    await userEvent.click(bottomCurrent);
    await userEvent.click(bottomNext);

    expect(props.actions.onExit).toHaveBeenCalledOnce();
    expect(props.actions.onOpenToc).toHaveBeenCalledTimes(3);
    expect(props.actions.onOpenSettings).toHaveBeenCalledOnce();
    expect(props.actions.onPrevious).toHaveBeenCalledTimes(2);
    expect(props.actions.onNext).toHaveBeenCalledTimes(2);
  });

  it('hides immersive chrome and disables chapter boundaries and unavailable chapter actions', () => {
    const props = chromeProps({
      visible: false,
      title: {
        bookTitle: 'Đọc truyện',
        chapterTitle: 'Chưa chọn chương',
      },
      navigation: {
        bookProgressLabel: 'Đã đọc 0% truyện',
        canGoNext: false,
        canGoPrevious: false,
        chapterCount: 0,
        chapterNumber: null,
        chapterPositionLabel: '1 / 1',
        locationLabel: 'Chưa có vị trí',
        progressLabel: '0% chương',
        progressPercent: 0,
        timeRemainingLabel: '0 phút còn lại',
        wordsRemainingLabel: '0 từ còn lại',
      },
    });
    const { container } = render(<ReaderChrome {...props} />);

    expect(container.querySelector('.reader-top-bar')).toHaveAttribute('data-visible', 'false');
    expect(screen.getByLabelText('Điều hướng chương nhanh')).toHaveAttribute('data-visible', 'false');
    expect(container.querySelector('.reader-bottom-bar')).toHaveAttribute('data-visible', 'false');
    expect(screen.getByRole('button', { name: 'Mở mục lục từ thanh trên' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Tìm kiếm' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '‹ Chương trước' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Chương - / 1' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Chương sau ›' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Chương trước' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Mục lục' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Chương sau' })).toBeDisabled();
  });
});
