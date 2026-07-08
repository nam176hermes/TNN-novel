import { cleanup, render, screen } from '@testing-library/react';
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
    expect(screen.getByText('Chờ duyệt')).toBeVisible();
    expect(screen.getByText('Đã khóa')).toBeVisible();
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
});
