import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ReaderAudioBar from './ReaderAudioBar';

function renderAudioBar(overrides: Partial<Parameters<typeof ReaderAudioBar>[0]> = {}) {
  const props = {
    autoNext: true,
    chapterTitle: 'Chương 2 · Thanh Ngưu trấn',
    downloadUrl: '/audio/ch2/download',
    hasNextChapter: true,
    open: true,
    streamUrl: '/audio/ch2',
    onAutoNextChange: vi.fn(),
    onClose: vi.fn(),
    onNextChapter: vi.fn(),
    ...overrides,
  };
  const result = render(<ReaderAudioBar {...props} />);
  return { ...props, ...result };
}

describe('ReaderAudioBar', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.useRealTimers();
    window.localStorage.clear();
  });

  it('moves to the next audiobook chapter when auto-next is enabled and audio ends', () => {
    const props = renderAudioBar();

    fireEvent.ended(screen.getByLabelText('Audio Chương 2 · Thanh Ngưu trấn'));

    expect(props.onNextChapter).toHaveBeenCalledTimes(1);
  });

  it('pauses playback when the sleep timer expires', () => {
    vi.useFakeTimers();
    const pause = vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {});
    renderAudioBar();

    fireEvent.change(screen.getByLabelText('Hẹn giờ ngủ'), { target: { value: '15' } });
    vi.advanceTimersByTime(15 * 60 * 1000);

    expect(pause).toHaveBeenCalledTimes(1);
  });

  it('shows the active sleep timer duration while listening', () => {
    renderAudioBar();

    fireEvent.change(screen.getByLabelText('Hẹn giờ ngủ'), { target: { value: '15' } });

    expect(screen.getByText('Tắt sau 15 phút')).toBeInTheDocument();
  });

  it('shows audiobook progress and remaining time while listening', () => {
    renderAudioBar();
    const audio = screen.getByLabelText('Audio Chương 2 · Thanh Ngưu trấn') as HTMLAudioElement;
    Object.defineProperty(audio, 'duration', { configurable: true, value: 180 });
    Object.defineProperty(audio, 'currentTime', { configurable: true, value: 90, writable: true });

    fireEvent.timeUpdate(audio);

    expect(screen.getByText('1:30 / 3:00 · còn 1:30 · 50%')).toBeInTheDocument();
  });

  it('changes audio playback speed for audiobook listening', () => {
    renderAudioBar();

    const audio = screen.getByLabelText('Audio Chương 2 · Thanh Ngưu trấn') as HTMLAudioElement;
    fireEvent.change(screen.getByLabelText('Tốc độ đọc audio'), { target: { value: '1.25' } });

    expect(audio.playbackRate).toBe(1.25);
  });

  it('skips audiobook playback backward and forward with safe bounds', () => {
    renderAudioBar();

    const audio = screen.getByLabelText('Audio Chương 2 · Thanh Ngưu trấn') as HTMLAudioElement;
    Object.defineProperty(audio, 'duration', { configurable: true, value: 60 });
    Object.defineProperty(audio, 'currentTime', { configurable: true, value: 20, writable: true });

    fireEvent.click(screen.getByRole('button', { name: 'Lùi 15 giây' }));
    expect(audio.currentTime).toBe(5);

    fireEvent.click(screen.getByRole('button', { name: 'Lùi 15 giây' }));
    expect(audio.currentTime).toBe(0);

    Object.defineProperty(audio, 'currentTime', { configurable: true, value: 45, writable: true });
    fireEvent.click(screen.getByRole('button', { name: 'Tiến 30 giây' }));
    expect(audio.currentTime).toBe(60);
  });

  it('remembers audiobook playback speed after reopening the player', () => {
    const { unmount } = renderAudioBar();

    fireEvent.change(screen.getByLabelText('Tốc độ đọc audio'), { target: { value: '1.5' } });
    unmount();
    renderAudioBar();

    expect(screen.getByLabelText('Tốc độ đọc audio')).toHaveValue('1.5');
    expect((screen.getByLabelText('Audio Chương 2 · Thanh Ngưu trấn') as HTMLAudioElement).playbackRate).toBe(1.5);
  });

  it('remembers chapter audio position after reopening the player', () => {
    const { unmount } = renderAudioBar();
    const audio = screen.getByLabelText('Audio Chương 2 · Thanh Ngưu trấn') as HTMLAudioElement;
    Object.defineProperty(audio, 'currentTime', { configurable: true, value: 42, writable: true });

    fireEvent.timeUpdate(audio);
    unmount();
    renderAudioBar();

    expect((screen.getByLabelText('Audio Chương 2 · Thanh Ngưu trấn') as HTMLAudioElement).currentTime).toBe(42);
  });

  it('clears saved chapter audio position when playback ends', () => {
    const { unmount } = renderAudioBar({ autoNext: false });
    const audio = screen.getByLabelText('Audio Chương 2 · Thanh Ngưu trấn') as HTMLAudioElement;
    Object.defineProperty(audio, 'currentTime', { configurable: true, value: 42, writable: true });

    fireEvent.timeUpdate(audio);
    fireEvent.ended(audio);
    unmount();
    renderAudioBar({ autoNext: false });

    expect((screen.getByLabelText('Audio Chương 2 · Thanh Ngưu trấn') as HTMLAudioElement).currentTime).toBe(0);
  });

  it('resumes playback when auto-next changes the audiobook source', async () => {
    const play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined);
    const props = {
      autoNext: true,
      chapterTitle: 'Chương 2 · Thanh Ngưu trấn',
      downloadUrl: '/audio/ch2/download',
      hasNextChapter: true,
      open: true,
      resumeOnSourceChange: true,
      streamUrl: '/audio/ch2',
      onAutoNextChange: vi.fn(),
      onClose: vi.fn(),
      onNextChapter: vi.fn(),
    };
    const { rerender } = render(<ReaderAudioBar {...props} />);

    expect(play).not.toHaveBeenCalled();

    rerender(
      <ReaderAudioBar
        {...props}
        chapterTitle="Chương 3 · Thất Huyền Môn"
        downloadUrl="/audio/ch3/download"
        streamUrl="/audio/ch3"
      />,
    );

    await waitFor(() => expect(play).toHaveBeenCalledTimes(1));
  });
});
