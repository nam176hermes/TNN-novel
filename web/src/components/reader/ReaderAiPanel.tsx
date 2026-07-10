import { Languages, Loader2, RotateCcw, Sparkles, X } from 'lucide-react';
import type { ReaderExplainResponse, ReaderExplainSpoilerMode } from '../../api/types';

export type ReaderAiPanelMode = 'explain' | 'translate_term';

export type ReaderAiPanelProps = {
  cached?: boolean;
  error: string;
  loading: boolean;
  mode: ReaderAiPanelMode;
  open: boolean;
  result: ReaderExplainResponse | null;
  selectedText: string;
  spoilerMode: ReaderExplainSpoilerMode;
  onClose(): void;
  onRetry(): void;
  onSpoilerModeChange(mode: ReaderExplainSpoilerMode): void;
};

function panelTitle(mode: ReaderAiPanelMode): string {
  return mode === 'translate_term' ? 'Dịch thuật ngữ' : 'Giải thích đoạn chọn';
}

function panelIcon(mode: ReaderAiPanelMode) {
  return mode === 'translate_term'
    ? <Languages aria-hidden="true" size={18} />
    : <Sparkles aria-hidden="true" size={18} />;
}

export default function ReaderAiPanel({
  cached = false,
  error,
  loading,
  mode,
  open,
  result,
  selectedText,
  spoilerMode,
  onClose,
  onRetry,
  onSpoilerModeChange,
}: ReaderAiPanelProps) {
  if (!open) return null;

  return (
    <div className="reader-drawer-backdrop">
      <aside aria-label="AI đọc truyện" className="reader-ai-panel" role="dialog">
        <header className="reader-drawer-header">
          <div>
            <p className="section-label">Reader AI</p>
            <h2>{panelIcon(mode)} {panelTitle(mode)}</h2>
            <span>{selectedText || 'Chưa có đoạn chọn'}</span>
          </div>
          <button
            aria-label="Đóng AI đọc truyện"
            className="reader-icon-button"
            onClick={onClose}
            title="Đóng AI đọc truyện"
            type="button"
          >
            <X aria-hidden="true" size={22} />
          </button>
        </header>

        <div aria-label="Chế độ spoiler" className="segmented-control reader-ai-spoiler" role="group">
          <button
            aria-pressed={spoilerMode === 'no_spoiler'}
            onClick={() => onSpoilerModeChange('no_spoiler')}
            type="button"
          >
            No spoiler
          </button>
          <button
            aria-pressed={spoilerMode === 'allow_spoiler'}
            onClick={() => onSpoilerModeChange('allow_spoiler')}
            type="button"
          >
            Cho phép spoiler
          </button>
        </div>

        <section className="reader-ai-result" aria-label="Kết quả AI">
          {loading ? (
            <p className="reader-ai-loading">
              <Loader2 aria-hidden="true" size={16} />
              Đang giải thích...
            </p>
          ) : null}
          {error ? (
            <div className="reader-ai-error" role="alert">
              <p>{error}</p>
              <button className="secondary-action" onClick={onRetry} type="button">
                <RotateCcw aria-hidden="true" size={15} />
                Thử lại
              </button>
            </div>
          ) : null}
          {!loading && !error && result ? (
            <>
              {cached ? <p className="reader-ai-cache-status">Kết quả đã lưu trong cache.</p> : null}
              <p>{result.explanation}</p>
              <div className="reader-ai-terms">
                <h3>Thuật ngữ</h3>
                {result.terms.length > 0 ? (
                  result.terms.map((term, index) => (
                    <article className="reader-ai-term" key={`${term.source}-${term.target}-${index}`}>
                      <strong>{term.source || term.target}</strong>
                      {term.target ? <span>{term.target}</span> : null}
                      {term.note ? <small>{term.note}</small> : null}
                    </article>
                  ))
                ) : (
                  <p>Không có thuật ngữ riêng trong đoạn chọn.</p>
                )}
              </div>
            </>
          ) : null}
          {!loading && !error && !result ? <p>Chọn một đoạn trong trang đọc để giải thích.</p> : null}
        </section>
      </aside>
    </div>
  );
}
