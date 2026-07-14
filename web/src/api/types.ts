export type TokenResponse = {
  access_token: string;
  refresh_token: string;
  token_type: string;
};

export type Provider = {
  id: string;
  label: string;
  base_url: string;
  model: string;
  api_key_env: string;
  api_key_set: boolean;
  temperature: number;
  timeout_seconds: number;
  supports_streaming: number;
  supports_batch: number;
  cost_input_per_1m: number;
  cost_output_per_1m: number;
  enabled: number;
  notes: string;
  created_at?: string;
  updated_at?: string;
};

export type ProviderDefaults = Record<string, string>;

export type TranslationPreset = {
  id: 'cheapest' | 'balanced' | 'quality_high' | string;
  label: string;
  description: string;
  chunk_size?: number | null;
};

export type CostEstimate = {
  provider_id: string;
  model: string;
  chapter_count: number;
  estimated_input_tokens: number;
  estimated_output_tokens: number;
  estimated_cost_usd: number;
  within_budget: boolean;
};

export type ProviderUsage = {
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_tokens: number;
  total_estimated_cost_usd: number;
};

export type ProviderTestResult = {
  provider_id: string;
  model: string;
  ok: boolean;
  sample: string;
};

export type JobStatus = {
  job_id: string;
  job_type?: string;
  status: string;
  state?: string;
  progress: number;
  total: number;
  current_book_id?: number;
  current_chapter_id?: number;
  current_chunk_index?: number;
  total_chunks?: number;
  current_step?: string;
  provider?: string;
  model?: string;
  message: string;
  error?: string;
  created_at?: string;
  updated_at?: string;
  started_at?: string;
  completed_at?: string;
  failed_at?: string;
  finished_at?: string | null;
  cancel_requested?: boolean;
  last_safe_error?: string;
  internal_error_ref?: string;
  target_ids?: number[];
  preset_id?: string;
  chunk_size?: number | null;
  active_stage?: string;
  stage_timings?: JobStageTiming[];
  retry_of_job_id?: string;
  retry_count?: number;
  previous_error?: string;
  last_retry_job_id?: string;
  skipped_completed_chapter_ids?: number[];
};

export type JobLogEntry = {
  id: number;
  job_id: string;
  event_type: string;
  state?: string;
  step?: string;
  message?: string;
  details?: Record<string, unknown>;
  created_at?: string;
};

export type JobStageTiming = {
  stage: string;
  status: string;
  elapsed_ms: number;
  provider_id?: string;
  model?: string;
  error?: string;
};

export type JobStartResponse = {
  job_id: string;
  status: string;
  message: string;
};

export type JobListResponse = {
  jobs: JobStatus[];
};

export type TtsChunkStatus = {
  id: string;
  job_id: string;
  chunk_index: number;
  text_hash: string;
  status: string;
  wav_path?: string;
  mp3_path?: string;
  duration_seconds?: number;
  qa_status?: string;
  qa_report?: Record<string, unknown>;
  error_message?: string;
  created_at?: string;
  updated_at?: string;
};

export type TtsJobStatus = {
  id?: string;
  job_id?: string;
  book_id?: number;
  chapter_id?: number;
  status: string;
  provider?: string;
  model?: string;
  progress?: number;
  output_mp3_ready?: boolean;
  output_m4b_ready?: boolean;
  output_mp3_download_url?: string;
  output_m4b_download_url?: string;
  error_message?: string;
  audio_summary?: {
    expected_chunk_count?: number;
    completed_chunk_count?: number;
    failed_chunk_count?: number;
    missing_chunk_file_count?: number;
    qa_warning_count?: number;
    output_mp3_ready?: boolean;
    output_mp3_size_bytes?: number;
    output_m4b_ready?: boolean;
    output_m4b_size_bytes?: number;
    warnings?: string[];
  };
  chunks: TtsChunkStatus[];
};

export type SystemStatus = {
  public_deploy: boolean;
  api_ready: boolean;
  active_provider: string;
  upload_max_bytes: number;
  asset_protection_enabled: boolean;
  active_jobs: number;
  running_jobs: number;
  queued_jobs?: number;
  retrying_jobs?: number;
  interrupted_jobs?: number;
  failed_jobs?: number;
  last_failed_job: JobStatus | null;
  recent_operational_errors?: Array<{
    id: number;
    event_type: string;
    severity: string;
    source: string;
    message: string;
    job_id: string;
    details: Record<string, unknown>;
    created_at: string;
  }>;
  recent_backup_events?: Array<{
    id: number;
    event_type: string;
    severity: string;
    source: string;
    message: string;
    job_id: string;
    details: Record<string, unknown>;
    created_at: string;
  }>;
  app_version: string;
  build: string;
  database_available: boolean;
  data_directory_available: boolean;
  data_size_bytes: number;
  storage_health: string;
  storage_label: string;
  backup_recommendation: string;
  db_size_bytes: number;
  cache_count: number;
  cache_size_bytes: number;
  ollama_host: string;
  ollama_model: string;
};

export type ExportFormat = 'txt' | 'docx' | 'epub';

export type AudiobookExportFormat = 'm4b';

export type BookAudioPlaylistItem = {
  chapter_id: number;
  chapter_number: number;
  title: string;
  duration_seconds: number;
  download_url: string;
  filename: string;
  order: number;
  size_bytes: number;
  stream_url: string;
};

export type BookAudioPlaylistResponse = {
  book_id: number;
  book_title?: string;
  chapters: BookAudioPlaylistItem[];
};

export type ReaderAnnotationExportFormat = 'json' | 'md' | 'csv';

export type ExportResponse = {
  book_id: number;
  book_title: string;
  format: ExportFormat;
  filename: string;
  path: string;
  download_url?: string;
  media_type: string;
  size_bytes: number;
  chapter_count: number;
};

export type SystemBackupRequest = {
  include_audio?: boolean;
  include_exports?: boolean;
  include_job_logs?: boolean;
  include_secrets?: boolean;
  passphrase?: string;
};

export type SystemBackupJobStart = {
  job_id: string;
  status: string;
  message: string;
};

export type SystemBackupItem = {
  filename: string;
  size_bytes: number;
  created_at: string;
  encrypted: boolean;
  secrets_included: boolean;
  included_modules: string[];
  excluded_modules: string[];
  manifest: Record<string, unknown>;
  download_url: string;
  metadata_status:
    | 'READY'
    | 'METADATA_MISSING'
    | 'METADATA_INVALID'
    | 'ARTIFACT_MISSING'
    | 'ARTIFACT_INVALID'
    | 'UNSUPPORTED_FORMAT';
  repair_needed: boolean;
  manifest_available: boolean;
  archive_available: boolean;
  warning: string;
};

export type SystemBackupList = {
  items: SystemBackupItem[];
};

export type ExportDownload = {
  blob: Blob;
  filename: string;
  mediaType: string;
};

export type ChapterTextResponse = {
  chapter_id: number;
  text: string;
};

export type ChapterContentResponse = ChapterTextResponse & {
  html: string;
};

export type ReaderProgressMode = 'scroll' | 'paginated';

export type ReaderProgressTextAnchor = {
  offset: number;
  prefix: string;
  suffix: string;
  text: string;
  version: 1;
};

export type ReaderAnnotationKind = 'bookmark' | 'highlight' | 'note';

export type ReaderSearchScope = 'translation' | 'notes' | 'highlights';

export type ReaderSearchSource = 'translation' | 'note' | 'highlight';

export type ReaderSearchResult = {
  chapter_id: number;
  chapter_number: number;
  chapter_title: string;
  char_end?: number;
  char_start?: number;
  snippet: string;
  paragraph_index: number;
  score: number;
  source: ReaderSearchSource;
};

export type ReaderProgress = {
  book_id: number;
  chapter_id: number;
  chapter_number: number;
  chapter_title: string;
  mode: ReaderProgressMode;
  percent: number;
  paragraph_index: number;
  char_offset: number;
  absolute_char_offset: number;
  page_index: number;
  anchor?: ReaderProgressTextAnchor | null;
  updated_at: string;
};

export type ReaderAnnotation = {
  id: number;
  book_id: number;
  chapter_id: number;
  chapter_number: number;
  chapter_title: string;
  kind: ReaderAnnotationKind;
  paragraph_index: number;
  char_start: number;
  char_end: number;
  selected_text: string;
  note: string;
  color: string;
  client_id?: string;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
};

export type ReaderStateResponse = {
  progress: ReaderProgress | null;
  annotations: ReaderAnnotation[];
};

export type ReaderSyncProgress = ReaderProgressUpdate & {
  updated_at?: string;
};

export type ReaderSyncAnnotation = {
  id?: number | null;
  client_id?: string | null;
  chapter_id: number;
  kind: ReaderAnnotationKind;
  paragraph_index?: number;
  char_start?: number;
  char_end?: number;
  selected_text?: string;
  note?: string;
  color?: string;
  created_at?: string;
  updated_at?: string;
  deleted_at?: string | null;
};

export type ReaderSyncRequest = {
  device_id?: string;
  last_sync_at?: string | null;
  progress?: ReaderSyncProgress | null;
  annotations?: ReaderSyncAnnotation[];
};

export type ReaderAnnotationImportItem = {
  id?: number | null;
  client_id?: string | null;
  chapter_id?: number | null;
  chapter_number?: number | null;
  kind: ReaderAnnotationKind;
  paragraph_index?: number;
  char_start?: number;
  char_end?: number;
  selected_text?: string;
  note?: string;
  color?: string;
};

export type ReaderAnnotationImportResponse = {
  summary: {
    imported: number;
    skipped: number;
    duplicates: number;
    invalid: number;
  };
  annotations: ReaderAnnotation[];
};

export type ReaderSyncConflict = {
  entity: 'progress' | 'annotation' | string;
  id: number | null;
  client_id: string | null;
  resolution: 'server_won' | 'client_won' | string;
  reason: string;
  server_annotation?: ReaderAnnotation | null;
  client_annotation?: ReaderSyncAnnotation | null;
};

export type ReaderSyncResponse = ReaderStateResponse & {
  conflicts: ReaderSyncConflict[];
  server_time: string;
};

export type ReaderExplainSpoilerMode = 'no_spoiler' | 'allow_spoiler';

export type ReaderExplainRequest = {
  text: string;
  context_before?: string;
  context_after?: string;
  spoiler_mode?: ReaderExplainSpoilerMode;
};

export type ReaderExplainTerm = {
  source: string;
  target: string;
  note: string;
};

export type ReaderExplainResponse = {
  explanation: string;
  terms: ReaderExplainTerm[];
};

export type ReaderDictionarySource = {
  source: 'glossary' | 'xray' | 'online' | string;
  term: string;
  target?: string;
  definition?: string;
  category?: string;
  provider?: string;
  part_of_speech?: string;
  aliases?: string[];
  variants?: string[];
  first_chapter_number?: number;
  mention_count?: number;
};

export type ReaderDictionaryResponse = {
  book_id: number;
  chapter_id: number | null;
  query: string;
  sources: ReaderDictionarySource[];
  offline_count: number;
  online: {
    status: 'skipped' | 'ok' | 'empty' | 'error' | string;
    error: string;
    count: number;
  };
  cache?: {
    hit: boolean;
    stored: boolean;
    scope: string;
    updated_at?: string;
  };
};

export type ReaderDictionaryPack = {
  book_id: number;
  chapter_id: number | null;
  sources: ReaderDictionarySource[];
  source_count: number;
  counts: {
    glossary: number;
    builtin: number;
    offline_dictionary: number;
    xray: number;
    [key: string]: number;
  };
  online: {
    status: 'skipped' | string;
    error: string;
    count: number;
  };
  generated_at: string;
  cache?: {
    hit: boolean;
    stored: boolean;
    scope: string;
    updated_at?: string;
  };
};

export type ReaderDictionaryFile = {
  filename: string;
  entry_count: number;
  size_bytes: number;
};

export type ReaderXrayEntityType = 'character' | 'faction' | 'location' | 'item' | 'realm' | 'skill';

export type ReaderXraySpoilerMode = 'no_spoiler' | 'allow_spoiler';

export type ReaderXrayMention = {
  id: number;
  chapter_id: number;
  chapter_number: number;
  paragraph_index: number;
  mention_text: string;
  context: string;
  spoiler_level: number;
};

export type ReaderXrayEntity = {
  id: number;
  book_id: number;
  type: ReaderXrayEntityType;
  name: string;
  aliases: string[];
  description: string;
  first_chapter_number: number;
  importance: number;
  metadata: Record<string, unknown>;
  mentions: ReaderXrayMention[];
  mention_count: number;
};

export type ReaderXrayTimelineEvent = {
  id: number;
  chapter_id: number;
  chapter_number: number;
  event_order: number;
  title: string;
  summary: string;
  spoiler_level: number;
  entities: string[];
};

export type ReaderXrayRelationship = {
  source: string;
  target: string;
  relation: string;
  evidence: string;
  chapter_number: number;
  strength: number;
  source_type: string;
};

export type ReaderXrayFactionNode = {
  name: string;
  description: string;
  parent: string;
  first_chapter_number: number;
  members: string[];
  children: string[];
};

export type ReaderXrayPowerRanking = {
  name: string;
  type: ReaderXrayEntityType | string;
  rank: number;
  label: string;
  basis: string;
  chapter_number: number;
  faction: string;
};

export type ReaderXrayResponse = {
  book_id: number;
  current_chapter_number: number | null;
  spoiler_mode: ReaderXraySpoilerMode;
  entities: ReaderXrayEntity[];
  relationships: ReaderXrayRelationship[];
  faction_tree: ReaderXrayFactionNode[];
  power_rankings: ReaderXrayPowerRanking[];
  timeline: ReaderXrayTimelineEvent[];
};

export type ReaderXrayEnrichOptions = {
  chapterId?: number | null;
  spoilerMode?: ReaderXraySpoilerMode;
};

export type ReaderProgressUpdate = {
  chapter_id: number;
  mode?: ReaderProgressMode;
  percent?: number;
  paragraph_index?: number;
  char_offset?: number;
  absolute_char_offset?: number;
  page_index?: number;
  anchor?: ReaderProgressTextAnchor | null;
};

export type ReaderAnnotationCreate = {
  kind: ReaderAnnotationKind;
  paragraph_index?: number;
  char_start?: number;
  char_end?: number;
  selected_text?: string;
  note?: string;
  color?: string;
};

export type ReaderAnnotationUpdate = Partial<ReaderAnnotationCreate>;

export type ImportPasteRequest = {
  title: string;
  chapter_number: number;
  chapter_title: string;
  text: string;
};

export type ImportFileRequest = {
  title: string;
  chapter_number: number;
  chapter_title: string;
  file: File;
};

export type ImportContentKind = 'raw' | 'translated' | 'both' | 'unknown';

export type WizardTextImportChapter = {
  chapter_number: number;
  chapter_title: string;
  text?: string;
  raw_text?: string;
  translated_text?: string;
};

export type WizardTextImportRequest = {
  title: string;
  author?: string;
  target_book_id?: number | null;
  content_kind: ImportContentKind;
  duplicate_strategy?: EbookDuplicateStrategy;
  source_type?: 'paste' | 'txt' | 'wizard' | string;
  chapters: WizardTextImportChapter[];
};

export type WizardTextImportResult = {
  book_id: number;
  title: string;
  content_kind: ImportContentKind | string;
  chapter_count: number;
  imported_chapters: number;
  skipped_chapters: number;
  overwritten_chapters: number;
  chapter_ids: number[];
  warnings?: EbookImportWarning[];
  message: string;
};

export type EbookDuplicateStrategy = 'error' | 'skip' | 'overwrite';

export type EbookBookMatchReason = 'title' | 'selected' | 'new';

export type EbookSplitMode = 'auto' | 'single';

export type EbookSplitMethod = 'toc' | 'heading' | 'spine' | 'single' | 'regex';

export type EbookPreviewChapter = {
  chapter_number: number;
  title: string;
  sample: string;
};

export type EbookImportWarning = {
  type: string;
  message: string;
  chapter_number?: number;
  title?: string;
};

export type EbookImportDryRun = {
  target_book_id: number | null;
  target_title: string;
  duplicate_strategy: EbookDuplicateStrategy;
  chapter_count: number;
  new_chapters: number;
  duplicate_chapters: number;
  would_import: number;
  would_skip: number;
  would_overwrite: number;
  would_error: number;
  existing_book_id: number | null;
  existing_book_title: string;
  existing_chapter_count: number;
  book_match_reason: EbookBookMatchReason;
  requires_existing_book_confirmation: boolean;
};

export type EbookPreview = {
  title: string;
  author: string;
  language: string;
  source_format: string;
  cover_present: boolean;
  cover_preview_url?: string;
  cover_url?: string;
  chapter_count: number;
  split_method?: EbookSplitMethod | string;
  toc_chapter_count?: number;
  chapters: EbookPreviewChapter[];
  first_chapters?: EbookPreviewChapter[];
  last_chapters?: EbookPreviewChapter[];
  warnings?: EbookImportWarning[];
  dry_run?: EbookImportDryRun;
  upload_id?: string;
  inbox_file?: string;
};

export type EbookInboxFile = {
  name: string;
  size: number;
  modified_at: string;
};

export type EbookInboxList = {
  directory: string;
  files: EbookInboxFile[];
};

export type EbookImportRequest = {
  file?: File;
  uploadId?: string;
  inboxFile?: string;
  targetBookId?: number | null;
  confirmedExistingBookId?: number | null;
  duplicateStrategy?: EbookDuplicateStrategy;
  splitMode?: EbookSplitMode;
};

export type EbookImportResult = {
  book_id: number;
  title: string;
  author: string;
  source_format: string;
  chapter_count: number;
  split_method?: EbookSplitMethod | string;
  toc_chapter_count?: number;
  imported_chapters: number;
  skipped_chapters: number;
  overwritten_chapters?: number;
  chapter_ids: number[];
  warnings?: EbookImportWarning[];
  cover_url?: string;
  message: string;
};

export type EbookImportHistoryRun = {
  id: number;
  book_id: number;
  title: string;
  filename: string;
  source_format: string;
  duplicate_strategy: EbookDuplicateStrategy | string;
  split_mode: EbookSplitMode | string;
  chapter_count: number;
  imported_chapters: number;
  skipped_chapters: number;
  overwritten_chapters: number;
  warning_count: number;
  warnings: EbookImportWarning[];
  created_at: string;
};

export type SourceChapterPreview = {
  chapter_number: number;
  title: string;
  url: string;
};

export type SourcePreview = {
  adapter_id: string;
  adapter_label: string;
  source: string;
  source_url: string;
  title: string;
  author: string;
  description: string;
  cover_url: string;
  chapters: SourceChapterPreview[];
  chapter_count: number;
  policy?: {
    source_id: string;
    label: string;
    delay_seconds: number;
    max_concurrency: number;
    retry_limit: number;
  } | null;
  managed_source_id: string;
  managed_source_status: string;
  managed_source_trust_level: string;
  automation_allowed: boolean;
  automation_reason: string;
  bypass_used: boolean;
  bypass_method: string;
};

export type URLFetchChapterRequest = {
  url: string;
  chapter_number: number;
  title: string;
};

export type URLFetchRequest = {
  source_url: string;
  title: string;
  author: string;
  source: string;
  chapters: URLFetchChapterRequest[];
};

export type URLFetchChapterResult = {
  chapter_number: number;
  title: string;
  url: string;
  success: boolean;
  error: string;
  text_length: number;
  book_id: number;
  chapter_id: number;
};

export type URLFetchResponse = {
  title: string;
  book_id: number;
  total: number;
  succeeded: number;
  failed: number;
  chapters: URLFetchChapterResult[];
};

export type SourceCapability = {
  source_id: string;
  label: string;
  domains: string[];
  adapter_id: string;
  adapter_label: string;
  extraction: 'selector' | 'generic' | string;
  direct_import: boolean;
  delay_seconds: number;
  max_concurrency: number;
  retry_limit: number;
  notes: string;
};

export type SourceCatalogEntry = {
  id: string;
  external_id: string;
  catalog_source: string;
  name: string;
  url: string;
  domain: string;
  author: string;
  downloads: number;
  version: string;
  raw_tags: string;
  tags: string[];
  unknown_tags: string[];
  supported: boolean;
  supported_status: 'supported' | 'unsupported' | 'unchecked' | 'failed' | string;
  supported_source_id: string;
  invalid_reason: string;
  updated_label: string;
  last_check_status: string;
  last_check_at: string;
  last_check_error: string;
  last_check_http_status: number | null;
  last_check_final_url: string;
  managed_source_id: string;
  managed_status: 'IMPORTED' | 'NEEDS_REVIEW' | 'VERIFIED' | 'BROKEN' | 'BLOCKED' | string;
  managed_trust_level: 'UNKNOWN' | 'LOW' | 'MEDIUM' | 'HIGH' | 'MANUAL_ONLY' | string;
  managed_last_test_status: string;
  managed_last_tested_at: string;
  managed_last_successful_fetch_at: string;
  managed_last_error: string;
  managed_rate_limit_requests_per_minute: number;
  managed_rate_limit_delay_ms: number;
  managed_max_concurrent_requests: number;
  managed_cooldown_after_error_seconds: number;
  managed_notes: string;
  managed_parser_type: string;
  managed_language: string;
  can_use_in_jobs: boolean;
  created_at: string;
  updated_at: string;
};

export type SourceCatalogList = {
  items: SourceCatalogEntry[];
  entries: SourceCatalogEntry[];
  total: number;
  page: number;
  per_page: number;
  page_size: number;
};

export type SourceCatalogQuery = {
  query?: string;
  tag?: string;
  domain?: string;
  supported?: 'true' | 'false' | 'supported' | 'unsupported' | 'all' | '';
  status?: string;
  trust_level?: string;
  page?: number;
  page_size?: number;
};

export type SourceCatalogHealthResult = {
  catalog_entry_id: string;
  domain: string;
  status: 'reachable' | 'timeout' | 'blocked' | 'captcha' | 'unsupported' | 'preview_ok' | 'error' | string;
  reason: string;
  checked_at: string;
  final_url: string;
  http_status: number | null;
};

export type ManagedSource = {
  id: string;
  catalog_entry_id: string;
  name: string;
  base_url: string;
  domain: string;
  language: string;
  parser_type: string;
  parser_config: Record<string, unknown>;
  status: 'IMPORTED' | 'NEEDS_REVIEW' | 'VERIFIED' | 'BROKEN' | 'BLOCKED' | string;
  trust_level: 'UNKNOWN' | 'LOW' | 'MEDIUM' | 'HIGH' | 'MANUAL_ONLY' | string;
  supported_source_id: string;
  last_test_status: string;
  last_tested_at: string;
  last_successful_fetch_at: string;
  last_error: string;
  rate_limit_requests_per_minute: number;
  rate_limit_delay_ms: number;
  max_concurrent_requests: number;
  cooldown_after_error_seconds: number;
  notes: string;
  can_use_in_jobs: boolean;
  created_at: string;
  updated_at: string;
};

export type ManagedSourceList = {
  items: ManagedSource[];
  total: number;
  page: number;
  per_page: number;
  page_size: number;
};

export type ManagedSourceTestResult = {
  source_id: string;
  domain: string;
  status: 'reachable' | 'blocked_by_policy' | 'timeout' | 'invalid_url' | 'fetch_failed' | 'parse_failed' | 'parser_config_missing' | 'success' | string;
  reason: string;
  tested_at: string;
  final_url: string;
  http_status: number | null;
};

export type ManagedSourceImportSummary = {
  selected: number;
  inserted: number;
  duplicates: number;
  invalid: number;
  skipped: number;
  items: ManagedSource[];
};

export type ManagedSourceQuery = {
  query?: string;
  status?: string;
  trust_level?: string;
  language?: string;
  page?: number;
  page_size?: number;
};

export type ManagedSourceUpdateRequest = {
  status?: string;
  trust_level?: string;
  parser_type?: string;
  parser_config?: Record<string, unknown>;
  notes?: string;
  rate_limit_requests_per_minute?: number;
  rate_limit_delay_ms?: number;
  max_concurrent_requests?: number;
  cooldown_after_error_seconds?: number;
};

export type SourceAdapterCandidate = {
  id: string;
  catalog_entry_id: string;
  domain: string;
  sample_url: string;
  detected_title: string;
  detected_chapter_list: Array<Record<string, unknown>>;
  parser_confidence: 'high' | 'medium' | 'low' | 'failed' | string;
  failure_reason: string;
  status: 'draft' | 'needs_review' | 'rejected' | 'promoted' | string;
  created_at: string;
  updated_at: string;
  reviewed_at: string;
  reviewed_by: string;
};

export type SourceAdapterCandidateList = {
  items: SourceAdapterCandidate[];
  total: number;
  page: number;
  per_page?: number;
  page_size: number;
};

export type ImportUrlRequest = {
  url: string;
  title: string;
  author?: string;
  source?: string;
  managed_source_id?: string;
  chapters: SourceChapterPreview[];
  retry_limit?: number;
};

export type ImportResponse = {
  book_id: number;
  chapter_id: number;
  path?: string;
  title?: string;
  chapter_number?: number;
  chapter_title?: string;
  message: string;
};

export type JobAttempt = {
  id?: number;
  job_id: string;
  chapter_id?: number | null;
  stage?: string;
  provider_id: string;
  model: string;
  status: string;
  error?: string;
  elapsed_ms?: number;
  created_at?: string;
};

export type JobAttemptResponse = {
  attempts: JobAttempt[];
};

export type QaReport = {
  book_id: number;
  chapter_id: number;
  job_id?: string;
  overall_status?: 'PASS' | 'WARNING' | 'FAIL' | 'NOT_RUN' | string;
  missing_paragraph_warning?: boolean | number;
  chinese_leakage_count?: number;
  name_consistency_status?: string;
  term_consistency_status?: string;
  length_ratio?: number;
  repetition_warning?: boolean | number;
  style_warnings?: Array<Record<string, unknown>>;
  glossary_violations?: Array<Record<string, unknown>>;
  suggested_fixes?: Array<Record<string, unknown>>;
  quality_score: number;
  fidelity_score?: number;
  style_score?: number;
  glossary_score?: number;
  audiobook_score?: number;
  verdict?: string;
  issues?: Array<Record<string, unknown>>;
  report_json?: Record<string, unknown> | string;
  created_at?: string;
};

export type TmSearchResult = {
  source_text: string;
  translation_text: string;
  match_score: number;
  stored_score?: number;
  book_id?: number;
  chapter_number?: number;
};

export type StyleProfile = {
  id: string;
  label: string;
  pronoun_rules: string;
  han_viet_level: string;
  preferred_terms: string;
  banned_modern_terms: string;
  prompt_rules: string;
  is_default: number;
  created_at?: string;
  updated_at?: string;
};

export type GlossaryTerm = {
  id: number;
  book_id: number;
  source_term: string;
  target_term: string;
  category?: string;
  mode?: string;
  approved?: number;
  pinyin?: string;
  notes_vi?: string;
  variants?: string;
  occurrence_count?: number;
  last_seen?: string;
  priority: number;
  locked: number;
  genre: string;
  term_type: string;
  alternatives?: string;
  gender?: string;
  first_seen_chapter_id?: number;
  first_seen_chapter_number?: number;
  review_status?: string;
  source_context?: string;
  created_at?: string;
  updated_at?: string;
};

export type GlossaryTermUpdate = Partial<
  Pick<
    GlossaryTerm,
    | 'target_term'
    | 'category'
    | 'mode'
    | 'approved'
    | 'pinyin'
    | 'notes_vi'
    | 'variants'
    | 'priority'
    | 'locked'
    | 'genre'
    | 'term_type'
    | 'alternatives'
    | 'gender'
    | 'review_status'
    | 'source_context'
  >
>;

export type Book = {
  id: number;
  title: string;
  author: string;
  source: string;
  source_url: string;
  cover_path?: string;
  cover_url?: string;
  created_at: string;
  updated_at: string;
};

export type BookUpdate = Partial<Pick<Book, 'title' | 'author' | 'source' | 'source_url'>>;

export type ChapterApi = {
  id: number;
  book_id: number;
  chapter_number: number;
  title: string;
  status: string;
  source_url: string;
  raw_text_path: string | null;
  cleaned_text_path: string | null;
  translated_text_path: string | null;
  content_html_path?: string | null;
  audio_path: string | null;
  translated_at: string | null;
  audio_created_at: string | null;
};

export type BookSummary = {
  id: number;
  title: string;
  translated: number;
  audio: number;
  failed: number;
  total: number;
  qa_low?: number;
  last_activity?: string;
  next_action?: string;
};

export type TranslatedBookSummary = {
  id: number;
  title: string;
  author: string;
  source: string;
  source_url: string;
  cover_path?: string;
  cover_url?: string;
  total_chapters: number;
  translated_chapters: number;
  audio_chapters: number;
  failed_chapters: number;
  qa_low_chapters: number;
  first_translated_chapter_id: number | null;
  latest_translated_chapter_id: number | null;
  latest_chapter_number: number | null;
  latest_chapter_title: string;
  last_activity: string;
};

export type Chapter = Pick<
  ChapterApi,
  'id' | 'book_id' | 'chapter_number' | 'title' | 'status' | 'audio_path'
> & {
  book_title?: string;
  content_html_path?: string | null;
  has_translation?: boolean;
  qa_score?: number;
  qa_verdict?: string;
  qa_issue_count?: number;
  top_issues?: string[];
  source_preview?: string;
  translation_preview?: string;
  latest_job_status?: string;
  latest_provider?: string;
  latest_model?: string;
  last_action?: string;
  error?: string;
};
