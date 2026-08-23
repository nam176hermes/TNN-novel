import { BookMarked, Search, ShieldCheck, Sparkles, UserRound, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import type {
  GlossaryFacets,
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
  onCreateBookOverride?(term: GlossaryTerm): void | Promise<void>;
  onLoadTermDetail?(termId: number): Promise<GlossaryTermDetail>;
  onLockToggle(termId: number, locked: boolean): void | Promise<void>;
  onPageChange?(page: number): void;
  onProfileChange(profileId: string): void;
  onQueryChange?(updates: Partial<GlossaryQuery>): void;
  onRejectTerm(termId: number): void | Promise<void>;
  onSaveAndApproveTerm(termId: number, updates: GlossaryTermUpdate, locked: boolean): void | Promise<void>;
  onUpdateTerm(termId: number, updates: GlossaryTermUpdate): void | Promise<void>;
};

type GlossaryRowProps = {
  term: GlossaryTerm;
  onApproveTerm(termId: number): void | Promise<void>;
  onCreateBookOverride?(term: GlossaryTerm): void | Promise<void>;
  onDetail(term: GlossaryTerm, opener: HTMLElement): void;
  onLockToggle(termId: number, locked: boolean): void | Promise<void>;
  onRejectTerm(termId: number): void | Promise<void>;
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
  onCreateBookOverride,
  onDetail,
  onLockToggle,
  onRejectTerm,
  onSaveAndApproveTerm,
  onUpdateTerm,
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
          {isPending(term) ? (
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
          <button aria-label={`Chi tiết ${term.source_term}`} className="secondary-action" onClick={(event) => onDetail(term, event.currentTarget)} type="button">Chi tiết</button>
        </div>
      </td>
    </tr>
  );
}

const literaryRuleSummary = 'Dịch theo nghĩa và khí văn; giữ nhịp thơ/đối liên; ưu tiên thành ngữ Việt cổ phong khi có.';
const tabs = [
  ['NEEDS_REVIEW,CONFLICT', 'Cần duyệt'], ['APPROVED', 'Đã duyệt'], ['LOCKED', 'Đã khóa'], ['REJECTED', 'Từ chối'], ['', 'Tất cả'],
] as const;

export default function GlossaryStyleView({
  profiles, selectedProfileId, glossaryTerms, error = '', facets = emptyFacets,
  loadState = glossaryTerms.length ? 'ready' : 'empty', page = 1, pages = 0, perPage = 50,
  query = fallbackQuery, total = glossaryTerms.length, onApproveTerm, onCreateBookOverride,
  onLoadTermDetail, onLockToggle, onPageChange, onProfileChange, onQueryChange, onRejectTerm,
  onSaveAndApproveTerm, onUpdateTerm,
}: GlossaryStyleViewProps) {
  const selectedProfile = profiles.find((profile) => profile.id === selectedProfileId) ?? null;
  const [search, setSearch] = useState(query.q);
  const [legacyStatus, setLegacyStatus] = useState('all');
  const [detail, setDetail] = useState<GlossaryTermDetail | null>(null);
  const [detailTerm, setDetailTerm] = useState<GlossaryTerm | null>(null);
  const [detailError, setDetailError] = useState('');
  const queueHeadingRef = useRef<HTMLHeadingElement | null>(null);
  const detailReturnFocusRef = useRef<HTMLElement | null>(null);
  const lastSearchRef = useRef(query.q);

  useEffect(() => setSearch(query.q), [query.q]);
  useEffect(() => {
    if (!onQueryChange || search === lastSearchRef.current) return;
    const timer = window.setTimeout(() => {
      lastSearchRef.current = search;
      onQueryChange({ page: 1, q: search });
    }, 250);
    return () => window.clearTimeout(timer);
  }, [onQueryChange, search]);

  const focusQueue = () => window.setTimeout(() => queueHeadingRef.current?.focus(), 0);
  const runMutation = async (call: () => void | Promise<void>) => { await call(); focusQueue(); };
  const selectPage = (nextPage: number) => { onPageChange?.(nextPage); focusQueue(); };
  const openDetail = (term: GlossaryTerm, opener: HTMLElement) => {
    detailReturnFocusRef.current = opener;
    setDetailTerm(term);
    setDetail(null);
    setDetailError('');
    if (onLoadTermDetail) void onLoadTermDetail(term.id).then(setDetail).catch((reason: unknown) => setDetailError(String(reason)));
  };
  const closeDetail = () => { setDetailTerm(null); setDetail(null); detailReturnFocusRef.current?.focus(); };

  const localSearch = search.trim().toLowerCase();
  const rows = (onQueryChange ? glossaryTerms : glossaryTerms.filter((term) => {
    if (legacyStatus !== 'all' && normalizedReviewStatus(term) !== legacyStatus) return false;
    return !localSearch || [term.source_term, term.target_term, term.term_type, term.source_context]
      .some((value) => String(value || '').toLowerCase().includes(localSearch));
  })).slice(0, 50);
  const rangeStart = total ? (page - 1) * perPage + 1 : 0;
  const rangeEnd = total ? Math.min(page * perPage, total) : 0;

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
          {tabs.map(([status, label]) => <button aria-selected={query.review_status === status} key={label} onClick={() => onQueryChange?.({ page: 1, review_status: status })} role="tab" type="button">{label}</button>)}
        </div>

        <div className="glossary-review-filters">
          <label>Phạm vi<select aria-label="Phạm vi thuật ngữ" onChange={(event) => onQueryChange?.({ page: 1, scope: event.target.value as GlossaryQuery['scope'] })} value={query.scope}><option value="book">Trong sách</option><option value="effective">Hiệu lực</option><option value="global">Toàn cục</option><option value="all">Tất cả</option></select></label>
          <label>Chế độ<select aria-label="Chế độ thuật ngữ" onChange={(event) => onQueryChange?.({ mode: event.target.value, page: 1 })} value={query.mode || ''}><option value="">Tất cả</option><option value="translate">Dịch</option><option value="transliterate">Phiên âm</option><option value="context">Ngữ cảnh</option></select></label>
          {!onQueryChange ? <label>Trạng thái<select aria-label="Lọc trạng thái thuật ngữ" onChange={(event) => setLegacyStatus(event.target.value)} value={legacyStatus}><option value="all">Tất cả</option><option value="NEEDS_REVIEW">Chờ duyệt</option><option value="APPROVED">Đã duyệt</option><option value="LOCKED">Đã khóa</option><option value="CONFLICT">Xung đột</option><option value="REJECTED">Từ chối</option></select></label> : null}
          <span className="status-chip status-chip-success">{rangeStart}–{rangeEnd} / {total}</span>
        </div>

        {loadState === 'loading' ? <p className="empty-detail" role="status">Đang tải hàng chờ…</p> : null}
        {loadState === 'error' ? <p className="empty-detail" role="alert">Không thể tải hàng chờ: {error}</p> : null}
        {loadState === 'empty' ? <p className="empty-detail">Không có thuật ngữ trong hàng chờ này.</p> : null}
        {loadState === 'ready' ? (
          <div className="glossary-table-wrap">
            <table className="provider-table glossary-management-table">
              <thead><tr><th>Gốc</th><th>Bản dịch</th><th>Loại</th><th>Ưu tiên</th><th>Trạng thái</th><th>Bằng chứng</th><th>Thao tác</th></tr></thead>
              <tbody>{rows.map((term) => <GlossaryRow key={term.id} onApproveTerm={(id) => runMutation(() => onApproveTerm(id))} onCreateBookOverride={onCreateBookOverride ? (item) => runMutation(() => onCreateBookOverride(item)) : undefined} onDetail={openDetail} onLockToggle={(id, locked) => runMutation(() => onLockToggle(id, locked))} onRejectTerm={(id) => runMutation(() => onRejectTerm(id))} onSaveAndApproveTerm={(id, updates, locked) => runMutation(() => onSaveAndApproveTerm(id, updates, locked))} onUpdateTerm={(id, updates) => runMutation(() => onUpdateTerm(id, updates))} term={term} />)}</tbody>
            </table>
          </div>
        ) : null}
        <nav aria-label="Phân trang thuật ngữ" className="glossary-pagination"><button disabled={page <= 1} onClick={() => selectPage(page - 1)} type="button">Trang trước</button><span>Trang {page} / {Math.max(pages, 1)}</span><button aria-label="Trang sau" disabled={pages === 0 || page >= pages} onClick={() => selectPage(page + 1)} type="button">Trang sau</button></nav>
      </section>

      <details className="panel style-profile-reference-panel">
        <summary>Profile văn phong (phụ)</summary>
        <label><span>Profile văn phong</span><select disabled={!profiles.length} onChange={(event) => onProfileChange(event.target.value)} value={profiles.length ? selectedProfileId : ''}>{!profiles.length ? <option value="">Chưa có profile</option> : null}{profiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.label}</option>)}</select></label>
        {selectedProfile ? <dl className="estimate-grid"><div><dt><UserRound aria-hidden="true" size={17} /> Quy tắc xưng hô</dt><dd>{selectedProfile.pronoun_rules || 'Chưa cấu hình'}</dd></div><div><dt><Sparkles aria-hidden="true" size={17} /> Mức Hán Việt</dt><dd>{selectedProfile.han_viet_level || 'Chưa cấu hình'}</dd></div><div><dt><BookMarked aria-hidden="true" size={17} /> Thuật ngữ ưu tiên</dt><dd>{selectedProfile.preferred_terms || 'Chưa cấu hình'}</dd></div><div><dt><ShieldCheck aria-hidden="true" size={17} /> Từ hiện đại cần tránh</dt><dd>{selectedProfile.banned_modern_terms || 'Chưa cấu hình'}</dd></div><div><dt><BookMarked aria-hidden="true" size={17} /> Quy tắc biên tập</dt><dd>{selectedProfile.prompt_rules || 'Chưa cấu hình'}</dd></div><div><dt><Sparkles aria-hidden="true" size={17} /> Xử lý thơ/thành ngữ</dt><dd>{literaryRuleSummary}</dd></div></dl> : <p className="empty-detail">Chưa có profile văn phong</p>}
      </details>

      {detailTerm ? (
        <aside aria-label={`Chi tiết ${detailTerm.source_term}`} aria-modal="true" className="glossary-detail-drawer" role="dialog">
          <header><h3>Chi tiết {detailTerm.source_term}</h3><button aria-label="Đóng chi tiết" onClick={closeDetail} type="button"><X aria-hidden="true" /></button></header>
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
