import {
  Activity,
  BookOpenCheck,
  BookOpenText,
  ClipboardList,
  Download,
  FilePlus2,
  FileText,
  Globe2,
  KeyRound,
  LibraryBig,
  Settings2,
} from 'lucide-react';
import type { WorkflowView } from './WorkflowShell';

export type ShellNavProps = {
  activeView: WorkflowView;
  ariaLabel?: string;
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
  { view: 'reader', label: 'Đọc truyện', icon: BookOpenCheck },
  { view: 'import', label: 'Nhập chương', icon: FilePlus2 },
  { view: 'sources', label: 'Nguồn truyện', icon: Globe2 },
  { view: 'glossary', label: 'Thuật ngữ & Văn phong', icon: ClipboardList },
  { view: 'providers', label: 'Model API', icon: KeyRound },
  { view: 'jobs', label: 'Tác vụ', icon: Settings2 },
  { view: 'status', label: 'Trạng thái', icon: Activity },
  { view: 'export', label: 'Xuất file', icon: Download },
];

export default function ShellNav({ activeView, ariaLabel = 'Quy trình', onViewChange }: ShellNavProps) {
  return (
    <nav aria-label={ariaLabel} className="workflow-nav">
      {workflowItems.map(({ view, label, icon: Icon }) => (
        <button
          aria-label={label}
          aria-pressed={activeView === view}
          className="workflow-nav-item"
          key={view}
          onClick={() => onViewChange(view)}
          type="button"
        >
          <Icon aria-hidden="true" size={18} />
          <span>{label}</span>
        </button>
      ))}
    </nav>
  );
}
