import { ChevronLeft, ChevronRight } from 'lucide-react';

export type ReaderProgressBarProps = {
  bookProgressLabel: string;
  canGoNext: boolean;
  canGoPrevious: boolean;
  locationLabel: string;
  progressLabel: string;
  progressPercent: number;
  timeRemainingLabel: string;
  visible?: boolean;
  wordsRemainingLabel: string;
  onNext(): void;
  onPrevious(): void;
};

export default function ReaderProgressBar({
  bookProgressLabel,
  canGoNext,
  canGoPrevious,
  locationLabel,
  progressLabel,
  progressPercent,
  timeRemainingLabel,
  visible = true,
  wordsRemainingLabel,
  onNext,
  onPrevious,
}: ReaderProgressBarProps) {
  const statsLabel = `${bookProgressLabel} · ${wordsRemainingLabel} · ${timeRemainingLabel}`;

  return (
    <footer className="reader-bottom-bar" data-visible={visible}>
      <button
        aria-label="Chương trước"
        className="reader-icon-button"
        disabled={!canGoPrevious}
        onClick={onPrevious}
        title="Chương trước"
        type="button"
      >
        <ChevronLeft aria-hidden="true" size={22} />
      </button>
      <div className="reader-progress-panel">
        <div className="reader-progress-meta">
          <span>{locationLabel}</span>
          <span>{progressLabel}</span>
          <span>{progressPercent}%</span>
        </div>
        <progress
          aria-label="Tiến độ đọc"
          aria-valuetext={`${locationLabel} · ${progressLabel} · ${statsLabel}`}
          max={100}
          value={progressPercent}
        />
        <div aria-label="Thống kê đọc" className="reader-progress-stats">
          <span>{bookProgressLabel}</span>
          <span>{wordsRemainingLabel}</span>
          <span>{timeRemainingLabel}</span>
        </div>
      </div>
      <button
        aria-label="Chương sau"
        className="reader-icon-button"
        disabled={!canGoNext}
        onClick={onNext}
        title="Chương sau"
        type="button"
      >
        <ChevronRight aria-hidden="true" size={22} />
      </button>
    </footer>
  );
}
