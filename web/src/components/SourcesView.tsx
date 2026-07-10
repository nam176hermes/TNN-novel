import { Fragment, useEffect, useMemo, useState } from 'react';
import {
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Copy,
  Database,
  Eye,
  FileJson,
  Globe2,
  MoreVertical,
  RefreshCw,
  Search,
  ShieldAlert,
  ShieldCheck,
  X,
} from 'lucide-react';
import sourcesInfoGlobe from '../assets/reference-ui/sources-info-globe.png';
import type {
  ManagedSource,
  ManagedSourceImportSummary,
  ManagedSourceTestResult,
  SourceAdapterCandidate,
  SourceAdapterCandidateList,
  SourceCapability,
  SourceCatalogEntry,
  SourceCatalogHealthResult,
  SourceCatalogList,
  SourceCatalogQuery,
} from '../api/types';
import type { LoadState } from '../state/types';

type SourceHubTab = 'supported' | 'catalog' | 'candidates' | 'health';

export type SourcesViewProps = {
  checkCatalogSource?: (entryId: string) => Promise<SourceCatalogHealthResult>;
  createParserCandidate?: (entryId: string) => Promise<SourceAdapterCandidate>;
  error: string;
  importCatalogSources?: (entryIds: string[]) => Promise<ManagedSourceImportSummary>;
  loadCatalog?: (params: SourceCatalogQuery) => Promise<SourceCatalogList>;
  loadParserCandidates?: () => Promise<SourceAdapterCandidateList>;
  markManagedSourceStatus?: (sourceId: string, status: 'BROKEN' | 'BLOCKED' | 'NEEDS_REVIEW') => Promise<ManagedSource>;
  onRefresh(): Promise<void> | void;
  sources: SourceCapability[];
  state: LoadState;
  testManagedSource?: (sourceId: string) => Promise<ManagedSourceTestResult>;
  verifyManagedSource?: (sourceId: string) => Promise<ManagedSource>;
};

const CATALOG_PAGE_SIZE = 25;

function domainHref(domain: string): string {
  const normalized = domain.trim().replace(/^https?:\/\//i, '').replace(/\/.*$/, '');
  return `https://${normalized}`;
}

function catalogEntries(catalog: SourceCatalogList | null): SourceCatalogEntry[] {
  return catalog?.items ?? catalog?.entries ?? [];
}

function sourceJsonHref(entry: SourceCatalogEntry): string {
  if (entry.catalog_source === 'yckceo' && entry.external_id && !entry.external_id.startsWith('generated:')) {
    return `https://www.yckceo.com/yuedu/shuyuan/json/id/${encodeURIComponent(entry.external_id)}.json`;
  }
  return '';
}

function statusLabel(entry: SourceCatalogEntry): string {
  if (entry.supported) return 'supported';
  return entry.supported_status || 'unsupported';
}

function statusTone(entry: SourceCatalogEntry): string {
  const status = statusLabel(entry);
  if (status === 'supported') return 'is-supported';
  if (status === 'failed') return 'is-failed';
  if (status === 'unchecked') return 'is-unchecked';
  return 'is-unsupported';
}

function healthTone(status: string): string {
  if (status === 'reachable' || status === 'preview_ok') return 'is-supported';
  if (status === 'blocked' || status === 'timeout' || status === 'captcha' || status === 'error') return 'is-failed';
  if (status === 'unchecked') return 'is-unchecked';
  return 'is-unsupported';
}

function selectedCatalogEntries(entries: SourceCatalogEntry[], selectedIds: Set<string>): SourceCatalogEntry[] {
  return entries.filter((entry) => selectedIds.has(entry.id));
}

function applyManagedSourceToEntry(entry: SourceCatalogEntry, managed: ManagedSource): SourceCatalogEntry {
  if (entry.id !== managed.catalog_entry_id) return entry;
  return {
    ...entry,
    managed_source_id: managed.id,
    managed_status: managed.status,
    managed_trust_level: managed.trust_level,
    managed_last_test_status: managed.last_test_status,
    managed_last_tested_at: managed.last_tested_at,
    managed_last_successful_fetch_at: managed.last_successful_fetch_at,
    managed_last_error: managed.last_error,
    managed_rate_limit_requests_per_minute: managed.rate_limit_requests_per_minute,
    managed_rate_limit_delay_ms: managed.rate_limit_delay_ms,
    managed_max_concurrent_requests: managed.max_concurrent_requests,
    managed_cooldown_after_error_seconds: managed.cooldown_after_error_seconds,
    managed_notes: managed.notes,
    managed_parser_type: managed.parser_type,
    managed_language: managed.language,
    can_use_in_jobs: managed.status === 'VERIFIED',
  };
}

function managedStatusLabel(entry: SourceCatalogEntry): string {
  return entry.managed_status || 'UNMANAGED';
}

function managedTrustLabel(entry: SourceCatalogEntry): string {
  return entry.managed_trust_level || 'UNKNOWN';
}

export default function SourcesView({
  checkCatalogSource,
  createParserCandidate,
  error,
  importCatalogSources,
  loadCatalog,
  loadParserCandidates,
  markManagedSourceStatus,
  onRefresh,
  sources,
  state,
  testManagedSource,
  verifyManagedSource,
}: SourcesViewProps) {
  const [activeTab, setActiveTab] = useState<SourceHubTab>('supported');
  const [catalog, setCatalog] = useState<SourceCatalogList | null>(null);
  const [catalogState, setCatalogState] = useState<LoadState>('idle');
  const [catalogError, setCatalogError] = useState('');
  const [catalogQuery, setCatalogQuery] = useState('');
  const [catalogTag, setCatalogTag] = useState('');
  const [catalogDomain, setCatalogDomain] = useState('');
  const [catalogSupported, setCatalogSupported] = useState('');
  const [catalogManagedStatus, setCatalogManagedStatus] = useState('');
  const [catalogTrustLevel, setCatalogTrustLevel] = useState('');
  const [catalogPage, setCatalogPage] = useState(1);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());
  const [expandedId, setExpandedId] = useState('');
  const [copyMessage, setCopyMessage] = useState('');
  const [healthLoadingId, setHealthLoadingId] = useState('');
  const [healthMessage, setHealthMessage] = useState('');
  const [managedMessage, setManagedMessage] = useState('');
  const [managedLoadingId, setManagedLoadingId] = useState('');
  const [candidateList, setCandidateList] = useState<SourceAdapterCandidateList | null>(null);
  const [candidateState, setCandidateState] = useState<LoadState>('idle');
  const [candidateError, setCandidateError] = useState('');
  const [candidateMessage, setCandidateMessage] = useState('');
  const [candidateLoadingId, setCandidateLoadingId] = useState('');

  const entries = useMemo(() => catalogEntries(catalog), [catalog]);
  const selectedEntries = useMemo(() => selectedCatalogEntries(entries, selectedIds), [entries, selectedIds]);
  const totalPages = Math.max(1, Math.ceil((catalog?.total ?? 0) / (catalog?.page_size ?? CATALOG_PAGE_SIZE)));

  useEffect(() => {
    if (activeTab !== 'catalog' || !loadCatalog) return;

    let cancelled = false;
    const timer = window.setTimeout(() => {
      setCatalogState('loading');
      setCatalogError('');
      void loadCatalog({
        query: catalogQuery.trim(),
        tag: catalogTag,
        domain: catalogDomain.trim(),
        supported: catalogSupported as SourceCatalogQuery['supported'],
        status: catalogManagedStatus,
        trust_level: catalogTrustLevel,
        page: catalogPage,
        page_size: CATALOG_PAGE_SIZE,
      })
        .then((result) => {
          if (cancelled) return;
          setCatalog(result);
          setCatalogState(catalogEntries(result).length > 0 ? 'ready' : 'empty');
        })
        .catch((loadError: unknown) => {
          if (cancelled) return;
          setCatalogError(loadError instanceof Error ? loadError.message : 'Không tải được kho nguồn.');
          setCatalogState('error');
        });
    }, 220);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [activeTab, catalogDomain, catalogManagedStatus, catalogPage, catalogQuery, catalogSupported, catalogTag, catalogTrustLevel, loadCatalog]);

  useEffect(() => {
    if (activeTab !== 'candidates' || !loadParserCandidates) return;

    let cancelled = false;
    setCandidateState('loading');
    setCandidateError('');
    void loadParserCandidates()
      .then((result) => {
        if (cancelled) return;
        setCandidateList(result);
        setCandidateState(result.items.length > 0 ? 'ready' : 'empty');
      })
      .catch((loadError: unknown) => {
        if (cancelled) return;
        setCandidateError(loadError instanceof Error ? loadError.message : 'Không tải được parser candidates.');
        setCandidateState('error');
      });

    return () => {
      cancelled = true;
    };
  }, [activeTab, loadParserCandidates]);

  function resetCatalogPage(): void {
    setCatalogPage(1);
    setSelectedIds(new Set());
  }

  async function copyText(value: string, label: string): Promise<void> {
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
      setCopyMessage(`Đã sao chép ${label}.`);
    } catch {
      setCopyMessage('Không thể sao chép. Trình duyệt chưa cấp quyền clipboard.');
    }
  }

  async function copyBulk(kind: 'url' | 'json'): Promise<void> {
    const values = selectedEntries
      .map((entry) => (kind === 'url' ? entry.url : sourceJsonHref(entry)))
      .filter(Boolean);
    await copyText(values.join('\n'), kind === 'url' ? 'URL đã chọn' : 'source JSON URL đã chọn');
  }

  function toggleSelected(entryId: string): void {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(entryId)) next.delete(entryId);
      else next.add(entryId);
      return next;
    });
  }

  function updateCatalogHealth(result: SourceCatalogHealthResult): void {
    setCatalog((current) => {
      if (!current) return current;
      const update = (entry: SourceCatalogEntry): SourceCatalogEntry => {
        if (entry.id !== result.catalog_entry_id) return entry;
        return {
          ...entry,
          last_check_status: result.status,
          last_check_at: result.checked_at,
          last_check_error: result.status === 'reachable' || result.status === 'preview_ok' ? '' : result.reason,
          last_check_http_status: result.http_status,
          last_check_final_url: result.final_url,
        };
      };
      return {
        ...current,
        entries: current.entries.map(update),
        items: current.items.map(update),
      };
    });
  }

  function updateCatalogManagedSource(managed: ManagedSource): void {
    setCatalog((current) => {
      if (!current) return current;
      const update = (entry: SourceCatalogEntry): SourceCatalogEntry => applyManagedSourceToEntry(entry, managed);
      return {
        ...current,
        entries: current.entries.map(update),
        items: current.items.map(update),
      };
    });
  }

  async function handleCheckCatalogSource(entry: SourceCatalogEntry): Promise<void> {
    if (!checkCatalogSource) return;
    setHealthLoadingId(entry.id);
    setHealthMessage('');
    try {
      const result = await checkCatalogSource(entry.id);
      updateCatalogHealth(result);
      setHealthMessage(`Đã kiểm tra ${entry.name || entry.domain}: ${result.status}.`);
    } catch {
      setHealthMessage('Không kiểm tra được nguồn. Kiểm tra kết nối API hoặc server logs.');
    } finally {
      setHealthLoadingId('');
    }
  }

  async function handleCreateParserCandidate(entry: SourceCatalogEntry): Promise<void> {
    if (!createParserCandidate) return;
    setCandidateLoadingId(entry.id);
    setCandidateMessage('');
    setCandidateError('');
    try {
      const candidate = await createParserCandidate(entry.id);
      setCandidateList((current) => {
        const currentItems = current?.items ?? [];
        const filtered = currentItems.filter((item) => item.id !== candidate.id);
        return {
          items: [candidate, ...filtered],
          total: Math.max(current?.total ?? 0, filtered.length + 1),
          page: current?.page ?? 1,
          per_page: current?.per_page ?? current?.page_size ?? 50,
          page_size: current?.page_size ?? 50,
        };
      });
      setCandidateMessage(`Đã tạo parser candidate cho ${entry.name || entry.domain}.`);
    } catch {
      setCandidateError('Không tạo được parser candidate. Kiểm tra API hoặc server logs.');
    } finally {
      setCandidateLoadingId('');
    }
  }

  async function handleImportCatalogEntries(entryIds: string[]): Promise<void> {
    if (!importCatalogSources || entryIds.length === 0) return;
    const selectedCount = entryIds.length;
    if (!window.confirm(`Import ${selectedCount} nguồn đã chọn vào Source Hub để review?`)) return;
    setManagedLoadingId('bulk-import');
    setManagedMessage('');
    setCatalogError('');
    try {
      const summary = await importCatalogSources(entryIds);
      summary.items.forEach((item) => {
        if (item?.id) updateCatalogManagedSource(item as ManagedSource);
      });
      setManagedMessage(
        `Đã nhập ${summary.inserted} nguồn vào Source Hub. Trùng: ${summary.duplicates}. Không hợp lệ: ${summary.invalid}.`,
      );
      setSelectedIds(new Set());
    } catch (loadError: unknown) {
      setCatalogError(loadError instanceof Error ? loadError.message : 'Không import được nguồn đã chọn.');
    } finally {
      setManagedLoadingId('');
    }
  }

  async function handleImportSelectedCatalog(): Promise<void> {
    await handleImportCatalogEntries([...selectedIds]);
  }

  async function handleTestManagedSource(entry: SourceCatalogEntry): Promise<void> {
    if (!testManagedSource || !entry.managed_source_id) return;
    setManagedLoadingId(entry.managed_source_id);
    setManagedMessage('');
    setCatalogError('');
    try {
      const result = await testManagedSource(entry.managed_source_id);
      setCatalog((current) => {
        if (!current) return current;
        const update = (item: SourceCatalogEntry): SourceCatalogEntry => {
          if (item.id !== entry.id) return item;
          return {
            ...item,
            managed_last_test_status: result.status,
            managed_last_tested_at: result.tested_at,
            managed_last_successful_fetch_at:
              result.status === 'success' ? result.tested_at : item.managed_last_successful_fetch_at,
            managed_last_error: result.status === 'success' ? '' : result.reason,
          };
        };
        return {
          ...current,
          entries: current.entries.map(update),
          items: current.items.map(update),
        };
      });
      setManagedMessage(`Đã test nguồn ${entry.name || entry.domain}: ${result.status}.`);
    } catch (loadError: unknown) {
      setCatalogError(loadError instanceof Error ? loadError.message : 'Không test được nguồn.');
    } finally {
      setManagedLoadingId('');
    }
  }

  async function handleVerifyManagedSource(entry: SourceCatalogEntry): Promise<void> {
    if (!verifyManagedSource || !entry.managed_source_id) return;
    setManagedLoadingId(entry.managed_source_id);
    setManagedMessage('');
    setCatalogError('');
    try {
      const managed = await verifyManagedSource(entry.managed_source_id);
      updateCatalogManagedSource(managed);
      setManagedMessage(`Nguồn ${entry.name || entry.domain} đã được xác minh và có thể dùng cho automation.`);
    } catch (loadError: unknown) {
      setCatalogError(loadError instanceof Error ? loadError.message : 'Không thể xác minh nguồn.');
    } finally {
      setManagedLoadingId('');
    }
  }

  async function handleSetManagedStatus(
    entry: SourceCatalogEntry,
    status: 'BROKEN' | 'BLOCKED' | 'NEEDS_REVIEW',
  ): Promise<void> {
    if (!markManagedSourceStatus || !entry.managed_source_id) return;
    setManagedLoadingId(entry.managed_source_id);
    setManagedMessage('');
    setCatalogError('');
    try {
      const managed = await markManagedSourceStatus(entry.managed_source_id, status);
      updateCatalogManagedSource(managed);
      setManagedMessage(`Đã cập nhật trạng thái ${entry.name || entry.domain} thành ${status}.`);
    } catch (loadError: unknown) {
      setCatalogError(loadError instanceof Error ? loadError.message : 'Không thể cập nhật trạng thái nguồn.');
    } finally {
      setManagedLoadingId('');
    }
  }

  return (
    <section aria-labelledby="sources-view-title" className="workflow-management-view sources-view sources-reference-view panel">
      <div className="management-view-header sources-reference-header">
        <div>
          <p className="sources-eyebrow">Source Hub</p>
          <h2 id="sources-view-title">Nguồn truyện</h2>
          <p className="view-subtitle">Quản lý nguồn hỗ trợ và tra cứu kho metadata nguồn truyện.</p>
        </div>
        <button className="secondary-action sources-refresh-button" disabled={state === 'loading'} onClick={() => void onRefresh()} type="button">
          <RefreshCw aria-hidden="true" size={15} />
          Refresh
        </button>
      </div>

      <div aria-label="Source Hub tabs" className="source-hub-tabs segmented-control" role="group">
        <button aria-pressed={activeTab === 'supported'} onClick={() => setActiveTab('supported')} type="button">
          Nguồn hỗ trợ
        </button>
        <button aria-pressed={activeTab === 'catalog'} onClick={() => setActiveTab('catalog')} type="button">
          Kho nguồn
        </button>
        <button aria-pressed={activeTab === 'candidates'} onClick={() => setActiveTab('candidates')} type="button">
          Ứng viên parser
        </button>
        <button aria-pressed={activeTab === 'health'} onClick={() => setActiveTab('health')} type="button">
          Health check
        </button>
      </div>

      {activeTab === 'supported' ? (
        <>
          {state === 'loading' ? <p className="source-support-note">Loading source policies...</p> : null}
          {error ? (
            <p className="status-error" role="alert">
              {error}
            </p>
          ) : null}
          {state !== 'loading' && !error && sources.length === 0 ? (
            <p className="source-support-note">No source policies returned by backend.</p>
          ) : null}

          {sources.length > 0 ? (
            <div className="source-support-table-wrap">
              <table className="source-support-table sources-table">
                <thead>
                  <tr>
                    <th scope="col">Source</th>
                    <th scope="col">Domains</th>
                    <th scope="col">Parser</th>
                    <th scope="col">Policy</th>
                    <th aria-label="Actions" scope="col" />
                  </tr>
                </thead>
                <tbody>
                  {sources.map((source) => {
                    const policyLabel = `${source.delay_seconds}s delay · ${source.max_concurrency} concurrent · ${source.retry_limit} retries`;
                    const primaryDomain = source.domains[0] ?? '';
                    return (
                      <tr key={source.source_id}>
                        <th scope="row">
                          <span className="source-name-cell">
                            <Globe2 aria-hidden="true" size={16} />
                            {source.label}
                          </span>
                        </th>
                        <td>
                          <ul className="source-domain-list">
                            {source.domains.map((domain) => (
                              <li key={domain}>
                                <a className="source-domain-link" href={domainHref(domain)} rel="noreferrer" target="_blank">
                                  {domain}
                                </a>
                              </li>
                            ))}
                          </ul>
                        </td>
                        <td>{source.adapter_label || source.adapter_id}</td>
                        <td>
                          <span className="source-policy-cell">
                            <Clock3 aria-hidden="true" size={15} />
                            <span aria-hidden="true">
                              {source.delay_seconds}s delay · {source.max_concurrency} concurrent
                            </span>
                            <span className="sr-only">{policyLabel}</span>
                          </span>
                        </td>
                        <td>
                          <button
                            aria-label={`Mở domain chính ${source.label}`}
                            className="icon-action source-row-action"
                            disabled={!primaryDomain}
                            onClick={() => {
                              if (primaryDomain) window.open(domainHref(primaryDomain), '_blank', 'noopener,noreferrer');
                            }}
                            type="button"
                          >
                            <MoreVertical aria-hidden="true" size={16} />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : null}
        </>
      ) : null}

      {activeTab === 'catalog' ? (
        <div className="source-catalog-panel">
          <div className="source-catalog-notice">
            <Database aria-hidden="true" size={18} />
            <p>Kho nguồn là metadata chỉ đọc. Chỉ nguồn đã khớp chính sách hỗ trợ hiện có mới được dùng qua luồng import an toàn.</p>
          </div>

          <div className="source-catalog-toolbar" role="search">
            <label>
              <span>Tìm nguồn</span>
              <div className="source-catalog-input">
                <Search aria-hidden="true" size={15} />
                <input
                  onChange={(event) => {
                    setCatalogQuery(event.target.value);
                    resetCatalogPage();
                  }}
                  placeholder="Tên, domain, tác giả..."
                  type="search"
                  value={catalogQuery}
                />
              </div>
            </label>
            <label>
              <span>Tag</span>
              <select
                onChange={(event) => {
                  setCatalogTag(event.target.value);
                  resetCatalogPage();
                }}
                value={catalogTag}
              >
                <option value="">Tất cả tag</option>
                <option value="search">search</option>
                <option value="explore">explore</option>
                <option value="manga">manga</option>
                <option value="audio">audio</option>
              </select>
            </label>
            <label>
              <span>Domain</span>
              <input
                onChange={(event) => {
                  setCatalogDomain(event.target.value);
                  resetCatalogPage();
                }}
                placeholder="69shuba.com"
                value={catalogDomain}
              />
            </label>
            <label>
              <span>Hỗ trợ</span>
              <select
                onChange={(event) => {
                  setCatalogSupported(event.target.value);
                  resetCatalogPage();
                }}
                value={catalogSupported}
              >
                <option value="">Tất cả</option>
                <option value="true">supported</option>
                <option value="false">unsupported</option>
              </select>
            </label>
            <label>
              <span>Review</span>
              <select
                onChange={(event) => {
                  setCatalogManagedStatus(event.target.value);
                  resetCatalogPage();
                }}
                value={catalogManagedStatus}
              >
                <option value="">Tất cả</option>
                <option value="UNMANAGED">Chưa import</option>
                <option value="IMPORTED">IMPORTED</option>
                <option value="NEEDS_REVIEW">NEEDS_REVIEW</option>
                <option value="VERIFIED">VERIFIED</option>
                <option value="BROKEN">BROKEN</option>
                <option value="BLOCKED">BLOCKED</option>
              </select>
            </label>
            <label>
              <span>Trust</span>
              <select
                onChange={(event) => {
                  setCatalogTrustLevel(event.target.value);
                  resetCatalogPage();
                }}
                value={catalogTrustLevel}
              >
                <option value="">Tất cả</option>
                <option value="MANUAL_ONLY">MANUAL_ONLY</option>
                <option value="UNKNOWN">UNKNOWN</option>
                <option value="LOW">LOW</option>
                <option value="MEDIUM">MEDIUM</option>
                <option value="HIGH">HIGH</option>
              </select>
            </label>
          </div>

          <div className="source-catalog-bulkbar">
            <span>{selectedIds.size} nguồn đã chọn</span>
            <button disabled={selectedIds.size === 0 || !importCatalogSources || managedLoadingId === 'bulk-import'} onClick={() => void handleImportSelectedCatalog()} type="button">
              <Database aria-hidden="true" size={14} />
              Import để review
            </button>
            <button disabled={selectedIds.size === 0} onClick={() => void copyBulk('url')} type="button">
              <Copy aria-hidden="true" size={14} />
              Sao chép URL đã chọn
            </button>
            <button disabled={selectedEntries.every((entry) => !sourceJsonHref(entry))} onClick={() => void copyBulk('json')} type="button">
              <FileJson aria-hidden="true" size={14} />
              Sao chép source JSON URL
            </button>
            <button disabled={selectedIds.size === 0} onClick={() => setSelectedIds(new Set())} type="button">
              <X aria-hidden="true" size={14} />
              Bỏ chọn
            </button>
          </div>
          {copyMessage ? <p className="source-copy-message">{copyMessage}</p> : null}
          {healthMessage ? <p className="source-health-message">{healthMessage}</p> : null}
          {managedMessage ? <p className="source-copy-message">{managedMessage}</p> : null}
          {candidateMessage ? <p className="source-copy-message">{candidateMessage}</p> : null}
          {candidateError ? (
            <p className="status-error" role="alert">
              {candidateError}
            </p>
          ) : null}

          {!loadCatalog ? <p className="source-support-note">Source catalog API chưa được cấu hình trong frontend.</p> : null}
          {catalogState === 'loading' ? <p className="source-support-note">Đang tải kho nguồn...</p> : null}
          {catalogError ? (
            <p className="status-error" role="alert">
              {catalogError}
            </p>
          ) : null}
          {catalogState === 'empty' && !catalogError ? <p className="source-support-note">Không có nguồn nào khớp bộ lọc.</p> : null}

          {entries.length > 0 ? (
            <>
              <div className="source-support-table-wrap source-catalog-table-wrap">
                <table className="source-support-table sources-table source-catalog-table">
                  <thead>
                    <tr>
                      <th aria-label="Select" scope="col" />
                      <th scope="col">Name</th>
                      <th scope="col">Domain</th>
                      <th scope="col">Tags</th>
                      <th scope="col">Status</th>
                      <th scope="col">Meta</th>
                      <th aria-label="Actions" scope="col" />
                    </tr>
                  </thead>
                  <tbody>
                    {entries.map((entry) => {
                      const jsonUrl = sourceJsonHref(entry);
                      const managedStatus = managedStatusLabel(entry);
                      const managedSourceId = entry.managed_source_id;
                      const managedBusy = managedSourceId !== '' && managedLoadingId === managedSourceId;
                      return (
                        <Fragment key={entry.id}>
                          <tr>
                            <td>
                              <input
                                aria-label={`Chọn nguồn ${entry.name || entry.domain}`}
                                checked={selectedIds.has(entry.id)}
                                onChange={() => toggleSelected(entry.id)}
                                type="checkbox"
                              />
                            </td>
                            <th scope="row">
                              <span className="source-catalog-name">{entry.name || entry.domain || 'Untitled source'}</span>
                              {entry.url ? (
                                <a className="source-catalog-url" href={entry.url} rel="noreferrer" target="_blank">
                                  {entry.url}
                                </a>
                              ) : null}
                            </th>
                            <td>{entry.domain || '—'}</td>
                            <td>
                              <span className="source-tag-list">
                                {[...entry.tags, ...entry.unknown_tags].map((tag) => (
                                  <span className="source-tag-chip" key={tag}>
                                    {tag}
                                  </span>
                                ))}
                              </span>
                            </td>
                            <td>
                              <span className={`source-status-badge ${statusTone(entry)}`}>
                                {entry.supported ? <CheckCircle2 aria-hidden="true" size={13} /> : <ShieldAlert aria-hidden="true" size={13} />}
                                {statusLabel(entry)}
                              </span>
                              <span className={`source-status-badge ${entry.can_use_in_jobs ? 'is-supported' : managedStatus === 'BLOCKED' || managedStatus === 'BROKEN' ? 'is-failed' : 'is-unchecked'}`}>
                                {managedStatus}
                              </span>
                              <span className="source-invalid-reason">
                                Trust: {managedTrustLabel(entry)} · Jobs: {entry.can_use_in_jobs ? 'enabled' : 'disabled'}
                              </span>
                              {entry.invalid_reason ? <span className="source-invalid-reason">{entry.invalid_reason}</span> : null}
                              {entry.last_check_status ? (
                                <span className={`source-status-badge source-health-badge ${healthTone(entry.last_check_status)}`}>
                                  {entry.last_check_status}
                                </span>
                              ) : null}
                              {entry.managed_last_test_status ? (
                                <span className={`source-status-badge source-health-badge ${healthTone(entry.managed_last_test_status === 'success' ? 'reachable' : 'error')}`}>
                                  test: {entry.managed_last_test_status}
                                </span>
                              ) : null}
                              {entry.last_check_at ? (
                                <span className="source-invalid-reason">
                                  Last checked: {entry.last_check_at}
                                  {entry.last_check_http_status ? ` · HTTP ${entry.last_check_http_status}` : ''}
                                </span>
                              ) : null}
                              {entry.managed_last_tested_at ? (
                                <span className="source-invalid-reason">
                                  Last fetch test: {entry.managed_last_tested_at}
                                </span>
                              ) : null}
                              {entry.managed_last_error ? <span className="source-invalid-reason">{entry.managed_last_error}</span> : null}
                              {entry.last_check_error ? <span className="source-invalid-reason">{entry.last_check_error}</span> : null}
                            </td>
                            <td>
                              <span className="source-catalog-meta">
                                {entry.author || 'Unknown author'}
                                <br />
                                {entry.version ? `v${entry.version}` : 'No version'}
                                <br />
                                {entry.managed_parser_type || 'parser n/a'}
                              </span>
                            </td>
                            <td>
                              <span className="source-row-actions">
                                <button
                                  aria-label={`Import source metadata ${entry.name || entry.domain}`}
                                  className="icon-action"
                                  disabled={Boolean(managedSourceId) || !importCatalogSources}
                                  onClick={() => {
                                    void handleImportCatalogEntries([entry.id]);
                                  }}
                                  type="button"
                                >
                                  <Database aria-hidden="true" size={15} />
                                </button>
                                <button aria-label={`Sao chép URL ${entry.name || entry.domain}`} className="icon-action" disabled={!entry.url} onClick={() => void copyText(entry.url, 'URL nguồn')} type="button">
                                  <Copy aria-hidden="true" size={15} />
                                </button>
                                <button aria-label={`Sao chép source JSON ${entry.name || entry.domain}`} className="icon-action" disabled={!jsonUrl} onClick={() => void copyText(jsonUrl, 'source JSON URL')} type="button">
                                  <FileJson aria-hidden="true" size={15} />
                                </button>
                                <button aria-label={`Xem metadata ${entry.name || entry.domain}`} className="icon-action" onClick={() => setExpandedId(expandedId === entry.id ? '' : entry.id)} type="button">
                                  <Eye aria-hidden="true" size={15} />
                                </button>
                                <button
                                  aria-label={`Check source ${entry.name || entry.domain}`}
                                  className="icon-action"
                                  disabled={!checkCatalogSource || healthLoadingId === entry.id}
                                  onClick={() => void handleCheckCatalogSource(entry)}
                                  type="button"
                                >
                                  <RefreshCw aria-hidden="true" size={15} />
                                </button>
                                <button
                                  aria-label={`Test managed source ${entry.name || entry.domain}`}
                                  className="icon-action"
                                  disabled={!managedSourceId || !testManagedSource || managedBusy}
                                  onClick={() => void handleTestManagedSource(entry)}
                                  type="button"
                                >
                                  <ShieldCheck aria-hidden="true" size={15} />
                                </button>
                                <button
                                  aria-label={`Verify managed source ${entry.name || entry.domain}`}
                                  className="icon-action"
                                  disabled={!managedSourceId || !verifyManagedSource || managedBusy}
                                  onClick={() => void handleVerifyManagedSource(entry)}
                                  type="button"
                                >
                                  <CheckCircle2 aria-hidden="true" size={15} />
                                </button>
                                <button
                                  aria-label={`Create parser candidate ${entry.name || entry.domain}`}
                                  className="icon-action"
                                  disabled={!createParserCandidate || candidateLoadingId === entry.id}
                                  onClick={() => void handleCreateParserCandidate(entry)}
                                  type="button"
                                >
                                  <FileJson aria-hidden="true" size={15} />
                                </button>
                              </span>
                              {managedSourceId ? (
                                <span className="source-row-actions">
                                  <button disabled={!markManagedSourceStatus || managedBusy} onClick={() => void handleSetManagedStatus(entry, 'NEEDS_REVIEW')} type="button">
                                    Review
                                  </button>
                                  <button disabled={!markManagedSourceStatus || managedBusy} onClick={() => void handleSetManagedStatus(entry, 'BROKEN')} type="button">
                                    Broken
                                  </button>
                                  <button disabled={!markManagedSourceStatus || managedBusy} onClick={() => void handleSetManagedStatus(entry, 'BLOCKED')} type="button">
                                    Block
                                  </button>
                                </span>
                              ) : null}
                            </td>
                          </tr>
                          {expandedId === entry.id ? (
                            <tr className="source-catalog-details-row">
                              <td colSpan={7}>
                                <div className="source-catalog-details-grid">
                                  <div>
                                    <strong>Base URL</strong>
                                    <p>{entry.url || '—'}</p>
                                  </div>
                                  <div>
                                    <strong>Parser</strong>
                                    <p>{entry.managed_parser_type || (entry.supported ? 'policy_supported' : 'generic_html')}</p>
                                  </div>
                                  <div>
                                    <strong>Rate limit</strong>
                                    <p>
                                      {entry.managed_rate_limit_requests_per_minute || 0} rpm · {entry.managed_rate_limit_delay_ms || 0} ms · {entry.managed_max_concurrent_requests || 0} concurrent
                                    </p>
                                  </div>
                                  <div>
                                    <strong>Cooldown</strong>
                                    <p>{entry.managed_cooldown_after_error_seconds || 0}s</p>
                                  </div>
                                  <div>
                                    <strong>Notes</strong>
                                    <p>{entry.managed_notes || 'Chưa có ghi chú review.'}</p>
                                  </div>
                                </div>
                                <pre>{JSON.stringify(entry, null, 2)}</pre>
                              </td>
                            </tr>
                          ) : null}
                        </Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <div className="source-catalog-pagination">
                <button disabled={catalogPage <= 1 || catalogState === 'loading'} onClick={() => setCatalogPage((page) => Math.max(1, page - 1))} type="button">
                  <ChevronLeft aria-hidden="true" size={15} />
                  Trang trước
                </button>
                <span>
                  Trang {catalog?.page ?? catalogPage} / {totalPages} · {catalog?.total ?? entries.length} nguồn
                </span>
                <button disabled={catalogPage >= totalPages || catalogState === 'loading'} onClick={() => setCatalogPage((page) => page + 1)} type="button">
                  Trang sau
                  <ChevronRight aria-hidden="true" size={15} />
                </button>
              </div>
            </>
          ) : null}
        </div>
      ) : null}

      {activeTab === 'candidates' ? (
        <div className="source-catalog-panel">
          <div className="source-catalog-notice">
            <ShieldAlert aria-hidden="true" size={18} />
            <p>Candidate is not a supported source. Import remains blocked until a developer/operator adds a real source policy and parser.</p>
          </div>
          {candidateMessage ? <p className="source-copy-message">{candidateMessage}</p> : null}
          {candidateError ? (
            <p className="status-error" role="alert">
              {candidateError}
            </p>
          ) : null}
          {!loadParserCandidates ? <p className="source-support-note">Parser candidate API chưa được cấu hình trong frontend.</p> : null}
          {candidateState === 'loading' ? <p className="source-support-note">Đang tải parser candidates...</p> : null}
          {candidateState === 'empty' && !candidateError ? <p className="source-support-note">Chưa có parser candidate nào.</p> : null}
          {(candidateList?.items.length ?? 0) > 0 ? (
            <div className="source-support-table-wrap source-catalog-table-wrap">
              <table className="source-support-table sources-table source-catalog-table source-candidate-table">
                <thead>
                  <tr>
                    <th scope="col">Title</th>
                    <th scope="col">Domain</th>
                    <th scope="col">Sample URL</th>
                    <th scope="col">Confidence</th>
                    <th scope="col">Status</th>
                    <th scope="col">Signals</th>
                    <th scope="col">Created</th>
                  </tr>
                </thead>
                <tbody>
                  {candidateList?.items.map((candidate) => (
                    <tr key={candidate.id}>
                      <th scope="row">{candidate.detected_title || 'Untitled candidate'}</th>
                      <td>{candidate.domain || '—'}</td>
                      <td>
                        {candidate.sample_url ? (
                          <a className="source-catalog-url" href={candidate.sample_url} rel="noreferrer" target="_blank">
                            {candidate.sample_url}
                          </a>
                        ) : (
                          '—'
                        )}
                      </td>
                      <td>
                        <span className={`source-status-badge ${candidate.parser_confidence === 'failed' ? 'is-failed' : 'is-unchecked'}`}>
                          {candidate.parser_confidence}
                        </span>
                        {candidate.failure_reason ? <span className="source-invalid-reason">{candidate.failure_reason}</span> : null}
                      </td>
                      <td>
                        <span className={`source-status-badge ${candidate.status === 'needs_review' ? 'is-supported' : 'is-unchecked'}`}>
                          {candidate.status}
                        </span>
                      </td>
                      <td>{candidate.detected_chapter_list.length} signals</td>
                      <td>{candidate.created_at || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </div>
      ) : null}

      {activeTab === 'health' ? (
        <div className="source-placeholder-panel">
          <ShieldAlert aria-hidden="true" size={22} />
          <h3>Health check chưa bật</h3>
          <p>Kiểm tra nguồn cần SSRF guard và giới hạn network riêng. Phase này không probe website ngoài.</p>
        </div>
      ) : null}

      <aside className="sources-info-panel" aria-label="Thông tin nguồn truyện">
        <div>
          <h3>
            <ShieldCheck aria-hidden="true" size={22} />
            Thông tin
          </h3>
          <p>Catalog chỉ là metadata tham khảo. Luồng import hiện tại vẫn phụ thuộc vào source policies và parser đã hỗ trợ.</p>
        </div>
        <img alt="" aria-hidden="true" src={sourcesInfoGlobe} />
      </aside>
    </section>
  );
}
