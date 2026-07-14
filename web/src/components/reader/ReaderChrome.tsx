import { ArrowLeft, Bookmark, List, MoreVertical, Search, Type } from 'lucide-react';
import ReaderProgressBar from './ReaderProgressBar';

export type ReaderChromeTitle = {
  bookTitle: string;
  chapterTitle: string;
  cover?: {
    alt: string;
    src: string;
  };
  offlineAvailable?: boolean;
};

export type ReaderChromeNavigation = {
  bookProgressLabel: string;
  canGoNext: boolean;
  canGoPrevious: boolean;
  chapterCount: number;
  chapterNumber: number | null;
  chapterPositionLabel: string;
  locationLabel: string;
  progressLabel: string;
  progressPercent: number;
  timeRemainingLabel: string;
  wordsRemainingLabel: string;
};

export type ReaderChromeActions = {
  bookmarked: boolean;
  onExit(): void;
  onNext(): void;
  onOpenSearch(): void;
  onOpenSettings(): void;
  onOpenToc(): void;
  onPrevious(): void;
  onToggleBookmark(): void;
  onToggleMore(): void;
};

export type ReaderChromeProps = {
  actions: ReaderChromeActions;
  navigation: ReaderChromeNavigation;
  title: ReaderChromeTitle;
  visible: boolean;
};

export type ReaderChromeTopProps = ReaderChromeProps;

export function ReaderChromeTop({ actions, navigation, title, visible }: ReaderChromeTopProps) {
  const chaptersAvailable = navigation.chapterCount > 0;

  return (
    <>
      <header className="reader-top-bar" data-visible={visible}>
        <button
          aria-label="Quay lại thư viện"
          className="reader-icon-button reader-back-button"
          onClick={actions.onExit}
          title="Quay lại thư viện"
          type="button"
        >
          <ArrowLeft aria-hidden="true" size={22} />
          <span>Thư viện</span>
        </button>

        <button
          aria-label="Mở mục lục từ thanh trên"
          className="reader-icon-button"
          disabled={!chaptersAvailable}
          onClick={actions.onOpenToc}
          title="Mục lục"
          type="button"
        >
          <List aria-hidden="true" size={22} />
        </button>

        <div className="reader-top-title">
          {title.cover ? (
            <img
              alt={title.cover.alt}
              className="reader-top-cover"
              src={title.cover.src}
            />
          ) : null}
          <div>
            <strong>{title.bookTitle}</strong>
            <span>{title.chapterTitle}</span>
          </div>
          {title.offlineAvailable ? (
            <span aria-label="Có sẵn offline" className="reader-offline-badge">Offline</span>
          ) : null}
        </div>

        <button
          aria-label="Tìm kiếm"
          className="reader-icon-button"
          disabled={!chaptersAvailable}
          onClick={actions.onOpenSearch}
          title="Tìm kiếm"
          type="button"
        >
          <Search aria-hidden="true" size={22} />
        </button>

        <button
          aria-label="Đánh dấu trang"
          aria-pressed={actions.bookmarked}
          className="reader-icon-button"
          onClick={actions.onToggleBookmark}
          title="Đánh dấu trang"
          type="button"
        >
          <Bookmark aria-hidden="true" fill={actions.bookmarked ? 'currentColor' : 'none'} size={22} />
        </button>

        <button
          aria-label="Cài đặt chữ"
          className="reader-icon-button reader-type-button"
          onClick={actions.onOpenSettings}
          title="Cài đặt chữ"
          type="button"
        >
          <Type aria-hidden="true" size={18} />
          <span>Aa</span>
        </button>

        <button
          aria-label="Thêm tùy chọn"
          className="reader-icon-button"
          onClick={actions.onToggleMore}
          title="Thêm tùy chọn"
          type="button"
        >
          <MoreVertical aria-hidden="true" size={22} />
        </button>
      </header>

      <div aria-label="Điều hướng chương nhanh" className="reader-reference-chapter-nav" data-visible={visible}>
        <button disabled={!navigation.canGoPrevious} onClick={actions.onPrevious} type="button">‹ Chương trước</button>
        <button disabled={!chaptersAvailable} onClick={actions.onOpenToc} type="button">
          Chương {navigation.chapterNumber ?? '-'} / {Math.max(navigation.chapterCount, 1).toLocaleString('vi-VN')}
        </button>
        <button disabled={!navigation.canGoNext} onClick={actions.onNext} type="button">Chương sau ›</button>
      </div>
    </>
  );
}

export type ReaderChromeBottomProps = Pick<ReaderChromeProps, 'actions' | 'navigation' | 'visible'>;

export function ReaderChromeBottom({ actions, navigation, visible }: ReaderChromeBottomProps) {
  const chaptersAvailable = navigation.chapterCount > 0;

  return (
    <ReaderProgressBar
      bookProgressLabel={navigation.bookProgressLabel}
      canGoNext={navigation.canGoNext}
      canGoPrevious={navigation.canGoPrevious}
      chapterPositionLabel={navigation.chapterPositionLabel}
      locationLabel={navigation.locationLabel}
      progressLabel={navigation.progressLabel}
      progressPercent={navigation.progressPercent}
      timeRemainingLabel={navigation.timeRemainingLabel}
      visible={visible}
      wordsRemainingLabel={navigation.wordsRemainingLabel}
      onNext={actions.onNext}
      onOpenToc={chaptersAvailable ? actions.onOpenToc : undefined}
      onPrevious={actions.onPrevious}
    />
  );
}

export default function ReaderChrome(props: ReaderChromeProps) {
  return (
    <>
      <ReaderChromeTop {...props} />
      <ReaderChromeBottom actions={props.actions} navigation={props.navigation} visible={props.visible} />
    </>
  );
}
