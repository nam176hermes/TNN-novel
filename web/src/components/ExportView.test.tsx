import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { BookSummary, ExportResponse } from '../api/types';
import ExportView from './ExportView';

const books: BookSummary[] = [
  {
    id: 1,
    title: 'Phàm Nhân Tu Tiên',
    translated: 2,
    audio: 1,
    failed: 0,
    total: 3,
  },
  {
    id: 2,
    title: 'Chưa dịch',
    translated: 0,
    audio: 0,
    failed: 0,
    total: 1,
  },
];

describe('ExportView', () => {
  afterEach(() => {
    cleanup();
  });

  it('renders export controls for translated books', async () => {
    const onExport = vi.fn();
    const onBookChange = vi.fn();

    render(
      <ExportView
        activeBookId={1}
        books={books}
        lastExport={null}
        onBookChange={onBookChange}
        onExport={onExport}
      />,
    );

    expect(screen.getByRole('heading', { name: 'Xuất file' })).toBeInTheDocument();
    expect(screen.getByLabelText('Book')).toHaveValue('1');
    expect(screen.getByText('2')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /EPUB/ }));

    expect(onExport).toHaveBeenCalledWith('epub');
  });

  it('opens export guidance instead of leaving the help button inert', async () => {
    render(
      <ExportView
        activeBookId={1}
        books={books}
        lastExport={null}
        onBookChange={() => undefined}
        onExport={() => undefined}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Hướng dẫn' }));

    expect(screen.getByRole('region', { name: 'Hướng dẫn xuất file' })).toHaveTextContent('Chọn truyện đã có bản dịch');
  });

  it('disables format buttons when selected book has no translations', () => {
    render(
      <ExportView
        activeBookId={2}
        books={books}
        lastExport={null}
        onBookChange={() => undefined}
        onExport={() => undefined}
      />,
    );

    expect(screen.getByRole('button', { name: /TXT/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: /DOCX/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: /EPUB/ })).toBeDisabled();
  });

  it('starts batch audio for translated chapters missing audio', async () => {
    const onCreateAudioBatch = vi.fn();

    render(
      <ExportView
        activeBookId={1}
        books={books}
        lastExport={null}
        onBookChange={() => undefined}
        onCreateAudioBatch={onCreateAudioBatch}
        onExport={() => undefined}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Tạo audio hàng loạt' }));

    expect(onCreateAudioBatch).toHaveBeenCalledWith(1, 1);
    expect(screen.getByText('1 chương đã dịch chưa có audio')).toBeInTheDocument();
  });

  it('shows last exported file details', () => {
    const lastExport: ExportResponse = {
      book_id: 1,
      book_title: 'Phàm Nhân Tu Tiên',
      format: 'docx',
      filename: 'pham_nhan_tu_tien.docx',
      path: '/tmp/pham_nhan_tu_tien.docx',
      media_type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      size_bytes: 2048,
      chapter_count: 2,
    };

    render(
      <ExportView
        activeBookId={1}
        books={books}
        lastExport={lastExport}
        onBookChange={() => undefined}
        onExport={() => undefined}
      />,
    );

    expect(screen.getByText(/pham_nhan_tu_tien\.docx/)).toHaveTextContent('2 chapters');
    expect(screen.getByText(/pham_nhan_tu_tien\.docx/)).toHaveTextContent('2.0 KB');
  });
});
