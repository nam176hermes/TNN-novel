import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../api/client';
import type { EbookBookMatchReason, EbookPreview } from '../api/types';
import ImportPanel from './ImportPanel';

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });

  return { promise, resolve };
}

function existingBookPreview({
  bookMatchReason = 'title',
  duplicateChapters = 2,
  existingBookId = 7,
  existingBookTitle = 'Trường Thiên Lục',
  newChapters = 43,
  duplicateStrategy = 'skip',
}: {
  bookMatchReason?: EbookBookMatchReason;
  duplicateChapters?: number;
  existingBookId?: number | null;
  existingBookTitle?: string;
  newChapters?: number;
  duplicateStrategy?: 'skip' | 'error' | 'overwrite';
} = {}): EbookPreview {
  const chapterCount = newChapters + duplicateChapters;
  return {
    title: existingBookTitle,
    author: 'Tác giả',
    language: 'vi',
    source_format: 'epub',
    cover_present: false,
    upload_id: `preview-upload-${existingBookId}`,
    chapter_count: chapterCount,
    chapters: [{ chapter_number: 1, title: 'Chương mở đầu', sample: 'Nội dung chương.' }],
    dry_run: {
      target_book_id: existingBookId,
      target_title: existingBookTitle,
      duplicate_strategy: duplicateStrategy,
      chapter_count: chapterCount,
      new_chapters: newChapters,
      duplicate_chapters: duplicateChapters,
      would_import: newChapters + (duplicateStrategy === 'overwrite' ? duplicateChapters : 0),
      would_skip: duplicateStrategy === 'skip' ? duplicateChapters : 0,
      would_overwrite: duplicateStrategy === 'overwrite' ? duplicateChapters : 0,
      would_error: duplicateStrategy === 'error' ? duplicateChapters : 0,
      existing_book_id: existingBookId,
      existing_book_title: existingBookTitle,
      existing_chapter_count: 120,
      book_match_reason: bookMatchReason,
      requires_existing_book_confirmation: true,
    },
  };
}

describe('ImportPanel', () => {
  afterEach(() => {
    cleanup();
  });

  it('disables submit when title or text is empty', async () => {
    render(<ImportPanel onCancel={() => undefined} onImportPaste={() => undefined} />);

    const submit = screen.getByRole('button', { name: 'Import chapter' });

    expect(submit).toBeDisabled();
    expect(screen.getByText('Paste source text to continue.')).toBeInTheDocument();
    expect(screen.queryByText('Trạng thái xử lý')).not.toBeInTheDocument();
    expect(screen.queryByText('Waiting for text')).not.toBeInTheDocument();
    expect(screen.queryByText('Đang chờ bạn dán nội dung...')).not.toBeInTheDocument();

    await userEvent.type(screen.getByLabelText('Book title'), 'Phàm Nhân Tu Tiên');
    expect(submit).toBeDisabled();
    expect(screen.getByText('Paste source text to continue.')).toBeInTheDocument();
    expect(screen.queryByText('Trạng thái xử lý')).not.toBeInTheDocument();

    await userEvent.clear(screen.getByLabelText('Book title'));
    await userEvent.type(screen.getByLabelText('Source text'), '二愣子 đứng bên triền núi.');
    expect(submit).toBeDisabled();
    expect(screen.getByText('Book title is required before import.')).toBeInTheDocument();
    expect(screen.getByText('Book title is missing')).toBeInTheDocument();
  });

  it('opens import guidance instead of leaving the help button inert', async () => {
    render(<ImportPanel onCancel={() => undefined} onImportPaste={() => undefined} />);

    await userEvent.click(screen.getByRole('button', { name: 'Hướng dẫn' }));

    expect(screen.getByRole('region', { name: 'Hướng dẫn nhập chương' })).toHaveTextContent('Wizard sẽ đi qua 4 bước');
  });

  it('shows paste text status and ready state when required metadata is present', async () => {
    render(<ImportPanel onCancel={() => undefined} onImportPaste={() => undefined} />);

    await userEvent.type(screen.getByLabelText('Book title'), 'Phàm Nhân Tu Tiên');
    fireEvent.change(screen.getByLabelText('Source text'), {
      target: { value: '第一章 山边小村\n张铁睁开双眼。' },
    });

    expect(screen.getByRole('heading', { name: 'Ready to import' })).toBeInTheDocument();
    expect(screen.getByText(/2 lines/i)).toBeInTheDocument();
    expect(screen.getByText(/Chinese chars/i)).toBeInTheDocument();
    expect(screen.getByText('Ready to import.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Import chapter' })).toBeEnabled();
  });

  it('only shows file processing status after a source file is selected', async () => {
    const file = new File(['山门前人声鼎沸。'], 'chapter-3.txt', { type: 'text/plain' });

    render(
      <ImportPanel
        onCancel={() => undefined}
        onImportFile={() => undefined}
        onImportPaste={() => undefined}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'File' }));

    expect(screen.getByText('Book title is required before import.')).toBeInTheDocument();
    expect(screen.queryByText('Trạng thái xử lý')).not.toBeInTheDocument();
    expect(screen.queryByText('Chưa có file được chọn')).not.toBeInTheDocument();

    await userEvent.type(screen.getByLabelText('Book title'), 'Phàm Nhân Tu Tiên');
    expect(screen.getByText('Select a source file to continue.')).toBeInTheDocument();
    expect(screen.queryByText('Trạng thái xử lý')).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Source file'), { target: { files: [file] } });

    expect(screen.getByText('Trạng thái xử lý')).toBeInTheDocument();
    expect(within(screen.getByLabelText('Import preview')).getByText('chapter-3.txt')).toBeInTheDocument();
  });

  it('calls onImportPaste with pasted chapter fields', async () => {
    const onImportPaste = vi.fn();

    render(<ImportPanel onCancel={() => undefined} onImportPaste={onImportPaste} />);

    await userEvent.type(screen.getByLabelText('Book title'), 'Phàm Nhân Tu Tiên');
    await userEvent.clear(screen.getByLabelText('Chapter number'));
    await userEvent.type(screen.getByLabelText('Chapter number'), '12');
    await userEvent.type(screen.getByLabelText('Chapter title'), 'Trấn Thanh Ngưu');
    await userEvent.type(screen.getByLabelText('Source text'), '少年跟着大叔入镇。');
    await userEvent.click(screen.getByRole('button', { name: 'Import chapter' }));

    expect(onImportPaste).toHaveBeenCalledWith({
      title: 'Phàm Nhân Tu Tiên',
      chapter_number: 12,
      chapter_title: 'Trấn Thanh Ngưu',
      text: '少年跟着大叔入镇。',
    });
  });

  it('auto-fills metadata from pasted Chinese source headers', async () => {
    const onImportPaste = vi.fn();

    render(<ImportPanel onCancel={() => undefined} onImportPaste={onImportPaste} />);

    const sourceText = '《Yong Ye [raw]》\n第十二章 雪夜来客\n秦铭推开门。';
    fireEvent.change(screen.getByLabelText('Source text'), { target: { value: sourceText } });

    expect(screen.getByLabelText('Book title')).toHaveValue('Yong Ye');
    expect(screen.getByLabelText('Chapter number')).toHaveValue(12);
    expect(screen.getByLabelText('Chapter title')).toHaveValue('雪夜来客');

    await userEvent.click(screen.getByRole('button', { name: 'Import chapter' }));

    expect(onImportPaste).toHaveBeenCalledWith({
      title: 'Yong Ye',
      chapter_number: 12,
      chapter_title: '雪夜来客',
      text: sourceText,
    });
  });

  it('calls onImportFile with selected source file fields', async () => {
    const onImportFile = vi.fn();
    const file = new File(['山门前人声鼎沸。'], 'chapter-3.txt', { type: 'text/plain' });

    render(
      <ImportPanel
        onCancel={() => undefined}
        onImportFile={onImportFile}
        onImportPaste={() => undefined}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'File' }));
    await userEvent.type(screen.getByLabelText('Book title'), 'Phàm Nhân Tu Tiên');
    await userEvent.clear(screen.getByLabelText('Chapter number'));
    await userEvent.type(screen.getByLabelText('Chapter number'), '3');
    await userEvent.type(screen.getByLabelText('Chapter title'), 'Thất Huyền Môn');
    await userEvent.upload(screen.getByLabelText('Source file'), file);
    await userEvent.click(screen.getByRole('button', { name: 'Import file' }));

    expect(onImportFile).toHaveBeenCalledWith({
      title: 'Phàm Nhân Tu Tiên',
      chapter_number: 3,
      chapter_title: 'Thất Huyền Môn',
      file,
    });
    expect(screen.getByLabelText('Import preview')).toHaveTextContent('chapter-3.txt');
  });

  it('previews and imports translated ebook files into the library', async () => {
    const onPreviewTranslatedEbook = vi.fn().mockResolvedValue({
      title: 'Đấu Phá Thương Khung',
      author: 'Thiên Tằm Thổ Đậu',
      language: 'vi',
      source_format: 'epub',
      cover_present: true,
      cover_preview_url: '/covers/previews/dau-pha.jpg',
      upload_id: 'preview-upload-1',
      split_method: 'toc',
      toc_chapter_count: 2,
      chapter_count: 2,
      chapters: [
        { chapter_number: 1, title: 'Vẫn Lạc Thiên Tài', sample: 'Đấu khí, ba đoạn!' },
        { chapter_number: 2, title: 'Đấu Giả', sample: 'Tiêu Viêm khẽ nắm tay.' },
      ],
    });
    const onImportTranslatedEbook = vi.fn().mockResolvedValue({
      book_id: 7,
      title: 'Đấu Phá Thương Khung',
      author: 'Thiên Tằm Thổ Đậu',
      source_format: 'epub',
      chapter_count: 2,
      imported_chapters: 2,
      skipped_chapters: 0,
      chapter_ids: [70, 71],
      message: 'Imported translated ebook',
    });
    const file = new File(['ebook'], 'dau-pha.epub', { type: 'application/epub+zip' });

    render(
      <ImportPanel
        books={[
          {
            id: 7,
            title: 'Đấu Phá Thương Khung',
          },
        ]}
        onCancel={() => undefined}
        onImportPaste={() => undefined}
        onImportTranslatedEbook={onImportTranslatedEbook}
        onPreviewTranslatedEbook={onPreviewTranslatedEbook}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Ebook bản dịch' }));
    await userEvent.upload(screen.getByLabelText('Ebook file'), file);

    expect(await screen.findByRole('heading', { name: 'Đấu Phá Thương Khung' })).toBeInTheDocument();
    expect(screen.getByText('Thiên Tằm Thổ Đậu')).toBeInTheDocument();
    expect(screen.getByText('2 chương')).toBeInTheDocument();
    expect(screen.getByText('Tách theo mục lục: 2 chương')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Bìa Đấu Phá Thương Khung' })).toHaveAttribute(
      'src',
      '/covers/previews/dau-pha.jpg',
    );
    expect(screen.getByText('Vẫn Lạc Thiên Tài')).toBeInTheDocument();
    expect(onPreviewTranslatedEbook).toHaveBeenCalledWith(file, 'auto', {
      duplicateStrategy: 'skip',
      targetBookId: null,
    });

    await userEvent.selectOptions(screen.getByLabelText('Gộp vào truyện có sẵn'), '7');
    await userEvent.click(screen.getByRole('radio', { name: 'Bỏ qua chương trùng' }));
    await userEvent.click(screen.getByRole('button', { name: 'Import vào Library' }));

    expect(onImportTranslatedEbook).toHaveBeenCalledWith({
      file,
      uploadId: 'preview-upload-1',
      duplicateStrategy: 'skip',
      splitMode: 'auto',
      targetBookId: 7,
    });
  });

  it('retries the retained upload after an import conflict with the current preview options', async () => {
    let resolveRetryPreview!: (preview: EbookPreview) => void;
    const retryPreview = new Promise<EbookPreview>((resolve) => {
      resolveRetryPreview = resolve;
    });
    const preview = existingBookPreview({ bookMatchReason: 'selected' });
    const onPreviewTranslatedEbook = vi.fn()
      .mockResolvedValueOnce(preview)
      .mockImplementationOnce(() => retryPreview);
    const onImportTranslatedEbook = vi.fn().mockRejectedValue(new ApiError(
      'Truyện này đã tồn tại trong Library. Hãy Preview và xác nhận gộp vào truyện hiện có.',
      409,
    ));
    const file = new File(['ebook'], 'retained.epub', { type: 'application/epub+zip' });

    render(
      <ImportPanel
        books={[{ id: 7, title: 'Trường Thiên Lục' }]}
        onCancel={() => undefined}
        onImportPaste={() => undefined}
        onImportTranslatedEbook={onImportTranslatedEbook}
        onPreviewTranslatedEbook={onPreviewTranslatedEbook}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Ebook bản dịch' }));
    await userEvent.selectOptions(screen.getByLabelText('Cách tách chương'), 'single');
    await userEvent.selectOptions(screen.getByLabelText('Gộp vào truyện có sẵn'), '7');
    await userEvent.click(screen.getByRole('radio', { name: 'Dừng khi trùng' }));
    await userEvent.upload(screen.getByLabelText('Ebook file'), file);
    await userEvent.click(await screen.findByLabelText('Tôi xác nhận gộp ebook này vào truyện đã có.'));
    await userEvent.click(screen.getByRole('button', { name: 'Import vào Library' }));

    const retryButton = await screen.findByRole('button', { name: 'Preview lại' });
    expect(retryButton).toBeEnabled();
    await userEvent.click(retryButton);

    expect(screen.getByRole('button', { name: 'Preview lại' })).toBeDisabled();
    expect(onPreviewTranslatedEbook).toHaveBeenLastCalledWith(file, 'single', {
      duplicateStrategy: 'error',
      targetBookId: 7,
    });

    resolveRetryPreview(preview);
    expect(await screen.findByLabelText('Tôi xác nhận gộp ebook này vào truyện đã có.')).not.toBeChecked();
  });

  it.each([
    {
      error: new ApiError('Máy chủ chưa thể xác nhận trạng thái import.', 500),
      message: 'Máy chủ chưa thể xác nhận trạng thái import.',
      name: 'a non-409 API failure',
    },
    {
      error: new TypeError('Failed to fetch'),
      message: 'Failed to fetch',
      name: 'network uncertainty',
    },
  ])('preserves the confirmed preview after $name without encouraging another submit', async ({ error, message }) => {
    const preview = existingBookPreview({ bookMatchReason: 'selected' });
    const onImportTranslatedEbook = vi.fn().mockRejectedValue(error);
    const file = new File(['ebook'], 'uncertain.epub', { type: 'application/epub+zip' });

    render(
      <ImportPanel
        books={[{ id: 7, title: 'Trường Thiên Lục' }]}
        onCancel={() => undefined}
        onImportPaste={() => undefined}
        onImportTranslatedEbook={onImportTranslatedEbook}
        onPreviewTranslatedEbook={vi.fn().mockResolvedValue(preview)}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Ebook bản dịch' }));
    await userEvent.upload(screen.getByLabelText('Ebook file'), file);
    const confirmation = await screen.findByLabelText('Tôi xác nhận gộp ebook này vào truyện đã có.');
    await userEvent.click(confirmation);
    await userEvent.click(screen.getByRole('button', { name: 'Import vào Library' }));

    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Trường Thiên Lục' })).toBeInTheDocument();
    expect(confirmation).toBeChecked();
    expect(screen.queryByRole('button', { name: 'Preview lại' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Import vào Library' })).toBeDisabled();
  });

  it('shows a guided ebook import flow and success summary', async () => {
    const onPreviewTranslatedEbook = vi.fn().mockResolvedValue({
      title: 'Đấu Phá Thương Khung',
      author: 'Thiên Tằm Thổ Đậu',
      language: 'vi',
      source_format: 'epub',
      cover_present: false,
      upload_id: 'preview-upload-1',
      split_method: 'toc',
      toc_chapter_count: 2,
      chapter_count: 2,
      chapters: [
        { chapter_number: 1, title: 'Vẫn Lạc Thiên Tài', sample: 'Đấu khí, ba đoạn!' },
        { chapter_number: 2, title: 'Đấu Giả', sample: 'Tiêu Viêm khẽ nắm tay.' },
      ],
      dry_run: {
        target_book_id: 7,
        target_title: 'Đấu Phá Thương Khung',
        duplicate_strategy: 'skip',
        chapter_count: 2,
        new_chapters: 2,
        duplicate_chapters: 0,
        would_import: 2,
        would_skip: 0,
        would_overwrite: 0,
        would_error: 0,
      },
    });
    const onImportTranslatedEbook = vi.fn().mockResolvedValue({
      book_id: 7,
      title: 'Đấu Phá Thương Khung',
      author: 'Thiên Tằm Thổ Đậu',
      source_format: 'epub',
      chapter_count: 2,
      imported_chapters: 2,
      skipped_chapters: 0,
      overwritten_chapters: 0,
      chapter_ids: [70, 71],
      message: 'Imported translated ebook',
    });
    const file = new File(['ebook'], 'dau-pha.epub', { type: 'application/epub+zip' });

    render(
      <ImportPanel
        books={[{ id: 7, title: 'Đấu Phá Thương Khung' }]}
        onCancel={() => undefined}
        onImportPaste={() => undefined}
        onImportTranslatedEbook={onImportTranslatedEbook}
        onPreviewTranslatedEbook={onPreviewTranslatedEbook}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Ebook bản dịch' }));

    const flow = screen.getByRole('list', { name: 'Luồng import ebook' });
    expect(within(flow).getByText('1. Chọn nguồn')).toBeInTheDocument();
    expect(within(flow).getByText('2. Preview mục lục')).toBeInTheDocument();
    expect(within(flow).getByText('3. Import vào Library')).toBeInTheDocument();
    expect(screen.getByText('Tự động theo tên truyện')).toBeInTheDocument();

    await userEvent.upload(screen.getByLabelText('Ebook file'), file);

    expect(await screen.findByText('Sẽ import 2 chương')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Import vào Library' }));

    expect(await screen.findByRole('status', { name: 'Kết quả import ebook' })).toHaveTextContent(
      'Đã import 2 chương vào Đấu Phá Thương Khung',
    );
  });

  it('blocks oversized ebook uploads and points users to the server inbox', async () => {
    const onPreviewTranslatedEbook = vi.fn();
    const largeFile = new File(['ebook'], 'huge-translated.epub', { type: 'application/epub+zip' });
    Object.defineProperty(largeFile, 'size', { value: 96 * 1024 * 1024 });
    const Panel = ImportPanel as any;

    render(
      <Panel
        ebookInboxDirectory="/srv/novel-tnn/inbox/ebooks"
        onCancel={() => undefined}
        onImportPaste={() => undefined}
        onPreviewTranslatedEbook={onPreviewTranslatedEbook}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Ebook bản dịch' }));
    await userEvent.upload(screen.getByLabelText('Ebook file'), largeFile);

    expect(await screen.findByText(/File lớn hơn 95 MB/i)).toBeInTheDocument();
    expect(screen.getByText(/inbox\/ebooks/i)).toBeInTheDocument();
    expect(onPreviewTranslatedEbook).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Preview lại' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Import vào Library' })).toBeDisabled();
  });

  it('explains translated TXT and HTML import support', async () => {
    const onPreviewTranslatedEbook = vi.fn().mockResolvedValue({
      title: 'Thanh Sơn bản dịch',
      author: '',
      language: 'vi',
      source_format: 'txt',
      cover_present: false,
      chapter_count: 2,
      split_method: 'regex',
      chapters: [
        { chapter_number: 1, title: 'Gió nổi', sample: 'Thiếu niên áo xanh đứng trước sơn môn.' },
        { chapter_number: 2, title: 'Kiếm ý', sample: 'Một luồng kiếm khí lạnh thấu xương vụt qua.' },
      ],
      warnings: [
        {
          type: 'regex_chapter_detection',
          message: 'App đã tự tạo danh sách chương từ heading text; hãy kiểm tra trước khi import.',
        },
      ],
    });
    const file = new File(['translated txt'], 'thanh-son.txt', { type: 'text/plain' });

    render(
      <ImportPanel
        onCancel={() => undefined}
        onImportPaste={() => undefined}
        onImportTranslatedEbook={() => undefined}
        onPreviewTranslatedEbook={onPreviewTranslatedEbook}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Ebook bản dịch' }));

    expect(screen.getByLabelText('Ebook file')).toHaveAttribute(
      'accept',
      expect.stringContaining('.txt'),
    );
    expect(screen.getByText(/TXT\/HTML đã dịch/i)).toBeInTheDocument();

    await userEvent.upload(screen.getByLabelText('Ebook file'), file);

    expect(await screen.findByText('Tách bằng heading TXT/HTML')).toBeInTheDocument();
    expect(screen.getByText(/tự tạo danh sách chương/i)).toBeInTheDocument();
  });

  it('previews and imports ebooks selected from the server inbox without uploading a File object', async () => {
    const onPreviewInboxEbook = vi.fn().mockResolvedValue({
      title: 'Đấu Phá Thương Khung',
      author: 'Thiên Tằm Thổ Đậu',
      language: 'vi',
      source_format: 'epub',
      cover_present: false,
      inbox_file: 'translated-from-inbox.epub',
      split_method: 'toc',
      toc_chapter_count: 1,
      chapter_count: 1,
      chapters: [{ chapter_number: 1, title: 'Vẫn Lạc Thiên Tài', sample: 'Đấu khí, ba đoạn!' }],
    });
    const onImportTranslatedEbook = vi.fn().mockResolvedValue({
      book_id: 7,
      title: 'Đấu Phá Thương Khung',
      author: 'Thiên Tằm Thổ Đậu',
      source_format: 'epub',
      chapter_count: 1,
      imported_chapters: 1,
      skipped_chapters: 0,
      chapter_ids: [70],
      message: 'Imported translated ebook',
    });
    const Panel = ImportPanel as any;

    render(
      <Panel
        ebookInboxDirectory="/srv/novel-tnn/inbox/ebooks"
        ebookInboxFiles={[{ name: 'translated-from-inbox.epub', size: 130 * 1024 * 1024, modified_at: '2026-06-27T00:00:00Z' }]}
        onCancel={() => undefined}
        onImportPaste={() => undefined}
        onImportTranslatedEbook={onImportTranslatedEbook}
        onPreviewInboxEbook={onPreviewInboxEbook}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Ebook bản dịch' }));
    await userEvent.click(screen.getByRole('button', { name: 'Server inbox' }));
    await userEvent.selectOptions(screen.getByLabelText('Server inbox ebook'), 'translated-from-inbox.epub');

    expect(await screen.findByRole('heading', { name: 'Đấu Phá Thương Khung' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Import vào Library' }));

    expect(onPreviewInboxEbook).toHaveBeenCalledWith('translated-from-inbox.epub', 'auto', {
      duplicateStrategy: 'skip',
      targetBookId: null,
    });
    expect(onImportTranslatedEbook).toHaveBeenCalledWith({
      inboxFile: 'translated-from-inbox.epub',
      duplicateStrategy: 'skip',
      splitMode: 'auto',
      targetBookId: undefined,
    });
  });

  it('retries the retained inbox selection with the current preview options', async () => {
    const preview = existingBookPreview({
      bookMatchReason: 'selected',
      existingBookTitle: 'Inbox preview',
    });
    const onPreviewInboxEbook = vi.fn()
      .mockRejectedValueOnce(new Error('Preview inbox failed'))
      .mockResolvedValueOnce(preview);

    render(
      <ImportPanel
        books={[{ id: 7, title: 'Inbox preview' }]}
        ebookInboxFiles={[{ name: 'retained.epub', size: 1024, modified_at: '2026-07-12T00:00:00Z' }]}
        onCancel={() => undefined}
        onImportPaste={() => undefined}
        onImportTranslatedEbook={() => undefined}
        onPreviewInboxEbook={onPreviewInboxEbook}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Ebook bản dịch' }));
    await userEvent.selectOptions(screen.getByLabelText('Cách tách chương'), 'single');
    await userEvent.selectOptions(screen.getByLabelText('Gộp vào truyện có sẵn'), '7');
    await userEvent.click(screen.getByRole('radio', { name: 'Ghi đè chương trùng' }));
    await userEvent.click(screen.getByRole('button', { name: 'Server inbox' }));
    await userEvent.selectOptions(screen.getByLabelText('Server inbox ebook'), 'retained.epub');

    expect(await screen.findByRole('alert')).toHaveTextContent('Preview inbox failed');
    await userEvent.click(screen.getByRole('button', { name: 'Preview lại' }));

    expect(onPreviewInboxEbook).toHaveBeenLastCalledWith('retained.epub', 'single', {
      duplicateStrategy: 'overwrite',
      targetBookId: 7,
    });
    expect(await screen.findByRole('heading', { name: 'Inbox preview' })).toBeInTheDocument();
  });

  it('defaults ebook duplicate handling to skipping existing chapters', async () => {
    const onPreviewTranslatedEbook = vi.fn().mockResolvedValue({
      title: 'Đấu Phá Thương Khung',
      author: 'Thiên Tằm Thổ Đậu',
      language: 'vi',
      source_format: 'epub',
      cover_present: false,
      chapter_count: 1,
      chapters: [{ chapter_number: 1, title: 'Vẫn Lạc Thiên Tài', sample: 'Đấu khí, ba đoạn!' }],
    });
    const onImportTranslatedEbook = vi.fn().mockResolvedValue({
      book_id: 7,
      title: 'Đấu Phá Thương Khung',
      author: 'Thiên Tằm Thổ Đậu',
      source_format: 'epub',
      chapter_count: 1,
      imported_chapters: 0,
      skipped_chapters: 1,
      chapter_ids: [],
      message: 'Imported translated ebook',
    });
    const file = new File(['ebook'], 'dau-pha.epub', { type: 'application/epub+zip' });

    render(
      <ImportPanel
        onCancel={() => undefined}
        onImportPaste={() => undefined}
        onImportTranslatedEbook={onImportTranslatedEbook}
        onPreviewTranslatedEbook={onPreviewTranslatedEbook}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Ebook bản dịch' }));
    expect(screen.getByRole('option', { name: 'Tự động: ưu tiên mục lục' })).toBeInTheDocument();
    await userEvent.upload(screen.getByLabelText('Ebook file'), file);
    expect(await screen.findByRole('heading', { name: 'Đấu Phá Thương Khung' })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'Bỏ qua chương trùng' })).toBeChecked();

    await userEvent.click(screen.getByRole('button', { name: 'Import vào Library' }));

    expect(onImportTranslatedEbook).toHaveBeenCalledWith({
      file,
      duplicateStrategy: 'skip',
      splitMode: 'auto',
      targetBookId: undefined,
    });
  });

  it('shows ebook dry-run counts, first/last preview groups, and warnings', async () => {
    const firstChapters = Array.from({ length: 20 }, (_, index) => ({
      chapter_number: index + 1,
      title: `Chương đầu ${index + 1}`,
      sample: `Sample đầu ${index + 1}`,
    }));
    const lastChapters = Array.from({ length: 20 }, (_, index) => ({
      chapter_number: index + 26,
      title: `Chương cuối ${index + 26}`,
      sample: `Sample cuối ${index + 26}`,
    }));
    const onPreviewTranslatedEbook = vi.fn().mockResolvedValue({
      title: 'Trường Thiên Lục',
      author: 'Tác giả',
      language: 'vi',
      source_format: 'epub',
      cover_present: false,
      chapter_count: 45,
      chapters: [...firstChapters, ...lastChapters],
      first_chapters: firstChapters,
      last_chapters: lastChapters,
      warnings: [
        { type: 'suspect_chapter', chapter_number: 2, title: 'part0000', message: 'Nghi ngờ trang rác: part0000' },
        { type: 'short_chapter', chapter_number: 2, title: 'part0000', message: 'Chương quá ngắn: #2 part0000' },
      ],
      dry_run: {
        target_book_id: 7,
        target_title: 'Trường Thiên Lục',
        duplicate_strategy: 'skip',
        chapter_count: 45,
        new_chapters: 43,
        duplicate_chapters: 2,
        would_import: 43,
        would_skip: 2,
        would_overwrite: 0,
        would_error: 0,
      },
    });
    const file = new File(['ebook'], 'truong-thien.epub', { type: 'application/epub+zip' });

    render(
      <ImportPanel
        books={[{ id: 7, title: 'Trường Thiên Lục' }]}
        onCancel={() => undefined}
        onImportPaste={() => undefined}
        onImportTranslatedEbook={() => undefined}
        onPreviewTranslatedEbook={onPreviewTranslatedEbook}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Ebook bản dịch' }));
    await userEvent.upload(screen.getByLabelText('Ebook file'), file);

    expect(await screen.findByText('20 chương đầu')).toBeInTheDocument();
    expect(screen.getByText('20 chương cuối')).toBeInTheDocument();
    expect(screen.getByText('Chương đầu 1')).toBeInTheDocument();
    expect(screen.getByText('Chương cuối 45')).toBeInTheDocument();
    expect(screen.getByText('Sẽ import 43 chương')).toBeInTheDocument();
    expect(screen.getByText('Bỏ qua 2 chương trùng')).toBeInTheDocument();
    expect(screen.getByText('Chương quá ngắn: #2 part0000')).toBeInTheDocument();
  });

  it('requires confirmation bound to the title-matched existing book before importing', async () => {
    const onPreviewTranslatedEbook = vi.fn().mockResolvedValue(existingBookPreview());
    const onImportTranslatedEbook = vi.fn();
    const file = new File(['ebook'], 'truong-thien.epub', { type: 'application/epub+zip' });

    render(
      <ImportPanel
        onCancel={() => undefined}
        onImportPaste={() => undefined}
        onImportTranslatedEbook={onImportTranslatedEbook}
        onPreviewTranslatedEbook={onPreviewTranslatedEbook}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Ebook bản dịch' }));
    await userEvent.upload(screen.getByLabelText('Ebook file'), file);

    expect(await screen.findByRole('alert')).toHaveTextContent('Truyện này đã có trong Library');
    expect(screen.getByRole('alert')).toHaveTextContent('43 chương mới · 2 chương trùng');
    expect(screen.getByText('Xác nhận gộp ebook vào truyện đã có trước khi import.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Import vào Library' })).toBeDisabled();

    await userEvent.click(screen.getByLabelText('Tôi xác nhận gộp ebook này vào truyện đã có.'));
    expect(screen.getByRole('button', { name: 'Import vào Library' })).toBeEnabled();
    await userEvent.click(screen.getByRole('button', { name: 'Import vào Library' }));

    expect(onImportTranslatedEbook).toHaveBeenCalledWith(expect.objectContaining({
      confirmedExistingBookId: 7,
    }));
  });

  it('uses explicit-target wording and requires confirmation even with zero duplicate chapters', async () => {
    const onPreviewTranslatedEbook = vi.fn().mockResolvedValue(existingBookPreview({
      bookMatchReason: 'selected',
      duplicateChapters: 0,
      newChapters: 45,
    }));
    const onImportTranslatedEbook = vi.fn();
    const file = new File(['ebook'], 'truong-thien.epub', { type: 'application/epub+zip' });

    render(
      <ImportPanel
        books={[{ id: 7, title: 'Trường Thiên Lục' }]}
        onCancel={() => undefined}
        onImportPaste={() => undefined}
        onImportTranslatedEbook={onImportTranslatedEbook}
        onPreviewTranslatedEbook={onPreviewTranslatedEbook}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Ebook bản dịch' }));
    await userEvent.selectOptions(screen.getByLabelText('Gộp vào truyện có sẵn'), '7');
    await userEvent.upload(screen.getByLabelText('Ebook file'), file);

    expect(await screen.findByRole('alert')).toHaveTextContent('Sẽ gộp vào truyện đã chọn');
    expect(screen.getByRole('alert')).toHaveTextContent('45 chương mới · 0 chương trùng');
    expect(screen.getByRole('button', { name: 'Import vào Library' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: 'Import vào Library' }));
    expect(onImportTranslatedEbook).not.toHaveBeenCalled();
  });

  it('does not show merge confirmation for a new story', async () => {
    const preview = existingBookPreview();
    const dryRun = preview.dry_run!;
    preview.dry_run = {
      ...dryRun,
      target_book_id: null,
      existing_book_id: null,
      existing_book_title: '',
      existing_chapter_count: 0,
      book_match_reason: 'new',
      requires_existing_book_confirmation: false,
    };
    const onPreviewTranslatedEbook = vi.fn().mockResolvedValue(preview);
    const file = new File(['ebook'], 'new-story.epub', { type: 'application/epub+zip' });

    render(
      <ImportPanel
        onCancel={() => undefined}
        onImportPaste={() => undefined}
        onImportTranslatedEbook={() => undefined}
        onPreviewTranslatedEbook={onPreviewTranslatedEbook}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Ebook bản dịch' }));
    await userEvent.upload(screen.getByLabelText('Ebook file'), file);

    await screen.findByRole('heading', { name: 'Trường Thiên Lục' });
    expect(screen.queryByLabelText('Tôi xác nhận gộp ebook này vào truyện đã có.')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Import vào Library' })).toBeEnabled();
  });

  it('resets existing-book confirmation when ebook preview inputs or source change', async () => {
    const onPreviewTranslatedEbook = vi.fn()
      .mockResolvedValueOnce(existingBookPreview())
      .mockResolvedValue(existingBookPreview({ existingBookId: 8, existingBookTitle: 'Preview mới' }));
    const onPreviewInboxEbook = vi.fn().mockResolvedValue(existingBookPreview({
      existingBookId: 9,
      existingBookTitle: 'Inbox preview',
    }));
    const firstFile = new File(['ebook-1'], 'first.epub', { type: 'application/epub+zip' });
    const secondFile = new File(['ebook-2'], 'second.epub', { type: 'application/epub+zip' });

    render(
      <ImportPanel
        books={[{ id: 8, title: 'Preview mới' }]}
        ebookInboxFiles={[
          { name: 'inbox-one.epub', size: 12, modified_at: '2026-07-12T00:00:00Z' },
          { name: 'inbox-two.epub', size: 13, modified_at: '2026-07-12T00:00:00Z' },
        ]}
        onCancel={() => undefined}
        onImportPaste={() => undefined}
        onImportTranslatedEbook={() => undefined}
        onPreviewInboxEbook={onPreviewInboxEbook}
        onPreviewTranslatedEbook={onPreviewTranslatedEbook}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Ebook bản dịch' }));
    await userEvent.upload(screen.getByLabelText('Ebook file'), firstFile);
    const confirmation = await screen.findByLabelText('Tôi xác nhận gộp ebook này vào truyện đã có.');
    await userEvent.click(confirmation);
    expect(confirmation).toBeChecked();

    await userEvent.upload(screen.getByLabelText('Ebook file'), secondFile);
    expect(await screen.findByLabelText('Tôi xác nhận gộp ebook này vào truyện đã có.')).not.toBeChecked();
    await userEvent.click(screen.getByLabelText('Tôi xác nhận gộp ebook này vào truyện đã có.'));

    await userEvent.selectOptions(screen.getByLabelText('Cách tách chương'), 'single');
    expect(await screen.findByLabelText('Tôi xác nhận gộp ebook này vào truyện đã có.')).not.toBeChecked();
    await userEvent.click(screen.getByLabelText('Tôi xác nhận gộp ebook này vào truyện đã có.'));

    await userEvent.selectOptions(screen.getByLabelText('Gộp vào truyện có sẵn'), '8');
    expect(await screen.findByLabelText('Tôi xác nhận gộp ebook này vào truyện đã có.')).not.toBeChecked();
    await userEvent.click(screen.getByLabelText('Tôi xác nhận gộp ebook này vào truyện đã có.'));

    await userEvent.click(screen.getByRole('radio', { name: 'Dừng khi trùng' }));
    expect(await screen.findByLabelText('Tôi xác nhận gộp ebook này vào truyện đã có.')).not.toBeChecked();
    await userEvent.click(screen.getByLabelText('Tôi xác nhận gộp ebook này vào truyện đã có.'));

    await userEvent.click(screen.getByRole('button', { name: 'Server inbox' }));
    expect(screen.getByRole('button', { name: 'Import vào Library' })).toBeDisabled();
    await userEvent.selectOptions(screen.getByLabelText('Server inbox ebook'), 'inbox-one.epub');
    expect(await screen.findByLabelText('Tôi xác nhận gộp ebook này vào truyện đã có.')).not.toBeChecked();
    await userEvent.click(screen.getByLabelText('Tôi xác nhận gộp ebook này vào truyện đã có.'));

    await userEvent.selectOptions(screen.getByLabelText('Server inbox ebook'), 'inbox-two.epub');
    expect(await screen.findByLabelText('Tôi xác nhận gộp ebook này vào truyện đã có.')).not.toBeChecked();

    await userEvent.click(screen.getByRole('button', { name: 'Upload file' }));
    expect(screen.getByRole('button', { name: 'Import vào Library' })).toBeDisabled();
  });

  it('ignores an older strategy preview that resolves after the newest strategy preview', async () => {
    const errorPreview = deferred<EbookPreview>();
    const overwritePreview = deferred<EbookPreview>();
    const initialPreview = existingBookPreview();
    const newestPreview = existingBookPreview({
      duplicateStrategy: 'overwrite',
      existingBookId: 9,
      existingBookTitle: 'Preview ghi đè mới nhất',
    });
    const stalePreview = existingBookPreview({
      duplicateStrategy: 'error',
      existingBookId: 8,
      existingBookTitle: 'Preview dừng cũ',
    });
    const onPreviewTranslatedEbook = vi.fn()
      .mockResolvedValueOnce(initialPreview)
      .mockImplementationOnce(() => errorPreview.promise)
      .mockImplementationOnce(() => overwritePreview.promise);
    const onImportTranslatedEbook = vi.fn();
    const file = new File(['ebook'], 'strategy-race.epub', { type: 'application/epub+zip' });

    render(
      <ImportPanel
        onCancel={() => undefined}
        onImportPaste={() => undefined}
        onImportTranslatedEbook={onImportTranslatedEbook}
        onPreviewTranslatedEbook={onPreviewTranslatedEbook}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Ebook bản dịch' }));
    await userEvent.upload(screen.getByLabelText('Ebook file'), file);
    await screen.findByRole('heading', { name: 'Trường Thiên Lục' });
    await userEvent.click(screen.getByRole('radio', { name: 'Dừng khi trùng' }));
    await userEvent.click(screen.getByRole('radio', { name: 'Ghi đè chương trùng' }));

    overwritePreview.resolve(newestPreview);
    expect(await screen.findByRole('heading', { name: 'Preview ghi đè mới nhất' })).toBeInTheDocument();
    errorPreview.resolve(stalePreview);
    await errorPreview.promise;
    await waitFor(() => {
      expect(screen.queryByRole('heading', { name: 'Preview dừng cũ' })).not.toBeInTheDocument();
      expect(screen.getByRole('heading', { name: 'Preview ghi đè mới nhất' })).toBeInTheDocument();
    });

    const warning = screen.getByRole('alert');
    expect(warning).toHaveTextContent('Chiến lược đã chọn: Ghi đè chương trùng');
    expect(warning).toHaveTextContent('Sẽ import 45 chương, gồm ghi đè 2 chương trùng.');
    await userEvent.click(screen.getByLabelText('Tôi xác nhận gộp ebook này vào truyện đã có.'));
    await userEvent.click(screen.getByRole('button', { name: 'Import vào Library' }));

    expect(onImportTranslatedEbook).toHaveBeenCalledWith(expect.objectContaining({
      confirmedExistingBookId: 9,
      duplicateStrategy: 'overwrite',
      uploadId: 'preview-upload-9',
    }));
  });

  it('ignores an older source preview that resolves after the newest file preview', async () => {
    const firstPreview = deferred<EbookPreview>();
    const secondPreview = deferred<EbookPreview>();
    const onPreviewTranslatedEbook = vi.fn()
      .mockImplementationOnce(() => firstPreview.promise)
      .mockImplementationOnce(() => secondPreview.promise);
    const onImportTranslatedEbook = vi.fn();
    const firstFile = new File(['old'], 'old.epub', { type: 'application/epub+zip' });
    const secondFile = new File(['new'], 'new.epub', { type: 'application/epub+zip' });

    render(
      <ImportPanel
        onCancel={() => undefined}
        onImportPaste={() => undefined}
        onImportTranslatedEbook={onImportTranslatedEbook}
        onPreviewTranslatedEbook={onPreviewTranslatedEbook}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Ebook bản dịch' }));
    await userEvent.upload(screen.getByLabelText('Ebook file'), firstFile);
    await userEvent.upload(screen.getByLabelText('Ebook file'), secondFile);
    secondPreview.resolve(existingBookPreview({ existingBookId: 12, existingBookTitle: 'Nguồn mới' }));
    expect(await screen.findByRole('heading', { name: 'Nguồn mới' })).toBeInTheDocument();
    firstPreview.resolve(existingBookPreview({ existingBookId: 11, existingBookTitle: 'Nguồn cũ' }));
    await firstPreview.promise;
    await waitFor(() => {
      expect(screen.queryByRole('heading', { name: 'Nguồn cũ' })).not.toBeInTheDocument();
      expect(screen.getByRole('heading', { name: 'Nguồn mới' })).toBeInTheDocument();
    });

    await userEvent.click(screen.getByLabelText('Tôi xác nhận gộp ebook này vào truyện đã có.'));
    await userEvent.click(screen.getByRole('button', { name: 'Import vào Library' }));
    expect(onImportTranslatedEbook).toHaveBeenCalledWith(expect.objectContaining({
      confirmedExistingBookId: 12,
      file: secondFile,
      uploadId: 'preview-upload-12',
    }));
  });

  it.each([
    {
      duplicateStrategy: 'skip' as const,
      expected: 'Chiến lược đã chọn: Bỏ qua chương trùng. Sẽ import 43 chương mới và bỏ qua 2 chương trùng.',
    },
    {
      duplicateStrategy: 'error' as const,
      expected: 'Chiến lược đã chọn: Dừng khi trùng. Sẽ dừng vì 2 chương trùng; chưa import chương nào.',
    },
    {
      duplicateStrategy: 'overwrite' as const,
      expected: 'Chiến lược đã chọn: Ghi đè chương trùng. Sẽ import 45 chương, gồm ghi đè 2 chương trùng.',
    },
  ])('names the selected $duplicateStrategy strategy beside its expected result', async ({ duplicateStrategy, expected }) => {
    const onPreviewTranslatedEbook = vi.fn().mockResolvedValue(existingBookPreview({ duplicateStrategy }));

    render(
      <ImportPanel
        onCancel={() => undefined}
        onImportPaste={() => undefined}
        onImportTranslatedEbook={() => undefined}
        onPreviewTranslatedEbook={onPreviewTranslatedEbook}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Ebook bản dịch' }));
    if (duplicateStrategy === 'error') {
      await userEvent.click(screen.getByRole('radio', { name: 'Dừng khi trùng' }));
    } else if (duplicateStrategy === 'overwrite') {
      await userEvent.click(screen.getByRole('radio', { name: 'Ghi đè chương trùng' }));
    }
    await userEvent.upload(
      screen.getByLabelText('Ebook file'),
      new File(['ebook'], `${duplicateStrategy}.epub`, { type: 'application/epub+zip' }),
    );

    expect(await screen.findByRole('alert')).toHaveTextContent(expected);
  });

  it('blocks translated ebook import when preview has no readable chapter body', async () => {
    const onPreviewTranslatedEbook = vi.fn().mockResolvedValue({
      title: 'Cầu Ma',
      author: 'Nhĩ Căn',
      language: 'vi',
      source_format: 'azw3',
      cover_present: true,
      split_method: 'toc',
      toc_chapter_count: 1483,
      chapter_count: 1482,
      chapters: [{ chapter_number: 2, title: 'Man Khải', sample: 'Chương 2 Man Khải' }],
      first_chapters: [{ chapter_number: 2, title: 'Man Khải', sample: 'Chương 2 Man Khải' }],
      last_chapters: [{ chapter_number: 1483, title: 'Kết', sample: 'Chương 1483 Kết' }],
      warnings: [
        {
          type: 'unreadable_ebook',
          message: 'Ebook gần như chỉ có tên chương/ảnh minh họa, không có nội dung chữ để đọc.',
        },
      ],
      dry_run: {
        target_book_id: null,
        target_title: 'Cầu Ma',
        duplicate_strategy: 'skip',
        chapter_count: 1482,
        new_chapters: 1482,
        duplicate_chapters: 0,
        would_import: 1482,
        would_skip: 0,
        would_overwrite: 0,
        would_error: 0,
      },
    });
    const onImportTranslatedEbook = vi.fn();
    const file = new File(['ebook'], 'cau-ma.azw3', { type: 'application/octet-stream' });

    render(
      <ImportPanel
        onCancel={() => undefined}
        onImportPaste={() => undefined}
        onImportTranslatedEbook={onImportTranslatedEbook}
        onPreviewTranslatedEbook={onPreviewTranslatedEbook}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Ebook bản dịch' }));
    await userEvent.upload(screen.getByLabelText('Ebook file'), file);

    expect(await screen.findByText('Ebook gần như chỉ có tên chương/ảnh minh họa, không có nội dung chữ để đọc.')).toBeInTheDocument();
    expect(screen.getByText('Ebook preview không có nội dung chữ đủ để import.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Import vào Library' })).toBeDisabled();

    await userEvent.click(screen.getByRole('button', { name: 'Import vào Library' }));
    expect(onImportTranslatedEbook).not.toHaveBeenCalled();
  });

  it('shows recent translated ebook import history', async () => {
    render(
      <ImportPanel
        ebookImportHistory={[
          {
            id: 1,
            book_id: 7,
            title: 'Trường Thiên Lục',
            filename: 'truong-thien.epub',
            source_format: 'epub',
            duplicate_strategy: 'skip',
            split_mode: 'auto',
            chapter_count: 45,
            imported_chapters: 43,
            skipped_chapters: 2,
            overwritten_chapters: 0,
            warning_count: 1,
            warnings: [{ type: 'short_chapter', message: 'Chương quá ngắn: #2 part0000' }],
            created_at: '2026-06-26T00:00:00Z',
          },
        ]}
        onCancel={() => undefined}
        onImportPaste={() => undefined}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Ebook bản dịch' }));

    expect(screen.getByRole('heading', { name: 'Lịch sử import ebook' })).toBeInTheDocument();
    expect(screen.getByText('truong-thien.epub')).toBeInTheDocument();
    expect(screen.getByText('Đã import 43, bỏ qua 2, ghi đè 0')).toBeInTheDocument();
  });

  it('refreshes ebook preview when split mode changes', async () => {
    const onPreviewTranslatedEbook = vi
      .fn()
      .mockResolvedValueOnce({
        title: 'Toàn Bản Dịch',
        author: '',
        language: 'vi',
        source_format: 'epub',
        cover_present: false,
        split_method: 'heading',
        toc_chapter_count: 0,
        chapter_count: 2,
        chapters: [{ chapter_number: 1, title: 'Khai cục', sample: 'Hắn mở mắt.' }],
      })
      .mockResolvedValueOnce({
        title: 'Toàn Bản Dịch',
        author: '',
        language: 'vi',
        source_format: 'epub',
        cover_present: false,
        split_method: 'single',
        toc_chapter_count: 0,
        chapter_count: 1,
        chapters: [{ chapter_number: 1, title: 'Toàn bộ ebook', sample: 'Chương 1: Khai cục' }],
      });
    const file = new File(['ebook'], 'full.epub', { type: 'application/epub+zip' });

    render(
      <ImportPanel
        onCancel={() => undefined}
        onImportPaste={() => undefined}
        onImportTranslatedEbook={() => undefined}
        onPreviewTranslatedEbook={onPreviewTranslatedEbook}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Ebook bản dịch' }));
    await userEvent.upload(screen.getByLabelText('Ebook file'), file);
    await screen.findByText('Khai cục');
    expect(screen.getByText('Không tìm thấy mục lục, dùng heading fallback')).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText('Cách tách chương'), 'single');

    expect(await screen.findByText('Toàn bộ ebook')).toBeInTheDocument();
    expect(screen.getByText('Import thành một chương')).toBeInTheDocument();
    expect(onPreviewTranslatedEbook).toHaveBeenLastCalledWith(file, 'single', {
      duplicateStrategy: 'skip',
      targetBookId: null,
    });
  });

  it('exposes URL and catalog as guided import sources', () => {
    render(<ImportPanel onCancel={() => undefined} onImportPaste={() => undefined} />);

    expect(screen.getByRole('button', { name: 'Paste' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'File' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'URL' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Kho nguồn' })).toBeInTheDocument();
    expect(screen.getByRole('list', { name: 'Import wizard steps' })).toHaveTextContent('Chọn nguồn');
  });

  it('commits multi-chapter paste through the reviewed wizard endpoint', async () => {
    const onImportWizardText = vi.fn().mockResolvedValue({
      book_id: 9,
      title: 'Yong Ye',
      content_kind: 'raw',
      chapter_count: 2,
      imported_chapters: 2,
      skipped_chapters: 0,
      overwritten_chapters: 0,
      chapter_ids: [91, 92],
      warnings: [],
      message: 'Imported reviewed text',
    });

    render(
      <ImportPanel
        onCancel={() => undefined}
        onImportPaste={() => undefined}
        onImportWizardText={onImportWizardText}
      />,
    );

    fireEvent.change(screen.getByLabelText('Source text'), {
      target: {
        value: '《Yong Ye [raw]》\n第十章 蛰是苑\n秦铭推开门。\n\n第十一章 雪夜\n风雪落下。',
      },
    });

    expect(screen.getByText('2 chương được phát hiện')).toBeInTheDocument();
    expect(screen.getByLabelText('Content mode')).toHaveValue('raw');

    await userEvent.click(screen.getByRole('button', { name: 'Import chapter' }));

    await waitFor(() => {
      expect(onImportWizardText.mock.calls[0][0]).toEqual(expect.objectContaining({
          title: 'Yong Ye',
          content_kind: 'raw',
          duplicate_strategy: 'skip',
          source_type: 'paste',
        }));
    });
    expect(onImportWizardText.mock.calls[0][1]).toEqual({ finalAction: 'open' });
    expect(onImportWizardText.mock.calls[0][0].chapters).toEqual([
      expect.objectContaining({ chapter_number: 10, chapter_title: '蛰是苑' }),
      expect.objectContaining({ chapter_number: 11, chapter_title: '雪夜' }),
    ]);
    expect(await screen.findByRole('status', { name: 'Kết quả import' })).toHaveTextContent('Đã lưu 2 chương vào Yong Ye');
  });

  it('renders malicious HTML-like imported text as inert escaped preview text', async () => {
    const { container } = render(
      <ImportPanel
        onCancel={() => undefined}
        onImportPaste={() => undefined}
        onImportWizardText={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText('Source text'), {
      target: {
        value: [
          '《Unsafe [raw]》',
          '第1章 恶意',
          '<script>alert(1)</script>',
          '<img src=x onerror=alert(1)>',
          '<iframe src="javascript:alert(1)"></iframe>',
          '少年继续前行。',
        ].join('\n'),
      },
    });

    expect(screen.getAllByText(/<script>alert\(1\)<\/script>/).length).toBeGreaterThan(0);
    expect(container.querySelector('script')).toBeNull();
    expect(container.querySelector('iframe')).toBeNull();
    expect(container.querySelector('img[src="x"]')).toBeNull();
  });

  it('requires explicit confirmation before overwriting duplicate wizard chapters', async () => {
    const onImportWizardText = vi.fn().mockResolvedValue({
      book_id: 7,
      title: 'Dup Book',
      content_kind: 'raw',
      chapter_count: 1,
      imported_chapters: 0,
      skipped_chapters: 0,
      overwritten_chapters: 1,
      chapter_ids: [701],
      warnings: [],
      message: 'Imported reviewed text',
    });

    render(
      <ImportPanel
        books={[{ id: 7, title: 'Dup Book' }]}
        chapters={[{ book_id: 7, chapter_number: 1, title: 'Old Chapter' }]}
        onCancel={() => undefined}
        onImportPaste={() => undefined}
        onImportWizardText={onImportWizardText}
      />,
    );

    fireEvent.change(screen.getByLabelText('Source text'), {
      target: { value: '《Dup Book [raw]》\n第1章 New Chapter\n新的内容。' },
    });
    await userEvent.selectOptions(screen.getByLabelText('Target book'), '7');
    await userEvent.selectOptions(screen.getByLabelText('Content mode'), 'raw');
    await userEvent.click(screen.getByLabelText('Ghi đè chương trùng đã xác nhận'));

    expect(screen.getByText(/Chương sẽ ghi đè/)).toHaveTextContent('1');
    expect(screen.getByRole('button', { name: 'Import chapter' })).toBeDisabled();

    await userEvent.click(screen.getByLabelText(/Tôi xác nhận ghi đè/));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Import chapter' })).toBeEnabled());
    await userEvent.click(screen.getByRole('button', { name: 'Import chapter' }));

    await waitFor(() => {
      expect(onImportWizardText.mock.calls[0][0]).toEqual(expect.objectContaining({
        duplicate_strategy: 'overwrite',
        target_book_id: 7,
      }));
    });
  });

  it('shows result actions for opening the book and viewing a created job', async () => {
    const onOpenImportedBook = vi.fn();
    const onOpenJob = vi.fn();
    const onImportWizardText = vi.fn().mockResolvedValue({
      book_id: 12,
      title: 'Job Book',
      content_kind: 'raw',
      chapter_count: 1,
      imported_chapters: 1,
      skipped_chapters: 0,
      overwritten_chapters: 0,
      chapter_ids: [1201],
      warnings: [{ type: 'too_short', message: 'Nội dung ngắn.' }],
      message: 'Imported reviewed text',
    });
    const onCreateTranslationJob = vi.fn().mockResolvedValue({
      job_id: 'job-translate-1',
      status: 'queued',
      message: 'Queued',
    });

    render(
      <ImportPanel
        onCancel={() => undefined}
        onCreateTranslationJob={onCreateTranslationJob}
        onImportPaste={() => undefined}
        onImportWizardText={onImportWizardText}
        onOpenImportedBook={onOpenImportedBook}
        onOpenJob={onOpenJob}
      />,
    );

    fireEvent.change(screen.getByLabelText('Source text'), {
      target: { value: '《Job Book [raw]》\n第1章 起始\n少年醒来。' },
    });
    await userEvent.click(screen.getByLabelText('Save and create translation job'));
    await userEvent.click(screen.getByRole('button', { name: 'Import chapter' }));

    const result = await screen.findByRole('status', { name: 'Kết quả import' });
    expect(result).toHaveTextContent('Đã lưu 1 chương vào Job Book');
    expect(result).toHaveTextContent('Nội dung ngắn.');
    expect(result).toHaveTextContent('Job đã tạo: job-translate-1');

    await userEvent.click(screen.getByRole('button', { name: 'Open reader/book' }));
    await userEvent.click(screen.getByRole('button', { name: 'View job status' }));

    expect(onOpenImportedBook).toHaveBeenCalledWith(expect.objectContaining({ book_id: 12 }));
    expect(onOpenJob).toHaveBeenCalledWith('job-translate-1');
  });

  it('previews a supported URL before starting an import job', async () => {
    const onPreviewImportUrl = vi.fn().mockResolvedValue({
      adapter_id: '69shuba',
      adapter_label: '69shuba',
      source: 'www.69shuba.com',
      source_url: 'https://www.69shuba.com/book/1',
      title: '凡人修仙传',
      author: '忘语',
      description: '',
      cover_url: '',
      chapter_count: 1,
      chapters: [
        {
          chapter_number: 1,
          title: '第一章 山边小村',
          url: 'https://www.69shuba.com/book/1/1.html',
        },
      ],
      policy: {
        source_id: '69shuba',
        label: '69shuba',
        delay_seconds: 8,
        max_concurrency: 1,
        retry_limit: 2,
      },
      managed_source_id: 'src-verified',
      managed_source_status: 'VERIFIED',
      managed_source_trust_level: 'HIGH',
      automation_allowed: true,
      automation_reason: '',
    });
    const onStartImportUrlJob = vi.fn().mockResolvedValue({
      job_id: 'job-url-1',
      status: 'queued',
      message: 'Import queued',
    });

    render(
      <ImportPanel
        onCancel={() => undefined}
        onImportPaste={() => undefined}
        onPreviewImportUrl={onPreviewImportUrl}
        onStartImportUrlJob={onStartImportUrlJob}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'URL' }));
    await userEvent.type(screen.getByLabelText('Source URL'), 'https://www.69shuba.com/book/1');
    await userEvent.click(screen.getByRole('button', { name: 'Preview URL' }));

    expect(await screen.findByRole('heading', { name: '凡人修仙传' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Tạo job import URL' }));

    expect(onStartImportUrlJob).toHaveBeenCalledWith({
      url: 'https://www.69shuba.com/book/1',
      title: '凡人修仙传',
      author: '忘语',
      source: 'www.69shuba.com',
      chapters: [
        {
          chapter_number: 1,
          title: '第一章 山边小村',
          url: 'https://www.69shuba.com/book/1/1.html',
        },
      ],
      retry_limit: 2,
      managed_source_id: 'src-verified',
    });
    expect(await screen.findByRole('status', { name: 'Kết quả import URL' })).toHaveTextContent('job-url-1');
  });

  it('blocks URL import automation for unverified sources and shows the review reason', async () => {
    const onPreviewImportUrl = vi.fn().mockResolvedValue({
      adapter_id: '69shuba',
      adapter_label: '69shuba',
      source: 'www.69shuba.com',
      source_url: 'https://www.69shuba.com/book/1',
      title: '凡人修仙传',
      author: '忘语',
      description: '',
      cover_url: '',
      chapter_count: 1,
      chapters: [
        {
          chapter_number: 1,
          title: '第一章 山边小村',
          url: 'https://www.69shuba.com/book/1/1.html',
        },
      ],
      policy: {
        source_id: '69shuba',
        label: '69shuba',
        delay_seconds: 8,
        max_concurrency: 1,
        retry_limit: 2,
      },
      managed_source_id: 'src-review',
      managed_source_status: 'NEEDS_REVIEW',
      managed_source_trust_level: 'MANUAL_ONLY',
      automation_allowed: false,
      automation_reason: 'Nguồn đang ở trạng thái NEEDS_REVIEW nên chưa thể tạo job tự động.',
    });
    const onStartImportUrlJob = vi.fn();

    render(
      <ImportPanel
        onCancel={() => undefined}
        onImportPaste={() => undefined}
        onPreviewImportUrl={onPreviewImportUrl}
        onStartImportUrlJob={onStartImportUrlJob}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'URL' }));
    await userEvent.type(screen.getByLabelText('Source URL'), 'https://www.69shuba.com/book/1');
    await userEvent.click(screen.getByRole('button', { name: 'Preview URL' }));

    expect(await screen.findAllByText('Nguồn đang ở trạng thái NEEDS_REVIEW nên chưa thể tạo job tự động.')).toHaveLength(2);
    expect(screen.getByRole('button', { name: 'Tạo job import URL' })).toBeDisabled();
    expect(onStartImportUrlJob).not.toHaveBeenCalled();
  });

  it('commits uploaded TXT with multiple chapters through the wizard endpoint', async () => {
    const onImportWizardText = vi.fn().mockResolvedValue({
      book_id: 10,
      title: 'Thanh Sơn',
      content_kind: 'raw',
      chapter_count: 2,
      imported_chapters: 2,
      skipped_chapters: 0,
      overwritten_chapters: 0,
      chapter_ids: [100, 101],
      warnings: [],
      message: 'Imported reviewed text',
    });
    const file = new File(['第1章 开始\n少年醒来。\n\n第2章 入山\n山风吹过。'], 'Thanh Son - Chương 1.txt', {
      type: 'text/plain',
    });

    render(
      <ImportPanel
        onCancel={() => undefined}
        onImportFile={() => undefined}
        onImportPaste={() => undefined}
        onImportWizardText={onImportWizardText}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'File' }));
    fireEvent.change(screen.getByLabelText('Source file'), { target: { files: [file] } });

    expect(await screen.findByText('2 chương được phát hiện')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Import file' }));

    expect(onImportWizardText.mock.calls[0][0]).toEqual(expect.objectContaining({
      source_type: 'txt',
      content_kind: 'raw',
    }));
    expect(onImportWizardText.mock.calls[0][1]).toEqual({ finalAction: 'open' });
    expect(onImportWizardText.mock.calls[0][0].chapters).toHaveLength(2);
  });

  it('blocks unsupported TXT wizard file types before commit', async () => {
    const onImportWizardText = vi.fn();
    const file = new File(['not a txt import'], 'chapter.pdf', { type: 'application/pdf' });

    render(
      <ImportPanel
        onCancel={() => undefined}
        onImportFile={() => undefined}
        onImportPaste={() => undefined}
        onImportWizardText={onImportWizardText}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'File' }));
    fireEvent.change(screen.getByLabelText('Source file'), { target: { files: [file] } });

    expect(await screen.findByRole('alert')).toHaveTextContent('Unsupported TXT import file type');
    expect(screen.getByRole('button', { name: 'Import file' })).toBeDisabled();
    expect(onImportWizardText).not.toHaveBeenCalled();
  });

  it('blocks oversized TXT wizard files before browser parsing', async () => {
    const onImportWizardText = vi.fn();
    const file = new File(['x'.repeat(5 * 1024 * 1024 + 1)], 'too-large.txt', { type: 'text/plain' });

    render(
      <ImportPanel
        onCancel={() => undefined}
        onImportFile={() => undefined}
        onImportPaste={() => undefined}
        onImportWizardText={onImportWizardText}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'File' }));
    fireEvent.change(screen.getByLabelText('Source file'), { target: { files: [file] } });

    expect(await screen.findByRole('alert')).toHaveTextContent('TXT file is too large');
    expect(screen.getByRole('button', { name: 'Import file' })).toBeDisabled();
    expect(onImportWizardText).not.toHaveBeenCalled();
  });

  it('rejects files that look like unsupported encoding before commit', async () => {
    const onImportWizardText = vi.fn();
    const file = new File([new Uint8Array(256).fill(0xff)], 'bad-encoding.txt', { type: 'text/plain' });

    render(
      <ImportPanel
        onCancel={() => undefined}
        onImportFile={() => undefined}
        onImportPaste={() => undefined}
        onImportWizardText={onImportWizardText}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'File' }));
    fireEvent.change(screen.getByLabelText('Source file'), { target: { files: [file] } });

    expect(await screen.findByRole('alert')).toHaveTextContent('Encoding không được hỗ trợ');
    expect(onImportWizardText).not.toHaveBeenCalled();
  });

  it('auto-fills metadata from selected file name and content', async () => {
    const file = new File(['第十二章 雪夜来客\n秦铭推开门。'], 'Yong Ye - Chương 12 - Tuyết Dạ.txt', {
      type: 'text/plain',
    });

    render(
      <ImportPanel
        onCancel={() => undefined}
        onImportFile={() => undefined}
        onImportPaste={() => undefined}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'File' }));
    await userEvent.upload(screen.getByLabelText('Source file'), file);

    await waitFor(() => {
      expect(screen.getByLabelText('Book title')).toHaveValue('Yong Ye');
      expect(screen.getByLabelText('Chapter number')).toHaveValue(12);
      expect(screen.getByLabelText('Chapter title')).toHaveValue('Tuyết Dạ');
    });
  });

  it('calls onCancel', async () => {
    const onCancel = vi.fn();

    render(<ImportPanel onCancel={onCancel} onImportPaste={() => undefined} />);

    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(onCancel).toHaveBeenCalledOnce();
  });

  it('displays pasted text in the preview', async () => {
    render(<ImportPanel onCancel={() => undefined} onImportPaste={() => undefined} />);

    await userEvent.type(screen.getByLabelText('Source text'), '山门前人声鼎沸。');

    expect(screen.getByLabelText('Import preview')).toHaveTextContent('山门前人声鼎沸。');
  });
});
