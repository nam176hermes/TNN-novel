import { BookOpenText, Copy, Highlighter, Languages, Sparkles, StickyNote, X, type LucideIcon } from 'lucide-react';

export type ReaderSelectionAction = 'highlight' | 'note' | 'copy' | 'dictionary' | 'explain' | 'translate_term';

export type ReaderSelectionPopoverProps = {
  anchor: { left: number; top: number } | null;
  selectedText: string;
  visible: boolean;
  onAction(action: ReaderSelectionAction): void;
  onClose(): void;
};

const actions: Array<{
  id: ReaderSelectionAction;
  label: string;
  title: string;
  icon: LucideIcon;
}> = [
  { id: 'highlight', label: 'Highlight', title: 'Highlight đoạn chọn', icon: Highlighter },
  { id: 'note', label: 'Note', title: 'Ghi chú đoạn chọn', icon: StickyNote },
  { id: 'copy', label: 'Copy', title: 'Copy đoạn chọn', icon: Copy },
  { id: 'dictionary', label: 'Dict', title: 'Tra từ điển', icon: BookOpenText },
  { id: 'explain', label: 'Explain', title: 'Giải thích đoạn chọn', icon: Sparkles },
  { id: 'translate_term', label: 'Term', title: 'Dịch thuật ngữ', icon: Languages },
];

export default function ReaderSelectionPopover({
  anchor,
  selectedText,
  visible,
  onAction,
  onClose,
}: ReaderSelectionPopoverProps) {
  if (!visible || !anchor || !selectedText.trim()) return null;

  return (
    <div
      aria-label="Tác vụ đoạn chọn"
      className="reader-selection-popover"
      role="dialog"
      style={{
        left: anchor.left,
        top: anchor.top,
      }}
    >
      <span className="reader-selection-preview">{selectedText}</span>
      <div aria-label="Tác vụ nhanh" className="reader-selection-actions" role="group">
        {actions.map((action) => {
          const Icon = action.icon;
          return (
            <button
              aria-label={action.title}
              key={action.id}
              onClick={() => onAction(action.id)}
              title={action.title}
              type="button"
            >
              <Icon aria-hidden="true" size={16} />
              <span>{action.label}</span>
            </button>
          );
        })}
        <button aria-label="Đóng tác vụ đoạn chọn" onClick={onClose} title="Đóng" type="button">
          <X aria-hidden="true" size={16} />
        </button>
      </div>
    </div>
  );
}
