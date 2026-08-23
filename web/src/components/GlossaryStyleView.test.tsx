import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { StyleProfile } from '../api/types';
import { fixtureGlossaryTerm, fixtureStyleProfile } from '../test/fixtures';
import GlossaryStyleView, { parseGlossaryImportText } from './GlossaryStyleView';

afterEach(cleanup);

const alternateProfile: StyleProfile = {
  ...fixtureStyleProfile,
  id: 'kiem_hiep',
  is_default: 0,
  label: 'Kiếm hiệp',
};

function props(overrides: Record<string, unknown> = {}) {
  return {
    glossaryTerms: [fixtureGlossaryTerm],
    onApproveTerm: vi.fn(),
    onLockToggle: vi.fn(),
    onProfileChange: vi.fn(),
    onRejectTerm: vi.fn(),
    onSaveAndApproveTerm: vi.fn(),
    onUpdateTerm: vi.fn(),
    profiles: [fixtureStyleProfile, alternateProfile],
    selectedProfileId: fixtureStyleProfile.id,
    ...overrides,
  };
}

describe('GlossaryStyleView', () => {
  it('loads and saves per-book extraction settings and re-extracts the selected chapter', async () => {
    const onLoadExtractionSettings = vi.fn().mockResolvedValue({
      book_id: 42, max_candidates_per_chapter: 100, mode: 'deterministic', provider_id: '',
    });
    const onSaveExtractionSettings = vi.fn().mockResolvedValue({
      book_id: 42, max_candidates_per_chapter: 100, mode: 'hybrid', provider_id: 'ollama',
    });
    const onReextractChapter = vi.fn().mockResolvedValue({
      created: 1, updated: 0, skipped: 0, warnings: [],
    });
    render(<GlossaryStyleView {...props({
      bookId: 42,
      chapterId: 9,
      onLoadExtractionSettings,
      onReextractChapter,
      onSaveExtractionSettings,
      providers: [{
        api_key_env: '', api_key_set: false, base_url: 'http://localhost:11434/v1',
        cost_input_per_1m: 0, cost_output_per_1m: 0, enabled: 1, id: 'ollama', label: 'Ollama',
        model: 'qwen', notes: '', supports_batch: 0, supports_streaming: 1, temperature: 0.3,
        timeout_seconds: 180,
      }],
    })} />);

    await userEvent.click(screen.getByText('Trích xuất thuật ngữ'));
    expect(onLoadExtractionSettings).toHaveBeenCalledWith(42);
    expect(await screen.findByLabelText('Chế độ trích xuất')).toHaveValue('deterministic');
    await userEvent.selectOptions(screen.getByLabelText('Chế độ trích xuất'), 'hybrid');
    await userEvent.selectOptions(screen.getByLabelText('Provider trích xuất'), 'ollama');
    await userEvent.click(screen.getByRole('button', { name: 'Lưu cài đặt trích xuất' }));
    expect(onSaveExtractionSettings).toHaveBeenCalledWith(42, { mode: 'hybrid', provider_id: 'ollama' });

    await userEvent.click(screen.getByRole('button', { name: 'Trích xuất lại chương' }));
    expect(onReextractChapter).toHaveBeenCalledWith(42, 9);
    expect(await screen.findByRole('status')).toHaveTextContent('1 thuật ngữ mới');
  });

  it('reloads open extraction settings on book switch and ignores stale completions', async () => {
    let resolveBookA!: (settings: {
      book_id: number; max_candidates_per_chapter: number; mode: 'hybrid'; provider_id: string;
    }) => void;
    let resolveBookB!: typeof resolveBookA;
    const bookA = new Promise<Parameters<typeof resolveBookA>[0]>((resolve) => { resolveBookA = resolve; });
    const bookB = new Promise<Parameters<typeof resolveBookB>[0]>((resolve) => { resolveBookB = resolve; });
    const onLoadExtractionSettings = vi.fn((bookId: number) => bookId === 1 ? bookA : bookB);
    const onSaveExtractionSettings = vi.fn().mockResolvedValue({
      book_id: 2, max_candidates_per_chapter: 100, mode: 'hybrid', provider_id: 'provider-b',
    });
    const onReextractChapter = vi.fn().mockResolvedValue({
      created: 0, updated: 0, skipped: 0, warnings: [],
    });
    const shared = {
      onLoadExtractionSettings,
      onReextractChapter,
      onSaveExtractionSettings,
      providers: ['provider-a', 'provider-b'].map((id) => ({
        api_key_env: '', api_key_set: false, base_url: 'http://localhost',
        cost_input_per_1m: 0, cost_output_per_1m: 0, enabled: 1, id, label: id,
        model: 'fake', notes: '', supports_batch: 0, supports_streaming: 0, temperature: 0,
        timeout_seconds: 1,
      })),
    };
    const { rerender } = render(<GlossaryStyleView {...props({
      ...shared, bookId: 1, chapterId: 11,
    })} />);

    await userEvent.click(screen.getByText('Trích xuất thuật ngữ'));
    expect(onLoadExtractionSettings).toHaveBeenCalledWith(1);
    rerender(<GlossaryStyleView {...props({ ...shared, bookId: 2, chapterId: 22 })} />);

    await waitFor(() => expect(onLoadExtractionSettings).toHaveBeenCalledWith(2));
    expect(screen.getByRole('button', { name: 'Lưu cài đặt trích xuất' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Trích xuất lại chương' })).toBeDisabled();

    await act(async () => resolveBookB({
      book_id: 2, max_candidates_per_chapter: 100, mode: 'hybrid', provider_id: 'provider-b',
    }));
    expect(await screen.findByLabelText('Provider trích xuất')).toHaveValue('provider-b');
    await act(async () => resolveBookA({
      book_id: 1, max_candidates_per_chapter: 100, mode: 'hybrid', provider_id: 'provider-a',
    }));
    expect(screen.getByLabelText('Provider trích xuất')).toHaveValue('provider-b');

    await userEvent.click(screen.getByRole('button', { name: 'Lưu cài đặt trích xuất' }));
    await userEvent.click(screen.getByRole('button', { name: 'Trích xuất lại chương' }));
    expect(onSaveExtractionSettings).toHaveBeenCalledWith(2, {
      mode: 'hybrid', provider_id: 'provider-b',
    });
    expect(onReextractChapter).toHaveBeenCalledWith(2, 22);
  });

  it('preserves blank target cells and treats an endpoint empty-scope metadata row as zero items', () => {
    const header = [
      'schema_version', 'scope', 'scope_book_id', 'id', 'book_id', 'source_term',
      'target_term', 'category', 'confidence', 'approved', 'locked', 'review_status',
      'mode', 'pinyin', 'notes_vi', 'variants', 'occurrence_count', 'priority',
      'genre', 'term_type', 'alternatives', 'gender', 'first_seen_chapter_id',
      'first_seen_chapter_number', 'source_context', 'archived_at', 'version', 'archived',
    ];
    const emptyMetadataRow = ['1', 'book', '42', ...Array(header.length - 3).fill('')];
    const blankTargetRow = [
      '1', 'book', '42', '7', '42', '待译', '', 'term', '1', '0', '0',
      'NEEDS_REVIEW', 'translate', '', '', '', '', '0', '', 'term', '', '',
      '0', '0', '', '', '1', 'false',
    ];

    expect(parseGlossaryImportText([header.join(','), blankTargetRow.join(',')].join('\n')))
      .toEqual([expect.objectContaining({
        approved: 0,
        book_id: 42,
        review_status: 'NEEDS_REVIEW',
        source_term: '待译',
        target_term: '',
      })]);
    expect(parseGlossaryImportText([header.join(','), emptyMetadataRow.join(',')].join('\n')))
      .toEqual([]);
  });

  it('selects versioned rows for bulk review and exposes create archive and restore actions', async () => {
    const onArchiveTerm = vi.fn().mockResolvedValue(undefined);
    const onBulkAction = vi.fn().mockResolvedValue(undefined);
    const onCreateTerm = vi.fn().mockResolvedValue(undefined);
    const onRestoreTerm = vi.fn().mockResolvedValue(undefined);
    const archived = {
      ...fixtureGlossaryTerm,
      archived: true,
      archived_at: '2026-08-23T00:00:00Z',
      id: 8,
      source_term: '归档',
      target_term: 'Lưu trữ',
      version: 5,
    };
    render(<GlossaryStyleView {...props({
      glossaryTerms: [{ ...fixtureGlossaryTerm, version: 3 }, archived],
      onArchiveTerm,
      onBulkAction,
      onCreateTerm,
      onRestoreTerm,
      query: {
        book_id: 42, page: 1, per_page: 50, q: '', review_status: '', scope: 'book', sort: 'review',
      },
      total: 2,
    })} />);

    await userEvent.click(screen.getByRole('checkbox', { name: 'Chọn 筑基' }));
    await userEvent.click(screen.getByRole('button', { name: 'Duyệt đã chọn' }));
    expect(onBulkAction).toHaveBeenCalledWith('approve', [{ id: 7, expected_version: 3 }]);

    await userEvent.click(screen.getByRole('button', { name: 'Lưu trữ 筑基' }));
    await userEvent.click(screen.getByRole('button', { name: 'Khôi phục 归档' }));
    expect(onArchiveTerm).toHaveBeenCalledWith(7);
    expect(onRestoreTerm).toHaveBeenCalledWith(8);

    await userEvent.click(screen.getByText('Tạo thuật ngữ'));
    await userEvent.type(screen.getByLabelText('Thuật ngữ gốc mới'), '新词');
    await userEvent.type(screen.getByLabelText('Bản dịch mới'), 'Từ mới');
    await userEvent.click(screen.getByRole('button', { name: 'Tạo thuật ngữ mới' }));
    expect(onCreateTerm).toHaveBeenCalledWith(expect.objectContaining({
      approved: 0, book_id: 42, review_status: 'NEEDS_REVIEW', source_term: '新词', target_term: 'Từ mới',
    }));
  });

  it('requires merge preview and drives import preview apply and exports', async () => {
    const memberA = { ...fixtureGlossaryTerm, id: 7, source_term: 'Ａ B', target_term: 'Một', version: 3 };
    const memberB = { ...fixtureGlossaryTerm, id: 8, source_term: 'a b', target_term: 'Hai', version: 4 };
    const memberC = { ...fixtureGlossaryTerm, id: 9, source_term: '另一', target_term: 'Ba', version: 2 };
    const memberD = { ...fixtureGlossaryTerm, id: 10, source_term: '另一', target_term: 'Bốn', version: 1 };
    const onLoadConflicts = vi.fn().mockResolvedValue({
      items: [
        { id: 'group', members: [memberA, memberB], types: ['normalized_duplicate'] },
        { id: 'other-group', members: [memberC, memberD], types: ['global_book_overlap'] },
      ],
      page: 1, pages: 2, per_page: 50, total: 52,
    });
    const onPreviewMerge = vi.fn().mockResolvedValue({
      canonical_id: 7, duplicate_ids: [8], digest: 'd'.repeat(64), evidence_count: 2,
    });
    const onApplyMerge = vi.fn().mockResolvedValue(undefined);
    const onPreviewImport = vi.fn().mockResolvedValue({
      actions: [{ item: 1, action: 'add' }], affected: [], conflict_policy: 'skip_conflicts',
      digest: 'i'.repeat(64), schema_version: 1, summary: { added: 1, updated: 0, skipped: 0 },
    });
    const onApplyImport = vi.fn().mockResolvedValue(undefined);
    const onExport = vi.fn().mockResolvedValue(undefined);
    render(<GlossaryStyleView {...props({
      onApplyImport, onApplyMerge, onExport, onLoadConflicts, onPreviewImport, onPreviewMerge,
    })} />);

    await userEvent.click(screen.getByText('Xung đột & hợp nhất'));
    await userEvent.click(screen.getByRole('button', { name: 'Tải xung đột' }));
    expect(await screen.findByText(/Ａ B → Một/)).toBeVisible();
    expect(screen.getByText(/另一 → Ba/)).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: 'Trang xung đột sau' }));
    expect(onLoadConflicts).toHaveBeenLastCalledWith(2);
    await userEvent.click(screen.getByRole('radio', { name: 'Chọn canonical Ａ B' }));
    await userEvent.click(screen.getByRole('button', { name: 'Xem trước hợp nhất' }));
    expect(onPreviewMerge).toHaveBeenCalledWith(7, [8]);
    await userEvent.click(await screen.findByRole('button', { name: 'Áp dụng hợp nhất' }));
    expect(onApplyMerge).toHaveBeenCalledWith(7, [8], 'd'.repeat(64));

    await userEvent.click(screen.getByText('Nhập & xuất'));
    fireEvent.change(screen.getByLabelText('Dữ liệu nhập JSON hoặc CSV'), {
      target: { value: JSON.stringify([{ source_term: '新词', target_term: 'Từ mới' }]) },
    });
    await userEvent.click(screen.getByRole('button', { name: 'Xem trước nhập' }));
    expect(await screen.findByText('Thêm 1 · Cập nhật 0 · Bỏ qua 0')).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: 'Áp dụng nhập' }));
    expect(onApplyImport).toHaveBeenCalledWith(
      [{ source_term: '新词', target_term: 'Từ mới' }], 'i'.repeat(64), 'skip_conflicts',
    );
    await userEvent.click(screen.getByRole('button', { name: 'Xuất JSON' }));
    await userEvent.click(screen.getByRole('button', { name: 'Xuất CSV' }));
    expect(onExport).toHaveBeenNthCalledWith(1, 'json');
    expect(onExport).toHaveBeenNthCalledWith(2, 'csv');
  });

  it('labels a partial conflict batch and reloads the remainder for repeated merge resolution', async () => {
    const memberA = { ...fixtureGlossaryTerm, id: 7, source_term: 'Ａ B', target_term: 'Một', version: 3 };
    const memberB = { ...fixtureGlossaryTerm, id: 8, source_term: 'a b', target_term: 'Hai', version: 4 };
    const memberC = { ...fixtureGlossaryTerm, id: 9, source_term: 'a b', target_term: 'Ba', version: 2 };
    const onLoadConflicts = vi.fn()
      .mockResolvedValueOnce({
        items: [{
          canonical_id: 7, id: 'stable-group', member_total: 250,
          members: [memberA, memberB], members_truncated: true, types: ['normalized_duplicate'],
        }],
        page: 1, pages: 1, per_page: 50, total: 1,
      })
      .mockResolvedValueOnce({
        items: [{
          canonical_id: 7, id: 'stable-group', member_total: 2,
          members: [memberA, memberC], members_truncated: false, types: ['normalized_duplicate'],
        }],
        page: 1, pages: 1, per_page: 50, total: 1,
      })
      .mockResolvedValueOnce({ items: [], page: 1, pages: 0, per_page: 50, total: 0 });
    const onPreviewMerge = vi.fn()
      .mockResolvedValueOnce({ canonical_id: 7, duplicate_ids: [8], digest: 'a'.repeat(64) })
      .mockResolvedValueOnce({ canonical_id: 7, duplicate_ids: [9], digest: 'b'.repeat(64) });
    const onApplyMerge = vi.fn().mockResolvedValue(undefined);
    render(<GlossaryStyleView {...props({ onApplyMerge, onLoadConflicts, onPreviewMerge })} />);

    await userEvent.click(screen.getByText('Xung đột & hợp nhất'));
    await userEvent.click(screen.getByRole('button', { name: 'Tải xung đột' }));
    expect(await screen.findByText(/lô 2\/250 thành viên/)).toHaveTextContent('lặp lại');
    await userEvent.click(screen.getByRole('radio', { name: 'Chọn canonical Ａ B' }));
    await userEvent.click(screen.getByRole('button', { name: 'Xem trước hợp nhất' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Áp dụng hợp nhất' }));

    expect(await screen.findByText(/a b → Ba/)).toBeVisible();
    await userEvent.click(screen.getByRole('radio', { name: 'Chọn canonical Ａ B' }));
    await userEvent.click(screen.getByRole('button', { name: 'Xem trước hợp nhất' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Áp dụng hợp nhất' }));

    expect(await screen.findByText('Không có xung đột.')).toBeVisible();
    expect(onPreviewMerge).toHaveBeenNthCalledWith(1, 7, [8]);
    expect(onPreviewMerge).toHaveBeenNthCalledWith(2, 7, [9]);
    expect(onApplyMerge).toHaveBeenCalledTimes(2);
    expect(onLoadConflicts).toHaveBeenCalledTimes(3);
  });

  it('accepts exported JSON envelopes and CSV with an explicit conflict policy', async () => {
    const onPreviewImport = vi.fn().mockResolvedValue({
      actions: [{ item: 1, action: 'add' }], affected: [], conflict_policy: 'reject_conflicts',
      digest: 'p'.repeat(64), schema_version: 1, summary: { added: 1, updated: 0, skipped: 0 },
    });
    const onApplyImport = vi.fn().mockResolvedValue(undefined);
    render(<GlossaryStyleView {...props({
      onApplyImport,
      onExport: vi.fn(),
      onPreviewImport,
    })} />);

    await userEvent.click(screen.getByText('Nhập & xuất'));
    await userEvent.selectOptions(screen.getByLabelText('Chính sách xung đột'), 'reject_conflicts');
    const input = screen.getByLabelText('Dữ liệu nhập JSON hoặc CSV');
    fireEvent.change(input, {
      target: {
        value: JSON.stringify({
          schema_version: 1,
          scope: { type: 'book', book_id: 42 },
          terms: [{ source_term: '包络', target_term: 'Phong bì', book_id: 42 }],
          total: 1,
        }),
      },
    });
    await userEvent.click(screen.getByRole('button', { name: 'Xem trước nhập' }));
    expect(onPreviewImport).toHaveBeenLastCalledWith(
      [{ source_term: '包络', target_term: 'Phong bì', book_id: 42 }],
      'reject_conflicts',
    );

    fireEvent.change(input, {
      target: {
        value: [
          'schema_version,scope,scope_book_id,source_term,target_term,book_id,approved,locked,review_status,archived',
          '1,book,42,逗号,"Dấu, phẩy",42,0,0,NEEDS_REVIEW,false',
        ].join('\n'),
      },
    });
    await userEvent.click(screen.getByRole('button', { name: 'Xem trước nhập' }));
    expect(onPreviewImport).toHaveBeenLastCalledWith(
      [expect.objectContaining({
        approved: 0,
        archived: false,
        book_id: 42,
        locked: 0,
        review_status: 'NEEDS_REVIEW',
        source_term: '逗号',
        target_term: 'Dấu, phẩy',
      })],
      'reject_conflicts',
    );
    await userEvent.click(screen.getByRole('button', { name: 'Áp dụng nhập' }));
    expect(onApplyImport).toHaveBeenCalledWith(
      expect.any(Array), 'p'.repeat(64), 'reject_conflicts',
    );

    fireEvent.change(input, {
      target: {
        value: JSON.stringify([{
          source_term: '错误', target_term: 'Sai', approved: -1, locked: 1,
        }]),
      },
    });
    await userEvent.click(screen.getByRole('button', { name: 'Xem trước nhập' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('trạng thái canonical');
    expect(onPreviewImport).toHaveBeenCalledTimes(2);

    fireEvent.change(input, {
      target: {
        value: JSON.stringify({
          schema_version: 1,
          scope: { type: 'book', book_id: 42 },
          terms: [{ source_term: 'scope', target_term: 'Phạm vi', book_id: 43 }],
        }),
      },
    });
    await userEvent.click(screen.getByRole('button', { name: 'Xem trước nhập' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('không khớp');
    expect(onPreviewImport).toHaveBeenCalledTimes(2);

    fireEvent.change(input, {
      target: {
        value: [
          'schema_version,scope,scope_book_id,source_term,target_term,book_id',
          '1,global,0,scope,Phạm vi,42',
        ].join('\n'),
      },
    });
    await userEvent.click(screen.getByRole('button', { name: 'Xem trước nhập' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('không khớp');
    expect(onPreviewImport).toHaveBeenCalledTimes(2);
  });

  it('keeps bulk selection create inputs and previews when mutations reject', async () => {
    const rejected = new Error('typed mutation failed');
    const memberA = { ...fixtureGlossaryTerm, id: 7, source_term: 'Ａ B', version: 3 };
    const memberB = { ...fixtureGlossaryTerm, id: 8, source_term: 'a b', version: 4 };
    render(<GlossaryStyleView {...props({
      onApplyImport: vi.fn().mockRejectedValue(rejected),
      onApplyMerge: vi.fn().mockRejectedValue(rejected),
      onBulkAction: vi.fn().mockRejectedValue(rejected),
      onCreateTerm: vi.fn().mockRejectedValue(rejected),
      onExport: vi.fn(),
      onLoadConflicts: vi.fn().mockResolvedValue({
        items: [{ id: 'group', members: [memberA, memberB], types: ['normalized_duplicate'] }],
        page: 1, pages: 1, per_page: 50, total: 1,
      }),
      onPreviewImport: vi.fn().mockResolvedValue({
        actions: [{ item: 1, action: 'add' }], affected: [], conflict_policy: 'skip_conflicts',
        digest: 'i'.repeat(64), schema_version: 1, summary: { added: 1, updated: 0, skipped: 0 },
      }),
      onPreviewMerge: vi.fn().mockResolvedValue({
        canonical_id: 7, duplicate_ids: [8], digest: 'm'.repeat(64), evidence_count: 1,
      }),
      query: {
        book_id: 42, page: 1, per_page: 50, q: '', review_status: '', scope: 'book', sort: 'review',
      },
    })} />);

    const selected = screen.getByRole('checkbox', { name: 'Chọn 筑基' });
    await userEvent.click(selected);
    await userEvent.click(screen.getByRole('button', { name: 'Duyệt đã chọn' }));
    expect(selected).toBeChecked();
    expect(await screen.findByRole('alert')).toHaveTextContent('typed mutation failed');

    await userEvent.click(screen.getByText('Tạo thuật ngữ'));
    await userEvent.type(screen.getByLabelText('Thuật ngữ gốc mới'), '保留');
    await userEvent.type(screen.getByLabelText('Bản dịch mới'), 'Giữ lại');
    await userEvent.click(screen.getByRole('button', { name: 'Tạo thuật ngữ mới' }));
    expect(screen.getByLabelText('Thuật ngữ gốc mới')).toHaveValue('保留');
    expect(screen.getByLabelText('Bản dịch mới')).toHaveValue('Giữ lại');

    await userEvent.click(screen.getByText('Xung đột & hợp nhất'));
    await userEvent.click(screen.getByRole('button', { name: 'Tải xung đột' }));
    await userEvent.click(await screen.findByRole('radio', { name: 'Chọn canonical Ａ B' }));
    await userEvent.click(screen.getByRole('button', { name: 'Xem trước hợp nhất' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Áp dụng hợp nhất' }));
    expect(screen.getByRole('button', { name: 'Áp dụng hợp nhất' })).toBeVisible();

    await userEvent.click(screen.getByText('Nhập & xuất'));
    fireEvent.change(screen.getByLabelText('Dữ liệu nhập JSON hoặc CSV'), {
      target: { value: JSON.stringify([{ source_term: '保留', target_term: 'Giữ lại' }]) },
    });
    await userEvent.click(screen.getByRole('button', { name: 'Xem trước nhập' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Áp dụng nhập' }));
    expect(screen.getByRole('button', { name: 'Áp dụng nhập' })).toBeVisible();
  });

  it('keeps style profiles in a secondary disclosure and changes the selected profile', async () => {
    const onProfileChange = vi.fn();
    render(<GlossaryStyleView {...props({ onProfileChange })} />);

    await userEvent.click(screen.getByText('Profile văn phong (phụ)'));
    expect(screen.getByText('Quy tắc biên tập')).toBeVisible();
    expect(screen.getByText('Văn phong cổ trang tu luyện.')).toBeVisible();
    await userEvent.selectOptions(screen.getByLabelText('Profile văn phong'), alternateProfile.id);
    expect(onProfileChange).toHaveBeenCalledWith('kiem_hiep');
  });

  it('edits a pending row through explicit approve, reject, and save-review actions', async () => {
    const onApproveTerm = vi.fn();
    const onRejectTerm = vi.fn();
    const onSaveAndApproveTerm = vi.fn();
    render(<GlossaryStyleView {...props({ onApproveTerm, onRejectTerm, onSaveAndApproveTerm })} />);

    await userEvent.clear(screen.getByLabelText('Bản dịch cho 筑基'));
    await userEvent.type(screen.getByLabelText('Bản dịch cho 筑基'), 'Trúc Cơ kỳ');
    await userEvent.click(screen.getByRole('button', { name: 'Duyệt 筑基' }));
    await userEvent.click(screen.getByRole('button', { name: 'Từ chối 筑基' }));
    await userEvent.click(screen.getByRole('button', { name: 'Lưu + Duyệt 筑基' }));

    expect(onApproveTerm).toHaveBeenCalledWith(7);
    expect(onRejectTerm).toHaveBeenCalledWith(7);
    expect(onSaveAndApproveTerm).toHaveBeenCalledWith(7, {
      priority: 40,
      target_term: 'Trúc Cơ kỳ',
      term_type: 'realm',
    }, false);
  });
});
