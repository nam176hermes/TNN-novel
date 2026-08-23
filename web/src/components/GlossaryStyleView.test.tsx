import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { StyleProfile } from '../api/types';
import { fixtureGlossaryTerm, fixtureStyleProfile } from '../test/fixtures';
import GlossaryStyleView from './GlossaryStyleView';

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
    fireEvent.change(screen.getByLabelText('Dữ liệu nhập JSON'), {
      target: { value: JSON.stringify([{ source_term: '新词', target_term: 'Từ mới' }]) },
    });
    await userEvent.click(screen.getByRole('button', { name: 'Xem trước nhập' }));
    expect(await screen.findByText('Thêm 1 · Cập nhật 0 · Bỏ qua 0')).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: 'Áp dụng nhập' }));
    expect(onApplyImport).toHaveBeenCalledWith(
      [{ source_term: '新词', target_term: 'Từ mới' }], 'i'.repeat(64),
    );
    await userEvent.click(screen.getByRole('button', { name: 'Xuất JSON' }));
    await userEvent.click(screen.getByRole('button', { name: 'Xuất CSV' }));
    expect(onExport).toHaveBeenNthCalledWith(1, 'json');
    expect(onExport).toHaveBeenNthCalledWith(2, 'csv');
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
