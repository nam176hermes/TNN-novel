import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { CSSProperties } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Chapter } from '../../api/types';
import ReaderTextSurface, { type ReaderTextSurfaceProps } from './ReaderTextSurface';

const chapter: Chapter = {
  audio_path: null,
  book_id: 42,
  chapter_number: 2,
  has_translation: true,
  id: 102,
  status: 'translated',
  title: 'Thanh Ngưu trấn',
};

function buildSurfaceProps(overrides: Partial<ReaderTextSurfaceProps> = {}): ReaderTextSurfaceProps {
  const paragraphs = ['Hàn Lập khẽ gật đầu.', 'Lục ca, ta cảm tạ huynh.'];
  return {
    fontFamily: 'serif',
    hasRichContent: false,
    highlightedParagraphs: new Set(),
    instantMode: false,
    isPaginatedMode: false,
    notesByParagraph: new Map(),
    paragraphs,
    readerStyle: { '--reader-font-size': '18px', '--reader-line-height': '1.9' } as CSSProperties,
    richBlocks: [],
    selectedChapter: chapter,
    textError: '',
    textState: 'ready',
    theme: 'light',
    visibleParagraphs: paragraphs.map((paragraph, index) => ({ index, paragraph })),
    visibleRichBlocks: [],
    width: 'medium',
    onOpenNote: vi.fn(),
    onToggleChrome: vi.fn(),
    onToggleHighlight: vi.fn(),
    ...overrides,
  };
}

function renderSurface(overrides: Partial<ReaderTextSurfaceProps> = {}) {
  const props = buildSurfaceProps(overrides);
  render(<ReaderTextSurface {...props} />);
  return props;
}

describe('ReaderTextSurface', () => {
  afterEach(() => {
    cleanup();
  });

  it('renders chapter title and visible paragraph blocks', () => {
    renderSurface();

    const article = screen.getByRole('article', { name: 'Nội dung đọc tiếng Việt' });
    expect(article).toHaveAttribute('data-reading-mode', 'scroll');
    expect(article).toHaveAttribute('data-font', 'serif');
    expect(screen.getByRole('heading', { name: 'Thanh Ngưu trấn' })).toBeInTheDocument();
    expect(screen.getByText('Hàn Lập khẽ gật đầu.')).toBeInTheDocument();
    expect(screen.getByText('Lục ca, ta cảm tạ huynh.')).toBeInTheDocument();
  });

  it('renders rich HTML when available outside paginated mode', () => {
    renderSurface({
      hasRichContent: true,
      paragraphs: ['Kiếm khí nổi lên.'],
      richBlocks: [
        { html: '<p>Kiếm khí nổi lên.</p>', index: 0, kind: 'text', text: 'Kiếm khí nổi lên.' },
        { html: '<img src="/book-assets/42/sword.png" alt="Kiếm quang"/>', index: 1, kind: 'image', text: 'Kiếm quang' },
      ],
      visibleParagraphs: [{ index: 0, paragraph: 'Kiếm khí nổi lên.' }],
    });

    const article = screen.getByRole('article', { name: 'Nội dung đọc tiếng Việt' });
    expect(within(article).getByRole('img', { name: 'Kiếm quang' })).toHaveAttribute(
      'src',
      '/book-assets/42/sword.png',
    );
    expect(article.querySelectorAll('.reader-rich-block')).toHaveLength(2);
  });

  it('keeps image-only rich blocks in the text model for progress and pagination measurement', () => {
    renderSurface({
      hasRichContent: true,
      paragraphs: ['Kiếm quang'],
      richBlocks: [
        { html: '<img src="/book-assets/42/sword.png" alt="Kiếm quang"/>', index: 0, kind: 'image', text: 'Kiếm quang' },
      ],
      visibleParagraphs: [],
    });

    const block = screen
      .getByRole('img', { name: 'Kiếm quang' })
      .closest('.reader-paragraph-block');
    const textElement = block?.querySelector('.reader-paragraph-text');
    const mirror = textElement?.querySelector('.reader-rich-text-mirror');

    expect(textElement).toHaveTextContent('Kiếm quang');
    expect(mirror).toHaveAttribute('aria-hidden', 'true');
    expect(mirror).toHaveTextContent('Kiếm quang');
  });

  it('keeps images in paginated rich HTML and only renders the current rich page blocks', () => {
    const richBlocks = [
      { html: '<p>Trang trước.</p>', index: 0, kind: 'text' as const, text: 'Trang trước.' },
      {
        html: '<figure><img src="/book-assets/42/sword.png" alt="Kiếm quang"/><figcaption>Kiếm quang</figcaption></figure>',
        index: 1,
        kind: 'image' as const,
        text: 'Kiếm quang',
      },
    ];
    renderSurface({
      hasRichContent: true,
      instantMode: true,
      isPaginatedMode: true,
      paragraphs: ['Trang trước.', 'Kiếm quang'],
      richBlocks,
      visibleParagraphs: [],
      visibleRichBlocks: [richBlocks[1]],
    });

    const article = screen.getByRole('article', { name: 'Nội dung đọc tiếng Việt' });
    expect(article).toHaveAttribute('data-reading-mode', 'paginated');
    expect(screen.queryByText('Trang trước.')).not.toBeInTheDocument();
    expect(within(article).getByRole('img', { name: 'Kiếm quang' })).toHaveAttribute(
      'src',
      '/book-assets/42/sword.png',
    );
    expect(article.querySelector('.reader-rich-block')).toHaveAttribute('data-paragraph-index', '1');
  });

  it('notifies the reader when rich HTML media finishes loading so pagination can be measured again', () => {
    const onRichMediaLoad = vi.fn();
    renderSurface({
      hasRichContent: true,
      isPaginatedMode: true,
      paragraphs: ['Kiếm quang'],
      richBlocks: [
        {
          html: '<figure><img src="/book-assets/42/sword.png" alt="Kiếm quang"/></figure>',
          index: 0,
          kind: 'image',
          text: 'Kiếm quang',
        },
      ],
      visibleParagraphs: [],
      visibleRichBlocks: [
        {
          html: '<figure><img src="/book-assets/42/sword.png" alt="Kiếm quang"/></figure>',
          index: 0,
          kind: 'image',
          text: 'Kiếm quang',
        },
      ],
      onRichMediaLoad,
    } as Partial<ReaderTextSurfaceProps>);

    fireEvent.load(screen.getByRole('img', { name: 'Kiếm quang' }));

    expect(onRichMediaLoad).toHaveBeenCalledTimes(1);
  });

  it('uses visible paragraphs for paginated mode and instant interactions', async () => {
    const onOpenNote = vi.fn();
    const onToggleHighlight = vi.fn();
    renderSurface({
      highlightedParagraphs: new Set([4]),
      instantMode: true,
      isPaginatedMode: true,
      notesByParagraph: new Map([[4, { note: 'Cần giữ giọng cổ trang.' }]]),
      paragraphs: [
        'Đoạn một.',
        'Đoạn hai.',
        'Đoạn ba.',
        'Đoạn bốn.',
        'Đoạn năm sang trang.',
      ],
      visibleParagraphs: [{ index: 4, paragraph: 'Đoạn năm sang trang.' }],
      onOpenNote,
      onToggleHighlight,
    });

    const article = screen.getByRole('article', { name: 'Nội dung đọc tiếng Việt' });
    expect(article).toHaveAttribute('data-reading-mode', 'paginated');
    expect(screen.queryByText('Đoạn một.')).not.toBeInTheDocument();
    expect(screen.getByText('Đoạn năm sang trang.')).toBeInTheDocument();
    expect(screen.getByText('Đoạn năm sang trang.').closest('.reader-paragraph-block')).toHaveAttribute(
      'data-highlighted',
      'true',
    );

    await userEvent.click(screen.getByRole('button', { name: 'Đánh dấu đoạn 5' }));
    expect(onToggleHighlight).toHaveBeenCalledWith(4, 'Đoạn năm sang trang.');

    await userEvent.click(screen.getByRole('button', { name: 'Mở ghi chú đoạn 5' }));
    expect(onOpenNote).toHaveBeenCalledWith(4, 'Đoạn năm sang trang.');
  });

  it('passes visible page character ranges to instant highlight and note actions', async () => {
    const onOpenNote = vi.fn();
    const onToggleHighlight = vi.fn();
    renderSurface({
      instantMode: true,
      isPaginatedMode: true,
      paragraphs: ['Đoạn rất dài cần tách trang theo ký tự.'],
      visibleParagraphs: [{
        charEnd: 22,
        charStart: 9,
        index: 0,
        paragraph: 'dài cần tách',
      } as { charEnd: number; charStart: number; index: number; paragraph: string }],
      onOpenNote,
      onToggleHighlight,
    });

    await userEvent.click(screen.getByRole('button', { name: 'Đánh dấu đoạn 1' }));
    expect(onToggleHighlight).toHaveBeenCalledWith(0, 'dài cần tách', { charStart: 9, charEnd: 22 });

    await userEvent.click(screen.getByRole('button', { name: 'Ghi chú đoạn 1' }));
    expect(onOpenNote).toHaveBeenCalledWith(0, 'dài cần tách', { charStart: 9, charEnd: 22 });
  });

  it('shows loading, empty, and imported-title-only states', () => {
    const { rerender } = render(
      <ReaderTextSurface
        {...buildSurfaceProps({
          hasTitleOnlyImportContent: true,
          paragraphs: [],
          selectedChapter: { ...chapter, title: 'Man Khải' },
          textState: 'loading',
          visibleParagraphs: [],
        })}
      />,
    );
    expect(screen.getByRole('status', { name: 'Đang tải nội dung chương' })).toBeInTheDocument();
    expect(screen.getByText('Đang tải nội dung chương…')).toBeInTheDocument();

    rerender(
      <ReaderTextSurface
        {...buildSurfaceProps({
          hasTitleOnlyImportContent: true,
          paragraphs: [],
          selectedChapter: { ...chapter, title: 'Man Khải' },
          visibleParagraphs: [],
        })}
      />,
    );
    expect(screen.getByText('Chưa có bản dịch tiếng Việt.')).toBeInTheDocument();
    expect(screen.getByText(/File import của chương này chỉ có tiêu đề/)).toBeInTheDocument();
  });

  it('marks empty reader states so mobile can render them as centered cards', () => {
    const { rerender } = render(
      <ReaderTextSurface
        {...buildSurfaceProps({
          paragraphs: [],
          richBlocks: [],
          selectedChapter: null,
          visibleParagraphs: [],
        })}
      />,
    );

    expect(screen.getByText('Chọn một truyện đã dịch để bắt đầu đọc.')).toHaveClass('reader-empty-state');

    rerender(
      <ReaderTextSurface
        {...buildSurfaceProps({
          paragraphs: [],
          richBlocks: [],
          selectedChapter: { ...chapter, title: 'Man Khải' },
          visibleParagraphs: [],
        })}
      />,
    );

    expect(screen.getByText('Chưa có bản dịch tiếng Việt.')).toHaveClass('reader-empty-state');
  });
});
