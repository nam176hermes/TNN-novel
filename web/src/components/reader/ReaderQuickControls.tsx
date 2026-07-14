import { BookOpenText, List, ScrollText, Type, Volume2 } from 'lucide-react';
import ReaderSettingsSheet, { type ReaderModeAvailability } from './ReaderSettingsSheet';
import type { ReaderSettings, ReaderTextMode } from './types';

export type ReaderQuickModeControls = ReaderModeAvailability & {
  value: ReaderTextMode;
  onChange(mode: ReaderTextMode): void;
};

export type ReaderQuickSettingsControls = {
  audioAvailable: boolean;
  audioBusy: boolean;
  autoScrollEnabled: boolean;
  canAutoScroll: boolean;
  open: boolean;
  value: ReaderSettings;
  onAudioAction(): void;
  onAutoScrollChange(enabled: boolean): void;
  onClose(): void;
  onOpen(): void;
  onToggleAutoScroll(): void;
  onUpdate(patch: Partial<ReaderSettings>): void;
};

export type ReaderQuickControlsProps = {
  modes: ReaderQuickModeControls;
  settings: ReaderQuickSettingsControls;
  visible: boolean;
  onOpenToc(): void;
};

export type ReaderTextModeSwitcherProps = Pick<ReaderQuickControlsProps, 'modes' | 'visible'>;

export function ReaderTextModeSwitcher({ modes, visible }: ReaderTextModeSwitcherProps) {
  return (
    <div aria-label="Chế độ nội dung" className="reader-text-mode-switcher" data-visible={visible} role="group">
      <button
        aria-pressed={modes.value === 'translation'}
        onClick={() => modes.onChange('translation')}
        type="button"
      >
        Bản dịch
      </button>
      <button
        aria-pressed={modes.value === 'raw'}
        disabled={!modes.rawAvailable}
        onClick={() => modes.onChange('raw')}
        title={modes.rawAvailable ? 'Đọc raw/source tiếng Trung' : 'Chương này chưa có raw/source text'}
        type="button"
      >
        Raw
      </button>
      <button
        aria-pressed={modes.value === 'split'}
        disabled={!modes.rawAvailable}
        onClick={() => modes.onChange('split')}
        title={modes.rawAvailable ? 'Đọc song song raw và bản dịch' : 'Chương này chưa có raw/source text'}
        type="button"
      >
        Song song
      </button>
      <button
        aria-pressed={modes.value === 'raw-collapsed'}
        disabled={!modes.rawAvailable}
        onClick={() => modes.onChange('raw-collapsed')}
        title={modes.rawAvailable ? 'Đọc bản dịch và mở raw từng đoạn' : 'Chương này chưa có raw/source text'}
        type="button"
      >
        Raw gọn
      </button>
      <button
        aria-pressed={modes.value === 'qa-overlay'}
        onClick={() => modes.onChange('qa-overlay')}
        title="Hiện cảnh báo QA trực tiếp trên đoạn dịch"
        type="button"
      >
        QA
      </button>
    </div>
  );
}

export type ReaderQuickActionBarProps = Pick<ReaderQuickControlsProps, 'onOpenToc' | 'settings' | 'visible'>;

export function ReaderQuickActionBar({ settings, visible, onOpenToc }: ReaderQuickActionBarProps) {
  return (
    <div aria-label="Công cụ đọc nhanh" className="reader-reference-actions" data-visible={visible}>
      <button aria-label="Mở mục lục đọc" onClick={onOpenToc} type="button">
        <List aria-hidden="true" size={16} />
        Mục lục
      </button>
      <button
        aria-pressed={settings.value.instantMode}
        onClick={() => settings.onUpdate({ instantMode: !settings.value.instantMode })}
        type="button"
      >
        <BookOpenText aria-hidden="true" size={16} />
        Tối ưu đọc
      </button>
      <button
        aria-pressed={settings.value.readingMode === 'scroll'}
        onClick={() => settings.onUpdate({
          readingMode: settings.value.readingMode === 'scroll' ? 'paginated' : 'scroll',
        })}
        type="button"
      >
        <ScrollText aria-hidden="true" size={16} />
        Cuộn đọc
      </button>
      <button
        aria-pressed={settings.autoScrollEnabled}
        disabled={!settings.canAutoScroll}
        onClick={settings.onToggleAutoScroll}
        type="button"
      >
        <Volume2 aria-hidden="true" size={16} />
        Tự động cuộn
      </button>
      <button onClick={settings.onOpen} type="button">
        <Type aria-hidden="true" size={16} />
        Cài đặt
      </button>
    </div>
  );
}

export type ReaderQuickSettingsSheetProps = Pick<ReaderQuickControlsProps, 'modes' | 'settings'>;

export function ReaderQuickSettingsSheet({ modes, settings }: ReaderQuickSettingsSheetProps) {
  return (
    <ReaderSettingsSheet
      audioAvailable={settings.audioAvailable}
      audioBusy={settings.audioBusy}
      autoScrollEnabled={settings.autoScrollEnabled}
      open={settings.open}
      rawAvailable={modes.rawAvailable}
      settings={settings.value}
      textMode={modes.value}
      onAudioAction={() => {
        settings.onClose();
        settings.onAudioAction();
      }}
      onAutoScrollChange={settings.onAutoScrollChange}
      onClose={settings.onClose}
      onTextModeChange={(mode) => {
        modes.onChange(mode);
        settings.onClose();
      }}
      onUpdate={settings.onUpdate}
    />
  );
}

export default function ReaderQuickControls(props: ReaderQuickControlsProps) {
  return (
    <>
      <ReaderTextModeSwitcher modes={props.modes} visible={props.visible} />
      <ReaderQuickActionBar settings={props.settings} visible={props.visible} onOpenToc={props.onOpenToc} />
      <ReaderQuickSettingsSheet modes={props.modes} settings={props.settings} />
    </>
  );
}
