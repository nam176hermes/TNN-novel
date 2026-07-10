import { Boxes, LogOut } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import type { BookSummary, Chapter } from '../api/types';
import ChapterNavigator from './ChapterNavigator';

export type AppShellProps = {
  books: BookSummary[];
  chapters: Chapter[];
  activeBookId: number | null;
  selectedChapterId: number | null;
  backendLoading: boolean;
  backendError: string;
  importOpen: boolean;
  workbench: ReactNode;
  insights: ReactNode;
  importPanel: ReactNode;
  onSelectBook(bookId: number): void;
  onSelectChapter(chapterId: number): void;
  onOpenImport(): void;
  onCloseImport(): void;
  onLogout(): void;
};

type MobilePanel = 'editor' | 'qa' | 'assist';

export default function AppShell({
  books,
  chapters,
  activeBookId,
  selectedChapterId,
  backendLoading,
  backendError,
  importOpen,
  workbench,
  insights,
  importPanel,
  onSelectBook,
  onSelectChapter,
  onOpenImport,
  onCloseImport,
  onLogout,
}: AppShellProps) {
  const [mobilePanel, setMobilePanel] = useState<MobilePanel>('editor');

  return (
    <main className="app-shell">
      <aside aria-label="Library sidebar" className="sidebar">
        <div className="brand-lockup">
          <Boxes aria-hidden="true" className="brand-mark" />
          <div>
            <h1>Novel-TNN Translator</h1>
            <p>CN to VN pipeline</p>
          </div>
        </div>
        <button className="secondary-action sidebar-logout" onClick={onLogout} type="button">
          <LogOut aria-hidden="true" size={16} />
          Logout
        </button>

        <ChapterNavigator
          activeBookId={activeBookId}
          books={books}
          chapters={chapters}
          onImport={onOpenImport}
          onSelectBook={onSelectBook}
          onSelectChapter={onSelectChapter}
          selectedChapterId={selectedChapterId}
        />
      </aside>

      <section aria-label="Translator workspace" className="workspace" data-mobile-panel={mobilePanel}>
        {workbench}

        <section aria-label="Mobile panels" className="mobile-panel-selector" role="tablist">
          <button
            aria-selected={mobilePanel === 'editor'}
            className="secondary-action"
            onClick={() => setMobilePanel('editor')}
            role="tab"
            type="button"
          >
            Editor
          </button>
          <button
            aria-selected={mobilePanel === 'qa'}
            className="secondary-action"
            onClick={() => setMobilePanel('qa')}
            role="tab"
            type="button"
          >
            QA
          </button>
          <button
            aria-selected={mobilePanel === 'assist'}
            className="secondary-action"
            onClick={() => setMobilePanel('assist')}
            role="tab"
            type="button"
          >
            Assist
          </button>
        </section>

        {backendLoading ? <p className="status-chip">Loading backend</p> : null}
        {backendError ? (
          <p className="status-error workspace-status" role="alert">
            {backendError}
          </p>
        ) : null}

        {importOpen ? (
          <section aria-label="Import workflow" className="import-workflow">
            <div className="topbar-actions">
              <button className="secondary-action" onClick={onCloseImport} type="button">
                Close import
              </button>
            </div>
            {importPanel}
          </section>
        ) : null}

        {insights}
      </section>
    </main>
  );
}
