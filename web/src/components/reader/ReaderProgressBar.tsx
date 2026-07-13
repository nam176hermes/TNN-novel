import { ChevronLeft, ChevronRight, List } from 'lucide-react';

export type ReaderProgressBarProps = {
  bookProgressLabel: string;
  canGoNext: boolean;
  canGoPrevious: boolean;
  chapterPositionLabel?: string;
  locationLabel: string;
  progressLabel: string;
  progressPercent: number;
  timeRemainingLabel: string;
  visible?: boolean;
  wordsRemainingLabel: string;
  onNext(): void;
  onOpenToc?(): void;
  onPrevious(): void;
};

export default function ReaderProgressBar({
  bookProgressLabel,
  canGoNext,
  canGoPrevious,
  chapterPositionLabel,
  locationLabel,
  progressLabel,
  progressPercent,
  timeRemainingLabel,
  visible = true,
  wordsRemainingLabel,
  onNext,
  onOpenToc,
  onPrevious,
}: ReaderProgressBarProps) {
  const statsLabel = `${bookProgressLabel} · ${wordsRemainingLabel} · ${timeRemainingLabel}`;

  return (
    <footer className="reader-bottom-bar" data-visible={visible}>
      <span className="sr-only">{locationLabel}</span>
      <span className="sr-only">{progressLabel}</span>
      <span className="sr-only">{bookProgressLabel}</span>
      <span className="sr-only">{wordsRemainingLabel}</span>
      <span className="sr-only">{timeRemainingLabel}</span>
      <button
        aria-label="Chương trước"
        className="reader-chapter-nav-button"
        disabled={!canGoPrevious}
        onClick={onPrevious}
        title="Chương trước"
        type="button"
      >
        <ChevronLeft aria-hidden="true" size={20} />
        <span>Chương trước</span>
      </button>
      <button
        aria-label="Mục lục"
        className="reader-progress-panel"
        disabled={!onOpenToc}
        onClick={onOpenToc}
        type="button"
      >
        <span className="reader-progress-position">
          <List aria-hidden="true" size={18} />
          {chapterPositionLabel || locationLabel}
        </span>
        <progress
          aria-label="Tiến độ đọc"
          aria-valuetext={`${locationLabel} · ${progressLabel} · ${statsLabel}`}
          max={100}
          value={progressPercent}
        />
      </button>
      <button
        aria-label="Chương sau"
        className="reader-chapter-nav-button"
        disabled={!canGoNext}
        onClick={onNext}
        title="Chương sau"
        type="button"
      >
        <ChevronRight aria-hidden="true" size={20} />
        <span>Chương sau</span>
      </button>
    </footer>
  );
}
