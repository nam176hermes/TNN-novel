import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ChapterNavigator from './ChapterNavigator';

const book = {
  id: 42,
  title: 'Live Book',
  translated: 1,
  audio: 0,
  failed: 0,
  total: 1,
};

const chapter = {
  id: 4201,
  book_id: 42,
  chapter_number: 1,
  title: 'Live Chapter',
  status: 'translated',
  audio_path: null,
};

describe('ChapterNavigator', () => {
  afterEach(() => {
    cleanup();
  });

  it('renames a book from the library books list', async () => {
    const onRenameBook = vi.fn().mockResolvedValue(undefined);
    const onSelectBook = vi.fn();

    render(
      <ChapterNavigator
        activeBookId={42}
        books={[book]}
        chapters={[chapter]}
        onImport={() => undefined}
        onRenameBook={onRenameBook}
        onSelectBook={onSelectBook}
        onSelectChapter={() => undefined}
        selectedChapterId={4201}
      />,
    );

    const booksList = screen.getByLabelText('Books');

    await userEvent.click(within(booksList).getByRole('button', { name: 'Đổi tên sách Live Book' }));

    expect(onSelectBook).not.toHaveBeenCalled();

    const renameForm = screen.getByRole('form', { name: 'Đổi tên Live Book' });
    const input = within(renameForm).getByLabelText('Tên sách mới');

    expect(input).toHaveValue('Live Book');

    await userEvent.clear(input);
    await userEvent.type(input, 'Đạo Quỷ Dị Tiên');
    await userEvent.click(within(renameForm).getByRole('button', { name: 'Lưu' }));

    await waitFor(() => expect(onRenameBook).toHaveBeenCalledWith(42, 'Đạo Quỷ Dị Tiên'));
  });
});
