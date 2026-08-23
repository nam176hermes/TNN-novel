import { BookMarked, Search, ShieldCheck, Sparkles, UserRound, X } from 'lucide-react';
import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { ApiError } from '../api/client';
import type {
  BookGlossarySettings,
  GlossaryFacets,
  GlossaryBulkAction,
  GlossaryBulkTermRef,
  GlossaryConflictPage,
  GlossaryImportItem,
  GlossaryImportPreview,
  GlossaryMergePreview,
  GlossaryQuery,
  GlossaryTerm,
  GlossaryTermDetail,
  GlossaryTermUpdate,
  GlossaryExtractionResult,
  Provider,
  StyleProfile,
} from '../api/types';
import type { LoadState } from '../state/types';

const emptyFacets: GlossaryFacets = { locked: {}, mode: {}, review_status: {}, scope: {}, term_type: {} };
const fallbackQuery: GlossaryQuery = {
  page: 1,
  per_page: 50,
  q: '',
  review_status: 'NEEDS_REVIEW,CONFLICT',
  scope: 'book',
  sort: 'review',
};
type GlossaryImportPolicy = 'skip_conflicts' | 'reject_conflicts';

export type GlossaryStyleViewProps = {
  bookId?: number;
  chapterId?: number;
  profiles: StyleProfile[];
  selectedProfileId: string;
  glossaryTerms: GlossaryTerm[];
  error?: string;
  facets?: GlossaryFacets;
  loadState?: LoadState;
  page?: number;
  pages?: number;
  perPage?: number;
  query?: GlossaryQuery;
  total?: number;
  onApproveTerm(termId: number): void | Promise<void>;
  onApplyImport?(items: GlossaryImportItem[], digest: string, policy: GlossaryImportPolicy): void | Promise<void>;
  onApplyMerge?(canonicalId: number, duplicateIds: number[], digest: string): void | Promise<void>;
  onArchiveTerm?(termId: number): void | Promise<void>;
  onBulkAction?(action: GlossaryBulkAction, terms: GlossaryBulkTermRef[]): void | Promise<void>;
  onCreateTerm?(term: GlossaryImportItem): void | Promise<void>;
  onCreateBookOverride?(term: GlossaryTerm): void | Promise<void>;
  onExport?(format: 'json' | 'csv'): void | Promise<void>;
  onLoadConflicts?(page?: number): Promise<GlossaryConflictPage>;
  onLoadTermDetail?(termId: number, options?: { signal?: AbortSignal }): Promise<GlossaryTermDetail>;
  onLoadExtractionSettings?(bookId: number): Promise<BookGlossarySettings>;
  onLockToggle(termId: number, locked: boolean): void | Promise<void>;
  onPageChange?(page: number): void;
  onProfileChange(profileId: string): void;
  onPreviewImport?(items: GlossaryImportItem[], policy: GlossaryImportPolicy): Promise<GlossaryImportPreview>;
  onPreviewMerge?(canonicalId: number, duplicateIds: number[]): Promise<GlossaryMergePreview>;
  onQueryChange?(updates: Partial<GlossaryQuery>): void;
  onRejectTerm(termId: number): void | Promise<void>;
  onReextractChapter?(bookId: number, chapterId: number): Promise<GlossaryExtractionResult>;
  onRestoreTerm?(termId: number): void | Promise<void>;
  onSaveAndApproveTerm(termId: number, updates: GlossaryTermUpdate, locked: boolean): void | Promise<void>;
  onSaveExtractionSettings?(
    bookId: number,
    settings: Pick<BookGlossarySettings, 'mode' | 'provider_id'>,
  ): Promise<BookGlossarySettings>;
  onUpdateTerm(termId: number, updates: GlossaryTermUpdate): void | Promise<void>;
  providers?: Provider[];
};

const importIntegerFields = new Set([
  'id', 'version', 'book_id', 'approved', 'locked', 'occurrence_count', 'priority',
  'first_seen_chapter_id', 'first_seen_chapter_number',
]);
const csvMetadataFields = new Set(['schema_version', 'scope', 'scope_book_id']);
const canonicalCsvItemFields = [
  'id', 'book_id', 'source_term', 'target_term', 'category', 'confidence', 'approved',
  'locked', 'review_status', 'mode', 'pinyin', 'notes_vi', 'variants', 'occurrence_count',
  'priority', 'genre', 'term_type', 'alternatives', 'gender', 'first_seen_chapter_id',
  'first_seen_chapter_number', 'source_context', 'archived_at', 'version', 'archived',
];

function csvRows(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = '';
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    if (quoted) {
      if (character === '"' && text[index + 1] === '"') {
        field += '"'; index += 1;
      } else if (character === '"') {
        quoted = false;
      } else {
        field += character;
      }
    } else if (character === '"') {
      if (field) throw new Error('CSV có dấu ngoặc kép không hợp lệ.');
      quoted = true;
    } else if (character === ',') {
      row.push(field); field = '';
    } else if (character === '\n') {
      row.push(field.replace(/\r$/, '')); rows.push(row); row = []; field = '';
    } else {
      field += character;
    }
  }
  if (quoted) throw new Error('CSV có trường trích dẫn chưa đóng.');
  if (field || row.length) { row.push(field.replace(/\r$/, '')); rows.push(row); }
  return rows.filter((candidate) => candidate.some((value) => value !== ''));
}

function validateImportItems(value: unknown): GlossaryImportItem[] {
  if (!Array.isArray(value)) throw new Error('Dữ liệu nhập phải chứa danh sách thuật ngữ.');
  if (value.length > 5000) throw new Error('Dữ liệu nhập vượt quá 5000 thuật ngữ.');
  return value.map((candidate, index) => {
    if (!candidate || typeof candidate !== 'object' || Array.isArray(candidate)) {
      throw new Error(`Dòng ${index + 1} không phải là một thuật ngữ hợp lệ.`);
    }
    const item = candidate as Record<string, unknown>;
    if (typeof item.source_term !== 'string' || typeof item.target_term !== 'string') {
      throw new Error(`Dòng ${index + 1} cần source_term và target_term dạng chuỗi.`);
    }
    for (const field of importIntegerFields) {
      if (field in item && (!Number.isSafeInteger(item[field]) || typeof item[field] === 'boolean')) {
        throw new Error(`Dòng ${index + 1}: ${field} phải là số nguyên hợp lệ.`);
      }
    }
    if ('archived' in item && typeof item.archived !== 'boolean') {
      throw new Error(`Dòng ${index + 1}: archived phải là true hoặc false.`);
    }
    if ('confidence' in item && (typeof item.confidence !== 'number' || !Number.isFinite(item.confidence))) {
      throw new Error(`Dòng ${index + 1}: confidence phải là số hợp lệ.`);
    }
    const status = String(item.review_status ?? '').trim().toUpperCase();
    const approved = item.approved ?? 1;
    const locked = item.locked ?? 0;
    const canonicalFlags: Record<string, [number, number]> = {
      NEEDS_REVIEW: [0, 0], APPROVED: [1, 0], REJECTED: [-1, 0], LOCKED: [1, 1], CONFLICT: [0, 0],
    };
    const flagsAreCanonical = status
      ? status in canonicalFlags && approved === canonicalFlags[status][0] && locked === canonicalFlags[status][1]
      : [[0, 0], [1, 0], [-1, 0], [1, 1]].some(([expectedApproved, expectedLocked]) => (
        approved === expectedApproved && locked === expectedLocked
      ));
    if (!flagsAreCanonical) {
      throw new Error(`Dòng ${index + 1} có trạng thái canonical không hợp lệ.`);
    }
    return item as GlossaryImportItem;
  });
}

function validateImportScope(scope: unknown, items: GlossaryImportItem[]): void {
  if (!scope || typeof scope !== 'object' || !['all', 'book', 'global'].includes(String((scope as Record<string, unknown>).type))) {
    throw new Error('Phạm vi nhập không hợp lệ.');
  }
  const record = scope as Record<string, unknown>;
  const scopeType = String(record.type);
  const scopeBookId = record.book_id ?? (scopeType === 'book' ? undefined : 0);
  if (!Number.isSafeInteger(scopeBookId) || Number(scopeBookId) < 0) {
    throw new Error('Mã sách trong phạm vi nhập không hợp lệ.');
  }
  if (scopeType === 'all') return;
  const expectedBookId = scopeType === 'global' ? 0 : Number(scopeBookId);
  if ((scopeType === 'global' && scopeBookId !== 0)
      || items.some((item) => (item.book_id ?? 0) !== expectedBookId)) {
    throw new Error('Phạm vi nhập không khớp với book_id của thuật ngữ.');
  }
}

export function parseGlossaryImportText(text: string): GlossaryImportItem[] {
  const trimmed = text.trim();
  if (!trimmed) throw new Error('Dữ liệu nhập đang trống.');
  if (new TextEncoder().encode(text).byteLength > 5 * 1024 * 1024) {
    throw new Error('Dữ liệu nhập vượt quá 5 MB.');
  }
  if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
    const payload = JSON.parse(trimmed) as unknown;
    if (Array.isArray(payload)) return validateImportItems(payload);
    if (!payload || typeof payload !== 'object') throw new Error('JSON nhập không hợp lệ.');
    const envelope = payload as Record<string, unknown>;
    if ('schema_version' in envelope && envelope.schema_version !== 1) {
      throw new Error('Phiên bản schema JSON không được hỗ trợ.');
    }
    const items = validateImportItems(envelope.items ?? envelope.terms);
    if ('scope' in envelope) validateImportScope(envelope.scope, items);
    return items;
  }

  const rows = csvRows(trimmed);
  const headers = rows[0] ?? [];
  if (new Set(headers).size !== headers.length) throw new Error('CSV có cột trùng tên.');
  for (const required of ['schema_version', 'scope', 'source_term', 'target_term']) {
    if (!headers.includes(required)) throw new Error(`CSV thiếu cột ${required}.`);
  }
  const parsedItems = rows.slice(1).map((values, index): GlossaryImportItem | null => {
    if (values.length !== headers.length) throw new Error(`Dòng CSV ${index + 1} sai số lượng cột.`);
    const record = Object.fromEntries(headers.map((header, column) => [header, values[column]]));
    if (record.schema_version !== '1') throw new Error(`Dòng CSV ${index + 1} có schema không hỗ trợ.`);
    if (!['all', 'book', 'global'].includes(record.scope)) throw new Error(`Dòng CSV ${index + 1} có scope không hợp lệ.`);
    const scopeBookId = Number(record.scope_book_id ?? (record.scope === 'book' ? Number.NaN : 0));
    if (
      canonicalCsvItemFields.every((fieldName) => headers.includes(fieldName))
      && canonicalCsvItemFields.every((fieldName) => record[fieldName] === '')
    ) {
      validateImportScope({ type: record.scope, book_id: scopeBookId }, []);
      return null;
    }
    const item: Record<string, unknown> = {};
    for (const [fieldName, rawValue] of Object.entries(record)) {
      if (csvMetadataFields.has(fieldName)) continue;
      if (importIntegerFields.has(fieldName)) {
        if (fieldName === 'occurrence_count' && rawValue === '') continue;
        const number = Number(rawValue);
        if (!Number.isSafeInteger(number)) throw new Error(`Dòng CSV ${index + 1}: ${fieldName} không hợp lệ.`);
        item[fieldName] = number;
      } else if (fieldName === 'confidence') {
        const number = Number(rawValue);
        if (!Number.isFinite(number)) throw new Error(`Dòng CSV ${index + 1}: confidence không hợp lệ.`);
        item[fieldName] = number;
      } else if (fieldName === 'archived') {
        if (!['true', 'false'].includes(rawValue.toLowerCase())) throw new Error(`Dòng CSV ${index + 1}: archived không hợp lệ.`);
        item[fieldName] = rawValue.toLowerCase() === 'true';
      } else {
        item[fieldName] = rawValue;
      }
    }
    const validated = validateImportItems([item]);
    validateImportScope({ type: record.scope, book_id: scopeBookId }, validated);
    return validated[0];
  });
  const items = parsedItems.filter((item): item is GlossaryImportItem => item !== null);
  return validateImportItems(items);
}

function operationErrorMessage(reason: unknown): string {
  if (reason instanceof ApiError && reason.code === 'normalized_source_collision') {
    return 'Không thể khôi phục vì canonical cùng thuật ngữ vẫn đang hoạt động. Hãy lưu trữ canonical trước rồi thử khôi phục lại.';
  }
  return reason instanceof Error ? reason.message : String(reason);
}

type GlossaryRowProps = {
  term: GlossaryTerm;
  onApproveTerm(termId: number): void | Promise<unknown>;
  onArchiveTerm?(termId: number): void | Promise<unknown>;
  onCreateBookOverride?(term: GlossaryTerm): void | Promise<unknown>;
  onDetail(term: GlossaryTerm, opener: HTMLElement): void;
  onLockToggle(termId: number, locked: boolean): void | Promise<unknown>;
  onRejectTerm(termId: number): void | Promise<unknown>;
  onRestoreTerm?(termId: number): void | Promise<unknown>;
  onSelect(term: GlossaryTerm, selected: boolean): void;
  selected: boolean;
  onSaveAndApproveTerm(termId: number, updates: GlossaryTermUpdate, locked: boolean): void | Promise<unknown>;
  onUpdateTerm(termId: number, updates: GlossaryTermUpdate): void | Promise<unknown>;
};

function normalizedReviewStatus(term: GlossaryTerm): string {
  const explicit = String(term.canonical_status || term.review_status || '').trim().toUpperCase();
  if (explicit) return explicit;
  if (term.locked === 1) return 'LOCKED';
  if (term.approved === -1) return 'REJECTED';
  if (term.approved === 1) return 'APPROVED';
  return 'NEEDS_REVIEW';
}

function isLocked(term: GlossaryTerm): boolean {
  return term.locked === 1 || normalizedReviewStatus(term) === 'LOCKED';
}

function isPending(term: GlossaryTerm): boolean {
  return ['NEEDS_REVIEW', 'CONFLICT'].includes(normalizedReviewStatus(term));
}

function statusLabel(term: GlossaryTerm): string {
  return {
    APPROVED: 'Đã duyệt',
    CONFLICT: 'Xung đột',
    LOCKED: 'Đã khóa',
    REJECTED: 'Từ chối',
  }[normalizedReviewStatus(term)] || 'Chờ duyệt';
}

function GlossaryRow({
  term,
  onApproveTerm,
  onArchiveTerm,
  onCreateBookOverride,
  onDetail,
  onLockToggle,
  onRejectTerm,
  onRestoreTerm,
  onSelect,
  onSaveAndApproveTerm,
  onUpdateTerm,
  selected,
}: GlossaryRowProps) {
  const [targetTerm, setTargetTerm] = useState(term.target_term);
  const [termType, setTermType] = useState(term.term_type || term.category || 'term');
  const [priority, setPriority] = useState(String(term.priority ?? 0));
  const locked = isLocked(term);

  useEffect(() => {
    setTargetTerm(term.target_term);
    setTermType(term.term_type || term.category || 'term');
    setPriority(String(term.priority ?? 0));
  }, [term]);

  const updates = (): GlossaryTermUpdate => ({
    priority: Number(priority) || 0,
    target_term: targetTerm,
    term_type: termType,
  });

  return (
    <tr>
      <td><input aria-label={`Chọn ${term.source_term}`} checked={selected} disabled={term.archived} onChange={(event) => onSelect(term, event.target.checked)} type="checkbox" /></td>
      <th scope="row">
        <span>{term.source_term}</span>
        {term.first_seen_chapter_number ? <small className="glossary-row-context">Ch. {term.first_seen_chapter_number}</small> : null}
      </th>
      <td><input aria-label={`Bản dịch cho ${term.source_term}`} onChange={(event) => setTargetTerm(event.target.value)} value={targetTerm} /></td>
      <td>
        <select aria-label={`Loại thuật ngữ cho ${term.source_term}`} onChange={(event) => setTermType(event.target.value)} value={termType}>
          <option value="term">Thuật ngữ</option><option value="character">Nhân vật</option><option value="realm">Cảnh giới</option>
          <option value="artifact">Pháp bảo</option><option value="technique">Thuật pháp</option><option value="sect">Môn phái</option>
          <option value="place">Địa danh</option><option value="title">Danh xưng</option><option value="concept">Khái niệm</option>
        </select>
      </td>
      <td><input aria-label={`Ưu tiên cho ${term.source_term}`} min="0" onChange={(event) => setPriority(event.target.value)} type="number" value={priority} /></td>
      <td>
        <span className={isPending(term) ? 'status-chip status-chip-warning' : 'status-chip'}>{statusLabel(term)}</span>
        <small className="glossary-row-context">{term.inherited ? 'Kế thừa' : term.book_id === 0 ? 'Toàn cục' : 'Trong sách'}</small>
      </td>
      <td>
        <span className="status-chip status-chip-muted">{term.evidence_count || 0} bằng chứng</span>
        <small className="glossary-row-context">v{term.version || 0}</small>
      </td>
      <td>
        <div className="dialog-actions glossary-row-actions">
          {term.archived ? (
            <button aria-label={`Khôi phục ${term.source_term}`} className="secondary-action" onClick={() => void onRestoreTerm?.(term.id)} type="button">Khôi phục</button>
          ) : isPending(term) ? (
            <>
              <button aria-label={`Duyệt ${term.source_term}`} className="primary-action" onClick={() => void onApproveTerm(term.id)} type="button">Duyệt</button>
              <button aria-label={`Từ chối ${term.source_term}`} className="danger-action" onClick={() => void onRejectTerm(term.id)} type="button">Từ chối</button>
              <button aria-label={`Lưu + Duyệt ${term.source_term}`} className="secondary-action" onClick={() => void onSaveAndApproveTerm(term.id, updates(), false)} type="button">Lưu + Duyệt</button>
            </>
          ) : (
            <>
              <button aria-label={`Lưu thay đổi ${term.source_term}`} className="secondary-action" onClick={() => void onUpdateTerm(term.id, updates())} type="button">Lưu</button>
              <button aria-label={`${locked ? 'Mở khóa' : 'Khóa thuật ngữ'} ${term.source_term}`} className="secondary-action" onClick={() => void onLockToggle(term.id, !locked)} type="button">{locked ? 'Mở khóa' : 'Khóa'}</button>
            </>
          )}
          {term.inherited && onCreateBookOverride ? <button aria-label={`Tạo bản ghi riêng cho ${term.source_term}`} className="secondary-action" onClick={() => void onCreateBookOverride(term)} type="button">Tạo bản riêng</button> : null}
          {!term.archived && onArchiveTerm ? <button aria-label={`Lưu trữ ${term.source_term}`} className="danger-action" onClick={() => void onArchiveTerm(term.id)} type="button">Lưu trữ</button> : null}
          <button aria-label={`Chi tiết ${term.source_term}`} className="secondary-action" onClick={(event) => onDetail(term, event.currentTarget)} type="button">Chi tiết</button>
        </div>
      </td>
    </tr>
  );
}

const literaryRuleSummary = 'Dịch theo nghĩa và khí văn; giữ nhịp thơ/đối liên; ưu tiên thành ngữ Việt cổ phong khi có.';
const tabs = [
  { archived: false, label: 'Cần duyệt', status: 'NEEDS_REVIEW,CONFLICT' },
  { archived: false, label: 'Đã duyệt', status: 'APPROVED' },
  { archived: false, label: 'Đã khóa', status: 'LOCKED' },
  { archived: false, label: 'Từ chối', status: 'REJECTED' },
  { archived: false, label: 'Tất cả', status: '' },
  { archived: true, label: 'Đã lưu trữ', status: '' },
] as const;

export default function GlossaryStyleView({
  bookId, chapterId,
  profiles, selectedProfileId, glossaryTerms, error = '', facets = emptyFacets,
  loadState = glossaryTerms.length ? 'ready' : 'empty', page = 1, pages = 0, perPage = 50,
  query = fallbackQuery, total = glossaryTerms.length, onApproveTerm, onCreateBookOverride,
  onApplyImport, onApplyMerge, onArchiveTerm, onBulkAction, onCreateTerm, onExport,
  onLoadConflicts, onLoadExtractionSettings, onLoadTermDetail, onLockToggle, onPageChange,
  onPreviewImport, onPreviewMerge, onProfileChange, onQueryChange, onRejectTerm,
  onReextractChapter, onRestoreTerm, onSaveAndApproveTerm, onSaveExtractionSettings,
  onUpdateTerm, providers = [],
}: GlossaryStyleViewProps) {
  const selectedProfile = profiles.find((profile) => profile.id === selectedProfileId) ?? null;
  const [search, setSearch] = useState(query.q);
  const [legacyStatus, setLegacyStatus] = useState('all');
  const [detail, setDetail] = useState<GlossaryTermDetail | null>(null);
  const [detailTerm, setDetailTerm] = useState<GlossaryTerm | null>(null);
  const [detailError, setDetailError] = useState('');
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [newSource, setNewSource] = useState('');
  const [newTarget, setNewTarget] = useState('');
  const [conflicts, setConflicts] = useState<GlossaryConflictPage | null>(null);
  const [activeConflictId, setActiveConflictId] = useState<string | null>(null);
  const [canonicalId, setCanonicalId] = useState<number | null>(null);
  const [mergePreview, setMergePreview] = useState<GlossaryMergePreview | null>(null);
  const [operationError, setOperationError] = useState('');
  const [importText, setImportText] = useState('');
  const [importItems, setImportItems] = useState<GlossaryImportItem[]>([]);
  const [importPreview, setImportPreview] = useState<GlossaryImportPreview | null>(null);
  const [importPolicy, setImportPolicy] = useState<GlossaryImportPolicy>('skip_conflicts');
  const [extractionMode, setExtractionMode] = useState<BookGlossarySettings['mode']>('deterministic');
  const [extractionProviderId, setExtractionProviderId] = useState('');
  const [extractionLoaded, setExtractionLoaded] = useState(false);
  const [extractionStatus, setExtractionStatus] = useState('');
  const queueHeadingRef = useRef<HTMLHeadingElement | null>(null);
  const detailDrawerRef = useRef<HTMLElement | null>(null);
  const detailCloseButtonRef = useRef<HTMLButtonElement | null>(null);
  const detailReturnFocusRef = useRef<HTMLElement | null>(null);
  const detailAbortRef = useRef<AbortController | null>(null);
  const detailRequestIdRef = useRef(0);
  const detailTermIdRef = useRef<number | null>(null);
  const lastSearchRef = useRef(query.q);
  const extractionPanelRef = useRef<HTMLDetailsElement | null>(null);
  const extractionRequestIdRef = useRef(0);
  const extractionBookIdRef = useRef(bookId);
  const extractionLoaderRef = useRef(onLoadExtractionSettings);
  extractionBookIdRef.current = bookId;
  extractionLoaderRef.current = onLoadExtractionSettings;

  const loadExtractionSettings = useCallback(async (targetBookId: number) => {
    const loader = extractionLoaderRef.current;
    if (!loader) return;
    const requestId = ++extractionRequestIdRef.current;
    setExtractionLoaded(false);
    setOperationError('');
    try {
      const settings = await loader(targetBookId);
      if (
        requestId !== extractionRequestIdRef.current
        || extractionBookIdRef.current !== targetBookId
        || settings.book_id !== targetBookId
      ) return;
      setExtractionMode(settings.mode);
      setExtractionProviderId(settings.provider_id);
      setExtractionLoaded(true);
    } catch (reason) {
      if (requestId !== extractionRequestIdRef.current) return;
      setOperationError(operationErrorMessage(reason));
    }
  }, []);

  useEffect(() => setSearch(query.q), [query.q]);
  useEffect(() => setSelectedIds(new Set()), [glossaryTerms]);
  useEffect(() => {
    extractionRequestIdRef.current += 1;
    setExtractionMode('deterministic');
    setExtractionProviderId('');
    setExtractionLoaded(false);
    setExtractionStatus('');
    if (bookId && extractionPanelRef.current?.open) void loadExtractionSettings(bookId);
  }, [bookId, loadExtractionSettings]);
  useEffect(() => {
    if (!onQueryChange || search === lastSearchRef.current) return;
    const timer = window.setTimeout(() => {
      lastSearchRef.current = search;
      onQueryChange({ page: 1, q: search });
    }, 250);
    return () => window.clearTimeout(timer);
  }, [onQueryChange, search]);
  useEffect(() => {
    if (!detailTerm) return;
    const timer = window.setTimeout(() => detailCloseButtonRef.current?.focus(), 0);
    return () => window.clearTimeout(timer);
  }, [detailTerm]);
  useEffect(() => () => {
    detailRequestIdRef.current += 1;
    detailAbortRef.current?.abort();
    extractionRequestIdRef.current += 1;
  }, []);

  const focusQueue = () => window.setTimeout(() => queueHeadingRef.current?.focus(), 0);
  const runMutation = async (call: () => void | Promise<void>): Promise<boolean> => {
    setOperationError('');
    try {
      await call();
      focusQueue();
      return true;
    } catch (reason) {
      setOperationError(operationErrorMessage(reason));
      return false;
    }
  };
  const selectPage = (nextPage: number) => { onPageChange?.(nextPage); focusQueue(); };
  const openDetail = (term: GlossaryTerm, opener: HTMLElement) => {
    detailRequestIdRef.current += 1;
    detailAbortRef.current?.abort();
    const controller = new AbortController();
    const requestId = detailRequestIdRef.current;
    detailAbortRef.current = controller;
    detailTermIdRef.current = term.id;
    detailReturnFocusRef.current = opener;
    setDetailTerm(term);
    setDetail(null);
    setDetailError('');
    if (onLoadTermDetail) {
      void onLoadTermDetail(term.id, { signal: controller.signal })
        .then((nextDetail) => {
          if (
            !controller.signal.aborted &&
            requestId === detailRequestIdRef.current &&
            detailTermIdRef.current === term.id
          ) {
            setDetail(nextDetail);
          }
        })
        .catch((reason: unknown) => {
          if (
            !controller.signal.aborted &&
            requestId === detailRequestIdRef.current &&
            detailTermIdRef.current === term.id
          ) {
            setDetailError(String(reason));
          }
        });
    }
  };
  const closeDetail = () => {
    detailRequestIdRef.current += 1;
    detailAbortRef.current?.abort();
    detailAbortRef.current = null;
    detailTermIdRef.current = null;
    setDetailTerm(null);
    setDetail(null);
    setDetailError('');
    detailReturnFocusRef.current?.focus();
  };
  const handleDetailKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      closeDetail();
      return;
    }
    if (event.key !== 'Tab') return;
    const drawer = detailDrawerRef.current;
    if (!drawer) return;
    const focusable = Array.from(drawer.querySelectorAll<HTMLElement>(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ));
    if (focusable.length === 0) {
      event.preventDefault();
      drawer.focus();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && (document.activeElement === first || !drawer.contains(document.activeElement))) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && (document.activeElement === last || !drawer.contains(document.activeElement))) {
      event.preventDefault();
      first.focus();
    }
  };

  const localSearch = search.trim().toLowerCase();
  const rows = (onQueryChange ? glossaryTerms : glossaryTerms.filter((term) => {
    if (legacyStatus !== 'all' && normalizedReviewStatus(term) !== legacyStatus) return false;
    return !localSearch || [term.source_term, term.target_term, term.term_type, term.source_context]
      .some((value) => String(value || '').toLowerCase().includes(localSearch));
  })).slice(0, 50);
  const rangeStart = total ? (page - 1) * perPage + 1 : 0;
  const rangeEnd = total ? Math.min(page * perPage, total) : 0;
  const selectableRows = rows.filter((term) => !term.archived);
  const selectedTerms = selectableRows.filter((term) => selectedIds.has(term.id));
  const selectTerm = (term: GlossaryTerm, selected: boolean) => setSelectedIds((current) => {
    const next = new Set(current);
    if (selected) next.add(term.id); else next.delete(term.id);
    return next;
  });
  const bulk = async (action: GlossaryBulkAction) => {
    if (!onBulkAction || selectedTerms.length === 0) return;
    const succeeded = await runMutation(() => onBulkAction(action, selectedTerms.map((term) => ({
      id: term.id, expected_version: term.version ?? 0,
    }))));
    if (succeeded) setSelectedIds(new Set());
  };
  const createTerm = async () => {
    if (!onCreateTerm || !newSource.trim()) return;
    const succeeded = await runMutation(() => onCreateTerm({
      approved: 0,
      book_id: query.book_id ?? 0,
      review_status: 'NEEDS_REVIEW',
      source_term: newSource.trim(),
      target_term: newTarget.trim(),
    }));
    if (succeeded) { setNewSource(''); setNewTarget(''); }
  };
  const activeConflict = conflicts?.items.find((conflict) => conflict.id === activeConflictId) ?? null;
  const duplicateIds = activeConflict && canonicalId !== null
    ? activeConflict.members.filter((term) => term.id !== canonicalId).map((term) => term.id)
    : [];
  const loadConflicts = async (conflictPage = 1) => {
    if (!onLoadConflicts) return;
    setOperationError(''); setMergePreview(null); setActiveConflictId(null); setCanonicalId(null);
    try { setConflicts(await onLoadConflicts(conflictPage)); } catch (reason) { setOperationError(String(reason)); }
  };
  const previewMerge = async () => {
    if (!onPreviewMerge || canonicalId === null || duplicateIds.length === 0) return;
    setOperationError('');
    try { setMergePreview(await onPreviewMerge(canonicalId, duplicateIds)); } catch (reason) { setOperationError(String(reason)); }
  };
  const applyMerge = async () => {
    if (!onApplyMerge || !mergePreview) return;
    setOperationError('');
    try {
      await onApplyMerge(mergePreview.canonical_id, mergePreview.duplicate_ids, mergePreview.digest);
      setMergePreview(null); await loadConflicts();
    } catch (reason) {
      setOperationError(operationErrorMessage(reason));
    }
  };
  const previewImport = async () => {
    if (!onPreviewImport) return;
    setOperationError(''); setImportPreview(null);
    try {
      const items = parseGlossaryImportText(importText);
      setImportItems(items);
      setImportPreview(await onPreviewImport(items, importPolicy));
    } catch (reason) { setOperationError(reason instanceof Error ? reason.message : 'Dữ liệu nhập không hợp lệ.'); }
  };
  const applyImport = async () => {
    if (!onApplyImport || !importPreview) return;
    setOperationError('');
    try {
      await onApplyImport(importItems, importPreview.digest, importPolicy);
      setImportPreview(null);
    } catch (reason) {
      setOperationError(operationErrorMessage(reason));
    }
  };
  const configuredProviders = providers.filter((provider) => (
    provider.enabled === 1 && (!provider.api_key_env || provider.api_key_set)
  ));
  const saveExtractionSettings = async () => {
    if (!bookId || !onSaveExtractionSettings || !extractionLoaded) return;
    const targetBookId = bookId;
    setOperationError(''); setExtractionStatus('');
    try {
      const settings = await onSaveExtractionSettings(targetBookId, {
        mode: extractionMode,
        provider_id: extractionMode === 'hybrid' ? extractionProviderId : '',
      });
      if (extractionBookIdRef.current !== targetBookId || settings.book_id !== targetBookId) return;
      setExtractionMode(settings.mode);
      setExtractionProviderId(settings.provider_id);
      setExtractionStatus('Đã lưu cài đặt trích xuất.');
    } catch (reason) {
      if (extractionBookIdRef.current !== targetBookId) return;
      setOperationError(operationErrorMessage(reason));
    }
  };
  const reextractChapter = async () => {
    if (!bookId || !chapterId || !onReextractChapter || !extractionLoaded) return;
    const targetBookId = bookId;
    const targetChapterId = chapterId;
    setOperationError(''); setExtractionStatus('');
    try {
      const result = await onReextractChapter(targetBookId, targetChapterId);
      if (extractionBookIdRef.current !== targetBookId) return;
      setExtractionStatus(
        `${result.created} thuật ngữ mới · ${result.updated} cập nhật · ${result.warnings.length} cảnh báo`,
      );
    } catch (reason) {
      if (extractionBookIdRef.current !== targetBookId) return;
      setOperationError(operationErrorMessage(reason));
    }
  };

  return (
    <section aria-labelledby="glossary-style-title" className="workflow-management-view glossary-style-view">
      <header className="panel workbench-title glossary-reference-title">
        <div><p className="section-label">Workflow</p><h2 id="glossary-style-title">Thuật ngữ & Văn phong</h2></div>
        <div className="workflow-status"><span className="status-chip">{facets.review_status.NEEDS_REVIEW || 0} chờ duyệt</span><span className="status-chip">{facets.review_status.CONFLICT || 0} xung đột</span></div>
      </header>

      <section aria-labelledby="glossary-table-title" className="panel glossary-review-panel">
        <div className="panel-header glossary-table-header">
          <div><p className="section-label">Glossary</p><h3 id="glossary-table-title" ref={queueHeadingRef} tabIndex={-1}>Hàng chờ duyệt</h3></div>
          <label className="glossary-search"><Search aria-hidden="true" size={14} /><span className="sr-only">Tìm thuật ngữ</span><input aria-label="Tìm thuật ngữ" onChange={(event) => setSearch(event.target.value)} placeholder="Tìm thuật ngữ..." type="search" value={search} /></label>
        </div>

        <div aria-label="Trạng thái thuật ngữ" className="glossary-review-tabs" role="tablist">
          {tabs.map((tab) => <button aria-selected={Boolean(query.archived) === tab.archived && query.review_status === tab.status} key={tab.label} onClick={() => onQueryChange?.({ archived: tab.archived, page: 1, review_status: tab.status, scope: tab.archived && query.scope === 'effective' ? 'book' : query.scope })} role="tab" type="button">{tab.label}</button>)}
        </div>

        <div className="glossary-review-filters">
          <label>Phạm vi<select aria-label="Phạm vi thuật ngữ" onChange={(event) => onQueryChange?.({ page: 1, scope: event.target.value as GlossaryQuery['scope'] })} value={query.scope}><option value="book">Trong sách</option><option value="effective">Hiệu lực</option><option value="global">Toàn cục</option><option value="all">Tất cả</option></select></label>
          <label>Chế độ<select aria-label="Chế độ thuật ngữ" onChange={(event) => onQueryChange?.({ mode: event.target.value, page: 1 })} value={query.mode || ''}><option value="">Tất cả</option><option value="translate">Dịch</option><option value="transliterate">Phiên âm</option><option value="context">Ngữ cảnh</option></select></label>
          {!onQueryChange ? <label>Trạng thái<select aria-label="Lọc trạng thái thuật ngữ" onChange={(event) => setLegacyStatus(event.target.value)} value={legacyStatus}><option value="all">Tất cả</option><option value="NEEDS_REVIEW">Chờ duyệt</option><option value="APPROVED">Đã duyệt</option><option value="LOCKED">Đã khóa</option><option value="CONFLICT">Xung đột</option><option value="REJECTED">Từ chối</option></select></label> : null}
          <span className="status-chip status-chip-success">{rangeStart}–{rangeEnd} / {total}</span>
        </div>

        {onBulkAction ? (
          <div aria-label="Thao tác hàng loạt" className="glossary-review-filters" role="toolbar">
            <span>{selectedTerms.length} đã chọn</span>
            <button disabled={!selectedTerms.length} onClick={() => void bulk('approve')} type="button">Duyệt đã chọn</button>
            <button disabled={!selectedTerms.length} onClick={() => void bulk('reject')} type="button">Từ chối đã chọn</button>
            <button disabled={!selectedTerms.length} onClick={() => void bulk('lock')} type="button">Khóa đã chọn</button>
            <button disabled={!selectedTerms.length} onClick={() => void bulk('archive')} type="button">Lưu trữ đã chọn</button>
          </div>
        ) : null}

        {onCreateTerm ? (
          <details className="glossary-operation-panel">
            <summary>Tạo thuật ngữ</summary>
            <div className="glossary-review-filters">
              <label>Gốc<input aria-label="Thuật ngữ gốc mới" onChange={(event) => setNewSource(event.target.value)} value={newSource} /></label>
              <label>Bản dịch<input aria-label="Bản dịch mới" onChange={(event) => setNewTarget(event.target.value)} value={newTarget} /></label>
              <button disabled={!newSource.trim()} onClick={() => void createTerm()} type="button">Tạo thuật ngữ mới</button>
            </div>
          </details>
        ) : null}

        {loadState === 'loading' ? <p className="empty-detail" role="status">Đang tải hàng chờ…</p> : null}
        {loadState === 'error' ? <p className="empty-detail" role="alert">Không thể tải hàng chờ: {error}</p> : null}
        {loadState === 'empty' ? <p className="empty-detail">Không có thuật ngữ trong hàng chờ này.</p> : null}
        {loadState === 'ready' ? (
          <div className="glossary-table-wrap">
            <table className="provider-table glossary-management-table">
              <thead><tr><th><input aria-label="Chọn tất cả" checked={selectableRows.length > 0 && selectedTerms.length === selectableRows.length} onChange={(event) => setSelectedIds(event.target.checked ? new Set(selectableRows.map((term) => term.id)) : new Set())} type="checkbox" /></th><th>Gốc</th><th>Bản dịch</th><th>Loại</th><th>Ưu tiên</th><th>Trạng thái</th><th>Bằng chứng</th><th>Thao tác</th></tr></thead>
              <tbody>{rows.map((term) => <GlossaryRow key={term.id} onApproveTerm={(id) => runMutation(() => onApproveTerm(id))} onArchiveTerm={onArchiveTerm ? (id) => runMutation(() => onArchiveTerm(id)) : undefined} onCreateBookOverride={onCreateBookOverride ? (item) => runMutation(() => onCreateBookOverride(item)) : undefined} onDetail={openDetail} onLockToggle={(id, locked) => runMutation(() => onLockToggle(id, locked))} onRejectTerm={(id) => runMutation(() => onRejectTerm(id))} onRestoreTerm={onRestoreTerm ? (id) => runMutation(() => onRestoreTerm(id)) : undefined} onSaveAndApproveTerm={(id, updates, locked) => runMutation(() => onSaveAndApproveTerm(id, updates, locked))} onSelect={selectTerm} onUpdateTerm={(id, updates) => runMutation(() => onUpdateTerm(id, updates))} selected={selectedIds.has(term.id)} term={term} />)}</tbody>
            </table>
          </div>
        ) : null}
        <nav aria-label="Phân trang thuật ngữ" className="glossary-pagination"><button disabled={page <= 1} onClick={() => selectPage(page - 1)} type="button">Trang trước</button><span>Trang {page} / {Math.max(pages, 1)}</span><button aria-label="Trang sau" disabled={pages === 0 || page >= pages} onClick={() => selectPage(page + 1)} type="button">Trang sau</button></nav>
      </section>

      {onLoadConflicts && onPreviewMerge && onApplyMerge ? (
        <details className="panel glossary-operation-panel">
          <summary>Xung đột & hợp nhất</summary>
          <button onClick={() => void loadConflicts()} type="button">Tải xung đột</button>
          {conflicts?.items.map((conflict) => (
            <fieldset key={conflict.id}>
              <legend>{conflict.types.join(' · ')}</legend>
              {conflict.members_truncated ? (
                <p>Đang hiển thị lô {conflict.members.length}/{conflict.member_total} thành viên. Hợp nhất lô này rồi lặp lại để xử lý phần còn lại.</p>
              ) : null}
              {conflict.members.map((term) => (
                <label key={term.id}>
                  <input aria-label={`Chọn canonical ${term.source_term}`} checked={activeConflictId === conflict.id && canonicalId === term.id} name="glossary-canonical" onChange={() => { setActiveConflictId(conflict.id); setCanonicalId(term.id); setMergePreview(null); }} type="radio" />
                  {term.source_term} → {term.target_term} · {term.book_id === 0 ? 'Toàn cục' : 'Trong sách'} · v{term.version ?? 0}{term.id === conflict.canonical_id ? ' · canonical mặc định' : ''}
                </label>
              ))}
            </fieldset>
          ))}
          {activeConflict ? <button onClick={() => void previewMerge()} type="button">Xem trước hợp nhất</button> : null}
          {mergePreview ? (
            <div role="status">
              <p>{mergePreview.evidence_count ?? 0} bằng chứng sẽ chuyển sang canonical.</p>
              <button onClick={() => void applyMerge()} type="button">Áp dụng hợp nhất</button>
            </div>
          ) : null}
          {conflicts && conflicts.pages > 1 ? (
            <nav aria-label="Phân trang xung đột" className="glossary-pagination">
              <button aria-label="Trang xung đột trước" disabled={conflicts.page <= 1} onClick={() => void loadConflicts(conflicts.page - 1)} type="button">Trang trước</button>
              <span>Trang {conflicts.page} / {conflicts.pages}</span>
              <button aria-label="Trang xung đột sau" disabled={conflicts.page >= conflicts.pages} onClick={() => void loadConflicts(conflicts.page + 1)} type="button">Trang sau</button>
            </nav>
          ) : null}
          {conflicts && conflicts.items.length === 0 ? <p>Không có xung đột.</p> : null}
        </details>
      ) : null}

      {onPreviewImport && onApplyImport && onExport ? (
        <details className="panel glossary-operation-panel">
          <summary>Nhập & xuất</summary>
          <label>Dữ liệu JSON hoặc CSV<textarea aria-label="Dữ liệu nhập JSON hoặc CSV" onChange={(event) => { setImportText(event.target.value); setImportPreview(null); }} value={importText} /></label>
          <label>Chính sách xung đột<select aria-label="Chính sách xung đột" onChange={(event) => { setImportPolicy(event.target.value as GlossaryImportPolicy); setImportPreview(null); }} value={importPolicy}><option value="skip_conflicts">Bỏ qua xung đột</option><option value="reject_conflicts">Từ chối toàn bộ khi có xung đột</option></select></label>
          <div className="dialog-actions">
            <button onClick={() => void previewImport()} type="button">Xem trước nhập</button>
            <button onClick={() => void runMutation(() => onExport('json'))} type="button">Xuất JSON</button>
            <button onClick={() => void runMutation(() => onExport('csv'))} type="button">Xuất CSV</button>
          </div>
          {importPreview ? (
            <div role="status">
              <p>Thêm {importPreview.summary.added} · Cập nhật {importPreview.summary.updated} · Bỏ qua {importPreview.summary.skipped}</p>
              <button onClick={() => void applyImport()} type="button">Áp dụng nhập</button>
            </div>
          ) : null}
        </details>
      ) : null}

      {bookId && onLoadExtractionSettings && onSaveExtractionSettings ? (
        <details className="panel glossary-operation-panel" onToggle={(event) => {
          if (event.currentTarget.open && !extractionLoaded) void loadExtractionSettings(bookId);
        }} ref={extractionPanelRef}>
          <summary>Trích xuất thuật ngữ</summary>
          <div className="glossary-review-filters">
            <label>Chế độ trích xuất<select aria-label="Chế độ trích xuất" disabled={!extractionLoaded} onChange={(event) => setExtractionMode(event.target.value as BookGlossarySettings['mode'])} value={extractionMode}><option value="deterministic">Deterministic</option><option value="hybrid">Hybrid</option></select></label>
            {extractionMode === 'hybrid' ? <label>Provider trích xuất<select aria-label="Provider trích xuất" disabled={!extractionLoaded} onChange={(event) => setExtractionProviderId(event.target.value)} value={extractionProviderId}><option value="">Chọn provider</option>{configuredProviders.map((provider) => <option key={provider.id} value={provider.id}>{provider.label}</option>)}</select></label> : null}
            <button disabled={!extractionLoaded || (extractionMode === 'hybrid' && !extractionProviderId)} onClick={() => void saveExtractionSettings()} type="button">Lưu cài đặt trích xuất</button>
            {chapterId && onReextractChapter ? <button disabled={!extractionLoaded} onClick={() => void reextractChapter()} type="button">Trích xuất lại chương</button> : null}
          </div>
          {extractionStatus ? <p role="status">{extractionStatus}</p> : null}
        </details>
      ) : null}

      {operationError ? <p role="alert">{operationError}</p> : null}

      <details className="panel style-profile-reference-panel">
        <summary>Profile văn phong (phụ)</summary>
        <label><span>Profile văn phong</span><select disabled={!profiles.length} onChange={(event) => onProfileChange(event.target.value)} value={profiles.length ? selectedProfileId : ''}>{!profiles.length ? <option value="">Chưa có profile</option> : null}{profiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.label}</option>)}</select></label>
        {selectedProfile ? <dl className="estimate-grid"><div><dt><UserRound aria-hidden="true" size={17} /> Quy tắc xưng hô</dt><dd>{selectedProfile.pronoun_rules || 'Chưa cấu hình'}</dd></div><div><dt><Sparkles aria-hidden="true" size={17} /> Mức Hán Việt</dt><dd>{selectedProfile.han_viet_level || 'Chưa cấu hình'}</dd></div><div><dt><BookMarked aria-hidden="true" size={17} /> Thuật ngữ ưu tiên</dt><dd>{selectedProfile.preferred_terms || 'Chưa cấu hình'}</dd></div><div><dt><ShieldCheck aria-hidden="true" size={17} /> Từ hiện đại cần tránh</dt><dd>{selectedProfile.banned_modern_terms || 'Chưa cấu hình'}</dd></div><div><dt><BookMarked aria-hidden="true" size={17} /> Quy tắc biên tập</dt><dd>{selectedProfile.prompt_rules || 'Chưa cấu hình'}</dd></div><div><dt><Sparkles aria-hidden="true" size={17} /> Xử lý thơ/thành ngữ</dt><dd>{literaryRuleSummary}</dd></div></dl> : <p className="empty-detail">Chưa có profile văn phong</p>}
      </details>

      {detailTerm ? (
        <aside aria-label={`Chi tiết ${detailTerm.source_term}`} aria-modal="true" className="glossary-detail-drawer" onKeyDown={handleDetailKeyDown} ref={detailDrawerRef} role="dialog" tabIndex={-1}>
          <header><h3>Chi tiết {detailTerm.source_term}</h3><button aria-label="Đóng chi tiết" onClick={closeDetail} ref={detailCloseButtonRef} type="button"><X aria-hidden="true" /></button></header>
          {detailError ? <p role="alert">{detailError}</p> : null}{!detail && !detailError ? <p role="status">Đang tải chi tiết…</p> : null}
          {detail ? (
            <>
              <dl className="glossary-detail-metadata">
                {Object.entries(detail)
                  .filter(([key]) => !['evidence', 'history'].includes(key))
                  .map(([key, value]) => (
                    <div key={key}><dt>{key}</dt><dd>{typeof value === 'object' ? JSON.stringify(value) : String(value ?? '')}</dd></div>
                  ))}
              </dl>
              <h4>Bằng chứng</h4>
              {detail.evidence.length ? (
                <ul>{detail.evidence.map((item) => (
                  <li key={item.id}>
                    {item.evidence_type} · {item.extractor} · {item.created_at}
                    {item.evidence ? <pre>{JSON.stringify(item.evidence, null, 2)}</pre> : null}
                  </li>
                ))}</ul>
              ) : <p>Không có bằng chứng.</p>}
              <h4>Lịch sử</h4>
              {detail.history.length ? (
                <ol>{detail.history.map((item) => (
                  <li key={item.id}>
                    {item.action} · {item.actor} · {item.request_id} · v{item.version} · {item.timestamp || item.created_at || ''}
                    {item.before ? <pre>before: {JSON.stringify(item.before, null, 2)}</pre> : null}
                    {item.after ? <pre>after: {JSON.stringify(item.after, null, 2)}</pre> : null}
                  </li>
                ))}</ol>
              ) : <p>Không có lịch sử.</p>}
            </>
          ) : null}
        </aside>
      ) : null}
    </section>
  );
}
