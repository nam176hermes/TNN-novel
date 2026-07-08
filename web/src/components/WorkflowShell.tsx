import {
  BookOpenText,
  Check,
  ChevronDown,
  Circle,
  FilePlus2,
  LogOut,
  MessageCircle,
  Settings,
} from 'lucide-react';
import { useEffect, useRef, type ReactNode } from 'react';
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
        <button className="workflow-mobile-import" onClick={onOpenImport} type="button">
          <FilePlus2 aria-hidden="true" size={18} />
          <span>Nhập</span>
        </button>
        <ShellNav activeView={activeView} ariaLabel="Quy trình di động" onViewChange={onViewChange} />
      </div>
    </main>
  );
}
