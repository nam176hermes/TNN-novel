import {
  Activity,
  BookOpenText,
  ClipboardList,
  Download,
  FilePlus2,
  FileText,
  Globe2,
  KeyRound,
  LibraryBig,
  Settings2,
  MoreHorizontal,
} from 'lucide-react';
import type { WorkflowView } from './WorkflowShell';

export type ShellNavProps = {
  activeView: WorkflowView;
  ariaLabel?: string;
  mobile?: boolean;
  moreOpen?: boolean;
  onOpenMore?(): void;
  onViewChange(view: WorkflowView): void;
};

const workflowItems: Array<{
  view: WorkflowView;
  label: string;
  icon: typeof BookOpenText;
}> = [
  { view: 'workbench', label: 'Bàn dịch', icon: BookOpenText },
  { view: 'raw', label: 'Raw chưa dịch', icon: FileText },
  { view: 'library', label: 'Thư viện', icon: LibraryBig },
  { view: 'import', label: 'Nhập chương', icon: FilePlus2 },
  { view: 'sources', label: 'Nguồn truyện', icon: Globe2 },
  { view: 'glossary', label: 'Thuật ngữ & Văn phong', icon: ClipboardList },
  { view: 'providers', label: 'Model API', icon: KeyRound },
  { view: 'jobs', label: 'Tác vụ', icon: Settings2 },
  { view: 'status', label: 'Trạng thái', icon: Activity },
  { view: 'export', label: 'Xuất file', icon: Download },
];

const mobileWorkflowItems = workflowItems.filter(({ view }) => (
  view === 'workbench' || view === 'library' || view === 'jobs'
));

const moreViews = new Set<WorkflowView>([
  'raw',
  'import',
  'sources',
  'glossary',
  'providers',
  'status',
  'export',
]);

export default function ShellNav({
  activeView,
  ariaLabel = 'Quy trình',
  mobile = false,
  moreOpen = false,
  onOpenMore,
  onViewChange,
}: ShellNavProps) {
  const items = mobile ? mobileWorkflowItems : workflowItems;
  const moreSelected = moreOpen || moreViews.has(activeView);

  return (
    <nav aria-label={ariaLabel} className="workflow-nav" data-mobile={mobile ? 'true' : undefined}>
      {items.map(({ view, label, icon: Icon }) => (
        <button
          aria-label={label}
          aria-pressed={activeView === view}
          className="workflow-nav-item"
          key={view}
          onClick={() => onViewChange(view)}
          type="button"
        >
          <Icon aria-hidden="true" size={18} />
          <span>{view === 'reader' && mobile ? 'Đọc' : label}</span>
        </button>
      ))}
      {mobile ? (
        <button
          aria-label="Thêm"
          aria-pressed={moreSelected}
          className="workflow-nav-item"
          onClick={onOpenMore}
          type="button"
        >
          <MoreHorizontal aria-hidden="true" size={18} />
          <span>Thêm</span>
        </button>
      ) : null}
    </nav>
  );
}
