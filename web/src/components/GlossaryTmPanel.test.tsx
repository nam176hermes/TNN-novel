import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import GlossaryTmPanel from './GlossaryTmPanel';

const noTmMatch = null;

describe('GlossaryTmPanel', () => {
  it('shows pending glossary count and best TM match', () => {
    render(
      <GlossaryTmPanel
        bestMatch={{
          source_text: '他拿起灵石。',
          translation_text: 'Hắn cầm linh thạch lên.',
          match_score: 100,
        }}
        glossaryTerms={[]}
        onLockToggle={vi.fn()}
        onUpdateTerm={vi.fn()}
        pendingCount={2}
      />,
    );

    expect(screen.getByText('2 pending terms')).toBeInTheDocument();
    expect(screen.getByText('TM 100%')).toBeInTheDocument();
    expect(screen.getByText('Hắn cầm linh thạch lên.')).toBeInTheDocument();
  });

  it('shows empty state when no TM match is selected', () => {
    render(<GlossaryTmPanel bestMatch={noTmMatch} glossaryTerms={[]} onLockToggle={vi.fn()} onUpdateTerm={vi.fn()} pendingCount={0} />);

    expect(screen.getByText('0 pending terms')).toBeInTheDocument();
    expect(screen.getByText('No TM match selected')).toBeInTheDocument();
  });

  it('supports quick glossary edit and lock toggle', async () => {
    const onUpdateTerm = vi.fn();
    const onLockToggle = vi.fn();

    render(
      <GlossaryTmPanel
        bestMatch={noTmMatch}
        glossaryTerms={[
          {
            id: 7,
            book_id: 1,
            source_term: '筑基',
            target_term: 'Trúc Cơ',
            locked: 1,
            genre: 'tien_hiep',
            term_type: 'realm',
            priority: 40,
          },
        ]}
        onLockToggle={onLockToggle}
        onUpdateTerm={onUpdateTerm}
        pendingCount={1}
      />,
    );

    await userEvent.clear(screen.getByLabelText('Vietnamese term for 筑基'));
    await userEvent.type(screen.getByLabelText('Vietnamese term for 筑基'), 'Trúc Cơ kỳ');
    await userEvent.click(screen.getByRole('button', { name: 'Save 筑基' }));
    await userEvent.click(screen.getByRole('button', { name: 'Unlock 筑基' }));

    expect(onUpdateTerm).toHaveBeenCalledWith(7, {
      target_term: 'Trúc Cơ kỳ',
      term_type: 'realm',
      genre: 'tien_hiep',
      priority: 40,
    });
    expect(onLockToggle).toHaveBeenCalledWith(7, false);
  });
});
