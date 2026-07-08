import { useMemo, useState } from 'react';
import { Bookmark, Download, Highlighter, StickyNote, X } from 'lucide-react';
import type { ReaderAnnotationExportFormat, ReaderAnnotationKind } from '../../api/types';

export type ReaderMarkPanelItem = {
  id: string;
  annotationId?: number;
  bookId: number;
  charEnd?: number;
  charStart?: number;
  chapterId: number;
  chapterNumber: number;
  chapterTitle: string;
  clientId?: string;
  kind: 'bookmark' | 'highlight' | 'note';
  paragraphIndex: number;
  text: string;
  note?: string;
  color?: string;
};

export type ReaderMarksPanelProps = {
  open: boolean;
  exportError?: string;
  exportStatus?: string;
  items: ReaderMarkPanelItem[];
  onClose(): void;
  onExport?(format: ReaderAnnotationExportFormat, kind: ReaderAnnotationKind): void;
  onJump(item: ReaderMarkPanelItem): void;
};

type ReaderMarksTab = ReaderMarkPanelItem['kind'];

const tabs: Array<{ id: ReaderMarksTab; label: string }> = [
  { id: 'bookmark', label: 'Bookmarks' },
  { id: 'highlight', label: 'Highlights' },
  { id: 'note', label: 'Notes' },
];

const exportFormats: Array<{ format: ReaderAnnotationExportFormat; label: string }> = [
  { format: 'md', label: 'Markdown' },
  { format: 'json', label: 'JSON' },
  { format: 'csv', label: 'CSV' },
];

function tabIcon(tab: ReaderMarksTab) {
  if (tab === 'bookmark') return <Bookmark aria-hidden="true" size={15} />;
  if (tab === 'highlight') return <Highlighter aria-hidden="true" size={15} />;
  return <StickyNote aria-hidden="true" size={15} />;
}

export default function ReaderMarksPanel({
  open,
  exportError = '',
  exportStatus = '',
  items,
  onClose,
  onExport,
  onJump,
}: ReaderMarksPanelProps) {
  const [activeTab, setActiveTab] = useState<ReaderMarksTab>('bookmark');
  const filteredItems = useMemo(
    () => items.filter((item) => item.kind === activeTab),
    [activeTab, items],
  );

  if (!open) return null;

  return (
    <div className="reader-drawer-backdrop">
      <aside aria-label="Dấu đọc" className="reader-marks-panel" role="dialog">
        <header className="reader-drawer-header">
          <div>
            <p className="section-label">Marks</p>
            <h2>Dấu đọc</h2>
            <span>{filteredItems.length.toLocaleString()} mục</span>
          </div>
          <button
            aria-label="Đóng dấu đọc"
            className="reader-icon-button"
            onClick={onClose}
            title="Đóng dấu đọc"
            type="button"
          >
            <X aria-hidden="true" size={22} />
          </button>
        </header>

        <div aria-label="Loại dấu đọc" className="segmented-control reader-marks-tabs" role="group">
          {tabs.map((tab) => (
            <button
              aria-pressed={activeTab === tab.id}
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              type="button"
            >
              {tabIcon(tab.id)}
              {tab.label}
            </button>
          ))}
        </div>

        <div className="reader-marks-actions">
          {onExport ? (
            <div aria-label="Xuất dấu đọc đang xem" className="reader-export-format-group reader-marks-export-group" role="group">
              {exportFormats.map((option) => (
                <button
                  aria-label={`Xuất ${option.label} ${activeTab}s`}
                  className="reader-menu-action"
                  disabled={filteredItems.length === 0}
                  key={option.format}
                  onClick={() => onExport(option.format, activeTab)}
                  type="button"
                >
                  <Download aria-hidden="true" size={15} />
                  {option.label}
                </button>
              ))}
            </div>
          ) : null}
          {exportStatus ? <p className="reader-export-status">{exportStatus}</p> : null}
          {exportError ? <p className="reader-sync-error">{exportError}</p> : null}
        </div>

        <div className="reader-marks-list">
          {filteredItems.map((item) => (
            <button
              aria-label={`Đến Ch. ${item.chapterNumber} đoạn ${item.paragraphIndex + 1}`}
              className="reader-mark-item"
              key={item.id}
              onClick={() => onJump(item)}
              type="button"
            >
              <span>Ch. {item.chapterNumber}</span>
              <strong>{item.chapterTitle}</strong>
              {item.kind === 'note' && item.note ? <em>{item.note}</em> : null}
              {item.text ? <small>{item.text}</small> : null}
            </button>
          ))}
          {filteredItems.length === 0 ? <p>Chưa có dấu đọc.</p> : null}
        </div>
      </aside>
    </div>
  );
}
