import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { GlossaryTerm, StyleProfile } from '../api/types';
import { fixtureGlossaryTerm, fixtureStyleProfile } from '../test/fixtures';
import GlossaryStyleView from './GlossaryStyleView';

afterEach(cleanup);

const alternateProfile: StyleProfile = {
  ...fixtureStyleProfile,
  id: 'kiem_hiep',
  label: 'Kiếm hiệp',
  han_viet_level: 'medium',
  is_default: 0,
};

const approvedUnlockedTerm: GlossaryTerm = {
  ...fixtureGlossaryTerm,
  id: 8,
  source_term: '灵石',
  target_term: 'linh thạch',
  approved: 1,
  locked: 0,
  review_status: 'APPROVED',
  priority: 20,
  term_type: 'artifact',
};

describe('GlossaryStyleView', () => {
  it('renders style selection, glossary rows, and pending/locked counts from props', () => {
    render(
      <GlossaryStyleView
        glossaryTerms={[fixtureGlossaryTerm, approvedUnlockedTerm]}
        onApproveTerm={vi.fn()}
        onLockToggle={vi.fn()}
        onProfileChange={vi.fn()}
        onRejectTerm={vi.fn()}
        onSaveAndApproveTerm={vi.fn()}
        onUpdateTerm={vi.fn()}
        profiles={[fixtureStyleProfile, alternateProfile]}
        selectedProfileId={fixtureStyleProfile.id}
      />,
    );

    expect(screen.getByRole('heading', { name: 'Thuật ngữ & Văn phong' })).toBeInTheDocument();
    expect(screen.getByLabelText('Profile văn phong')).toHaveValue('tien_hiep');
    expect(screen.getByText('1 thuật ngữ chờ duyệt')).toBeVisible();
    expect(screen.getByText('1 thuật ngữ đã khóa')).toBeVisible();
    expect(screen.getByText('筑基')).toBeVisible();
    expect(screen.getByText('灵石')).toBeVisible();
    expect(screen.getByDisplayValue('Trúc Cơ')).toBeVisible();
    expect(screen.getAllByText('Chờ duyệt').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Đã khóa').length).toBeGreaterThan(0);
    expect(screen.getByText('Quy tắc biên tập')).toBeVisible();
    expect(screen.getByText('Văn phong cổ trang tu luyện.')).toBeVisible();
    expect(screen.getByText('Xử lý thơ/thành ngữ')).toBeVisible();
  });

  it('uses explicit review actions for pending glossary terms', async () => {
    const user = userEvent.setup();
    const onProfileChange = vi.fn();
    const onApproveTerm = vi.fn();
    const onRejectTerm = vi.fn();
    const onSaveAndApproveTerm = vi.fn();

    render(
      <GlossaryStyleView
        glossaryTerms={[fixtureGlossaryTerm]}
        onApproveTerm={onApproveTerm}
        onLockToggle={vi.fn()}
        onProfileChange={onProfileChange}
        onRejectTerm={onRejectTerm}
        onSaveAndApproveTerm={onSaveAndApproveTerm}
        onUpdateTerm={vi.fn()}
        profiles={[fixtureStyleProfile, alternateProfile]}
        selectedProfileId={fixtureStyleProfile.id}
      />,
    );

    await user.selectOptions(screen.getByLabelText('Profile văn phong'), alternateProfile.id);
    await user.clear(screen.getByLabelText('Bản dịch cho 筑基'));
    await user.type(screen.getByLabelText('Bản dịch cho 筑基'), 'Trúc Cơ kỳ');
    await user.click(screen.getByRole('button', { name: 'Duyệt 筑基' }));
    await user.click(screen.getByRole('button', { name: 'Từ chối 筑基' }));
    await user.click(screen.getByRole('button', { name: 'Lưu + Duyệt 筑基' }));
    await user.click(screen.getByRole('button', { name: 'Lưu + Duyệt + Khóa 筑基' }));

    expect(onProfileChange).toHaveBeenCalledWith('kiem_hiep');
    expect(onApproveTerm).toHaveBeenCalledWith(7);
    expect(onRejectTerm).toHaveBeenCalledWith(7);
    expect(onSaveAndApproveTerm).toHaveBeenNthCalledWith(1, 7, {
      target_term: 'Trúc Cơ kỳ',
      term_type: 'realm',
      genre: 'tien_hiep',
      priority: 40,
    }, false);
    expect(onSaveAndApproveTerm).toHaveBeenNthCalledWith(2, 7, {
      target_term: 'Trúc Cơ kỳ',
      term_type: 'realm',
      genre: 'tien_hiep',
      priority: 40,
    }, true);
  });

  it('filters glossary rows with the search box and focuses search from the filter icon', async () => {
    render(
      <GlossaryStyleView
        glossaryTerms={[fixtureGlossaryTerm, approvedUnlockedTerm]}
        onApproveTerm={vi.fn()}
        onLockToggle={vi.fn()}
        onProfileChange={vi.fn()}
        onRejectTerm={vi.fn()}
        onSaveAndApproveTerm={vi.fn()}
        onUpdateTerm={vi.fn()}
        profiles={[fixtureStyleProfile, alternateProfile]}
        selectedProfileId={fixtureStyleProfile.id}
      />,
    );

    const search = screen.getByPlaceholderText('Tìm thuật ngữ...');
    await userEvent.click(screen.getByRole('button', { name: 'Tập trung tìm thuật ngữ' }));
    expect(search).toHaveFocus();

    await userEvent.type(search, 'linh thạch');
    expect(screen.queryByText('筑基')).not.toBeInTheDocument();
    expect(screen.getByText('灵石')).toBeVisible();
    expect(screen.getByText('1 / 2')).toBeVisible();
  });

  it('filters by review status and shows first-seen context without executing notes', async () => {
    const rejectedTerm: GlossaryTerm = {
      ...approvedUnlockedTerm,
      id: 9,
      source_term: '青云宗',
      target_term: 'Thanh Vân Tông',
      approved: -1,
      locked: 0,
      review_status: 'REJECTED',
      source_context: '<script>alert(1)</script> 青云宗 xuất hiện lần đầu',
      first_seen_chapter_number: 3,
      term_type: 'sect',
    };

    render(
      <GlossaryStyleView
        glossaryTerms={[fixtureGlossaryTerm, approvedUnlockedTerm, rejectedTerm]}
        onApproveTerm={vi.fn()}
        onLockToggle={vi.fn()}
        onProfileChange={vi.fn()}
        onRejectTerm={vi.fn()}
        onSaveAndApproveTerm={vi.fn()}
        onUpdateTerm={vi.fn()}
        profiles={[fixtureStyleProfile, alternateProfile]}
        selectedProfileId={fixtureStyleProfile.id}
      />,
    );

    expect(screen.getByText('Ch. 3')).toBeVisible();
    expect(screen.getByText('<script>alert(1)</script> 青云宗 xuất hiện lần đầu')).toBeVisible();
    expect(document.querySelector('script')).toBeNull();

    await userEvent.selectOptions(screen.getByLabelText('Lọc trạng thái thuật ngữ'), 'REJECTED');

    expect(screen.queryByText('筑基')).not.toBeInTheDocument();
    expect(screen.queryByText('灵石')).not.toBeInTheDocument();
    expect(screen.getByText('青云宗')).toBeVisible();
    expect(screen.getAllByText('Từ chối').length).toBeGreaterThan(0);
  });

  it('uses the row icon as a real quick lock action', async () => {
    const onLockToggle = vi.fn();
    render(
      <GlossaryStyleView
        glossaryTerms={[approvedUnlockedTerm]}
        onApproveTerm={vi.fn()}
        onLockToggle={onLockToggle}
        onProfileChange={vi.fn()}
        onRejectTerm={vi.fn()}
        onSaveAndApproveTerm={vi.fn()}
        onUpdateTerm={vi.fn()}
        profiles={[fixtureStyleProfile, alternateProfile]}
        selectedProfileId={fixtureStyleProfile.id}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Khóa nhanh 灵石' }));

    expect(onLockToggle).toHaveBeenCalledWith(8, true);
  });

  it('shows honest empty states without demo glossary rows', () => {
    render(
      <GlossaryStyleView
        glossaryTerms={[]}
        onApproveTerm={vi.fn()}
        onLockToggle={vi.fn()}
        onProfileChange={vi.fn()}
        onRejectTerm={vi.fn()}
        onSaveAndApproveTerm={vi.fn()}
        onUpdateTerm={vi.fn()}
        profiles={[]}
        selectedProfileId=""
      />,
    );

    expect(screen.getByLabelText('Profile văn phong')).toBeDisabled();
    expect(screen.getByText('Chưa có profile văn phong')).toBeVisible();
    expect(screen.getByText('Chưa có thuật ngữ nào')).toBeVisible();
    expect(screen.queryByText('筑基')).not.toBeInTheDocument();
  });

  it('keeps production-scale glossary DOM bounded while search can reach every term', async () => {
    const largeGlossary = Array.from({ length: 600 }, (_, index): GlossaryTerm => ({
      ...approvedUnlockedTerm,
      id: 1000 + index,
      source_term: `术语-${index + 1}`,
      target_term: `Thuật ngữ ${index + 1}`,
    }));

    render(
      <GlossaryStyleView
        glossaryTerms={largeGlossary}
        onApproveTerm={vi.fn()}
        onLockToggle={vi.fn()}
        onProfileChange={vi.fn()}
        onRejectTerm={vi.fn()}
        onSaveAndApproveTerm={vi.fn()}
        onUpdateTerm={vi.fn()}
        profiles={[fixtureStyleProfile]}
        selectedProfileId={fixtureStyleProfile.id}
      />,
    );

    expect(screen.getAllByRole('row').length).toBeLessThan(50);
    expect(screen.getByText('600 / 600')).toBeVisible();

    await userEvent.type(screen.getByPlaceholderText('Tìm thuật ngữ...'), 'Thuật ngữ 600');

    expect(screen.getByText('术语-600')).toBeVisible();
    expect(screen.getByText('1 / 600')).toBeVisible();
  });

  it('measures dynamic glossary cards without materializing the complete list', async () => {
    const originalRect = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'getBoundingClientRect');
    Object.defineProperty(HTMLElement.prototype, 'getBoundingClientRect', {
      configurable: true,
      value() {
        const height = this.hasAttribute('data-virtual-index') ? 320 : 0;
        return { bottom: height, height, left: 0, right: 0, top: 0, width: 0, x: 0, y: 0, toJSON: () => ({}) };
      },
    });
    const largeGlossary = Array.from({ length: 600 }, (_, index): GlossaryTerm => ({
      ...approvedUnlockedTerm,
      id: 2000 + index,
      source_term: `动态-${index + 1}`,
      target_term: `Động ${index + 1}`,
    }));

    try {
      const { container } = render(
        <GlossaryStyleView
          glossaryTerms={largeGlossary}
          onApproveTerm={vi.fn()}
          onLockToggle={vi.fn()}
          onProfileChange={vi.fn()}
          onRejectTerm={vi.fn()}
          onSaveAndApproveTerm={vi.fn()}
          onUpdateTerm={vi.fn()}
          profiles={[fixtureStyleProfile]}
          selectedProfileId={fixtureStyleProfile.id}
        />,
      );

      await waitFor(() => {
        const spacerHeights = Array.from(container.querySelectorAll<HTMLElement>('.glossary-virtual-spacer td'))
          .map((element) => Number.parseFloat(element.style.height));
        expect(Math.max(...spacerHeights)).toBeGreaterThan(100_000);
      });
      expect(screen.getAllByRole('row').length).toBeLessThan(50);
    } finally {
      cleanup();
      if (originalRect) {
        Object.defineProperty(HTMLElement.prototype, 'getBoundingClientRect', originalRect);
      } else {
        Reflect.deleteProperty(HTMLElement.prototype, 'getBoundingClientRect');
      }
    }
  });
});
