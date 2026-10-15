import { useState } from 'react';
import { ApiClient } from '../../api/client';
import type { JobStartResponse, SourceCatalogList, SourcePreview, URLFetchResponse } from '../../api/types';
import { useImportJob } from '../../state/useImportJob';
import { errorMessage } from './importLabels';
import type { EbookPreviewState, ImportPanelProps } from './types';

const SOURCE_CHAPTER_PAGE_SIZE = 25;
const disabledImportJobClient = new ApiClient('');

export function useSourceImport({ importJobClient, title, onPreviewTitle, onJobCreated,
  onPreviewImportUrl, onStartImportUrlJob, onFetchSourceChapters, loadSourceCatalog }: Pick<ImportPanelProps,
  'importJobClient' | 'onPreviewImportUrl' | 'onStartImportUrlJob' | 'onFetchSourceChapters' | 'loadSourceCatalog'> & {
  title: string;
  onPreviewTitle(title: string): void;
  onJobCreated(job: JobStartResponse | null): void;
}) {
  const [sourceUrl, setSourceUrl] = useState('');
  const [sourcePreview, setSourcePreview] = useState<SourcePreview | null>(null);
  const [sourcePreviewState, setSourcePreviewState] = useState<EbookPreviewState>('idle');
  const [sourcePreviewError, setSourcePreviewError] = useState('');
  const [selectedChapterUrls, setSelectedChapterUrls] = useState<Set<string>>(new Set());
  const [chapterPage, setChapterPage] = useState(0);
  const [rangeStart, setRangeStart] = useState('');
  const [rangeEnd, setRangeEnd] = useState('');
  const [fetchState, setFetchState] = useState<EbookPreviewState>('idle');
  const [fetchResult, setFetchResult] = useState<URLFetchResponse | null>(null);
  const [fetchError, setFetchError] = useState('');
  const [catalogQuery, setCatalogQuery] = useState('');
  const [catalogState, setCatalogState] = useState<EbookPreviewState>('idle');
  const [catalogError, setCatalogError] = useState('');
  const [catalog, setCatalog] = useState<SourceCatalogList | null>(null);
  const importJob = useImportJob(importJobClient ?? disabledImportJobClient, {
    enabled: Boolean(importJobClient),
  });

  const sourceChapterPageCount = Math.max(
    1,
    Math.ceil((sourcePreview?.chapters.length ?? 0) / SOURCE_CHAPTER_PAGE_SIZE),
  );
  const visibleSourceChapters = sourcePreview?.chapters.slice(
    chapterPage * SOURCE_CHAPTER_PAGE_SIZE,
    (chapterPage + 1) * SOURCE_CHAPTER_PAGE_SIZE,
  ) ?? [];
  const allVisibleChaptersSelected = visibleSourceChapters.length > 0
    && visibleSourceChapters.every((chapter) => selectedChapterUrls.has(chapter.url));
  const durableImportActive = Boolean(importJobClient && importJob.state.phase !== 'idle');
  async function handlePreviewSourceUrl(): Promise<void> {
    if (!onPreviewImportUrl || !sourceUrl.trim()) return;
    setSourcePreview(null);
    setSourcePreviewError('');
    setSourcePreviewState('loading');
    setSelectedChapterUrls(new Set());
    setChapterPage(0);
    setRangeStart('');
    setRangeEnd('');
    setFetchResult(null);
    setFetchError('');
    try {
      const preview = await onPreviewImportUrl(sourceUrl.trim());
      setSourcePreview(preview);
      setSourcePreviewState('ready');
      onPreviewTitle(preview.title);
    } catch (error) {
      setSourcePreviewState('error');
      setSourcePreviewError(errorMessage(error));
    }
  }

  function toggleChapterSelection(url: string): void {
    setSelectedChapterUrls((prev) => {
      const next = new Set(prev);
      if (next.has(url)) next.delete(url);
      else next.add(url);
      return next;
    });
  }

  function toggleSelectVisibleChapters(): void {
    if (visibleSourceChapters.length === 0) return;
    setSelectedChapterUrls((current) => {
      const next = new Set(current);
      if (allVisibleChaptersSelected) {
        visibleSourceChapters.forEach((chapter) => next.delete(chapter.url));
      } else {
        visibleSourceChapters.forEach((chapter) => next.add(chapter.url));
      }
      return next;
    });
  }

  function selectChapterRange(): void {
    if (!sourcePreview) return;
    const first = Number.parseInt(rangeStart, 10);
    const last = Number.parseInt(rangeEnd, 10);
    if (!Number.isFinite(first) || !Number.isFinite(last)) return;
    const minimum = Math.min(first, last);
    const maximum = Math.max(first, last);
    setSelectedChapterUrls((current) => {
      const next = new Set(current);
      sourcePreview.chapters.forEach((chapter) => {
        if (chapter.chapter_number >= minimum && chapter.chapter_number <= maximum) {
          next.add(chapter.url);
        }
      });
      return next;
    });
  }

  async function handleFetchChapters(): Promise<void> {
    if (!sourcePreview || selectedChapterUrls.size === 0) return;
    setFetchState('loading');
    setFetchError('');
    setFetchResult(null);
    try {
      const chapters = sourcePreview.chapters
        .filter((c) => selectedChapterUrls.has(c.url))
        .map((c) => ({ url: c.url, chapter_number: c.chapter_number, title: c.title }));
      const request = {
        source_url: sourcePreview.source_url || sourceUrl,
        title: title || sourcePreview.title,
        author: sourcePreview.author,
        source: sourcePreview.source,
        chapters,
      };
      if (importJobClient) {
        await importJob.createJob(request);
        return;
      }
      if (!onFetchSourceChapters) return;
      const result = await onFetchSourceChapters(request);
      setFetchResult(result);
      setFetchState('ready');
    } catch (error) {
      setFetchState('error');
      setFetchError(errorMessage(error));
    }
  }

  async function handleCatalogSearch(): Promise<void> {
    if (!loadSourceCatalog) return;
    setCatalogState('loading');
    setCatalogError('');
    try {
      const result = await loadSourceCatalog({
        query: catalogQuery,
        supported: 'all',
        page: 1,
        page_size: 20,
      });
      setCatalog(result);
      setCatalogState('ready');
    } catch (error) {
      setCatalogState('error');
      setCatalogError(errorMessage(error));
    }
  }

  async function submitSourceUrl(): Promise<void> {
    if (!sourcePreview || !onStartImportUrlJob) return;
    try {
      const job = await onStartImportUrlJob({
        url: sourcePreview.source_url || sourceUrl,
        title: sourcePreview.title,
        author: sourcePreview.author,
        source: sourcePreview.source,
        chapters: sourcePreview.chapters,
        retry_limit: sourcePreview.policy?.retry_limit ?? 2,
        managed_source_id: sourcePreview.managed_source_id,
      });
      onJobCreated(job ?? null);
    } catch (error) {
      setSourcePreviewError(errorMessage(error));
    }
  }

  function updateSourceUrl(url: string): void {
    setSourceUrl(url);
    setSourcePreview(null);
    setSourcePreviewState('idle');
    setSourcePreviewError('');
  }

  function chooseCatalogSource(url: string): void {
    setSourceUrl(url);
    setSourcePreview(null);
    setSourcePreviewState('idle');
  }

  return {
    sourceUrl, sourcePreview, sourcePreviewState, sourcePreviewError,
    selectedChapterUrls, chapterPage, setChapterPage, rangeStart, setRangeStart, rangeEnd, setRangeEnd,
    fetchState, fetchResult, fetchError, catalogQuery, setCatalogQuery,
    catalogState, catalogError, catalog, importJob, sourceChapterPageCount,
    visibleSourceChapters, allVisibleChaptersSelected, durableImportActive,
    handlePreviewSourceUrl, toggleChapterSelection, toggleSelectVisibleChapters,
    selectChapterRange, handleFetchChapters, handleCatalogSearch, submitSourceUrl,
    updateSourceUrl, chooseCatalogSource,
  };
}
