import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ReviewEditor from './ReviewEditor';

describe('ReviewEditor', () => {
  afterEach(() => {
    cleanup();
  });

  it('renders the source as read-only article content', () => {
    render(
      <ReviewEditor
        onChange={vi.fn()}
        onSave={vi.fn()}
        savedTranslationText="Bản dịch đã lưu."
        sourceText="原文内容"
        translationText="Bản dịch đã lưu."
      />,
    );

    const source = screen.getByRole('article');
    expect(source).toHaveTextContent('原文内容');
    expect(screen.queryByDisplayValue('原文内容')).not.toBeInTheDocument();
  });

  it('edits the Vietnamese translation textarea', async () => {
    const onChange = vi.fn();
    function Harness() {
      const [text, setText] = useState('Bản dịch cũ.');

      return (
        <ReviewEditor
          onChange={(nextText) => {
            setText(nextText);
            onChange(nextText);
          }}
          onSave={vi.fn()}
          savedTranslationText="Bản dịch cũ."
          sourceText="原文内容"
          translationText={text}
        />
      );
    }

    render(<Harness />);

    await userEvent.clear(screen.getByLabelText('Vietnamese translation'));
    await userEvent.type(screen.getByLabelText('Vietnamese translation'), 'Bản dịch mới.');

    expect(onChange).toHaveBeenLastCalledWith('Bản dịch mới.');
  });

  it('disables save when the translation is not dirty', () => {
    render(
      <ReviewEditor
        onChange={vi.fn()}
        onSave={vi.fn()}
        savedTranslationText="Bản dịch đã lưu."
        sourceText="原文内容"
        translationText="Bản dịch đã lưu."
      />,
    );

    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
  });

  it('saves the edited translation text', async () => {
    const onSave = vi.fn();
    render(
      <ReviewEditor
        onChange={vi.fn()}
        onSave={onSave}
        savedTranslationText="Bản dịch đã lưu."
        sourceText="原文内容"
        translationText="Bản dịch đã sửa."
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Save' }));

    expect(onSave).toHaveBeenCalledWith('Bản dịch đã sửa.');
  });

  it('renders an optional copy action', async () => {
    const onCopyTranslation = vi.fn();
    render(
      <ReviewEditor
        onChange={vi.fn()}
        onCopyTranslation={onCopyTranslation}
        onSave={vi.fn()}
        savedTranslationText="Bản dịch."
        sourceText="原文内容"
        translationText="Bản dịch."
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Copy' }));

    expect(onCopyTranslation).toHaveBeenCalledOnce();
  });
});
