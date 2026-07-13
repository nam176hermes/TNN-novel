import {
  BookOpenText,
  Check,
  ChevronDown,
  Circle,
  FilePlus2,
  Download,
  Globe2,
  KeyRound,
  LogOut,
  MessageCircle,
  Settings,
  Settings2,
  X,
} from 'lucide-react';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import avatarAdmin from '../assets/reference-ui/avatar-admin-latest.png';
import brandBook from '../assets/reference-ui/brand-sidebar-book.png';
import brandCube from '../assets/reference-ui/brand-sidebar-cube.png';
import brandExport from '../assets/reference-ui/brand-sidebar-export.png';
import brandJobs from '../assets/reference-ui/brand-sidebar-jobs.png';
import ShellNav from './ShellNav';

export type WorkflowView =
  | 'workbench'
  | 'raw'
  | 'library'
  | 'reader'
  | 'import'
  | 'sources'
  | 'glossary'
  | 'providers'
  | 'jobs'
  | 'status'
  | 'export';

export type WorkflowShellProps = {
  activeView: WorkflowView;
  apiBaseUrl: string;
  apiStatus?: 'checking' | 'offline' | 'ready';
  onLogout(): void;
  onOpenImport(): void;
  onViewChange(view: WorkflowView): void;
  renderView(view: WorkflowView): ReactNode;
};

function brandMarkForView(view: WorkflowView): string {
  if (view === 'jobs') return brandJobs;
  if (view === 'providers' || view === 'status') return brandCube;
  if (
    view === 'glossary'
    || view === 'import'
    || view === 'library'
    || view === 'raw'
    || view === 'reader'
    || view === 'sources'
    || view === 'workbench'
  ) return brandBook;
  return brandExport;
}

export default function WorkflowShell({
  activeView,
  apiBaseUrl,
  apiStatus = 'checking',
  onLogout,
  onOpenImport,
  onViewChange,
  renderView,
}: WorkflowShellProps) {
  const mainRef = useRef<HTMLElement | null>(null);
  const [mobileMoreOpen, setMobileMoreOpen] = useState(false);
  const apiStatusLabel = apiStatus === 'ready'
    ? 'Hoạt động tốt'
    : apiStatus === 'offline'
      ? 'Không sẵn sàng'
      : 'Đang kiểm tra';

  useEffect(() => {
    if (activeView === 'reader') return;
    const main = mainRef.current;
    if (!main) return;
    if (typeof main.scrollTo === 'function') {
      main.scrollTo({ left: 0, top: 0 });
      return;
    }
    main.scrollLeft = 0;
    main.scrollTop = 0;
  }, [activeView]);

  useEffect(() => {
    setMobileMoreOpen(false);
  }, [activeView]);

  function openMobileView(view: WorkflowView): void {
    setMobileMoreOpen(false);
    onViewChange(view);
  }

  return (
    <main className="workflow-shell" data-active-view={activeView}>
      <aside aria-label="Thanh quy trình" className="workflow-sidebar">
        <div className="brand-lockup workflow-brand">
          <img alt="" aria-hidden="true" className="brand-mark brand-mark-image" src={brandMarkForView(activeView)} />
          <div>
            <h1>Novel-TNN</h1>
            <p>Dịch truyện CN → VN</p>
          </div>
        </div>

        <ShellNav activeView={activeView} onViewChange={onViewChange} />

        <div className="workflow-sidebar-footer">
          <section aria-label="API Status" className="sidebar-status-card" data-status={apiStatus}>
            <Circle aria-hidden="true" className="sidebar-status-dot" size={14} />
            <div>
              <strong>API Status</strong>
              <span>{apiStatusLabel}</span>
            </div>
            <Check aria-hidden="true" className="sidebar-status-check" size={16} />
          </section>
          <section aria-label="Operator" className="sidebar-user-card">
            <img alt="" aria-hidden="true" className="sidebar-avatar sidebar-avatar-image" src={avatarAdmin} />
            <div>
              <strong>Admin</strong>
              <span>Quản trị viên</span>
            </div>
            <ChevronDown aria-hidden="true" size={15} />
          </section>
          <p className="workflow-api-base">API: {apiBaseUrl}</p>
          <button className="secondary-action sidebar-logout" onClick={onLogout} type="button">
            <LogOut aria-hidden="true" size={16} />
            Đăng xuất
          </button>
          <nav aria-label="Liên kết nhanh" className="sidebar-quick-actions">
            <button aria-label="Mở trạng thái hệ thống" onClick={() => onViewChange('status')} type="button">
              <BookOpenText aria-hidden="true" size={18} />
            </button>
            <button aria-label="Mở tác vụ" onClick={() => onViewChange('jobs')} type="button">
              <MessageCircle aria-hidden="true" size={18} />
            </button>
            <button aria-label="Mở Model API" onClick={() => onViewChange('providers')} type="button">
              <Settings aria-hidden="true" size={18} />
            </button>
          </nav>
        </div>
      </aside>

      <section aria-label="Không gian làm việc" className="workflow-main" ref={mainRef}>
        {renderView(activeView)}
      </section>

      <div className="workflow-mobile-bar">
        <ShellNav
          activeView={activeView}
          ariaLabel="Điều hướng chính trên di động"
          mobile
          moreOpen={mobileMoreOpen}
          onOpenMore={() => setMobileMoreOpen(true)}
          onViewChange={onViewChange}
        />
      </div>

      {mobileMoreOpen ? (
        <div className="mobile-more-backdrop" onClick={() => setMobileMoreOpen(false)} role="presentation">
          <aside
            aria-label="Thêm"
            aria-modal="true"
            className="mobile-more-sheet"
            onClick={(event) => event.stopPropagation()}
            role="dialog"
          >
            <span aria-hidden="true" className="mobile-sheet-handle" />
            <header>
              <h2>Thêm</h2>
              <button aria-label="Đóng menu Thêm" onClick={() => setMobileMoreOpen(false)} type="button">
                <X aria-hidden="true" size={22} />
              </button>
            </header>
            <section aria-labelledby="mobile-more-manage">
              <h3 id="mobile-more-manage">Quản lý</h3>
              <button
                onClick={() => {
                  setMobileMoreOpen(false);
                  onOpenImport();
                }}
                type="button"
              >
                <FilePlus2 aria-hidden="true" />Nhập chương
              </button>
              <button onClick={() => openMobileView('sources')} type="button"><Globe2 aria-hidden="true" />Nguồn truyện</button>
              <button onClick={() => openMobileView('glossary')} type="button"><BookOpenText aria-hidden="true" />Thuật ngữ &amp; Văn phong</button>
            </section>
            <section aria-labelledby="mobile-more-system">
              <h3 id="mobile-more-system">Hệ thống</h3>
              <button onClick={() => openMobileView('providers')} type="button"><KeyRound aria-hidden="true" />Model API</button>
              <button onClick={() => openMobileView('status')} type="button"><Settings2 aria-hidden="true" />Trạng thái</button>
              <button onClick={() => openMobileView('export')} type="button"><Download aria-hidden="true" />Xuất file</button>
            </section>
            <section aria-labelledby="mobile-more-account">
              <h3 id="mobile-more-account">Tài khoản</h3>
              <button onClick={() => openMobileView('status')} type="button"><Settings aria-hidden="true" />Cài đặt</button>
              <button className="mobile-more-logout" onClick={onLogout} type="button"><LogOut aria-hidden="true" />Đăng xuất</button>
            </section>
          </aside>
        </div>
      ) : null}
    </main>
  );
}
