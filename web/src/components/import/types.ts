import type { ApiClient } from '../../api/client';
import type {
  EbookDuplicateStrategy,
  EbookImportHistoryRun,
  EbookImportRequest,
  EbookImportResult,
  EbookInboxFile,
  EbookPreview,
  EbookSplitMode,
  ImportFileRequest,
  ImportPasteRequest,
  ImportUrlRequest,
  JobStartResponse,
  SourceCatalogList,
  SourceCatalogQuery,
  SourcePreview,
  URLFetchResponse,
  WizardTextImportRequest,
  WizardTextImportResult
} from '../../api/types';
export type ImportPanelProps = {
  importJobClient?: ApiClient;
  onImportPaste: (request: ImportPasteRequest) => Promise<void> | void;
  onImportFile?: (request: ImportFileRequest) => Promise<void> | void;
  onImportWizardText?: (
    request: WizardTextImportRequest,
    options?: { finalAction: FinalImportAction },
  ) => Promise<WizardTextImportResult | void> | void;
  onPreviewTranslatedEbook?: (
    file: File,
    splitMode: EbookSplitMode,
    options?: { duplicateStrategy?: EbookDuplicateStrategy; targetBookId?: number | null },
  ) => Promise<EbookPreview>;
  onPreviewInboxEbook?: (
    filename: string,
    splitMode: EbookSplitMode,
    options?: { duplicateStrategy?: EbookDuplicateStrategy; targetBookId?: number | null },
  ) => Promise<EbookPreview>;
  onImportTranslatedEbook?: (request: EbookImportRequest) => Promise<EbookImportResult | void> | void;
  onPreviewImportUrl?: (url: string) => Promise<SourcePreview>;
  onStartImportUrlJob?: (request: ImportUrlRequest) => Promise<JobStartResponse | void> | void;
  onFetchSourceChapters?: (request: {
    source_url: string;
    title: string;
    author: string;
    source: string;
    chapters: Array<{ url: string; chapter_number: number; title: string }>;
  }) => Promise<URLFetchResponse>;
  onCreateTranslationJob?: (bookId: number, chapterIds: number[]) => Promise<JobStartResponse | void> | void;
  onCreateTtsJob?: (bookId: number, chapterIds: number[]) => Promise<JobStartResponse | void> | void;
  loadSourceCatalog?: (params: SourceCatalogQuery) => Promise<SourceCatalogList>;
  onOpenImportedBook?: (result: WizardTextImportResult) => void;
  onOpenJob?: (jobId: string) => void;
  onReturnToLibrary?: () => void;
  onCancel: () => void;
  books?: Array<{ id: number; title: string }>;
  chapters?: Array<{ book_id: number; chapter_number: number; title?: string }>;
  ebookInboxDirectory?: string;
  ebookInboxError?: string;
  ebookInboxFiles?: EbookInboxFile[];
  ebookImportHistory?: EbookImportHistoryRun[];
  loading?: boolean;
  onRefreshEbookInbox?: () => Promise<void> | void;
};

export type ImportMode = 'paste' | 'file' | 'ebook' | 'url' | 'catalog';
export type EbookSource = 'upload' | 'inbox';
export type EbookPreviewState = 'idle' | 'loading' | 'ready' | 'error';
export type EbookPreviewFile = Pick<File, 'name' | 'size'>;
export type FinalImportAction = 'save' | 'open' | 'translate' | 'tts';

