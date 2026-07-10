import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ApiClient, ApiError } from '../api/client';
import type { QaReport } from '../api/types';
import { fixtureChapter, fixtureQaReport } from '../test/fixtures';
import { qaIssuesFromReport, useQa } from './useQa';

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });

  return { promise, resolve };
}

describe('qaIssuesFromReport', () => {
  it('normalizes issues from direct report issues without inventing missing issues', () => {
    expect(qaIssuesFromReport(null)).toEqual([]);
    expect(qaIssuesFromReport({ ...fixtureQaReport, issues: undefined, report_json: {} })).toEqual([]);
    expect(qaIssuesFromReport(fixtureQaReport)).toEqual([
      { type: 'term_inconsistency', message: 'Check 筑基 usage' },
    ]);
  });

  it('falls back to report_json issues and suggested fixes', () => {
    const report: QaReport = {
      ...fixtureQaReport,
      issues: undefined,
      report_json: { issues: [{ type: 'style', suggested_fix: 'Tighten phrasing' }] },
    };

    expect(qaIssuesFromReport(report)).toEqual([
      { type: 'style', message: 'Tighten phrasing', suggestedFix: 'Tighten phrasing' },
    ]);
  });

  it('keeps actionable QA fields for segment-level fixes', () => {
    const report: QaReport = {
      ...fixtureQaReport,
      issues: [
        {
          type: 'pronoun_modern',
          segment: 'tôi cảm ơn anh',
          reason: 'Xưng hô hiện đại trong thoại cổ trang',
          suggested_fix: 'ta cảm tạ huynh',
        },
      ],
    };

    expect(qaIssuesFromReport(report)).toEqual([
      {
        type: 'pronoun_modern',
        message: 'Xưng hô hiện đại trong thoại cổ trang',
        segment: 'tôi cảm ơn anh',
        reason: 'Xưng hô hiện đại trong thoại cổ trang',
        suggestedFix: 'ta cảm tạ huynh',
      },
    ]);
  });
});

describe('useQa', () => {
  it('loads QA report for the selected chapter and starts a QA job', async () => {
    const client = {
      getQaReport: vi.fn().mockResolvedValue(fixtureQaReport),
      startQaJob: vi.fn().mockResolvedValue({ job_id: 'qa-1', status: 'pending', message: 'QA started' }),
    } as unknown as ApiClient;

    const { result } = renderHook(() => useQa(client, true, fixtureChapter));

    await waitFor(() => expect(result.current.state).toBe('ready'));
    expect(result.current.report).toBe(fixtureQaReport);
    expect(result.current.issues).toEqual([{ type: 'term_inconsistency', message: 'Check 筑基 usage' }]);

    await expect(result.current.startQa()).resolves.toMatchObject({ job_id: 'qa-1' });
    expect(client.startQaJob).toHaveBeenCalledWith(42, [4201]);
  });

  it('uses non-fatal empty state when there is no selected chapter or no QA report', async () => {
    const client = {
      getQaReport: vi.fn().mockResolvedValue(null),
      startQaJob: vi.fn(),
    } as unknown as ApiClient;

    const { result, rerender } = renderHook(({ chapter }) => useQa(client, true, chapter), {
      initialProps: { chapter: null as typeof fixtureChapter | null },
    });

    expect(result.current.state).toBe('idle');
    expect(result.current.report).toBeNull();
    expect(result.current.issues).toEqual([]);

    rerender({ chapter: fixtureChapter });

    await waitFor(() => expect(result.current.state).toBe('empty'));
    expect(result.current.report).toBeNull();
    expect(result.current.issues).toEqual([]);

    rerender({ chapter: null });

    expect(result.current.state).toBe('idle');
    expect(result.current.report).toBeNull();
  });

  it('resets when disabled and ignores stale out-of-order QA report responses', async () => {
    const slowReport = deferred<QaReport | null>();
    const fastReport = deferred<QaReport | null>();
    const client = {
      getQaReport: vi.fn((bookId: number, chapterId: number) => {
        if (bookId === 42 && chapterId === 4201) return slowReport.promise;
        if (bookId === 42 && chapterId === 4202) return fastReport.promise;
        throw new Error(`Unexpected QA request ${bookId}/${chapterId}`);
      }),
      startQaJob: vi.fn(),
    } as unknown as ApiClient;

    const { result, rerender } = renderHook(
      ({ enabled, chapter }) => useQa(client, enabled, chapter),
      { initialProps: { enabled: true, chapter: fixtureChapter } },
    );

    rerender({
      enabled: true,
      chapter: { ...fixtureChapter, id: 4202, title: 'Fresh Chapter' },
    });

    fastReport.resolve({ ...fixtureQaReport, chapter_id: 4202, quality_score: 9.4 });

    await waitFor(() => expect(result.current.report?.chapter_id).toBe(4202));

    slowReport.resolve({ ...fixtureQaReport, chapter_id: 4201, quality_score: 1.1 });

    await waitFor(() => expect(result.current.report?.chapter_id).toBe(4202));
    expect(result.current.report?.quality_score).toBe(9.4);

    rerender({ enabled: false, chapter: { ...fixtureChapter, id: 4202 } });

    expect(result.current.state).toBe('idle');
    expect(result.current.report).toBeNull();
    expect(result.current.error).toBe('');
  });

  it('calls onAuthError when QA report load returns 401', async () => {
    const onAuthError = vi.fn();
    const client = {
      getQaReport: vi.fn().mockRejectedValue(new ApiError('Expired', 401)),
      startQaJob: vi.fn(),
    } as unknown as ApiClient;

    renderHook(() => useQa(client, true, fixtureChapter, onAuthError));

    await waitFor(() => expect(onAuthError).toHaveBeenCalledTimes(1));
  });

  it('returns null when starting QA without an enabled selected chapter', async () => {
    const client = {
      getQaReport: vi.fn(),
      startQaJob: vi.fn(),
    } as unknown as ApiClient;

    const { result } = renderHook(() => useQa(client, false, fixtureChapter));

    await act(async () => {
      await expect(result.current.startQa()).resolves.toBeNull();
    });
    expect(client.startQaJob).not.toHaveBeenCalled();
  });
});
