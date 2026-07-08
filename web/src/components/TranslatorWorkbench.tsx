import type {
  Chapter,
  CostEstimate,
  GlossaryTerm,
  GlossaryTermUpdate,
  JobStatus,
  Provider,
  StyleProfile,
  TmSearchResult,
} from '../api/types';
import GlossaryTmPanel from './GlossaryTmPanel';
import JobProgress from './JobProgress';
import ProviderCostPanel, { type QualityMode } from './ProviderCostPanel';
import QualityPanel, { type QualityDetails, type QualityIssue } from './QualityPanel';
import ReviewEditor from './ReviewEditor';

export type TranslatorWorkbenchProps = {
  chapter: Chapter | null;
  sourceText: string;
  translationText: string;
  savedTranslationText: string | null;
  providers: Provider[];
  styleProfiles: StyleProfile[];
  glossaryTerms: GlossaryTerm[];
  glossaryPendingCount: number;
  tmBestMatch?: TmSearchResult | null;
  selectedProviderId: string;
  selectedStyleProfileId: string;
  selectedMode: QualityMode;
  estimate: CostEstimate | null;
  activeJob: JobStatus | null;
  qaIssues: QualityIssue[];
  qaScore?: number;
  qaVerdict?: string;
  qaDetails?: QualityDetails;
  textLoading?: boolean;
  onTranslationChange(text: string): void;
  onSaveTranslation(text: string): void;
  onCopyTranslation?: () => void;
  onProviderChange(providerId: string): void;
  onStyleProfileChange(styleProfileId: string): void;
  onModeChange(mode: QualityMode): void;
  onGlossaryTermUpdate(termId: number, updates: GlossaryTermUpdate): void;
  onGlossaryTermLockToggle(termId: number, locked: boolean): void;
  onEstimate(): void;
  onTranslate(): void;
  onRunQa(): void;
};

export type { QualityMode };

export default function TranslatorWorkbench({
  chapter,
  sourceText,
  translationText,
  savedTranslationText,
  providers,
  styleProfiles,
  glossaryTerms,
  glossaryPendingCount,
  tmBestMatch = null,
  selectedProviderId,
  selectedStyleProfileId,
  selectedMode,
  estimate,
  activeJob,
  qaIssues,
  qaScore,
  qaVerdict,
  qaDetails,
  textLoading = false,
  onTranslationChange,
  onSaveTranslation,
  onCopyTranslation,
  onProviderChange,
  onStyleProfileChange,
  onModeChange,
  onGlossaryTermUpdate,
  onGlossaryTermLockToggle,
  onEstimate,
  onTranslate,
  onRunQa,
}: TranslatorWorkbenchProps) {
  if (!chapter) {
    return (
      <section aria-label="Translator workbench" className="translator-workbench">
        <div className="panel">
          <p className="empty-detail">Select a chapter to review.</p>
        </div>
      </section>
    );
  }

  return (
    <section aria-label="Translator workbench" className="translator-workbench">
      <header className="panel workbench-header">
        <div>
          <p className="section-label">Chapter {chapter.chapter_number}</p>
          <h2>{chapter.title}</h2>
        </div>
        <span className="status-chip">{chapter.status}</span>
      </header>

      <ProviderCostPanel
        estimate={estimate}
        onEstimate={onEstimate}
        onModeChange={onModeChange}
        onProviderChange={onProviderChange}
        onStyleProfileChange={onStyleProfileChange}
        onTranslate={onTranslate}
        providers={providers}
        styleProfiles={styleProfiles}
        selectedMode={selectedMode}
        selectedProviderId={selectedProviderId}
        selectedStyleProfileId={selectedStyleProfileId}
        translating={activeJob?.status === 'running'}
      />

      <JobProgress job={activeJob} />

      <ReviewEditor
        loading={textLoading}
        onChange={onTranslationChange}
        onCopyTranslation={onCopyTranslation}
        onSave={onSaveTranslation}
        savedTranslationText={savedTranslationText}
        sourceText={sourceText}
        translationText={translationText}
      />

      <QualityPanel
        issues={qaIssues}
        details={qaDetails}
        onRunQa={onRunQa}
        score={qaScore}
        verdict={qaVerdict}
      />

      <GlossaryTmPanel
        bestMatch={tmBestMatch}
        glossaryTerms={glossaryTerms}
        onLockToggle={onGlossaryTermLockToggle}
        onUpdateTerm={onGlossaryTermUpdate}
        pendingCount={glossaryPendingCount}
      />
    </section>
  );
}
