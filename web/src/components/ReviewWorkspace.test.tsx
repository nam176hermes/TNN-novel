import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ReviewWorkspace from './ReviewWorkspace';

describe('ReviewWorkspace', () => {
  afterEach(() => {
    cleanup();
  });

  it('shows source, translation, QA issues, and repair actions', () => {
    render(
      <ReviewWorkspace
        issues={[{ type: 'glossary', message: 'Check term 灵石' }]}
        onPolish={vi.fn()}
        onRetranslate={vi.fn()}
        onSave={vi.fn()}
        sourceParagraph="他拿起灵石。"
        translatedParagraph="Hắn cầm linh thạch lên."
      />,
    );

    expect(screen.getByText('他拿起灵石。')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Hắn cầm linh thạch lên.')).toBeInTheDocument();
    expect(screen.getByText('Check term 灵石')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Polish paragraph' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retranslate paragraph' })).toBeInTheDocument();
  });

  it('saves edited translation text', async () => {
    const onSave = vi.fn();
    render(
      <ReviewWorkspace
        issues={[]}
        onPolish={vi.fn()}
        onRetranslate={vi.fn()}
        onSave={onSave}
        sourceParagraph="他点点头。"
        translatedParagraph="Hắn gật đầu."
      />,
    );

    await userEvent.clear(screen.getByLabelText('Vietnamese translation'));
    await userEvent.type(screen.getByLabelText('Vietnamese translation'), 'Hắn khẽ gật đầu.');
    await userEvent.click(screen.getByRole('button', { name: 'Save edited translation' }));

    expect(onSave).toHaveBeenCalledWith('Hắn khẽ gật đầu.');
  });

  it('syncs the editor when the selected paragraph changes', () => {
    const { rerender } = render(
      <ReviewWorkspace
        issues={[]}
        onPolish={vi.fn()}
        onRetranslate={vi.fn()}
        onSave={vi.fn()}
        sourceParagraph="他点点头。"
        translatedParagraph="Hắn gật đầu."
      />,
    );

    rerender(
      <ReviewWorkspace
        issues={[]}
        onPolish={vi.fn()}
        onRetranslate={vi.fn()}
        onSave={vi.fn()}
        sourceParagraph="他拿起灵石。"
        translatedParagraph="Hắn cầm linh thạch lên."
      />,
    );

    expect(screen.getByLabelText('Vietnamese translation')).toHaveValue('Hắn cầm linh thạch lên.');
  });
});
