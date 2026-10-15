import { Headphones, Moon, Sun, X } from 'lucide-react';
import { useDialogFocusLifecycle } from '../../hooks/useDialogFocusLifecycle';
import type {
  ReaderFontFamily,
  ReaderMode,
  ReaderSettings,
  ReaderTextMode,
  ReaderTheme,
  ReaderWidth,
} from './types';

export type ReaderModeAvailability = {
  rawAvailable: boolean;
  rawCollapsedAvailable: boolean;
  splitAvailable: boolean;
};

export type ReaderSettingsSheetProps = Partial<ReaderModeAvailability> & {
  open: boolean;
  settings: ReaderSettings;
  onClose(): void;
  audioAvailable?: boolean;
  audioBusy?: boolean;
  autoScrollEnabled?: boolean;
  textMode?: ReaderTextMode;
  onAudioAction?(): void;
  onAutoScrollChange?(enabled: boolean): void;
  onTextModeChange?(mode: ReaderTextMode): void;
  onUpdate(patch: Partial<ReaderSettings>): void;
};

const themeOptions: Array<{ id: ReaderTheme; label: string }> = [
  { id: 'light', label: 'Sáng' },
  { id: 'dark', label: 'Tối' },
  { id: 'sepia', label: 'Giấy' },
  { id: 'eink', label: 'E-ink' },
];

const widthOptions: Array<{ id: ReaderWidth; label: string }> = [
  { id: 'narrow', label: 'Hẹp' },
  { id: 'medium', label: 'Vừa' },
  { id: 'wide', label: 'Rộng' },
];

const fontOptions: Array<{ id: ReaderFontFamily; label: string }> = [
  { id: 'serif', label: 'Serif' },
  { id: 'sans', label: 'Sans' },
];

const readingModeOptions: Array<{ id: ReaderMode; label: string }> = [
  { id: 'scroll', label: 'Cuộn' },
  { id: 'paginated', label: 'Trang' },
];

export default function ReaderSettingsSheet({
  audioAvailable = false,
  audioBusy = false,
  autoScrollEnabled = false,
  open,
  rawAvailable = true,
  rawCollapsedAvailable = true,
  splitAvailable = true,
  settings,
  textMode = 'translation',
  onAudioAction,
  onAutoScrollChange,
  onClose,
  onTextModeChange,
  onUpdate,
}: ReaderSettingsSheetProps) {
  const dialogRef = useDialogFocusLifecycle<HTMLElement>(open, onClose);
  if (!open) return null;

  const updateFontSize = (delta: number) => {
    onUpdate({ fontSize: Math.min(24, Math.max(16, settings.fontSize + delta)) });
  };

  return (
    <div className="reader-sheet-backdrop">
      <section
        aria-label="Cài đặt đọc"
        aria-modal="true"
        className="reader-settings-sheet"
        ref={dialogRef}
        role="dialog"
        tabIndex={-1}
      >
        <header className="reader-sheet-header">
          <div>
            <p className="section-label">Aa</p>
            <h2>Tùy chỉnh đọc</h2>
          </div>
          <button
            aria-label="Đóng cài đặt đọc"
            className="reader-icon-button"
            data-dialog-initial-focus
            onClick={onClose}
            title="Đóng cài đặt đọc"
            type="button"
          >
            <X aria-hidden="true" size={22} />
          </button>
        </header>

        <div className="reader-settings-grid">
          <section className="reader-setting-group reader-setting-full reader-content-mode-group">
            <span>Nội dung</span>
            <div aria-label="Nội dung đọc" className="reader-content-mode-grid" role="group">
              {([
                ['translation', 'Bản dịch'],
                ['split', 'Song song'],
                ['raw-collapsed', 'Raw gọn'],
                ['qa-overlay', 'QA'],
              ] as Array<[ReaderTextMode, string]>).map(([mode, label]) => (
                <button
                  aria-pressed={textMode === mode}
                  disabled={!onTextModeChange
                    || (mode === 'split' && !splitAvailable)
                    || (mode === 'raw-collapsed' && !rawCollapsedAvailable)}
                  key={mode}
                  onClick={() => onTextModeChange?.(mode)}
                  type="button"
                >
                  {label}
                </button>
              ))}
            </div>
            <button
              aria-pressed={textMode === 'raw'}
              className="reader-raw-mode-row"
              disabled={!onTextModeChange || !rawAvailable}
              onClick={() => onTextModeChange?.('raw')}
              type="button"
            >
              <span>Raw tiếng Trung</span>
              {!rawAvailable ? <small>Chương hiện tại chưa có raw/source tiếng Trung.</small> : null}
            </button>
          </section>

          <div className="reader-setting-group">
            <span>Nền đọc</span>
            <div aria-label="Nền đọc" className="segmented-control reader-theme-control" role="group">
              {themeOptions.map((theme) => (
                <button
                  aria-pressed={settings.theme === theme.id}
                  key={theme.id}
                  onClick={() => onUpdate({ theme: theme.id })}
                  type="button"
                >
                  {theme.id === 'dark' || theme.id === 'eink' ? (
                    <Moon aria-hidden="true" size={15} />
                  ) : (
                    <Sun aria-hidden="true" size={15} />
                  )}
                  {theme.label}
                </button>
              ))}
            </div>
          </div>

          <div className="reader-setting-group">
            <span>Font</span>
            <div aria-label="Font chữ" className="segmented-control" role="group">
              {fontOptions.map((font) => (
                <button
                  aria-pressed={settings.fontFamily === font.id}
                  key={font.id}
                  onClick={() => onUpdate({ fontFamily: font.id })}
                  type="button"
                >
                  {font.label}
                </button>
              ))}
            </div>
          </div>

          <div className="reader-setting-group">
            <span>Điều chỉnh nhanh</span>
            <div aria-label="Điều chỉnh nhanh" className="reader-quick-controls" role="group">
              <button aria-label="Giảm cỡ chữ" onClick={() => updateFontSize(-1)} type="button">
                A-
              </button>
              <button aria-label="Tăng cỡ chữ" onClick={() => updateFontSize(1)} type="button">
                A+
              </button>
            </div>
          </div>

          <label className="reader-range-control">
            <span>Cỡ chữ</span>
            <input
              aria-label="Cỡ chữ"
              max={24}
              min={16}
              onChange={(event) => onUpdate({ fontSize: Number(event.target.value) })}
              step={1}
              type="range"
              value={settings.fontSize}
            />
            <output>{settings.fontSize}px</output>
          </label>

          <label className="reader-range-control">
            <span>Giãn dòng</span>
            <input
              aria-label="Giãn dòng"
              max={2.2}
              min={1.5}
              onChange={(event) => onUpdate({ lineHeight: Number(event.target.value) })}
              step={0.1}
              type="range"
              value={settings.lineHeight}
            />
            <output>{settings.lineHeight.toFixed(1)}</output>
          </label>

          <label className="reader-range-control">
            <span>Giãn đoạn</span>
            <input
              aria-label="Giãn đoạn"
              max={2.4}
              min={0.6}
              onChange={(event) => onUpdate({ paragraphSpacing: Number(event.target.value) })}
              step={0.05}
              type="range"
              value={settings.paragraphSpacing}
            />
            <output>{settings.paragraphSpacing.toFixed(2)}em</output>
          </label>

          <label className="reader-range-control">
            <span>Lề đọc</span>
            <input
              aria-label="Lề đọc"
              max={1.5}
              min={0.75}
              onChange={(event) => onUpdate({ marginScale: Number(event.target.value) })}
              step={0.05}
              type="range"
              value={settings.marginScale}
            />
            <output>{Math.round(settings.marginScale * 100)}%</output>
          </label>

          <label className="reader-range-control">
            <span>Giãn chữ</span>
            <input
              aria-label="Giãn chữ"
              max={1.5}
              min={0}
              onChange={(event) => onUpdate({ characterSpacing: Number(event.target.value) })}
              step={0.05}
              type="range"
              value={settings.characterSpacing}
            />
            <output>{settings.characterSpacing.toFixed(2)}px</output>
          </label>

          <label className="reader-range-control">
            <span>Độ đậm</span>
            <input
              aria-label="Độ đậm"
              max={800}
              min={350}
              onChange={(event) => onUpdate({ fontWeight: Number(event.target.value) })}
              step={25}
              type="range"
              value={settings.fontWeight}
            />
            <output>{settings.fontWeight}</output>
          </label>

          <div className="reader-setting-group reader-setting-full">
            <span>Khổ đọc</span>
            <div aria-label="Khổ đọc" className="segmented-control" role="group">
              {widthOptions.map((width) => (
                <button
                  aria-pressed={settings.width === width.id}
                  key={width.id}
                  onClick={() => onUpdate({ width: width.id })}
                  type="button"
                >
                  {width.label}
                </button>
              ))}
            </div>
          </div>

          <div className="reader-setting-group reader-setting-full">
            <span>Chế độ đọc</span>
            <div aria-label="Chế độ đọc" className="segmented-control" role="group">
              {readingModeOptions.map((mode) => (
                <button
                  aria-pressed={settings.readingMode === mode.id}
                  key={mode.id}
                  onClick={() => onUpdate({ readingMode: mode.id })}
                  type="button"
                >
                  {mode.label}
                </button>
              ))}
            </div>
          </div>

          <label className="reader-toggle-control reader-setting-full">
            <input
              aria-label="Tự động cuộn"
              checked={autoScrollEnabled}
              disabled={!onAutoScrollChange}
              onChange={(event) => onAutoScrollChange?.(event.target.checked)}
              type="checkbox"
            />
            <span>
              <strong>Tự động cuộn</strong>
              <small>Chỉ hoạt động trong chế độ cuộn.</small>
            </span>
          </label>

          <section className="reader-setting-group reader-setting-full reader-audio-setting">
            <span>Âm thanh</span>
            <button disabled={!onAudioAction || audioBusy} onClick={onAudioAction} type="button">
              <Headphones aria-hidden="true" size={18} />
              <span>
                <strong>{audioAvailable ? 'Nghe audio chương' : 'Tạo audio'}</strong>
                <small>{audioAvailable ? 'Mở trình phát thu gọn.' : 'Audio không tự động được tạo.'}</small>
              </span>
            </button>
          </section>

          <label className="reader-toggle-control reader-setting-full">
            <input
              aria-label="Instant mode"
              checked={settings.instantMode}
              onChange={(event) => onUpdate({ instantMode: event.target.checked })}
              type="checkbox"
            />
            <span>
              <strong>Tương tác nhanh</strong>
              <small>Hiện nút highlight và ghi chú ngay cạnh từng đoạn.</small>
            </span>
          </label>

          <label className="reader-toggle-control reader-setting-full">
            <input
              aria-label="Toàn màn hình"
              checked={settings.fullscreen}
              onChange={(event) => onUpdate({ fullscreen: event.target.checked })}
              type="checkbox"
            />
            <span>
              <strong>Toàn màn hình</strong>
              <small>Giảm khoảng trống chrome để trang đọc giống app reader chuyên dụng.</small>
            </span>
          </label>
        </div>
      </section>
    </div>
  );
}
