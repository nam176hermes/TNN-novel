import { FileText, Highlighter, Loader2, Search, StickyNote, X } from 'lucide-react';
import type { ReactNode } from 'react';
import type { ReaderSearchResult, ReaderSearchScope } from '../../api/types';
import type { ReaderSearchOptions } from '../../state/readerSearch';

export type ReaderSearchPanelProps = {
  bookResults: ReaderSearchResult[];
  currentResults: ReaderSearchResult[];
  error: string;
  loading: boolean;
  open: boolean;
  options: ReaderSearchOptions;
  query: string;
  onClose(): void;
  onJump(result: ReaderSearchResult): void;
  onOptionsChange(options: ReaderSearchOptions): void;
  onQueryChange(query: string): void;
};

const scopeOptions: Array<{ id: ReaderSearchScope; label: string }> = [
  { id: 'translation', label: 'Translation' },
  { id: 'notes', label: 'Notes' },
  { id: 'highlights', label: 'Highlights' },
];

function sourceLabel(source: ReaderSearchResult['source']): string {
  if (source === 'translation') return 'Bản dịch';
  if (source === 'highlight') return 'Highlight';
  return 'Note';
}

function sourceIcon(source: ReaderSearchResult['source']) {
  if (source === 'translation') return <FileText aria-hidden="true" size={14} />;
  if (source === 'highlight') return <Highlighter aria-hidden="true" size={14} />;
  return <StickyNote aria-hidden="true" size={14} />;
}

function activeScopes(options: ReaderSearchOptions): ReaderSearchScope[] {
  return options.scopes && options.scopes.length > 0
    ? options.scopes
    : ['translation', 'notes', 'highlights'];
}

function ReaderSearchResults({
  emptyText,
  headingAddon,
  results,
  title,
  onJump,
}: {
  emptyText: string;
  headingAddon?: ReactNode;
  results: ReaderSearchResult[];
  title: string;
  onJump(result: ReaderSearchResult): void;
}) {
  return (
    <section className="reader-search-results" aria-label={title}>
      <h3>
        {title}
        {headingAddon}
      </h3>
      <div className="reader-search-list">
        {results.map((result, index) => (
          <button
            aria-label={`Đến Ch. ${result.chapter_number} đoạn ${result.paragraph_index + 1}`}
            className="reader-search-result"
            key={`${result.source}-${result.chapter_id}-${result.paragraph_index}-${index}`}
            onClick={() => onJump(result)}
            type="button"
          >
            <span className="reader-search-result-meta">
              <span>{sourceIcon(result.source)} {sourceLabel(result.source)}</span>
              <span>Ch. {result.chapter_number}</span>
            </span>
            <strong>{result.chapter_title}</strong>
            <small>{result.snippet}</small>
          </button>
        ))}
        {results.length === 0 ? <p>{emptyText}</p> : null}
      </div>
    </section>
  );
}

export default function ReaderSearchPanel({
  bookResults,
  currentResults,
  error,
  loading,
  open,
  options,
  query,
  onClose,
  onJump,
  onOptionsChange,
  onQueryChange,
}: ReaderSearchPanelProps) {
  if (!open) return null;

  const scopes = activeScopes(options);
  const trimmedQuery = query.trim();

  function patchOptions(patch: Partial<ReaderSearchOptions>): void {
    onOptionsChange({
      ...options,
      ...patch,
    });
  }

  function toggleScope(scope: ReaderSearchScope): void {
    const nextScopes = scopes.includes(scope)
      ? scopes.filter((item) => item !== scope)
      : [...scopes, scope];
    patchOptions({ scopes: nextScopes.length > 0 ? nextScopes : scopes });
  }

  return (
    <div className="reader-drawer-backdrop">
      <aside aria-label="Tìm trong truyện" className="reader-search-panel" role="dialog">
        <header className="reader-drawer-header">
          <div>
            <p className="section-label">Search</p>
            <h2>Tìm trong truyện</h2>
            <span>{trimmedQuery ? `${currentResults.length + bookResults.length} kết quả` : 'Nhập từ khóa để tìm'}</span>
          </div>
          <button
            aria-label="Đóng tìm kiếm"
            className="reader-icon-button"
            onClick={onClose}
            title="Đóng tìm kiếm"
            type="button"
          >
            <X aria-hidden="true" size={22} />
          </button>
        </header>

        <label className="reader-search-field">
          <span>Từ khóa</span>
          <Search aria-hidden="true" size={18} />
          <input
            aria-label="Từ khóa"
            autoFocus
            onChange={(event) => onQueryChange(event.target.value)}
            placeholder="Tìm tên, câu thoại, note..."
            type="search"
            value={query}
          />
        </label>

        <div className="reader-search-options" aria-label="Tùy chọn tìm kiếm">
          <label>
            <input
              checked={Boolean(options.caseSensitive)}
              onChange={(event) => patchOptions({ caseSensitive: event.target.checked })}
              type="checkbox"
            />
            Case sensitive
          </label>
          <label>
            <input
              checked={Boolean(options.wholeWord)}
              onChange={(event) => patchOptions({ wholeWord: event.target.checked })}
              type="checkbox"
            />
            Whole word
          </label>
          <label>
            <input
              checked={Boolean(options.regex)}
              onChange={(event) => patchOptions({ regex: event.target.checked })}
              type="checkbox"
            />
            Regex
          </label>
        </div>

        <div className="reader-search-options reader-search-scopes" aria-label="Phạm vi tìm kiếm">
          {scopeOptions.map((scope) => (
            <label key={scope.id}>
              <input
                checked={scopes.includes(scope.id)}
                onChange={() => toggleScope(scope.id)}
                type="checkbox"
              />
              {scope.label}
            </label>
          ))}
        </div>

        <div className="reader-search-body">
          {error ? <p className="reader-search-error">{error}</p> : null}
          <ReaderSearchResults
            emptyText={trimmedQuery ? 'Không có kết quả trong chương hiện tại.' : 'Chưa có từ khóa.'}
            results={trimmedQuery ? currentResults : []}
            title="Chương hiện tại"
            onJump={onJump}
          />
          <ReaderSearchResults
            emptyText={trimmedQuery ? 'Không có kết quả toàn sách.' : 'Chưa có từ khóa.'}
            headingAddon={
              loading
                ? <Loader2 aria-label="Đang tìm toàn bộ sách" className="reader-search-loader" size={15} />
                : null
            }
            results={trimmedQuery ? bookResults : []}
            title="Toàn bộ sách"
            onJump={onJump}
          />
        </div>
      </aside>
    </div>
  );
}
