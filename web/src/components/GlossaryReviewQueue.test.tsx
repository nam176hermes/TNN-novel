import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type {
  GlossaryFacets,
  GlossaryQuery,
  GlossaryTerm,
  GlossaryTermDetail,
} from '../api/types';
import { fixtureGlossaryTerm, fixtureStyleProfile } from '../test/fixtures';
import GlossaryStyleView from './GlossaryStyleView';

afterEach(cleanup);

const query: GlossaryQuery = {
  page: 1,
  per_page: 50,
  q: '',
  review_status: 'NEEDS_REVIEW,CONFLICT',
  scope: 'book',
  sort: 'review',
};

const facets: GlossaryFacets = {
  locked: { '0': 1 },
  mode: { translate: 1 },
  review_status: { NEEDS_REVIEW: 1 },
  scope: { book: 1 },
  term_type: { realm: 1 },
};

function props(overrides: Record<string, unknown> = {}) {
  return {
    error: '',
    facets,
    glossaryTerms: [
      {
        ...fixtureGlossaryTerm,
        canonical_status: 'NEEDS_REVIEW',
        evidence_count: 2,
        inherited: false,
        version: 3,
      },
    ],
    loadState: 'ready' as const,
    onApproveTerm: vi.fn().mockResolvedValue(undefined),
    onCreateBookOverride: vi.fn().mockResolvedValue(undefined),
    onLoadTermDetail: vi.fn().mockResolvedValue({
      ...fixtureGlossaryTerm,
      canonical_status: 'NEEDS_REVIEW',
      evidence: [{
        id: 1,
        evidence: { excerpt: '第十章' },
        evidence_type: 'occurrence',
        extractor: 'test',
        created_at: '2026-08-23',
      }],
      evidence_count: 1,
      history: [{
        id: 1,
        action: 'add',
        actor: 'tester',
        after: { target_term: 'Trúc Cơ' },
        before: { target_term: '' },
        request_id: 'req-1',
        timestamp: '2026-08-23 12:00:00',
        version: 1,
      }],
      inherited: false,
      version: 3,
    } satisfies GlossaryTermDetail),
    onLockToggle: vi.fn().mockResolvedValue(undefined),
    onPageChange: vi.fn(),
    onProfileChange: vi.fn(),
    onQueryChange: vi.fn(),
    onRejectTerm: vi.fn().mockResolvedValue(undefined),
    onSaveAndApproveTerm: vi.fn().mockResolvedValue(undefined),
    onUpdateTerm: vi.fn().mockResolvedValue(undefined),
    page: 1,
    pages: 1,
    perPage: 50,
    profiles: [fixtureStyleProfile],
    query,
    selectedProfileId: fixtureStyleProfile.id,
    total: 1,
    ...overrides,
  };
}

describe('GlossaryStyleView review queue', () => {
  it('starts on the review queue and debounces server search for 250ms', async () => {
    vi.useFakeTimers();
    const onQueryChange = vi.fn();
    render(<GlossaryStyleView {...props({ onQueryChange })} />);

    expect(screen.getByRole('tab', { name: 'Cần duyệt' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText('1–1 / 1')).toBeVisible();

    fireEvent.change(screen.getByRole('searchbox', { name: 'Tìm thuật ngữ' }), { target: { value: 'linh thạch' } });
    expect(onQueryChange).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(249);
    expect(onQueryChange).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(onQueryChange).toHaveBeenCalledWith({ page: 1, q: 'linh thạch' });
    vi.useRealTimers();
  });

  it('renders at most 50 semantic rows and keeps focus stable after mutation and paging', async () => {
    const terms = Array.from({ length: 60 }, (_, index): GlossaryTerm => ({
      ...fixtureGlossaryTerm,
      id: index + 1,
      source_term: `术语-${index + 1}`,
      target_term: `Thuật ngữ ${index + 1}`,
      version: 1,
    }));
    const onApproveTerm = vi.fn().mockResolvedValue(undefined);
    const onPageChange = vi.fn();
    render(
      <GlossaryStyleView
        {...props({ glossaryTerms: terms, onApproveTerm, onPageChange, pages: 2, total: 60 })}
      />,
    );

    expect(screen.getAllByRole('row')).toHaveLength(51);
    await userEvent.click(screen.getByRole('button', { name: 'Duyệt 术语-1' }));
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Hàng chờ duyệt' })).toHaveFocus());

    await userEvent.click(screen.getByRole('button', { name: 'Trang sau' }));
    expect(onPageChange).toHaveBeenCalledWith(2);
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Hàng chờ duyệt' })).toHaveFocus());
  });

  it('shows scope, inheritance, evidence, version, override action, and detail drawer', async () => {
    const inherited = {
      ...fixtureGlossaryTerm,
      book_id: 0,
      canonical_status: 'APPROVED',
      evidence_count: 2,
      inherited: true,
      review_status: 'APPROVED',
      version: 7,
    } satisfies GlossaryTerm;
    const onCreateBookOverride = vi.fn().mockResolvedValue(undefined);
    render(
      <GlossaryStyleView
        {...props({
          glossaryTerms: [inherited],
          onCreateBookOverride,
          query: { ...query, review_status: 'APPROVED', scope: 'effective' },
        })}
      />,
    );

    expect(screen.getByText('Kế thừa')).toBeVisible();
    expect(screen.getByText('2 bằng chứng')).toBeVisible();
    expect(screen.getByText('v7')).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: 'Tạo bản ghi riêng cho 筑基' }));
    expect(onCreateBookOverride).toHaveBeenCalledWith(inherited);

    await userEvent.click(screen.getByRole('button', { name: 'Chi tiết 筑基' }));
    expect(await screen.findByRole('dialog', { name: 'Chi tiết 筑基' })).toBeVisible();
    expect(await screen.findByText(/occurrence/)).toBeVisible();
    expect(screen.getByText(/第十章/)).toBeVisible();
    expect(screen.getByText(/req-1/)).toBeVisible();
    expect(screen.getAllByText(/Trúc Cơ/).length).toBeGreaterThanOrEqual(2);
    await userEvent.click(screen.getByRole('button', { name: 'Đóng chi tiết' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('renders explicit loading, error, and empty states', () => {
    const { rerender } = render(<GlossaryStyleView {...props({ glossaryTerms: [], loadState: 'loading' })} />);
    expect(screen.getByText('Đang tải hàng chờ…')).toBeVisible();

    rerender(<GlossaryStyleView {...props({ error: 'network down', glossaryTerms: [], loadState: 'error' })} />);
    expect(screen.getByRole('alert')).toHaveTextContent('network down');

    rerender(<GlossaryStyleView {...props({ glossaryTerms: [], loadState: 'empty', total: 0 })} />);
    expect(screen.getByText('Không có thuật ngữ trong hàng chờ này.')).toBeVisible();
  });
});
