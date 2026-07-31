import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ApiError, type ApiClient } from '../api/client';
import type { Chapter, JobStartResponse, QaReport } from '../api/types';
import { formatError, type LoadState } from './types';

export type NormalizedQaIssue = {
  type: string;
  message: string;
  segment?: string;
  reason?: string;
  suggestedFix?: string;
};

function readIssueField(issue: Record<string, unknown>, keys: string[]): string | undefined {
  for (const key of keys) {
    const value = issue[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return undefined;
}

export function qaIssuesFromReport(report: QaReport | null): NormalizedQaIssue[] {
  if (!report) return [];

  const reportJson = typeof report.report_json === 'object' && report.report_json !== null ? report.report_json : {};
  const rawIssues = Array.isArray(report.issues)
    ? report.issues
    : Array.isArray(reportJson.issues)
      ? reportJson.issues
      : [];

  return rawIssues.map((issue) => {
    const issueRecord = typeof issue === 'object' && issue !== null ? issue as Record<string, unknown> : {};
    const type = 'type' in issueRecord ? String(issueRecord.type) : 'qa';
    const segment = readIssueField(issueRecord, [
      'segment',
      'translated_segment',
      'current_text',
      'offending_text',
      'text',
    ]);
    const messageField = readIssueField(issueRecord, ['message']);
    const reason = readIssueField(issueRecord, ['reason', 'detail']);
    const suggestedFix = readIssueField(issueRecord, [
      'suggested_fix',
      'suggestedFix',
      'replacement',
      'rewrite',
      'fix',
    ]);
    const message = messageField ?? reason ?? suggestedFix ?? JSON.stringify(issue);
    return {
      type,
      message,
      ...(segment ? { segment } : {}),
      ...(reason ? { reason } : {}),
      ...(suggestedFix ? { suggestedFix } : {}),
    };
  });
}

export function useQa(client: ApiClient, enabled: boolean, chapter: Chapter | null, onAuthError?: () => void) {
  const [report, setReport] = useState<QaReport | null>(null);
  const [state, setState] = useState<LoadState>('idle');
  const [error, setError] = useState('');
  const requestIdRef = useRef(0);
  const activeRequestRef = useRef<{
    controller: AbortController;
    key: string;
    promise: Promise<QaReport | null>;
  } | null>(null);
  const bookId = chapter?.book_id ?? null;
  const chapterId = chapter?.id ?? null;

  const reset = useCallback((nextState: LoadState = 'idle') => {
    requestIdRef.current += 1;
    activeRequestRef.current?.controller.abort();
    activeRequestRef.current = null;
    setReport(null);
    setState(nextState);
    setError('');
  }, []);

  const refresh = useCallback(async () => {
    if (!enabled || bookId === null || chapterId === null) {
      reset('idle');
      return null;
    }

    const requestKey = `${bookId}:${chapterId}`;
    if (activeRequestRef.current?.key === requestKey) return activeRequestRef.current.promise;
    activeRequestRef.current?.controller.abort();
    const controller = new AbortController();
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    setError('');
    setState('loading');

    const promise = (async () => {
      try {
        const nextReport = await client.getQaReport(bookId, chapterId, { signal: controller.signal });
        if (requestId !== requestIdRef.current) return nextReport;
        setReport(nextReport);
        setState(nextReport ? 'ready' : 'empty');
        return nextReport;
      } catch (nextError) {
        if (controller.signal.aborted || (nextError instanceof DOMException && nextError.name === 'AbortError')) return null;
        if (requestId !== requestIdRef.current) throw nextError;
        if (nextError instanceof ApiError && nextError.status === 401) {
          onAuthError?.();
        }
        setReport(null);
        setError(formatError(nextError));
        setState('error');
        throw nextError;
      }
    })();
    activeRequestRef.current = { controller, key: requestKey, promise };
    try {
      return await promise;
    } finally {
      if (activeRequestRef.current?.promise === promise) activeRequestRef.current = null;
    }
  }, [bookId, chapterId, client, enabled, onAuthError, reset]);

  const startQa = useCallback(async (): Promise<JobStartResponse | null> => {
    if (!enabled || bookId === null || chapterId === null) return null;
    setError('');

    try {
      return await client.startQaJob(bookId, [chapterId]);
    } catch (nextError) {
      if (nextError instanceof ApiError && nextError.status === 401) {
        onAuthError?.();
      }
      setError(formatError(nextError));
      throw nextError;
    }
  }, [bookId, chapterId, client, enabled, onAuthError]);

  useEffect(() => {
    if (!enabled || bookId === null || chapterId === null) {
      reset('idle');
      return undefined;
    }

    void refresh().catch(() => {});
    return () => {
      requestIdRef.current += 1;
      activeRequestRef.current?.controller.abort();
      activeRequestRef.current = null;
    };
  }, [bookId, chapterId, enabled, refresh, reset]);

  const issues = useMemo(() => qaIssuesFromReport(report), [report]);

  return { error, issues, refresh, report, startQa, state };
}
