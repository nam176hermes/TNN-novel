import { BookMarked, Search, ShieldCheck, Sparkles, UserRound, X } from 'lucide-react';
import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import type {
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

export type GlossaryStyleViewProps = {
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
  onApplyImport?(items: GlossaryImportItem[], digest: string): void | Promise<void>;
  onApplyMerge?(canonicalId: number, duplicateIds: number[], digest: string): void | Promise<void>;
  onArchiveTerm?(termId: number): void | Promise<void>;
  onBulkAction?(action: GlossaryBulkAction, terms: GlossaryBulkTermRef[]): void | Promise<void>;
  onCreateTerm?(term: GlossaryImportItem): void | Promise<void>;
  onCreateBookOverride?(term: GlossaryTerm): void | Promise<void>;
  onExport?(format: 'json' | 'csv'): void | Promise<void>;
  onLoadConflicts?(page?: number): Promise<GlossaryConflictPage>;
  onLoadTermDetail?(termId: number, options?: { signal?: AbortSignal }): Promise<GlossaryTermDetail>;
  onLockToggle(termId: number, locked: boolean): void | Promise<void>;
  onPageChange?(page: number): void;
  onProfileChange(profileId: string): void;
  onPreviewImport?(items: GlossaryImportItem[]): Promise<GlossaryImportPreview>;
  onPreviewMerge?(canonicalId: number, duplicateIds: number[]): Promise<GlossaryMergePreview>;
  onQueryChange?(updates: Partial<GlossaryQuery>): void;
  onRejectTerm(termId: number): void | Promise<void>;
  onRestoreTerm?(termId: number): void | Promise<void>;
  onSaveAndApproveTerm(termId: number, updates: GlossaryTermUpdate, locked: boolean): void | Promise<void>;
  onUpdateTerm(termId: number, updates: GlossaryTermUpdate): void | Promise<void>;
};

type GlossaryRowProps = {
  term: GlossaryTerm;
  onApproveTerm(termId: number): void | Promise<void>;
  onArchiveTerm?(termId: number): void | Promise<void>;
  onCreateBookOverride?(term: GlossaryTerm): void | Promise<void>;
  onDetail(term: GlossaryTerm, opener: HTMLElement): void;
  onLockToggle(termId: number, locked: boolean): void | Promise<void>;
  onRejectTerm(termId: number): void | Promise<void>;
  onRestoreTerm?(termId: number): void | Promise<void>;
  onSelect(term: GlossaryTerm, selected: boolean): void;
  selected: boolean;
  onSaveAndApproveTerm(termId: number, updates: GlossaryTermUpdate, locked: boolean): void | Promise<void>;
  onUpdateTerm(termId: number, updates: GlossaryTermUpdate): void | Promise<void>;
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
  profiles, selectedProfileId, glossaryTerms, error = '', facets = emptyFacets,
  loadState = glossaryTerms.length ? 'ready' : 'empty', page = 1, pages = 0, perPage = 50,
  query = fallbackQuery, total = glossaryTerms.length, onApproveTerm, onCreateBookOverride,
  onApplyImport, onApplyMerge, onArchiveTerm, onBulkAction, onCreateTerm, onExport,
  onLoadConflicts, onLoadTermDetail, onLockToggle, onPageChange, onPreviewImport,
  onPreviewMerge, onProfileChange, onQueryChange, onRejectTerm, onRestoreTerm,
  onSaveAndApproveTerm, onUpdateTerm,
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
  const queueHeadingRef = useRef<HTMLHeadingElement | null>(null);
  const detailDrawerRef = useRef<HTMLElement | null>(null);
  const detailCloseButtonRef = useRef<HTMLButtonElement | null>(null);
  const detailReturnFocusRef = useRef<HTMLElement | null>(null);
  const detailAbortRef = useRef<AbortController | null>(null);
  const detailRequestIdRef = useRef(0);
  const detailTermIdRef = useRef<number | null>(null);
  const lastSearchRef = useRef(query.q);

  useEffect(() => setSearch(query.q), [query.q]);
  useEffect(() => setSelectedIds(new Set()), [glossaryTerms]);
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
  }, []);

  const focusQueue = () => window.setTimeout(() => queueHeadingRef.current?.focus(), 0);
  const runMutation = async (call: () => void | Promise<void>) => { await call(); focusQueue(); };
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
    await runMutation(() => onBulkAction(action, selectedTerms.map((term) => ({
      id: term.id, expected_version: term.version ?? 0,
    }))));
    setSelectedIds(new Set());
  };
  const createTerm = async () => {
    if (!onCreateTerm || !newSource.trim()) return;
    await runMutation(() => onCreateTerm({
      approved: 0,
      book_id: query.book_id ?? 0,
      review_status: 'NEEDS_REVIEW',
      source_term: newSource.trim(),
      target_term: newTarget.trim(),
    }));
    setNewSource(''); setNewTarget('');
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
    await onApplyMerge(mergePreview.canonical_id, mergePreview.duplicate_ids, mergePreview.digest);
    setMergePreview(null); await loadConflicts();
  };
  const previewImport = async () => {
    if (!onPreviewImport) return;
    setOperationError(''); setImportPreview(null);
    try {
      const parsed: unknown = JSON.parse(importText);
      if (!Array.isArray(parsed)) throw new Error('Dữ liệu nhập phải là danh sách JSON.');
      const items = parsed as GlossaryImportItem[];
      setImportItems(items);
      setImportPreview(await onPreviewImport(items));
    } catch (reason) { setOperationError(reason instanceof Error ? reason.message : 'Dữ liệu nhập không hợp lệ.'); }
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
              {conflict.members.map((term) => (
                <label key={term.id}>
                  <input aria-label={`Chọn canonical ${term.source_term}`} checked={activeConflictId === conflict.id && canonicalId === term.id} name="glossary-canonical" onChange={() => { setActiveConflictId(conflict.id); setCanonicalId(term.id); setMergePreview(null); }} type="radio" />
                  {term.source_term} → {term.target_term} · {term.book_id === 0 ? 'Toàn cục' : 'Trong sách'} · v{term.version ?? 0}
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
          <label>Dữ liệu JSON<textarea aria-label="Dữ liệu nhập JSON" onChange={(event) => { setImportText(event.target.value); setImportPreview(null); }} value={importText} /></label>
          <div className="dialog-actions">
            <button onClick={() => void previewImport()} type="button">Xem trước nhập</button>
            <button onClick={() => void onExport('json')} type="button">Xuất JSON</button>
            <button onClick={() => void onExport('csv')} type="button">Xuất CSV</button>
          </div>
          {importPreview ? (
            <div role="status">
              <p>Thêm {importPreview.summary.added} · Cập nhật {importPreview.summary.updated} · Bỏ qua {importPreview.summary.skipped}</p>
              <button onClick={() => void onApplyImport(importItems, importPreview.digest)} type="button">Áp dụng nhập</button>
            </div>
          ) : null}
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
