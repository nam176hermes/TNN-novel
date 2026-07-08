import { BookOpenText, Loader2, RotateCcw, X } from 'lucide-react';
import type { ReaderDictionaryResponse, ReaderDictionarySource } from '../../api/types';

export type ReaderDictionaryPanelProps = {
  error: string;
  includeOnline: boolean;
  loading: boolean;
  open: boolean;
  query: string;
  result: ReaderDictionaryResponse | null;
  onClose(): void;
  onIncludeOnlineChange(value: boolean): void;
  onRetry(): void;
};

function sourceLabel(source: ReaderDictionarySource): string {
  if (source.source === 'glossary') return 'Glossary';
  if (source.source === 'builtin') return source.provider ? `Built-in · ${source.provider}` : 'Built-in';
  if (source.source === 'offline_dictionary') {
    return source.provider ? `Offline dictionary · ${source.provider}` : 'Offline dictionary';
  }
  if (source.source === 'xray') return 'X-Ray';
  if (source.source === 'online') return source.provider ? `Online · ${source.provider}` : 'Online';
  return source.source || 'Nguồn';
}

function definitionFor(source: ReaderDictionarySource): string {
  return source.definition || source.target || '';
}

export default function ReaderDictionaryPanel({
  error,
  includeOnline,
  loading,
  open,
  query,
  result,
  onClose,
  onIncludeOnlineChange,
  onRetry,
}: ReaderDictionaryPanelProps) {
  if (!open) return null;

  const sources = result?.sources ?? [];

  return (
    <div className="reader-drawer-backdrop">
      <aside aria-label="Từ điển đọc truyện" className="reader-dictionary-panel" role="dialog">
        <header className="reader-drawer-header">
          <div>
            <p className="section-label">Dictionary</p>
            <h2><BookOpenText aria-hidden="true" size={18} /> Tra cứu</h2>
            <span>{query || 'Chọn từ/cụm từ để tra'}</span>
          </div>
          <button
            aria-label="Đóng từ điển"
            className="reader-icon-button"
            onClick={onClose}
            title="Đóng từ điển"
            type="button"
          >
            <X aria-hidden="true" size={22} />
          </button>
        </header>

        <label className="reader-toggle-control reader-dictionary-toggle">
          <input
            aria-label="Online fallback"
            checked={includeOnline}
            onChange={(event) => onIncludeOnlineChange(event.target.checked)}
            type="checkbox"
          />
          <span>
            <strong>Online fallback</strong>
            <small>Ưu tiên glossary/X-Ray offline, chỉ hỏi online khi bật.</small>
          </span>
        </label>

        <section aria-label="Kết quả từ điển" className="reader-dictionary-results">
          {loading ? (
            <p className="reader-ai-loading">
              <Loader2 aria-hidden="true" size={16} />
              Đang tra cứu...
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
              <p className="reader-dictionary-status">
                {result.offline_count.toLocaleString('vi-VN')} offline · online {result.online.status}
                {result.cache?.hit ? ' · cache hit' : ''}
                {result.cache?.stored ? ' · cached' : ''}
              </p>
              <div className="reader-dictionary-list">
                {sources.map((source, index) => (
                  <article className="reader-dictionary-card" key={`${source.source}-${source.term}-${index}`}>
                    <header>
                      <strong>{source.term || query}</strong>
                      <span>{sourceLabel(source)}</span>
                    </header>
                    {source.target ? <p className="reader-dictionary-target">{source.target}</p> : null}
                    {definitionFor(source) ? <p>{definitionFor(source)}</p> : null}
                    {source.aliases?.length ? <small>Alias: {source.aliases.join(', ')}</small> : null}
                    {source.variants?.length ? <small>Biến thể: {source.variants.join(', ')}</small> : null}
                    {source.category ? <small>{source.category}</small> : null}
                  </article>
                ))}
                {sources.length === 0 ? <p>Không tìm thấy kết quả phù hợp.</p> : null}
              </div>
              {result.online.status === 'error' && result.online.error ? (
                <p className="reader-sync-error">{result.online.error}</p>
              ) : null}
            </>
          ) : null}
          {!loading && !error && !result ? <p>Chọn một từ trong trang đọc rồi bấm Dictionary.</p> : null}
        </section>
      </aside>
    </div>
  );
}
