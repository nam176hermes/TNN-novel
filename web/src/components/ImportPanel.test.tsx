import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ImportPanel from './ImportPanel';

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

    expect(screen.getByRole('region', { name: 'Hướng dẫn nhập chương' })).toHaveTextContent('Paste dùng cho văn bản chương đơn');
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

    await userEvent.upload(screen.getByLabelText('Source file'), file);

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
        ebookInboxDirectory="/home/thenam176/novel_pipeline/inbox/ebooks"
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
        ebookInboxDirectory="/home/thenam176/novel_pipeline/inbox/ebooks"
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

  it('does not expose URL import from the import page', () => {
    render(<ImportPanel onCancel={() => undefined} onImportPaste={() => undefined} />);

    expect(screen.getByRole('button', { name: 'Paste' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'File' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'URL' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Source URL')).not.toBeInTheDocument();
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
