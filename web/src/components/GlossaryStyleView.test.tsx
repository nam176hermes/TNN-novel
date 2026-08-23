import { cleanup, render, screen } from '@testing-library/react';
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
