import {
  BookMarked,
  Filter,
  MoreVertical,
  Search,
  ShieldCheck,
  Sparkles,
  UserRound,
} from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import type { GlossaryTerm, GlossaryTermUpdate, StyleProfile } from '../api/types';
import { useWindowedList } from '../hooks/useWindowedList';

export type GlossaryStyleViewProps = {
  profiles: StyleProfile[];
  selectedProfileId: string;
  glossaryTerms: GlossaryTerm[];
  onApproveTerm(termId: number): void;
  onProfileChange(profileId: string): void;
  onRejectTerm(termId: number): void;
  onSaveAndApproveTerm(termId: number, updates: GlossaryTermUpdate, locked: boolean): void;
  onUpdateTerm(termId: number, updates: GlossaryTermUpdate): void;
  onLockToggle(termId: number, locked: boolean): void;
};

type GlossaryRowProps = {
  rowIndex: number;
  term: GlossaryTerm;
  onApproveTerm(termId: number): void;
  onRejectTerm(termId: number): void;
  onSaveAndApproveTerm(termId: number, updates: GlossaryTermUpdate, locked: boolean): void;
  onUpdateTerm(termId: number, updates: GlossaryTermUpdate): void;
  onLockToggle(termId: number, locked: boolean): void;
};

function isLocked(term: GlossaryTerm): boolean {
  return term.locked === 1 || normalizedReviewStatus(term) === 'LOCKED';
}

function isPending(term: GlossaryTerm): boolean {
  return ['NEEDS_REVIEW', 'CONFLICT'].includes(normalizedReviewStatus(term));
}

function normalizedReviewStatus(term: GlossaryTerm): string {
  const explicit = String(term.review_status ?? '').trim().toUpperCase();
  if (explicit) return explicit;
  if (term.locked === 1) return 'LOCKED';
  if (term.approved === -1) return 'REJECTED';
  if (term.approved === 1) return 'APPROVED';
  return 'NEEDS_REVIEW';
}

function statusLabel(term: GlossaryTerm): string {
  switch (normalizedReviewStatus(term)) {
    case 'LOCKED':
      return 'Đã khóa';
    case 'APPROVED':
      return 'Đã duyệt';
    case 'REJECTED':
      return 'Từ chối';
    case 'CONFLICT':
      return 'Xung đột';
    default:
      return 'Chờ duyệt';
  }
}

function lockLabel(term: GlossaryTerm): string {
  return isLocked(term) ? 'Đã khóa' : 'Chưa khóa';
}

const literaryRuleSummary =
  'Dịch theo nghĩa và khí văn; giữ nhịp thơ/đối liên; ưu tiên thành ngữ Việt cổ phong khi có.';

function GlossaryRow({
  rowIndex,
  term,
  onApproveTerm,
  onRejectTerm,
  onSaveAndApproveTerm,
  onUpdateTerm,
  onLockToggle,
}: GlossaryRowProps) {
  const [targetTerm, setTargetTerm] = useState(term.target_term);
  const [termType, setTermType] = useState(term.term_type || term.category || 'term');
  const [genre, setGenre] = useState(term.genre || '');
  const [priority, setPriority] = useState(String(term.priority ?? 0));
  const locked = isLocked(term);

  useEffect(() => {
    setTargetTerm(term.target_term);
    setTermType(term.term_type || term.category || 'term');
    setGenre(term.genre || '');
    setPriority(String(term.priority ?? 0));
  }, [term]);

  function buildUpdates(): GlossaryTermUpdate {
    return {
      target_term: targetTerm,
      genre,
      priority: Number(priority) || 0,
      term_type: termType,
    };
  }

  function saveTerm(): void {
    onUpdateTerm(term.id, buildUpdates());
  }

  return (
    <tr aria-rowindex={rowIndex + 2} data-virtual-index={rowIndex}>
      <th scope="row">
        <span>{term.source_term}</span>
        {term.first_seen_chapter_number ? (
          <small className="glossary-row-context">Ch. {term.first_seen_chapter_number}</small>
        ) : null}
        {term.source_context ? (
          <small className="glossary-row-context">{term.source_context}</small>
        ) : null}
      </th>
      <td>
        <input
          aria-label={`Bản dịch cho ${term.source_term}`}
          onChange={(event) => setTargetTerm(event.target.value)}
          value={targetTerm}
        />
      </td>
      <td>
        <select
          aria-label={`Loại thuật ngữ cho ${term.source_term}`}
          onChange={(event) => setTermType(event.target.value)}
          value={termType}
        >
          <option value="term">Thuật ngữ</option>
          <option value="character">Nhân vật</option>
          <option value="realm">Cảnh giới</option>
          <option value="artifact">Pháp bảo</option>
          <option value="technique">Thuật pháp</option>
          <option value="sect">Môn phái</option>
          <option value="place">Địa danh</option>
          <option value="title">Danh xưng</option>
          <option value="concept">Khái niệm</option>
        </select>
      </td>
      <td>
        <input
          aria-label={`Thể loại cho ${term.source_term}`}
          onChange={(event) => setGenre(event.target.value)}
          value={genre}
        />
      </td>
      <td>
        <input
          aria-label={`Ưu tiên cho ${term.source_term}`}
          min="0"
          onChange={(event) => setPriority(event.target.value)}
          type="number"
          value={priority}
        />
      </td>
      <td>
        <span
          className={
            normalizedReviewStatus(term) === 'REJECTED'
              ? 'status-chip status-chip-danger'
              : isPending(term)
                ? 'status-chip status-chip-warning'
                : 'status-chip status-chip-success'
          }
        >
          {statusLabel(term)}
        </span>
      </td>
      <td>
        <span className={locked ? 'status-chip' : 'status-chip status-chip-muted'}>{lockLabel(term)}</span>
      </td>
      <td>
        <div className="dialog-actions">
          {isPending(term) ? (
            <>
              <button aria-label={`Duyệt ${term.source_term}`} className="primary-action" onClick={() => onApproveTerm(term.id)} type="button">
                Duyệt
              </button>
              <button aria-label={`Từ chối ${term.source_term}`} className="danger-action" onClick={() => onRejectTerm(term.id)} type="button">
                Từ chối
              </button>
              <button
                aria-label={`Lưu + Duyệt ${term.source_term}`}
                className="secondary-action glossary-pending-extra"
                onClick={() => onSaveAndApproveTerm(term.id, buildUpdates(), false)}
                type="button"
              >
                Lưu thay đổi
              </button>
              <button
                aria-label={`Lưu + Duyệt + Khóa ${term.source_term}`}
                className="secondary-action glossary-pending-extra"
                onClick={() => onSaveAndApproveTerm(term.id, buildUpdates(), true)}
                type="button"
              >
                Khóa thuật ngữ
              </button>
            </>
          ) : (
            <>
              <button aria-label={`Lưu thay đổi ${term.source_term}`} className="secondary-action" onClick={saveTerm} type="button">
                Lưu thay đổi
              </button>
              <button
                aria-label={`${locked ? 'Mở khóa' : 'Khóa thuật ngữ'} ${term.source_term}`}
                className={locked ? 'secondary-action' : 'primary-action'}
                onClick={() => onLockToggle(term.id, !locked)}
                type="button"
              >
                {locked ? 'Mở khóa' : 'Khóa thuật ngữ'}
              </button>
            </>
          )}
          <button
            aria-label={`${locked ? 'Mở khóa nhanh' : 'Khóa nhanh'} ${term.source_term}`}
            className="icon-action glossary-row-menu"
            onClick={() => onLockToggle(term.id, !locked)}
            title={locked ? 'Mở khóa nhanh' : 'Khóa nhanh'}
            type="button"
          >
            <MoreVertical aria-hidden="true" size={14} />
          </button>
        </div>
      </td>
    </tr>
  );
}

export default function GlossaryStyleView({
  profiles,
  selectedProfileId,
  glossaryTerms,
  onApproveTerm,
  onProfileChange,
  onRejectTerm,
  onSaveAndApproveTerm,
  onUpdateTerm,
  onLockToggle,
}: GlossaryStyleViewProps) {
  const pendingCount = glossaryTerms.filter(isPending).length;
  const lockedCount = glossaryTerms.filter(isLocked).length;
  const selectedProfile = profiles.find((profile) => profile.id === selectedProfileId) ?? null;
  const selectedValue = profiles.length > 0 ? selectedProfileId : '';
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const normalizedSearch = searchQuery.trim().toLowerCase();
  const visibleTerms = glossaryTerms.filter((term) => {
    if (statusFilter !== 'all' && normalizedReviewStatus(term) !== statusFilter) return false;
    if (!normalizedSearch) return true;
    return [
      term.source_term,
      term.target_term,
      term.category,
      term.term_type,
      term.genre,
      term.review_status,
      term.source_context,
    ].some((value) => String(value ?? '').toLowerCase().includes(normalizedSearch));
  });
  const glossaryWindow = useWindowedList({
    count: visibleTerms.length,
    estimateSize: 118,
    measureItems: true,
    resetKey: `${statusFilter}:${normalizedSearch}:${visibleTerms.length}`,
  });
  const windowedTerms = visibleTerms.slice(glossaryWindow.startIndex, glossaryWindow.endIndex);

  return (
    <section aria-labelledby="glossary-style-title" className="workflow-management-view glossary-style-view">
      <header className="panel workbench-title glossary-reference-title">
        <div>
          <p className="section-label">Workflow</p>
          <h2 id="glossary-style-title">Thuật ngữ & Văn phong</h2>
        </div>
        <div className="workflow-status">
          <span className="status-chip">{pendingCount} thuật ngữ chờ duyệt</span>
          <span className="status-chip">{lockedCount} thuật ngữ đã khóa</span>
        </div>
      </header>

      <section aria-labelledby="style-profile-title" className="panel style-profile-reference-panel">
        <div className="panel-header">
          <div>
            <p className="section-label">Văn phong</p>
            <h3 id="style-profile-title">Profile đang dùng</h3>
          </div>
        </div>

        <label>
          <span>Profile văn phong</span>
          <select
            disabled={profiles.length === 0}
            onChange={(event) => onProfileChange(event.target.value)}
            value={selectedValue}
          >
            {profiles.length === 0 ? <option value="">Chưa có profile</option> : null}
            {profiles.map((profile) => (
              <option key={profile.id} value={profile.id}>
                {profile.label}
              </option>
            ))}
          </select>
        </label>

        {selectedProfile ? (
          <dl className="estimate-grid">
            <div>
              <dt><UserRound aria-hidden="true" size={17} /> Quy tắc xưng hô</dt>
              <dd>{selectedProfile.pronoun_rules || 'Chưa cấu hình'}</dd>
            </div>
            <div>
              <dt><Sparkles aria-hidden="true" size={17} /> Mức Hán Việt</dt>
              <dd>{selectedProfile.han_viet_level || 'Chưa cấu hình'}</dd>
            </div>
            <div>
              <dt><BookMarked aria-hidden="true" size={17} /> Thuật ngữ ưu tiên</dt>
              <dd>{selectedProfile.preferred_terms || 'Chưa cấu hình'}</dd>
            </div>
            <div>
              <dt><ShieldCheck aria-hidden="true" size={17} /> Từ hiện đại cần tránh</dt>
              <dd>{selectedProfile.banned_modern_terms || 'Chưa cấu hình'}</dd>
            </div>
            <div>
              <dt><BookMarked aria-hidden="true" size={17} /> Quy tắc biên tập</dt>
              <dd>{selectedProfile.prompt_rules || 'Chưa cấu hình'}</dd>
            </div>
            <div>
              <dt><Sparkles aria-hidden="true" size={17} /> Xử lý thơ/thành ngữ</dt>
              <dd>{literaryRuleSummary}</dd>
            </div>
          </dl>
        ) : (
          <p className="empty-detail">Chưa có profile văn phong</p>
        )}
      </section>

      <section aria-labelledby="glossary-table-title" className="panel">
        <div className="panel-header glossary-table-header">
          <div>
            <p className="section-label">Glossary</p>
            <h3 id="glossary-table-title">Bảng thuật ngữ</h3>
          </div>
          <div className="glossary-toolbar" aria-label="Bộ lọc thuật ngữ">
            <label className="glossary-search">
              <Search aria-hidden="true" size={14} />
              <span className="sr-only">Tìm thuật ngữ</span>
              <input
                onChange={(event) => setSearchQuery(event.target.value)}
                placeholder="Tìm thuật ngữ..."
                ref={searchInputRef}
                type="search"
                value={searchQuery}
              />
            </label>
            <label className="glossary-search glossary-status-filter">
              <span className="sr-only">Lọc trạng thái thuật ngữ</span>
              <select
                aria-label="Lọc trạng thái thuật ngữ"
                onChange={(event) => setStatusFilter(event.target.value)}
                value={statusFilter}
              >
                <option value="all">Tất cả</option>
                <option value="NEEDS_REVIEW">Chờ duyệt</option>
                <option value="APPROVED">Đã duyệt</option>
                <option value="LOCKED">Đã khóa</option>
                <option value="CONFLICT">Xung đột</option>
                <option value="REJECTED">Từ chối</option>
              </select>
            </label>
            <button
              aria-label="Tập trung tìm thuật ngữ"
              className="icon-action"
              onClick={() => searchInputRef.current?.focus()}
              type="button"
            >
              <Filter aria-hidden="true" size={15} />
            </button>
          </div>
        </div>

        {glossaryTerms.length > 0 ? (
          <>
            <div className="glossary-filter-tabs" aria-label="Trạng thái thuật ngữ">
              <span className="status-chip status-chip-success">
                {visibleTerms.length} / {glossaryTerms.length}
              </span>
              <span>Gốc</span>
              <span>Bản dịch</span>
              <span>Loại</span>
              <span>Thể loại</span>
              <span>Ưu tiên</span>
              <span>Duyệt</span>
              <span>Khóa</span>
              <span>Thao tác</span>
            </div>
            {visibleTerms.length > 0 ? (
              <div
                aria-label="Danh sách thuật ngữ"
                className="glossary-table-wrap"
                onScroll={glossaryWindow.onScroll}
                ref={glossaryWindow.containerRef}
                tabIndex={0}
              >
              <table aria-rowcount={visibleTerms.length + 1} className="provider-table glossary-management-table">
                <thead>
                  <tr>
                    <th>Gốc</th>
                    <th>Bản dịch</th>
                    <th>Loại</th>
                    <th>Thể loại</th>
                    <th>Ưu tiên</th>
                    <th>Duyệt</th>
                    <th>Khóa</th>
                    <th>Thao tác</th>
                  </tr>
                </thead>
                <tbody>
                  {glossaryWindow.paddingTop > 0 ? (
                    <tr aria-hidden="true" className="glossary-virtual-spacer">
                      <td colSpan={8} style={{ height: glossaryWindow.paddingTop }} />
                    </tr>
                  ) : null}
                  {windowedTerms.map((term, offset) => (
                    <GlossaryRow
                      key={term.id}
                      onApproveTerm={onApproveTerm}
                      onLockToggle={onLockToggle}
                      onRejectTerm={onRejectTerm}
                      onSaveAndApproveTerm={onSaveAndApproveTerm}
                      onUpdateTerm={onUpdateTerm}
                      rowIndex={glossaryWindow.startIndex + offset}
                      term={term}
                    />
                  ))}
                  {glossaryWindow.paddingBottom > 0 ? (
                    <tr aria-hidden="true" className="glossary-virtual-spacer">
                      <td colSpan={8} style={{ height: glossaryWindow.paddingBottom }} />
                    </tr>
                  ) : null}
                </tbody>
              </table>
              </div>
            ) : (
              <p className="empty-detail">Không có thuật ngữ khớp tìm kiếm.</p>
            )}
          </>
        ) : (
          <p className="empty-detail">Chưa có thuật ngữ nào</p>
        )}
      </section>
    </section>
  );
}
