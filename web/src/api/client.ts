import type {
  AudiobookExportFormat,
  Book,
  BookAudioPlaylistResponse,
  BookUpdate,
  ChapterApi,
  ChapterContentResponse,
  ChapterTextResponse,
  CostEstimate,
  EbookImportRequest,
  EbookImportResult,
  EbookImportHistoryRun,
  EbookInboxList,
  EbookPreview,
  EbookDuplicateStrategy,
  ExportDownload,
  ExportFormat,
  ExportResponse,
  SystemBackupItem,
  SystemBackupJobStart,
  SystemBackupList,
  SystemBackupRequest,
  GlossaryTerm,
  GlossaryTermUpdate,
  ImportFileRequest,
  ImportJobAccepted,
  ImportJobEvent,
  ImportJobEventStream,
  ImportJobSnapshot,
  ImportPasteRequest,
  ImportResponse,
  ImportUrlRequest,
  JobAttempt,
  JobAttemptResponse,
  JobListResponse,
  JobLogEntry,
  JobStartResponse,
  JobStatus,
  JobEventSubscriptionOptions,
  Provider,
  ProviderDefaults,
  ProviderTestResult,
  ProviderUsage,
  QaReport,
  ReaderAnnotation,
  ReaderAnnotationCreate,
  ReaderAnnotationExportFormat,
  ReaderAnnotationImportItem,
  ReaderAnnotationImportResponse,
  ReaderAnnotationKind,
  ReaderAnnotationUpdate,
  ReaderDictionaryPack,
  ReaderDictionaryFile,
  ReaderDictionaryResponse,
  ReaderExplainRequest,
  ReaderExplainResponse,
  ReaderProgress,
  ReaderProgressUpdate,
  ReaderSearchResult,
  ReaderSearchScope,
  ReaderStateResponse,
  ReaderSyncRequest,
  ReaderSyncResponse,
  ReaderXrayEnrichOptions,
  ReaderXrayResponse,
  ReaderXraySpoilerMode,
  ManagedSource,
  ManagedSourceImportSummary,
  ManagedSourceList,
  ManagedSourceQuery,
  ManagedSourceTestResult,
  ManagedSourceUpdateRequest,
  SourceAdapterCandidate,
  SourceAdapterCandidateList,
  SourceCapability,
  SourceCatalogHealthResult,
  SourceCatalogList,
  SourceCatalogQuery,
  SourcePreview,
  StyleProfile,
  SystemStatus,
  TmSearchResult,
  TokenResponse,
  TranslatedBookSummary,
  TtsJobStatus,
  URLFetchRequest,
  URLFetchResponse,
  WizardTextImportRequest,
  WizardTextImportResult,
} from './types';

type ErrorPayload = {
  detail?: unknown;
  message?: unknown;
};

export type ReaderBookSearchOptions = {
  caseSensitive?: boolean;
  regex?: boolean;
  scopes?: ReaderSearchScope[];
  wholeWord?: boolean;
};

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly retryable: boolean;

  constructor(message: string, status: number, code = '', retryable = false) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.retryable = retryable;
  }
}

function normalizeBaseUrl(baseUrl: string): string {
  return baseUrl.replace(/\/+$/, '');
}

function formatDetail(detail: unknown): string {
  if (typeof detail === 'string') return detail;
  if (detail == null) return '';

  try {
    return JSON.stringify(detail);
  } catch {
    return String(detail);
  }
}

function jobPayload(
  bookId: number,
  chapterIds: number[],
  params: Record<string, string> = {},
  limit = 15,
) {
  return {
    book_id: bookId,
    chapter_ids: chapterIds,
    limit,
    params,
  };
}

function compactParams(params: Record<string, string | undefined>): Record<string, string> {
  return Object.fromEntries(
    Object.entries(params).filter((entry): entry is [string, string] => Boolean(entry[1])),
  );
}

function filenameFromContentDisposition(value: string | null, fallback: string): string {
  if (!value) return fallback;
  const utf8Match = value.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match) return decodeURIComponent(utf8Match[1].replace(/"/g, ''));
  const asciiMatch = value.match(/filename="?([^";]+)"?/i);
  return asciiMatch ? asciiMatch[1] : fallback;
}

const browserFetch: typeof fetch = (input, init) => fetch(input, { credentials: 'include', ...init });

export class ApiClient {
  token = '';

  private readonly baseUrl: string;

  constructor(
    baseUrl: string,
    private readonly fetcher: typeof fetch = browserFetch,
  ) {
    this.baseUrl = normalizeBaseUrl(baseUrl);
  }

  private headers(): Record<string, string> {
    return this.token ? { Authorization: `Bearer ${this.token}` } : {};
  }

  private absoluteApiUrl(value: string): string {
    if (!value) return value;
    try {
      return new URL(value, `${this.baseUrl}/`).href;
    } catch {
      return value;
    }
  }

  private async assertOk(response: Response, fallbackMessage: string): Promise<void> {
    if (response.ok) return;

    const status = response.status;
    const statusText = response.statusText ? ` ${response.statusText}` : '';
    const statusLabel = typeof status === 'number' && status > 0 ? ` (${status}${statusText})` : '';
    const error = await this.errorInfo(response);
    const detailLabel = error.message ? `: ${error.message}` : '';

    throw new ApiError(
      `${fallbackMessage}${statusLabel}${detailLabel}`,
      status,
      error.code,
      error.retryable,
    );
  }

  private async errorDetail(response: Response): Promise<string> {
    return (await this.errorInfo(response)).message;
  }

  private async errorInfo(response: Response): Promise<{ message: string; code: string; retryable: boolean }> {
    try {
      const payload = (await response.json()) as ErrorPayload;
      const detail = payload.detail;
      if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
        const typed = detail as Record<string, unknown>;
        return {
          message: formatDetail(typed.message ?? detail),
          code: typeof typed.code === 'string' ? typed.code : '',
          retryable: typed.retryable === true,
        };
      }
      return {
        message: formatDetail(detail ?? payload.message ?? payload),
        code: '',
        retryable: false,
      };
    } catch {
      try {
        return { message: (await response.text()).trim(), code: '', retryable: false };
      } catch {
        return { message: '', code: '', retryable: false };
      }
    }
  }

  async login(username: string, password: string): Promise<TokenResponse> {
    const response = await this.fetcher(`${this.baseUrl}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    await this.assertOk(response, 'Login failed');

    const data = (await response.json()) as TokenResponse;
    this.token = data.access_token;
    return data;
  }

  async refresh(refreshToken: string): Promise<TokenResponse> {
    const response = await this.fetcher(`${this.baseUrl}/api/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    await this.assertOk(response, 'Refresh failed');

    const data = (await response.json()) as TokenResponse;
    this.token = data.access_token;
    return data;
  }

  async logout(): Promise<void> {
    const response = await this.fetcher(`${this.baseUrl}/api/auth/logout`, {
      method: 'POST',
      headers: this.headers(),
    });
    await this.assertOk(response, 'Logout failed');
  }

  async getProviders(): Promise<Provider[]> {
    const response = await this.fetcher(`${this.baseUrl}/api/providers`, {
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to load providers');

    const data = (await response.json()) as { providers: Provider[] };
    return data.providers;
  }

  async getBooks(): Promise<Book[]> {
    const response = await this.fetcher(`${this.baseUrl}/api/books`, {
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to load books');

    return (await response.json()) as Book[];
  }

  async getTranslatedBooks(): Promise<TranslatedBookSummary[]> {
    const response = await this.fetcher(`${this.baseUrl}/api/library/books`, {
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to load translated books');

    const data = (await response.json()) as { books: TranslatedBookSummary[] };
    return data.books;
  }

  async updateBook(bookId: number, updates: BookUpdate): Promise<Book> {
    const response = await this.fetcher(`${this.baseUrl}/api/books/${bookId}`, {
      method: 'PATCH',
      headers: { ...this.headers(), 'Content-Type': 'application/json' },
      body: JSON.stringify(updates),
    });
    await this.assertOk(response, 'Failed to update book');

    return (await response.json()) as Book;
  }

  async deleteBook(bookId: number): Promise<void> {
    const response = await this.fetcher(`${this.baseUrl}/api/books/${bookId}`, {
      method: 'DELETE',
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to delete book');
  }

  async updateBookCover(bookId: number, cover: File): Promise<Book> {
    const body = new FormData();
    body.append('cover', cover);
    const response = await this.fetcher(`${this.baseUrl}/api/books/${bookId}/cover`, {
      method: 'POST',
      headers: this.headers(),
      body,
    });
    await this.assertOk(response, 'Failed to update book cover');

    return (await response.json()) as Book;
  }

  async getChapters(bookId: number): Promise<ChapterApi[]> {
    const response = await this.fetcher(`${this.baseUrl}/api/books/${bookId}/chapters`, {
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to load chapters');

    return (await response.json()) as ChapterApi[];
  }

  async importPaste(request: ImportPasteRequest): Promise<ImportResponse> {
    const response = await this.fetcher(`${this.baseUrl}/api/import/paste`, {
      method: 'POST',
      headers: { ...this.headers(), 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    });
    await this.assertOk(response, 'Failed to import pasted chapter');

    return (await response.json()) as ImportResponse;
  }

  async importFile(request: ImportFileRequest): Promise<ImportResponse> {
    const body = new FormData();
    body.append('title', request.title);
    body.append('chapter_number', String(request.chapter_number));
    body.append('chapter_title', request.chapter_title);
    body.append('file', request.file);

    const response = await this.fetcher(`${this.baseUrl}/api/import/file`, {
      method: 'POST',
      headers: this.headers(),
      body,
    });
    await this.assertOk(response, 'Failed to import source file');

    return (await response.json()) as ImportResponse;
  }

  async importWizardText(request: WizardTextImportRequest): Promise<WizardTextImportResult> {
    const response = await this.fetcher(`${this.baseUrl}/api/import/wizard/text`, {
      method: 'POST',
      headers: { ...this.headers(), 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    });
    await this.assertOk(response, 'Failed to import reviewed text');

    return (await response.json()) as WizardTextImportResult;
  }

  async previewTranslatedEbook(
    file: File,
    splitMode = 'auto',
    options: { duplicateStrategy?: EbookDuplicateStrategy; targetBookId?: number | null } = {},
  ): Promise<EbookPreview> {
    const body = new FormData();
    body.append('file', file);
    body.append('split_mode', splitMode);
    body.append('duplicate_strategy', options.duplicateStrategy ?? 'skip');
    if (options.targetBookId != null) {
      body.append('target_book_id', String(options.targetBookId));
    }

    const response = await this.fetcher(`${this.baseUrl}/api/import/ebook/preview`, {
      method: 'POST',
      headers: this.headers(),
      body,
    });
    await this.assertOk(response, 'Failed to preview translated ebook');

    return (await response.json()) as EbookPreview;
  }

  async getEbookInboxFiles(): Promise<EbookInboxList> {
    const response = await this.fetcher(`${this.baseUrl}/api/import/ebook/inbox`, {
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to load ebook inbox');

    return (await response.json()) as EbookInboxList;
  }

  async previewInboxTranslatedEbook(
    filename: string,
    splitMode = 'auto',
    options: { duplicateStrategy?: EbookDuplicateStrategy; targetBookId?: number | null } = {},
  ): Promise<EbookPreview> {
    const body = new FormData();
    body.append('filename', filename);
    body.append('split_mode', splitMode);
    body.append('duplicate_strategy', options.duplicateStrategy ?? 'skip');
    if (options.targetBookId != null) {
      body.append('target_book_id', String(options.targetBookId));
    }

    const response = await this.fetcher(`${this.baseUrl}/api/import/ebook/inbox/preview`, {
      method: 'POST',
      headers: this.headers(),
      body,
    });
    await this.assertOk(response, 'Failed to preview inbox ebook');

    return (await response.json()) as EbookPreview;
  }

  async getEbookImportHistory(limit = 20): Promise<EbookImportHistoryRun[]> {
    const query = limit === 20 ? '' : `?${new URLSearchParams({ limit: String(limit) }).toString()}`;
    const response = await this.fetcher(`${this.baseUrl}/api/import/ebook/history${query}`, {
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to load ebook import history');

    const data = (await response.json()) as { runs: EbookImportHistoryRun[] };
    return data.runs;
  }

  private translatedEbookImportBody(request: EbookImportRequest): FormData {
    const body = new FormData();
    if (request.uploadId) {
      body.append('upload_id', request.uploadId);
    } else if (request.inboxFile) {
      body.append('inbox_file', request.inboxFile);
    } else if (request.file) {
      body.append('file', request.file);
    } else {
      throw new Error('No ebook file selected');
    }
    body.append('duplicate_strategy', request.duplicateStrategy ?? 'skip');
    body.append('split_mode', request.splitMode ?? 'auto');
    if (request.targetBookId != null) {
      body.append('target_book_id', String(request.targetBookId));
    }
    if (request.confirmedExistingBookId != null) {
      body.append('confirmed_existing_book_id', String(request.confirmedExistingBookId));
    }
    return body;
  }

  async importTranslatedEbook(request: EbookImportRequest): Promise<EbookImportResult> {
    const body = this.translatedEbookImportBody(request);
    const response = await this.fetcher(`${this.baseUrl}/api/import/ebook`, {
      method: 'POST',
      headers: this.headers(),
      body,
    });
    await this.assertOk(response, 'Failed to import translated ebook');

    return (await response.json()) as EbookImportResult;
  }

  async startTranslatedEbookImportJob(request: EbookImportRequest): Promise<JobStartResponse> {
    const body = this.translatedEbookImportBody(request);
    const response = await this.fetcher(`${this.baseUrl}/api/import/ebook/job`, {
      method: 'POST',
      headers: this.headers(),
      body,
    });
    await this.assertOk(response, 'Failed to start translated ebook import');

    return (await response.json()) as JobStartResponse;
  }

  async previewImportUrl(url: string): Promise<SourcePreview> {
    const response = await this.fetcher(`${this.baseUrl}/api/import/url/preview`, {
      method: 'POST',
      headers: { ...this.headers(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    });
    await this.assertOk(response, 'Failed to preview source URL');

    return (await response.json()) as SourcePreview;
  }

  async fetchSourceChapters(request: URLFetchRequest): Promise<URLFetchResponse> {
    const response = await this.fetcher(`${this.baseUrl}/api/import/url/fetch`, {
      method: 'POST',
      headers: { ...this.headers(), 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    });
    await this.assertOk(response, 'Failed to fetch source chapters');

    return (await response.json()) as URLFetchResponse;
  }

  async createImportJob(request: URLFetchRequest): Promise<ImportJobAccepted> {
    const response = await this.fetcher(`${this.baseUrl}/api/import/jobs`, {
      method: 'POST',
      headers: { ...this.headers(), 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    });
    await this.assertOk(response, 'Failed to create import job');
    return (await response.json()) as ImportJobAccepted;
  }

  async getImportJob(jobId: string): Promise<ImportJobSnapshot> {
    const response = await this.fetcher(`${this.baseUrl}/api/import/jobs/${encodeURIComponent(jobId)}`, {
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to load import job');
    return (await response.json()) as ImportJobSnapshot;
  }

  async cancelImportJob(jobId: string): Promise<ImportJobSnapshot> {
    const response = await this.fetcher(`${this.baseUrl}/api/import/jobs/${encodeURIComponent(jobId)}/cancel`, {
      method: 'POST',
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to cancel import job');
    return (await response.json()) as ImportJobSnapshot;
  }

  async retryFailedTasks(jobId: string): Promise<ImportJobSnapshot> {
    const response = await this.fetcher(`${this.baseUrl}/api/import/jobs/${encodeURIComponent(jobId)}/retry-failed`, {
      method: 'POST',
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to retry import tasks');
    return (await response.json()) as ImportJobSnapshot;
  }

  async retryFailedImportTasks(jobId: string): Promise<ImportJobSnapshot> {
    return this.retryFailedTasks(jobId);
  }

  subscribeJobEvents(
    jobId: string,
    onEvent: (event: ImportJobEvent) => void,
    options: JobEventSubscriptionOptions = {},
  ): ImportJobEventStream {
    const controller = new AbortController();
    const query = options.cursor != null ? `?cursor=${Math.max(0, Math.trunc(options.cursor))}` : '';
    const headers = this.headers();
    if (options.lastEventId != null) {
      headers['Last-Event-ID'] = String(Math.max(0, Math.trunc(options.lastEventId)));
    }
    const done = (async () => {
      try {
        const response = await this.fetcher(
          `${this.baseUrl}/api/import/jobs/${encodeURIComponent(jobId)}/events${query}`,
          { headers, signal: controller.signal },
        );
        await this.assertOk(response, 'Failed to stream import job events');
        if (!response.body) throw new ApiError('Import job event stream has no response body', response.status);

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        while (true) {
          const { value, done: readerDone } = await reader.read();
          if (readerDone) break;
          buffer += decoder.decode(value, { stream: true });
          buffer = this.consumeImportJobSseBlocks(buffer, onEvent);
        }
        buffer += decoder.decode();
        this.consumeImportJobSseBlocks(`${buffer}\n\n`, onEvent);
      } catch (error) {
        if (
          controller.signal.aborted &&
          typeof error === 'object' &&
          error !== null &&
          'name' in error &&
          error.name === 'AbortError'
        ) {
          return;
        }
        throw error;
      }
    })();
    return { abort: () => controller.abort(), done };
  }

  openImportJobEventStream(
    jobId: string,
    onEvent: (event: ImportJobEvent) => void,
    options: JobEventSubscriptionOptions = {},
  ): ImportJobEventStream {
    return this.subscribeJobEvents(jobId, onEvent, options);
  }

  private consumeImportJobSseBlocks(
    input: string,
    onEvent: (event: ImportJobEvent) => void,
  ): string {
    let buffer = input;
    while (true) {
      const boundary = buffer.match(/\r?\n\r?\n/);
      if (!boundary || boundary.index == null) return buffer;
      const block = buffer.slice(0, boundary.index);
      buffer = buffer.slice(boundary.index + boundary[0].length);
      if (!block || block.startsWith(':')) continue;
      const data = block
        .split(/\r?\n/)
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.slice(5).trimStart())
        .join('\n');
      if (data) onEvent(JSON.parse(data) as ImportJobEvent);
    }
  }

  async getImportSources(): Promise<SourceCapability[]> {
    const response = await this.fetcher(`${this.baseUrl}/api/import/sources`, {
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to load import sources');

    const data = (await response.json()) as { sources: SourceCapability[] };
    return data.sources;
  }

  async getSourceCatalog(params: SourceCatalogQuery = {}): Promise<SourceCatalogList> {
    const query = new URLSearchParams(
      compactParams({
        query: params.query,
        tag: params.tag,
        domain: params.domain,
        supported: params.supported,
        status: params.status,
        trust_level: params.trust_level,
        page: params.page ? String(params.page) : undefined,
        page_size: params.page_size ? String(params.page_size) : undefined,
      }),
    );
    const suffix = query.toString() ? `?${query.toString()}` : '';
    const response = await this.fetcher(`${this.baseUrl}/api/source-catalog${suffix}`, {
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to load source catalog');

    return (await response.json()) as SourceCatalogList;
  }

  async checkSourceCatalogEntry(entryId: string): Promise<SourceCatalogHealthResult> {
    const response = await this.fetcher(`${this.baseUrl}/api/source-catalog/${encodeURIComponent(entryId)}/check`, {
      method: 'POST',
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to check source catalog entry');

    return (await response.json()) as SourceCatalogHealthResult;
  }

  async importManagedSources(entryIds: string[]): Promise<ManagedSourceImportSummary> {
    const response = await this.fetcher(`${this.baseUrl}/api/sources/import-catalog`, {
      method: 'POST',
      headers: { ...this.headers(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ entry_ids: entryIds }),
    });
    await this.assertOk(response, 'Failed to import selected sources');

    return (await response.json()) as ManagedSourceImportSummary;
  }

  async getManagedSources(params: ManagedSourceQuery = {}): Promise<ManagedSourceList> {
    const query = new URLSearchParams(
      compactParams({
        query: params.query,
        status: params.status,
        trust_level: params.trust_level,
        language: params.language,
        page: params.page ? String(params.page) : undefined,
        page_size: params.page_size ? String(params.page_size) : undefined,
      }),
    );
    const suffix = query.toString() ? `?${query.toString()}` : '';
    const response = await this.fetcher(`${this.baseUrl}/api/sources${suffix}`, {
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to load managed sources');

    return (await response.json()) as ManagedSourceList;
  }

  async getManagedSource(sourceId: string): Promise<ManagedSource> {
    const response = await this.fetcher(`${this.baseUrl}/api/sources/${encodeURIComponent(sourceId)}`, {
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to load managed source');

    return (await response.json()) as ManagedSource;
  }

  async updateManagedSource(sourceId: string, payload: ManagedSourceUpdateRequest): Promise<ManagedSource> {
    const response = await this.fetcher(`${this.baseUrl}/api/sources/${encodeURIComponent(sourceId)}`, {
      method: 'PATCH',
      headers: { ...this.headers(), 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    await this.assertOk(response, 'Failed to update managed source');

    return (await response.json()) as ManagedSource;
  }

  async testManagedSource(sourceId: string): Promise<ManagedSourceTestResult> {
    const response = await this.fetcher(`${this.baseUrl}/api/sources/${encodeURIComponent(sourceId)}/test`, {
      method: 'POST',
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to test source');

    return (await response.json()) as ManagedSourceTestResult;
  }

  async verifyManagedSource(sourceId: string): Promise<ManagedSource> {
    const response = await this.fetcher(`${this.baseUrl}/api/sources/${encodeURIComponent(sourceId)}/verify`, {
      method: 'POST',
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to verify source');

    return (await response.json()) as ManagedSource;
  }

  async setManagedSourceStatus(sourceId: string, status: 'BROKEN' | 'BLOCKED' | 'NEEDS_REVIEW'): Promise<ManagedSource> {
    const response = await this.fetcher(`${this.baseUrl}/api/sources/${encodeURIComponent(sourceId)}/status`, {
      method: 'POST',
      headers: { ...this.headers(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ status }),
    });
    await this.assertOk(response, 'Failed to update source status');

    return (await response.json()) as ManagedSource;
  }

  async createSourceAdapterCandidate(entryId: string, sampleUrl = ''): Promise<SourceAdapterCandidate> {
    const body = sampleUrl ? { sample_url: sampleUrl } : {};
    const response = await this.fetcher(`${this.baseUrl}/api/source-catalog/${encodeURIComponent(entryId)}/parser-candidate`, {
      method: 'POST',
      headers: { ...this.headers(), 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    await this.assertOk(response, 'Failed to create parser candidate');

    return (await response.json()) as SourceAdapterCandidate;
  }

  async getSourceAdapterCandidates(page = 1, pageSize = 50): Promise<SourceAdapterCandidateList> {
    const query = new URLSearchParams({
      page: String(page),
      page_size: String(pageSize),
    });
    const response = await this.fetcher(`${this.baseUrl}/api/source-adapter-candidates?${query.toString()}`, {
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to load parser candidates');

    return (await response.json()) as SourceAdapterCandidateList;
  }

  async getSourceAdapterCandidate(candidateId: string): Promise<SourceAdapterCandidate> {
    const response = await this.fetcher(`${this.baseUrl}/api/source-adapter-candidates/${encodeURIComponent(candidateId)}`, {
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to load parser candidate');

    return (await response.json()) as SourceAdapterCandidate;
  }

  async startImportUrlJob(request: ImportUrlRequest): Promise<JobStartResponse> {
    const response = await this.fetcher(`${this.baseUrl}/api/import/url`, {
      method: 'POST',
      headers: { ...this.headers(), 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    });
    await this.assertOk(response, 'Failed to start URL import');

    return (await response.json()) as JobStartResponse;
  }

  async getChapterSource(bookId: number, chapterId: number): Promise<string> {
    const response = await this.fetcher(`${this.baseUrl}/api/books/${bookId}/chapters/${chapterId}/source`, {
      headers: this.headers(),
    });
    if (!response.ok && response.status === 404) {
      const detail = await this.errorDetail(response);
      if (detail === 'Source text not found') return '';

      const statusText = response.statusText ? ` ${response.statusText}` : '';
      const detailLabel = detail ? `: ${detail}` : '';
      throw new ApiError(`Failed to load chapter source (404${statusText})${detailLabel}`, response.status);
    }
    await this.assertOk(response, 'Failed to load chapter source');

    const data = (await response.json()) as ChapterTextResponse;
    return data.text;
  }

  async getChapterTranslation(bookId: number, chapterId: number): Promise<string | null> {
    const response = await this.fetcher(`${this.baseUrl}/api/books/${bookId}/chapters/${chapterId}/translation`, {
      headers: this.headers(),
    });
    if (response.status === 404) return null;
    await this.assertOk(response, 'Failed to load chapter translation');

    const data = (await response.json()) as ChapterTextResponse;
    return data.text;
  }

  async getChapterContent(bookId: number, chapterId: number): Promise<{ text: string; html: string } | null> {
    const response = await this.fetcher(`${this.baseUrl}/api/books/${bookId}/chapters/${chapterId}/content`, {
      headers: this.headers(),
    });
    if (response.status === 404) return null;
    await this.assertOk(response, 'Failed to load chapter content');

    const data = (await response.json()) as ChapterContentResponse;
    return { text: data.text, html: data.html };
  }

  async saveChapterTranslation(bookId: number, chapterId: number, text: string): Promise<void> {
    const response = await this.fetcher(`${this.baseUrl}/api/books/${bookId}/chapters/${chapterId}/translation`, {
      method: 'PATCH',
      headers: { ...this.headers(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    await this.assertOk(response, 'Failed to save chapter translation');
  }

  async deleteChapterTranslation(bookId: number, chapterId: number): Promise<void> {
    const response = await this.fetcher(`${this.baseUrl}/api/books/${bookId}/chapters/${chapterId}/translation`, {
      method: 'DELETE',
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to delete chapter translation');
  }

  async deleteChapter(bookId: number, chapterId: number): Promise<void> {
    const response = await this.fetcher(`${this.baseUrl}/api/books/${bookId}/chapters/${chapterId}`, {
      method: 'DELETE',
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to delete chapter');
  }

  async getReaderState(bookId: number): Promise<ReaderStateResponse> {
    const response = await this.fetcher(`${this.baseUrl}/api/books/${bookId}/reader/state`, {
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to load reader state');

    return (await response.json()) as ReaderStateResponse;
  }

  async saveReaderProgress(bookId: number, update: ReaderProgressUpdate): Promise<ReaderProgress> {
    const response = await this.fetcher(`${this.baseUrl}/api/books/${bookId}/reader/progress`, {
      method: 'PATCH',
      headers: { ...this.headers(), 'Content-Type': 'application/json' },
      body: JSON.stringify(update),
    });
    await this.assertOk(response, 'Failed to save reader progress');

    const data = (await response.json()) as { progress: ReaderProgress };
    return data.progress;
  }

  async getReaderAnnotations(bookId: number): Promise<ReaderAnnotation[]> {
    const response = await this.fetcher(`${this.baseUrl}/api/books/${bookId}/annotations`, {
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to load reader annotations');

    const data = (await response.json()) as { annotations: ReaderAnnotation[] };
    return data.annotations;
  }

  async createReaderAnnotation(
    bookId: number,
    chapterId: number,
    annotation: ReaderAnnotationCreate,
  ): Promise<ReaderAnnotation> {
    const response = await this.fetcher(`${this.baseUrl}/api/books/${bookId}/chapters/${chapterId}/annotations`, {
      method: 'POST',
      headers: { ...this.headers(), 'Content-Type': 'application/json' },
      body: JSON.stringify(annotation),
    });
    await this.assertOk(response, 'Failed to create reader annotation');

    const data = (await response.json()) as { annotation: ReaderAnnotation };
    return data.annotation;
  }

  async updateReaderAnnotation(
    bookId: number,
    annotationId: number,
    annotation: ReaderAnnotationUpdate,
  ): Promise<ReaderAnnotation> {
    const response = await this.fetcher(`${this.baseUrl}/api/books/${bookId}/annotations/${annotationId}`, {
      method: 'PATCH',
      headers: { ...this.headers(), 'Content-Type': 'application/json' },
      body: JSON.stringify(annotation),
    });
    await this.assertOk(response, 'Failed to update reader annotation');

    const data = (await response.json()) as { annotation: ReaderAnnotation };
    return data.annotation;
  }

  async deleteReaderAnnotation(bookId: number, annotationId: number): Promise<void> {
    const response = await this.fetcher(`${this.baseUrl}/api/books/${bookId}/annotations/${annotationId}`, {
      method: 'DELETE',
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to delete reader annotation');
  }

  async syncReaderState(bookId: number, request: ReaderSyncRequest): Promise<ReaderSyncResponse> {
    const response = await this.fetcher(`${this.baseUrl}/api/books/${bookId}/reader/sync`, {
      method: 'POST',
      headers: { ...this.headers(), 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    });
    await this.assertOk(response, 'Failed to sync reader state');

    return (await response.json()) as ReaderSyncResponse;
  }

  async explainReaderSelection(
    bookId: number,
    chapterId: number,
    request: ReaderExplainRequest,
  ): Promise<ReaderExplainResponse> {
    const response = await this.fetcher(
      `${this.baseUrl}/api/books/${bookId}/chapters/${chapterId}/reader/explain`,
      {
        method: 'POST',
        headers: { ...this.headers(), 'Content-Type': 'application/json' },
        body: JSON.stringify(request),
      },
    );
    await this.assertOk(response, 'Failed to explain selected text');

    return (await response.json()) as ReaderExplainResponse;
  }

  async searchBook(
    bookId: number,
    query: string,
    options: ReaderBookSearchOptions = {},
  ): Promise<ReaderSearchResult[]> {
    const params = new URLSearchParams({ q: query });
    if (options.scopes?.length) params.set('scope', options.scopes.join(','));
    if (options.caseSensitive) params.set('case_sensitive', 'true');
    if (options.regex) params.set('regex', 'true');
    if (options.wholeWord) params.set('whole_word', 'true');

    const response = await this.fetcher(`${this.baseUrl}/api/books/${bookId}/search?${params.toString()}`, {
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to search reader book');

    const data = (await response.json()) as { results: ReaderSearchResult[] };
    return data.results;
  }

  async getReaderXray(
    bookId: number,
    chapterId?: number | null,
    spoilerMode: ReaderXraySpoilerMode = 'no_spoiler',
  ): Promise<ReaderXrayResponse> {
    const params = new URLSearchParams({ spoiler_mode: spoilerMode });
    if (chapterId != null) params.set('chapter_id', String(chapterId));
    const response = await this.fetcher(`${this.baseUrl}/api/books/${bookId}/reader/xray?${params.toString()}`, {
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to load reader X-Ray');

    return (await response.json()) as ReaderXrayResponse;
  }

  async enrichReaderXray(
    bookId: number,
    options: ReaderXrayEnrichOptions = {},
  ): Promise<ReaderXrayResponse> {
    const response = await this.fetcher(`${this.baseUrl}/api/books/${bookId}/reader/xray/enrich`, {
      method: 'POST',
      headers: { ...this.headers(), 'Content-Type': 'application/json' },
      body: JSON.stringify({
        chapter_id: options.chapterId ?? null,
        spoiler_mode: options.spoilerMode ?? 'no_spoiler',
      }),
    });
    await this.assertOk(response, 'Failed to enrich reader X-Ray');

    return (await response.json()) as ReaderXrayResponse;
  }

  async lookupReaderDictionary(
    bookId: number,
    query: string,
    options: { chapterId?: number | null; includeOnline?: boolean } = {},
  ): Promise<ReaderDictionaryResponse> {
    const params = new URLSearchParams({ q: query });
    if (options.chapterId != null) params.set('chapter_id', String(options.chapterId));
    if (options.includeOnline === false) params.set('include_online', 'false');
    const response = await this.fetcher(`${this.baseUrl}/api/books/${bookId}/dictionary/lookup?${params.toString()}`, {
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to lookup reader dictionary');

    return (await response.json()) as ReaderDictionaryResponse;
  }

  async getReaderDictionaryPack(
    bookId: number,
    options: { chapterId?: number | null } = {},
  ): Promise<ReaderDictionaryPack> {
    const params = new URLSearchParams();
    if (options.chapterId != null) params.set('chapter_id', String(options.chapterId));
    const suffix = params.toString() ? `?${params.toString()}` : '';
    const response = await this.fetcher(`${this.baseUrl}/api/books/${bookId}/dictionary/pack${suffix}`, {
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to load reader dictionary pack');

    return (await response.json()) as ReaderDictionaryPack;
  }

  async listReaderDictionaries(): Promise<ReaderDictionaryFile[]> {
    const response = await this.fetcher(`${this.baseUrl}/api/reader/dictionaries`, {
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to load reader dictionaries');

    const data = (await response.json()) as { dictionaries: ReaderDictionaryFile[] };
    return data.dictionaries;
  }

  async uploadReaderDictionary(file: File): Promise<ReaderDictionaryFile> {
    const body = new FormData();
    body.append('file', file);
    const response = await this.fetcher(`${this.baseUrl}/api/reader/dictionaries`, {
      method: 'POST',
      headers: this.headers(),
      body,
    });
    await this.assertOk(response, 'Failed to upload reader dictionary');

    return (await response.json()) as ReaderDictionaryFile;
  }

  async deleteReaderDictionary(filename: string): Promise<void> {
    const response = await this.fetcher(`${this.baseUrl}/api/reader/dictionaries/${encodeURIComponent(filename)}`, {
      method: 'DELETE',
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to delete reader dictionary');
  }

  readerDictionaryDownloadUrl(filename: string): string {
    return `${this.baseUrl}/api/reader/dictionaries/${encodeURIComponent(filename)}/download`;
  }

  async downloadReaderDictionary(filename: string): Promise<ExportDownload> {
    const response = await this.fetcher(this.readerDictionaryDownloadUrl(filename), {
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to download reader dictionary');

    const mediaType = response.headers.get('content-type') ?? 'application/octet-stream';
    return {
      blob: await response.blob(),
      filename: filenameFromContentDisposition(response.headers.get('content-disposition'), filename),
      mediaType,
    };
  }

  chapterAudioUrl(bookId: number, chapterId: number): string {
    return `${this.baseUrl}/api/books/${bookId}/chapters/${chapterId}/audio`;
  }

  chapterAudioDownloadUrl(bookId: number, chapterId: number): string {
    return `${this.baseUrl}/api/books/${bookId}/chapters/${chapterId}/audio/download`;
  }

  async getBookAudioPlaylist(bookId: number): Promise<BookAudioPlaylistResponse> {
    const response = await this.fetcher(`${this.baseUrl}/api/books/${bookId}/audio/playlist`, {
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to load audiobook playlist');

    const playlist = (await response.json()) as BookAudioPlaylistResponse;
    return {
      ...playlist,
      chapters: playlist.chapters.map((chapter) => ({
        ...chapter,
        download_url: this.absoluteApiUrl(chapter.download_url),
        stream_url: this.absoluteApiUrl(chapter.stream_url),
      })),
    };
  }

  async getProviderDefaults(): Promise<ProviderDefaults> {
    const response = await this.fetcher(`${this.baseUrl}/api/providers/defaults`, {
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to load provider defaults');

    const data = (await response.json()) as { defaults: ProviderDefaults };
    return data.defaults;
  }

  async estimateCost(
    providerId: string,
    sourceChars: number,
    chapterCount = 1,
    maxCostUsd?: number,
    promptOverheadTokens?: number,
  ): Promise<CostEstimate> {
    const body: Record<string, number | string> = {
      provider_id: providerId,
      source_chars: sourceChars,
      chapter_count: chapterCount,
    };

    if (maxCostUsd !== undefined) body.max_cost_usd = maxCostUsd;
    if (promptOverheadTokens !== undefined) body.prompt_overhead_tokens = promptOverheadTokens;

    const response = await this.fetcher(`${this.baseUrl}/api/providers/estimate`, {
      method: 'POST',
      headers: { ...this.headers(), 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    await this.assertOk(response, 'Failed to estimate cost');

    return (await response.json()) as CostEstimate;
  }

  async getProviderUsage(): Promise<ProviderUsage> {
    const response = await this.fetcher(`${this.baseUrl}/api/providers/usage`, {
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to load provider usage');

    const data = (await response.json()) as { usage: ProviderUsage };
    return data.usage;
  }

  async getSystemStatus(): Promise<SystemStatus> {
    const response = await this.fetcher(`${this.baseUrl}/api/system/status`, {
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to load system status');

    return (await response.json()) as SystemStatus;
  }

  async saveProviderKey(providerId: string, apiKey: string): Promise<Provider> {
    const response = await this.fetcher(`${this.baseUrl}/api/providers/${encodeURIComponent(providerId)}/key`, {
      method: 'POST',
      headers: { ...this.headers(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_key: apiKey }),
    });
    await this.assertOk(response, 'Failed to save provider API key');

    const data = (await response.json()) as { provider: Provider };
    return data.provider;
  }

  async testProvider(providerId: string, prompt: string): Promise<ProviderTestResult> {
    const response = await this.fetcher(`${this.baseUrl}/api/providers/test`, {
      method: 'POST',
      headers: { ...this.headers(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider_id: providerId, prompt }),
    });
    await this.assertOk(response, 'Failed to test provider');

    return (await response.json()) as ProviderTestResult;
  }

  async startTranslateJob(
    bookId: number,
    chapterIds: number[],
    presetId: string,
    styleProfileId?: string,
    chunkSize?: number | null,
  ): Promise<JobStartResponse> {
    const params = compactParams({
      preset_id: presetId,
      style_profile_id: styleProfileId,
      chunk_size: chunkSize ? String(chunkSize) : undefined,
    });
    const response = await this.fetcher(`${this.baseUrl}/api/jobs/translate`, {
      method: 'POST',
      headers: { ...this.headers(), 'Content-Type': 'application/json' },
      body: JSON.stringify(jobPayload(bookId, chapterIds, params)),
    });
    await this.assertOk(response, 'Failed to start translate job');

    return (await response.json()) as JobStartResponse;
  }

  async startBookTranslateJob(
    bookId: number,
    presetId: string,
    styleProfileId?: string,
    chunkSize?: number | null,
    options: { chapterIds?: number[]; limit?: number } = {},
  ): Promise<JobStartResponse> {
    const params = compactParams({
      preset_id: presetId,
      style_profile_id: styleProfileId,
      chunk_size: chunkSize ? String(chunkSize) : undefined,
    });
    const chapterIds = options.chapterIds ?? [];
    const limit = options.limit ?? (chapterIds.length || 500);
    const response = await this.fetcher(`${this.baseUrl}/api/jobs/translate`, {
      method: 'POST',
      headers: { ...this.headers(), 'Content-Type': 'application/json' },
      body: JSON.stringify(jobPayload(bookId, chapterIds, params, limit)),
    });
    await this.assertOk(response, 'Failed to start batch translate job');

    return (await response.json()) as JobStartResponse;
  }

  async exportBook(bookId: number, format: ExportFormat): Promise<ExportResponse> {
    const response = await this.fetcher(`${this.baseUrl}/api/books/${bookId}/exports`, {
      method: 'POST',
      headers: { ...this.headers(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ format }),
    });
    await this.assertOk(response, 'Failed to export book');

    return (await response.json()) as ExportResponse;
  }

  async downloadBookExport(bookId: number, format: ExportFormat): Promise<ExportDownload> {
    const response = await this.fetcher(`${this.baseUrl}/api/books/${bookId}/exports/${format}/download`, {
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to download exported book');

    const blob = await response.blob();
    return {
      blob,
      filename: filenameFromContentDisposition(
        response.headers.get('content-disposition'),
        `book.${format}`,
      ),
      mediaType: response.headers.get('content-type') ?? blob.type,
    };
  }

  async downloadAudiobookExport(bookId: number, format: AudiobookExportFormat): Promise<ExportDownload> {
    const response = await this.fetcher(`${this.baseUrl}/api/books/${bookId}/exports/audiobook/${format}/download`, {
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to download audiobook export');

    const blob = await response.blob();
    return {
      blob,
      filename: filenameFromContentDisposition(
        response.headers.get('content-disposition'),
        `audiobook.${format}`,
      ),
      mediaType: response.headers.get('content-type') ?? blob.type,
    };
  }

  async downloadReaderAnnotations(
    bookId: number,
    format: ReaderAnnotationExportFormat,
    options: { kind?: ReaderAnnotationKind | ReaderAnnotationKind[] | null } = {},
  ): Promise<ExportDownload> {
    const params = new URLSearchParams();
    const kinds = Array.isArray(options.kind) ? options.kind : options.kind ? [options.kind] : [];
    if (kinds.length > 0) params.set('kind', kinds.join(','));
    const suffix = params.toString() ? `?${params.toString()}` : '';
    const response = await this.fetcher(`${this.baseUrl}/api/books/${bookId}/exports/annotations/${format}/download${suffix}`, {
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to download reader annotations');

    const blob = await response.blob();
    return {
      blob,
      filename: filenameFromContentDisposition(
        response.headers.get('content-disposition'),
        `reader-annotations.${format}`,
      ),
      mediaType: response.headers.get('content-type') ?? blob.type,
    };
  }

  async listSystemBackups(): Promise<SystemBackupList> {
    const response = await this.fetcher(`${this.baseUrl}/api/system/backups`, {
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to load system backups');
    return (await response.json()) as SystemBackupList;
  }

  async createSystemBackup(payload: SystemBackupRequest = {}): Promise<SystemBackupJobStart> {
    const response = await this.fetcher(`${this.baseUrl}/api/system/backups`, {
      method: 'POST',
      headers: { ...this.headers(), 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    await this.assertOk(response, 'Failed to create system backup');
    return (await response.json()) as SystemBackupJobStart;
  }

  async downloadSystemBackup(filename: string): Promise<ExportDownload> {
    const response = await this.fetcher(`${this.baseUrl}/api/system/backups/${encodeURIComponent(filename)}/download`, {
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to download system backup');
    const blob = await response.blob();
    return {
      blob,
      filename: filenameFromContentDisposition(
        response.headers.get('content-disposition'),
        filename,
      ),
      mediaType: response.headers.get('content-type') ?? blob.type,
    };
  }

  async importReaderAnnotations(
    bookId: number,
    annotations: ReaderAnnotationImportItem[],
  ): Promise<ReaderAnnotationImportResponse> {
    const response = await this.fetcher(`${this.baseUrl}/api/books/${bookId}/annotations/import`, {
      body: JSON.stringify({ annotations }),
      headers: this.headers(),
      method: 'POST',
    });
    await this.assertOk(response, 'Failed to import reader annotations');
    return (await response.json()) as ReaderAnnotationImportResponse;
  }

  async getStyleProfiles(): Promise<StyleProfile[]> {
    const response = await this.fetcher(`${this.baseUrl}/api/style-profiles`, {
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to load style profiles');

    const data = (await response.json()) as { profiles: StyleProfile[] };
    return data.profiles;
  }

  async getDefaultStyleProfile(): Promise<StyleProfile> {
    const response = await this.fetcher(`${this.baseUrl}/api/style-profiles/default`, {
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to load default style profile');

    const data = (await response.json()) as { profile: StyleProfile };
    return data.profile;
  }

  async setDefaultStyleProfile(styleProfileId: string): Promise<StyleProfile> {
    const response = await this.fetcher(`${this.baseUrl}/api/style-profiles/default`, {
      method: 'PATCH',
      headers: { ...this.headers(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ style_profile_id: styleProfileId }),
    });
    await this.assertOk(response, 'Failed to set default style profile');

    const data = (await response.json()) as { default: StyleProfile };
    return data.default;
  }

  async startQaJob(bookId: number, chapterIds: number[]): Promise<JobStartResponse> {
    const response = await this.fetcher(`${this.baseUrl}/api/jobs/qa`, {
      method: 'POST',
      headers: { ...this.headers(), 'Content-Type': 'application/json' },
      body: JSON.stringify(jobPayload(bookId, chapterIds)),
    });
    await this.assertOk(response, 'Failed to start QA job');

    return (await response.json()) as JobStartResponse;
  }

  async startTtsJob(bookId: number, chapterIds: number[]): Promise<JobStartResponse> {
    const response = await this.fetcher(`${this.baseUrl}/api/jobs/tts`, {
      method: 'POST',
      headers: { ...this.headers(), 'Content-Type': 'application/json' },
      body: JSON.stringify(jobPayload(bookId, chapterIds)),
    });
    await this.assertOk(response, 'Failed to start TTS job');

    return (await response.json()) as JobStartResponse;
  }

  async startBookTtsJob(
    bookId: number,
    options: { limit?: number; voice?: string } = {},
  ): Promise<JobStartResponse> {
    const params: Record<string, string> = {};
    if (options.voice) params.voice = options.voice;
    const response = await this.fetcher(`${this.baseUrl}/api/jobs/tts`, {
      method: 'POST',
      headers: { ...this.headers(), 'Content-Type': 'application/json' },
      body: JSON.stringify(jobPayload(bookId, [], params, options.limit ?? 200)),
    });
    await this.assertOk(response, 'Failed to start audiobook TTS job');

    return (await response.json()) as JobStartResponse;
  }

  async streamJob(jobId: string, onEvent: (job: JobStatus) => void, signal: AbortSignal): Promise<void> {
    const response = await this.fetcher(`${this.baseUrl}/api/jobs/${jobId}/events`, {
      headers: { ...this.headers(), Accept: 'text/event-stream', 'Cache-Control': 'no-cache' },
      signal,
    });
    await this.assertOk(response, 'Failed to stream job events');
    if (!response.body) throw new Error('Failed to stream job events: missing response body');

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const chunks = buffer.split(/\r?\n\r?\n/);
      buffer = chunks.pop() ?? '';

      for (const chunk of chunks) {
        const line = chunk
          .split(/\r?\n/)
          .map((item) => item.trim())
          .find((item) => item.startsWith('data:'));
        if (!line) continue;

        const payload = JSON.parse(line.replace(/^data:\s*/, '')) as Partial<JobStatus>;
        if (
          payload.status &&
          payload.job_id &&
          typeof payload.progress === 'number' &&
          typeof payload.total === 'number' &&
          typeof payload.message === 'string'
        ) {
          onEvent(payload as JobStatus);
        }
      }
    }
  }

  async getJobStatus(jobId: string): Promise<JobStatus> {
    const response = await this.fetcher(`${this.baseUrl}/api/jobs/${jobId}`, {
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to load job status');

    return (await response.json()) as JobStatus;
  }

  async listJobs(limit = 50): Promise<JobStatus[]> {
    const response = await this.fetcher(`${this.baseUrl}/api/jobs?limit=${encodeURIComponent(String(limit))}`, {
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to load jobs');

    const data = (await response.json()) as JobListResponse;
    return data.jobs;
  }

  async getJobAttempts(jobId: string): Promise<JobAttempt[]> {
    const response = await this.fetcher(`${this.baseUrl}/api/jobs/${jobId}/attempts`, {
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to load job attempts');

    const data = (await response.json()) as JobAttemptResponse;
    return data.attempts;
  }

  async getJobLogs(jobId: string): Promise<JobLogEntry[]> {
    const response = await this.fetcher(`${this.baseUrl}/api/jobs/${jobId}/logs`, {
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to load job logs');

    return (await response.json()) as JobLogEntry[];
  }

  async retryFailedJob(jobId: string): Promise<JobStartResponse> {
    const response = await this.fetcher(`${this.baseUrl}/api/jobs/${encodeURIComponent(jobId)}/retry`, {
      method: 'POST',
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to retry job');

    return (await response.json()) as JobStartResponse;
  }

  async getTtsJob(jobId: string): Promise<TtsJobStatus> {
    const response = await this.fetcher(`${this.baseUrl}/api/tts/jobs/${encodeURIComponent(jobId)}`, {
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to load TTS job');

    return (await response.json()) as TtsJobStatus;
  }

  async retryTtsJob(jobId: string): Promise<JobStartResponse> {
    const response = await this.fetcher(`${this.baseUrl}/api/tts/jobs/${encodeURIComponent(jobId)}/retry`, {
      method: 'POST',
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to retry TTS chunks');

    return (await response.json()) as JobStartResponse;
  }

  async cancelJob(jobId: string): Promise<void> {
    const response = await this.fetcher(`${this.baseUrl}/api/jobs/${jobId}/cancel`, {
      method: 'POST',
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to cancel job');
  }

  async getQaReport(bookId: number, chapterId: number): Promise<QaReport | null> {
    const response = await this.fetcher(`${this.baseUrl}/api/books/${bookId}/chapters/${chapterId}/qa`, {
      headers: this.headers(),
    });
    if (response.status === 204 || response.status === 404) return null;
    await this.assertOk(response, 'Failed to load QA report');

    return (await response.json()) as QaReport;
  }

  async searchTm(query: string): Promise<TmSearchResult[]> {
    const response = await this.fetcher(`${this.baseUrl}/api/glossary/tm/search?q=${encodeURIComponent(query)}`, {
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to search translation memory');

    const data = (await response.json()) as { results: TmSearchResult[] };
    return data.results;
  }

  async getGlossaryTerms(bookId?: number): Promise<GlossaryTerm[]> {
    const query = bookId === undefined ? 'per_page=500' : `book_id=${bookId}&per_page=500`;
    const response = await this.fetcher(`${this.baseUrl}/api/glossary?${query}`, {
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to load glossary terms');

    const data = (await response.json()) as { items: GlossaryTerm[] };
    return data.items;
  }

  async updateGlossaryTerm(termId: number, updates: GlossaryTermUpdate): Promise<void> {
    const response = await this.fetcher(`${this.baseUrl}/api/glossary/terms/${termId}`, {
      method: 'PATCH',
      headers: { ...this.headers(), 'Content-Type': 'application/json' },
      body: JSON.stringify(updates),
    });
    await this.assertOk(response, 'Failed to update glossary term');
  }

  async lockGlossaryTerm(termId: number): Promise<void> {
    const response = await this.fetcher(`${this.baseUrl}/api/glossary/terms/${termId}/lock`, {
      method: 'POST',
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to lock glossary term');
  }

  async unlockGlossaryTerm(termId: number): Promise<void> {
    const response = await this.fetcher(`${this.baseUrl}/api/glossary/terms/${termId}/unlock`, {
      method: 'POST',
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to unlock glossary term');
  }

  async approveGlossaryTerm(termId: number): Promise<void> {
    const response = await this.fetcher(`${this.baseUrl}/api/glossary/terms/${termId}/approve`, {
      method: 'POST',
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to approve glossary term');
  }

  async rejectGlossaryTerm(termId: number): Promise<void> {
    const response = await this.fetcher(`${this.baseUrl}/api/glossary/terms/${termId}/reject`, {
      method: 'POST',
      headers: this.headers(),
    });
    await this.assertOk(response, 'Failed to reject glossary term');
  }
}
