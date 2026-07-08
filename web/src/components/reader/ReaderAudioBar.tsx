import { useEffect, useRef, useState } from 'react';
import { Clock, Download, Gauge, RotateCcw, RotateCw, Volume2, X } from 'lucide-react';

export type ReaderAudioBarProps = {
  autoNext: boolean;
  chapterTitle: string;
  downloadUrl: string;
  hasNextChapter: boolean;
  open: boolean;
  resumeOnSourceChange?: boolean;
  streamUrl: string;
  onAutoNextChange(value: boolean): void;
  onClose(): void;
  onNextChapter(): void;
};

const sleepTimerOptions = [
  { minutes: 0, label: 'Không hẹn giờ' },
  { minutes: 15, label: '15 phút' },
  { minutes: 30, label: '30 phút' },
  { minutes: 60, label: '60 phút' },
];

const playbackRateOptions = [
  { rate: 0.85, label: '0.85x' },
  { rate: 1, label: '1.0x' },
  { rate: 1.15, label: '1.15x' },
  { rate: 1.25, label: '1.25x' },
  { rate: 1.5, label: '1.5x' },
  { rate: 2, label: '2.0x' },
];

const AUDIO_PLAYBACK_RATE_STORAGE_KEY = 'novel-reader-audio-playback-rate-v1';
const AUDIO_POSITION_STORAGE_KEY = 'novel-reader-audio-position-v1';
const SKIP_BACK_SECONDS = 15;
const SKIP_FORWARD_SECONDS = 30;
const playbackRates = new Set(playbackRateOptions.map((option) => option.rate));

function loadPlaybackRate(): number {
  try {
    const savedRate = Number(window.localStorage.getItem(AUDIO_PLAYBACK_RATE_STORAGE_KEY));
    return playbackRates.has(savedRate) ? savedRate : 1;
  } catch {
    return 1;
  }
}

function savePlaybackRate(rate: number): void {
  if (!playbackRates.has(rate)) return;
  try {
    window.localStorage.setItem(AUDIO_PLAYBACK_RATE_STORAGE_KEY, String(rate));
  } catch {
    // Audio playback still works when browser storage is unavailable.
  }
}

function audioPositionKey(streamUrl: string): string {
  return streamUrl.trim();
}

function loadAudioPositions(): Record<string, number> {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(AUDIO_POSITION_STORAGE_KEY) ?? '{}') as unknown;
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    return Object.fromEntries(
      Object.entries(parsed)
        .filter((entry): entry is [string, number] => (
          typeof entry[0] === 'string'
          && typeof entry[1] === 'number'
          && Number.isFinite(entry[1])
          && entry[1] > 0
        )),
    );
  } catch {
    return {};
  }
}

function loadAudioPosition(streamUrl: string): number {
  const key = audioPositionKey(streamUrl);
  if (!key) return 0;
  return loadAudioPositions()[key] ?? 0;
}

function saveAudioPosition(streamUrl: string, currentTime: number, duration: number): void {
  const key = audioPositionKey(streamUrl);
  if (!key || !Number.isFinite(currentTime) || currentTime < 1) return;
  if (Number.isFinite(duration) && duration > 0 && duration - currentTime < 3) return;
  try {
    window.localStorage.setItem(AUDIO_POSITION_STORAGE_KEY, JSON.stringify({
      ...loadAudioPositions(),
      [key]: Math.floor(currentTime),
    }));
  } catch {
    // Audiobook playback continues when browser storage is unavailable.
  }
}

function clearAudioPosition(streamUrl: string): void {
  const key = audioPositionKey(streamUrl);
  if (!key) return;
  try {
    const positions = loadAudioPositions();
    delete positions[key];
    window.localStorage.setItem(AUDIO_POSITION_STORAGE_KEY, JSON.stringify(positions));
  } catch {
    // Ignore storage failures while closing or advancing audio.
  }
}

function boundedSeekTime(currentTime: number, deltaSeconds: number, duration: number): number {
  const safeCurrentTime = Number.isFinite(currentTime) ? currentTime : 0;
  const nextTime = Math.max(0, Math.round(safeCurrentTime + deltaSeconds));
  if (Number.isFinite(duration) && duration > 0) {
    return Math.min(duration, nextTime);
  }
  return nextTime;
}

function formatAudioClock(seconds: number): string {
  const safeSeconds = Math.max(0, Math.floor(Number.isFinite(seconds) ? seconds : 0));
  const hours = Math.floor(safeSeconds / 3600);
  const minutes = Math.floor((safeSeconds % 3600) / 60);
  const remainder = safeSeconds % 60;
  const paddedMinutes = hours > 0 ? String(minutes).padStart(2, '0') : String(minutes);
  const paddedSeconds = String(remainder).padStart(2, '0');
  return hours > 0 ? `${hours}:${paddedMinutes}:${paddedSeconds}` : `${paddedMinutes}:${paddedSeconds}`;
}

export default function ReaderAudioBar({
  autoNext,
  chapterTitle,
  downloadUrl,
  hasNextChapter,
  open,
  resumeOnSourceChange = false,
  streamUrl,
  onAutoNextChange,
  onClose,
  onNextChapter,
}: ReaderAudioBarProps) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const previousStreamUrlRef = useRef(streamUrl);
  const [audioProgress, setAudioProgress] = useState({ currentTime: 0, duration: 0 });
  const [sleepMinutes, setSleepMinutes] = useState(0);
  const [playbackRate, setPlaybackRate] = useState(loadPlaybackRate);
  const activeSleepLabel = sleepMinutes > 0
    ? sleepTimerOptions.find((option) => option.minutes === sleepMinutes)?.label ?? `${sleepMinutes} phút`
    : '';
  const audioProgressLabel = audioProgress.duration > 0
    ? `${formatAudioClock(audioProgress.currentTime)} / ${formatAudioClock(audioProgress.duration)} · còn ${formatAudioClock(audioProgress.duration - audioProgress.currentTime)} · ${Math.round((audioProgress.currentTime / audioProgress.duration) * 100)}%`
    : '';

  useEffect(() => {
    if (!open || sleepMinutes <= 0) return undefined;
    const timeout = window.setTimeout(() => {
      audioRef.current?.pause();
      setSleepMinutes(0);
    }, sleepMinutes * 60 * 1000);
    return () => window.clearTimeout(timeout);
  }, [open, sleepMinutes]);

  useEffect(() => {
    const previousStreamUrl = previousStreamUrlRef.current;
    previousStreamUrlRef.current = streamUrl;
    if (!open || !resumeOnSourceChange || !previousStreamUrl || previousStreamUrl === streamUrl) return;
    void audioRef.current?.play().catch(() => {
      // Browsers may block autoplay; the visible audio controls remain available.
    });
  }, [open, resumeOnSourceChange, streamUrl]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!open || !audio) return;
    audio.playbackRate = playbackRate;
    savePlaybackRate(playbackRate);
  }, [open, playbackRate, streamUrl]);

  useEffect(() => {
    setAudioProgress({ currentTime: 0, duration: 0 });
  }, [streamUrl]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!open || !audio) return;
    const savedPosition = loadAudioPosition(streamUrl);
    if (savedPosition <= 0) return;
    if (Number.isFinite(audio.duration) && audio.duration > 0 && savedPosition >= audio.duration - 3) return;
    audio.currentTime = savedPosition;
    setAudioProgress({
      currentTime: savedPosition,
      duration: Number.isFinite(audio.duration) && audio.duration > 0 ? audio.duration : 0,
    });
  }, [open, streamUrl]);

  if (!open) return null;

  function handleAudioEnded(): void {
    clearAudioPosition(streamUrl);
    if (autoNext && hasNextChapter) {
      onNextChapter();
    }
  }

  function handleTimeUpdate(): void {
    const audio = audioRef.current;
    if (!audio) return;
    setAudioProgress({
      currentTime: Number.isFinite(audio.currentTime) ? audio.currentTime : 0,
      duration: Number.isFinite(audio.duration) && audio.duration > 0 ? audio.duration : 0,
    });
    saveAudioPosition(streamUrl, audio.currentTime, audio.duration);
  }

  function handleAudioMetadata(): void {
    const audio = audioRef.current;
    if (!audio) return;
    setAudioProgress({
      currentTime: Number.isFinite(audio.currentTime) ? audio.currentTime : 0,
      duration: Number.isFinite(audio.duration) && audio.duration > 0 ? audio.duration : 0,
    });
  }

  function seekAudio(deltaSeconds: number): void {
    const audio = audioRef.current;
    if (!audio) return;
    const nextTime = boundedSeekTime(audio.currentTime, deltaSeconds, audio.duration);
    audio.currentTime = nextTime;
    setAudioProgress({
      currentTime: nextTime,
      duration: Number.isFinite(audio.duration) && audio.duration > 0 ? audio.duration : 0,
    });
    if (nextTime < 1) {
      clearAudioPosition(streamUrl);
      return;
    }
    saveAudioPosition(streamUrl, nextTime, audio.duration);
  }

  return (
    <section aria-label="Audio chương" className="reader-audio-bar">
      <div>
        <Volume2 aria-hidden="true" size={18} />
        <span>{chapterTitle}</span>
      </div>
      <audio
        aria-label={`Audio ${chapterTitle}`}
        controls
        crossOrigin="use-credentials"
        onDurationChange={handleAudioMetadata}
        onEnded={handleAudioEnded}
        onLoadedMetadata={handleAudioMetadata}
        onTimeUpdate={handleTimeUpdate}
        preload="metadata"
        ref={audioRef}
        src={streamUrl}
      />
      <div aria-label="Cài đặt audiobook" className="reader-audio-controls">
        <button
          aria-label="Lùi 15 giây"
          className="reader-audio-seek"
          onClick={() => seekAudio(-SKIP_BACK_SECONDS)}
          title="Lùi 15 giây"
          type="button"
        >
          <RotateCcw aria-hidden="true" size={14} />
          <span>-15s</span>
        </button>
        <button
          aria-label="Tiến 30 giây"
          className="reader-audio-seek"
          onClick={() => seekAudio(SKIP_FORWARD_SECONDS)}
          title="Tiến 30 giây"
          type="button"
        >
          <RotateCw aria-hidden="true" size={14} />
          <span>+30s</span>
        </button>
        <label className="reader-audio-toggle">
          <input
            aria-label="Tự phát chương kế tiếp"
            checked={autoNext}
            disabled={!hasNextChapter}
            onChange={(event) => onAutoNextChange(event.target.checked)}
            type="checkbox"
          />
          <span>Tự phát</span>
        </label>
        <label className="reader-audio-sleep">
          <Clock aria-hidden="true" size={14} />
          <select
            aria-label="Hẹn giờ ngủ"
            onChange={(event) => setSleepMinutes(Number(event.target.value))}
            value={sleepMinutes}
          >
            {sleepTimerOptions.map((option) => (
              <option key={option.minutes} value={option.minutes}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        {activeSleepLabel ? <span className="reader-audio-sleep-status">Tắt sau {activeSleepLabel}</span> : null}
        {audioProgressLabel ? (
          <span aria-live="polite" className="reader-audio-progress-status">
            {audioProgressLabel}
          </span>
        ) : null}
        <label className="reader-audio-speed">
          <Gauge aria-hidden="true" size={14} />
          <select
            aria-label="Tốc độ đọc audio"
            onChange={(event) => setPlaybackRate(Number(event.target.value))}
            value={playbackRate}
          >
            {playbackRateOptions.map((option) => (
              <option key={option.rate} value={option.rate}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <a className="reader-audio-download" href={downloadUrl}>
        <Download aria-hidden="true" size={16} />
        MP3
      </a>
      <button
        aria-label="Đóng audio"
        className="reader-icon-button"
        onClick={onClose}
        title="Đóng audio"
        type="button"
      >
        <X aria-hidden="true" size={18} />
      </button>
    </section>
  );
}
