import { describe, expect, it } from 'vitest';
import { extractReaderRichBlocks, htmlTextContent, sliceReaderRichBlockHtml } from './readerRichContent';

describe('readerRichContent', () => {
  it('extracts stable rich blocks for text and image content', () => {
    const blocks = extractReaderRichBlocks(
      '<p>Kiếm khí nổi lên.</p><figure><img src="/book-assets/42/sword.png" alt="Kiếm quang"/></figure>',
    );

    expect(blocks).toEqual([
      {
        html: '<p>Kiếm khí nổi lên.</p>',
        index: 0,
        kind: 'text',
        text: 'Kiếm khí nổi lên.',
      },
      {
        html: '<figure><img src="/book-assets/42/sword.png" alt="Kiếm quang"></figure>',
        index: 1,
        kind: 'image',
        text: 'Kiếm quang',
      },
    ]);
  });

  it('uses image alt text for image-only chapters', () => {
    expect(extractReaderRichBlocks('<p><img src="/book-assets/42/ch1.png" alt="Trang 1"></p>')).toMatchObject([
      {
        index: 0,
        kind: 'image',
        text: 'Trang 1',
      },
    ]);
  });

  it('does not treat media labels as visible HTML text for rich text mirrors', () => {
    expect(htmlTextContent('<figure><img src="/book-assets/42/ch1.png" alt="Kiếm quang"></figure>')).toBe('');
    expect(htmlTextContent('<svg role="img" aria-label="Trận đồ"></svg>')).toBe('');
  });

  it('assigns fallback text to unlabeled media blocks for progress anchors', () => {
    const blocks = extractReaderRichBlocks(`
      <figure><img src="/book-assets/42/map.png"></figure>
      <video src="/book-assets/42/intro.mp4"></video>
      <audio src="/book-assets/42/theme.mp3"></audio>
    `);

    expect(blocks.map((block) => ({
      kind: block.kind,
      text: block.text,
    }))).toEqual([
      { kind: 'image', text: 'Hình ảnh' },
      { kind: 'structure', text: 'Video' },
      { kind: 'structure', text: 'Âm thanh' },
    ]);
  });

  it('classifies EPUB tables, lists, and code blocks as standalone structures for pagination', () => {
    const blocks = extractReaderRichBlocks(`
      <table><tr><td>Cảnh giới</td><td>Trúc Cơ</td></tr></table>
      <ul><li>Phi kiếm</li><li>Phù lục</li></ul>
      <pre>Đinh!
Hệ thống thức tỉnh.</pre>
    `);

    expect(blocks.map((block) => ({
      html: block.html,
      kind: block.kind,
      text: block.text,
    }))).toEqual([
      {
        html: '<table><tbody><tr><td>Cảnh giới</td><td>Trúc Cơ</td></tr></tbody></table>',
        kind: 'structure',
        text: 'Cảnh giới Trúc Cơ',
      },
      {
        html: '<ul><li>Phi kiếm</li><li>Phù lục</li></ul>',
        kind: 'structure',
        text: 'Phi kiếm Phù lục',
      },
      {
        html: '<pre>Đinh!\nHệ thống thức tỉnh.</pre>',
        kind: 'structure',
        text: 'Đinh! Hệ thống thức tỉnh.',
      },
    ]);
  });

  it('keeps EPUB media, definition lists, and math blocks as pagination units', () => {
    const blocks = extractReaderRichBlocks(`
      <picture>
        <source srcset="/book-assets/42/map.webp" type="image/webp">
        <img src="/book-assets/42/map.png" alt="Bản đồ Thanh Ngưu trấn">
      </picture>
      <svg role="img" aria-label="Sơ đồ trận pháp"><title>Sơ đồ trận pháp</title><text>Trận nhãn</text></svg>
      <video poster="/book-assets/42/intro.jpg" aria-label="Ảo cảnh nhập môn"></video>
      <audio title="Khúc tiêu trong đêm"></audio>
      <dl><dt>Cảnh giới</dt><dd>Luyện Khí</dd></dl>
      <math aria-label="Công thức trận pháp"><mi>x</mi><mo>+</mo><mi>y</mi></math>
    `);

    expect(blocks.map((block) => ({
      kind: block.kind,
      text: block.text,
    }))).toEqual([
      { kind: 'image', text: 'Bản đồ Thanh Ngưu trấn' },
      { kind: 'image', text: 'Sơ đồ trận pháp' },
      { kind: 'structure', text: 'Ảo cảnh nhập môn' },
      { kind: 'structure', text: 'Khúc tiêu trong đêm' },
      { kind: 'structure', text: 'Cảnh giới Luyện Khí' },
      { kind: 'structure', text: 'Công thức trận pháp' },
    ]);
  });

  it('splits nested EPUB wrapper sections into stable leaf blocks for pagination', () => {
    const blocks = extractReaderRichBlocks(`
      <section class="chapter" id="chapter-1">
        <h2>Chương 1: Mưa đêm</h2>
        <div class="chapter-body">
          <p>Hàn Lập khép cửa.</p>
          <figure>
            <img src="/book-assets/42/rain.png" alt="Mưa đêm"/>
            <figcaption>Mưa đêm ngoài trấn</figcaption>
          </figure>
          <p>Tiếng chuông xa dần.</p>
        </div>
      </section>
    `);

    expect(blocks.map((block) => ({
      index: block.index,
      kind: block.kind,
      text: block.text,
    }))).toEqual([
      { index: 0, kind: 'text', text: 'Chương 1: Mưa đêm' },
      { index: 1, kind: 'text', text: 'Hàn Lập khép cửa.' },
      { index: 2, kind: 'image', text: 'Mưa đêm ngoài trấn' },
      { index: 3, kind: 'text', text: 'Tiếng chuông xa dần.' },
    ]);
  });

  it('keeps direct wrapper text when splitting mixed EPUB content', () => {
    const blocks = extractReaderRichBlocks(`
      <section>
        Lời dẫn trước chương.
        <p>Đoạn chính.</p>
      </section>
    `);

    expect(blocks.map((block) => block.text)).toEqual([
      'Lời dẫn trước chương.',
      'Đoạn chính.',
    ]);
    expect(blocks[0]?.html).toBe('<p>Lời dẫn trước chương.</p>');
  });

  it('keeps contiguous EPUB inline text fragments in one paragraph block', () => {
    const blocks = extractReaderRichBlocks(`
      Lời <span>dẫn</span> <em>trước</em> chương.
      <p>Đoạn chính.</p>
    `);

    expect(blocks.map((block) => ({
      html: block.html,
      kind: block.kind,
      text: block.text,
    }))).toEqual([
      {
        html: '<p>Lời <span>dẫn</span> <em>trước</em> chương.</p>',
        kind: 'text',
        text: 'Lời dẫn trước chương.',
      },
      {
        html: '<p>Đoạn chính.</p>',
        kind: 'text',
        text: 'Đoạn chính.',
      },
    ]);
  });

  it('ignores non-reading EPUB script, style, and noscript nodes', () => {
    const blocks = extractReaderRichBlocks(`
      <style>.chapter { color: red; }</style>
      <script>window.bad = true;</script>
      <noscript>Bật JavaScript để đọc trang này.</noscript>
      <p>Đoạn truyện thật.</p>
    `);

    expect(blocks.map((block) => block.text)).toEqual(['Đoạn truyện thật.']);
    expect(blocks.map((block) => block.html).join('')).not.toContain('window.bad');
    expect(blocks.map((block) => block.html).join('')).not.toContain('.chapter');
    expect(blocks.map((block) => block.html).join('')).not.toContain('Bật JavaScript');
  });

  it('ignores CSS-hidden EPUB helper text when extracting rich block text', () => {
    const blocks = extractReaderRichBlocks(`
      <p>Độc <span hidden>ẩn một</span><span style="display:none">ẩn hai</span>Tu</p>
      <table>
        <tr>
          <td>Cảnh giới</td>
          <td style="visibility: hidden">ẩn ba</td>
          <td>Trúc Cơ</td>
        </tr>
      </table>
      <figure>
        <img src="/book-assets/42/map.png" alt="">
        <figcaption>Bản đồ thật<span style="visibility: collapse">ẩn bốn</span></figcaption>
      </figure>
    `);

    expect(blocks.map((block) => block.text)).toEqual([
      'Độc Tu',
      'Cảnh giới Trúc Cơ',
      'Bản đồ thật',
    ]);
    expect(htmlTextContent(blocks[0]?.html ?? '')).toBe('Độc Tu');
  });

  it('ignores EPUB stylesheet-hidden helper text when extracting rich block text', () => {
    const html = `
      <style>
        .epub-helper, .print-only { display: none; }
        .collapse-helper { visibility: collapse; }
      </style>
      <p>Độc <span class="epub-helper">ẩn một</span><span class="print-only">ẩn hai</span>Tu<span class="collapse-helper">ẩn ba</span>.</p>
    `;
    const blocks = extractReaderRichBlocks(html);

    expect(blocks).toHaveLength(1);
    expect(blocks[0]?.text).toBe('Độc Tu.');
    expect(blocks[0]?.html).not.toContain('ẩn một');
    expect(blocks[0]?.html).not.toContain('ẩn hai');
    expect(blocks[0]?.html).not.toContain('ẩn ba');
    expect(htmlTextContent(html)).toBe('Độc Tu.');
  });

  it('ignores aria-hidden EPUB mirror text when a rich block has readable text', () => {
    const html = '<p>Hàn <strong>Lập</strong><span aria-hidden="true">Hàn Lập</span> nhập môn.</p>';
    const blocks = extractReaderRichBlocks(html);

    expect(blocks).toHaveLength(1);
    expect(blocks[0]?.text).toBe('Hàn Lập nhập môn.');
    expect(blocks[0]?.html).not.toContain('Hàn Lập</span>');
    expect(htmlTextContent(html)).toBe('Hàn Lập nhập môn.');
  });

  it('keeps aria-hidden EPUB text when it is the only progress anchor for a rich block', () => {
    const html = '<figure><img src="/book-assets/42/map.png" alt=""><span aria-hidden="true">Bản đồ Thanh Vân</span></figure>';
    const blocks = extractReaderRichBlocks(html);

    expect(blocks).toHaveLength(1);
    expect(blocks[0]).toMatchObject({
      kind: 'image',
      text: 'Bản đồ Thanh Vân',
    });
    expect(htmlTextContent(blocks[0]?.html ?? '')).toBe('Bản đồ Thanh Vân');
  });

  it('keeps EPUB ruby annotations visually without counting them as reading text', () => {
    const blocks = extractReaderRichBlocks(`
      <p>Hàn Lập đạt <ruby>筑基<rp>(</rp><rt>Trúc Cơ</rt><rp>)</rp></ruby>.</p>
    `);

    expect(blocks).toHaveLength(1);
    expect(blocks[0]?.html).toContain('<ruby>筑基<rp>(</rp><rt>Trúc Cơ</rt><rp>)</rp></ruby>');
    expect(blocks[0]?.text).toBe('Hàn Lập đạt 筑基.');
    expect(htmlTextContent(blocks[0]?.html ?? '')).toBe('Hàn Lập đạt 筑基.');
  });

  it('keeps EPUB footnotes as semantic keep-together blocks for pagination', () => {
    const blocks = extractReaderRichBlocks(`
      <section>
        <p>Đoạn chính có chú thích.</p>
        <aside epub:type="footnote" role="doc-footnote" id="fn1">
          <p>[1] Chú thích về pháp bảo.</p>
          <p>Dòng chú thích thứ hai.</p>
        </aside>
      </section>
    `);

    expect(blocks).toHaveLength(2);
    expect(blocks[0]).toMatchObject({
      index: 0,
      kind: 'text',
      text: 'Đoạn chính có chú thích.',
    });
    expect(blocks[1]).toMatchObject({
      index: 1,
      kind: 'structure',
      pageBreakInsideAvoid: true,
      text: '[1] Chú thích về pháp bảo. Dòng chú thích thứ hai.',
    });
    expect(blocks[1]?.html).toContain('<aside');
    expect(blocks[1]?.html).toContain('role="doc-footnote"');
  });

  it('preserves explicit EPUB page break hints on rich blocks', () => {
    const blocks = extractReaderRichBlocks(`
      <p>Trang trước.</p>
      <p style="break-before: page; page-break-after: always">Trang riêng.</p>
      <p class="chapter-pagebreak">Trang sau.</p>
    `);

    expect(blocks.map((block) => ({
      pageBreakAfter: block.pageBreakAfter,
      pageBreakBefore: block.pageBreakBefore,
      text: block.text,
    }))).toEqual([
      { pageBreakAfter: undefined, pageBreakBefore: undefined, text: 'Trang trước.' },
      { pageBreakAfter: true, pageBreakBefore: true, text: 'Trang riêng.' },
      { pageBreakAfter: undefined, pageBreakBefore: true, text: 'Trang sau.' },
    ]);
  });

  it('distinguishes EPUB page-break-before and page-break-after tokens', () => {
    const blocks = extractReaderRichBlocks(`
      <p class="page-break-after">Trang trước.</p>
      <p data-page-break-before="always">Trang sau.</p>
    `);

    expect(blocks.map((block) => ({
      pageBreakAfter: block.pageBreakAfter,
      pageBreakBefore: block.pageBreakBefore,
      text: block.text,
    }))).toEqual([
      { pageBreakAfter: true, pageBreakBefore: undefined, text: 'Trang trước.' },
      { pageBreakAfter: undefined, pageBreakBefore: true, text: 'Trang sau.' },
    ]);
  });

  it('honors short data-page-break before and after values', () => {
    const blocks = extractReaderRichBlocks(`
      <p data-page-break="after">Trang trước.</p>
      <p data-page-break="before">Trang sau.</p>
    `);

    expect(blocks.map((block) => ({
      pageBreakAfter: block.pageBreakAfter,
      pageBreakBefore: block.pageBreakBefore,
      text: block.text,
    }))).toEqual([
      { pageBreakAfter: true, pageBreakBefore: undefined, text: 'Trang trước.' },
      { pageBreakAfter: undefined, pageBreakBefore: true, text: 'Trang sau.' },
    ]);
  });

  it('honors EPUB converter data-break before and after values', () => {
    const blocks = extractReaderRichBlocks(`
      <p data-break-after="page">Trang trước.</p>
      <p data-break-before="page">Trang sau.</p>
    `);

    expect(blocks.map((block) => ({
      pageBreakAfter: block.pageBreakAfter,
      pageBreakBefore: block.pageBreakBefore,
      text: block.text,
    }))).toEqual([
      { pageBreakAfter: true, pageBreakBefore: undefined, text: 'Trang trước.' },
      { pageBreakAfter: undefined, pageBreakBefore: true, text: 'Trang sau.' },
    ]);
  });

  it('honors EPUB converter break-inside avoid hints', () => {
    const blocks = extractReaderRichBlocks(`
      <figure data-break-inside="avoid">
        <img src="/book-assets/42/map.png" alt="Bản đồ cấm địa">
        <figcaption>Bản đồ cấm địa</figcaption>
      </figure>
      <table data-page-break-inside="avoid">
        <tr><td>Cảnh giới</td><td>Trúc Cơ</td></tr>
      </table>
    `);

    expect(blocks.map((block) => ({
      pageBreakInsideAvoid: block.pageBreakInsideAvoid,
      text: block.text,
    }))).toEqual([
      { pageBreakInsideAvoid: true, text: 'Bản đồ cấm địa' },
      { pageBreakInsideAvoid: true, text: 'Cảnh giới Trúc Cơ' },
    ]);
  });

  it('honors EPUB converter keep-together boolean hints', () => {
    const blocks = extractReaderRichBlocks(`
      <figure data-keep-together="true">
        <img src="/book-assets/42/formation.png" alt="Trận đồ">
        <figcaption>Trận đồ</figcaption>
      </figure>
      <table data-avoid-break="true">
        <tr><td>Pháp bảo</td><td>Phi kiếm</td></tr>
      </table>
    `);

    expect(blocks.map((block) => ({
      pageBreakInsideAvoid: block.pageBreakInsideAvoid,
      text: block.text,
    }))).toEqual([
      { pageBreakInsideAvoid: true, text: 'Trận đồ' },
      { pageBreakInsideAvoid: true, text: 'Pháp bảo Phi kiếm' },
    ]);
  });

  it('carries empty EPUB pagebreak markers to the following readable block', () => {
    const blocks = extractReaderRichBlocks(`
      <p>Trang trước.</p>
      <span epub:type="pagebreak" id="page-3"></span>
      <p>Trang sau.</p>
    `);

    expect(blocks.map((block) => ({
      pageBreakBefore: block.pageBreakBefore,
      text: block.text,
    }))).toEqual([
      { pageBreakBefore: undefined, text: 'Trang trước.' },
      { pageBreakBefore: true, text: 'Trang sau.' },
    ]);
  });

  it('treats explicit hr pagebreak markers as pagination hints instead of readable blocks', () => {
    const blocks = extractReaderRichBlocks(`
      <p>Trang trước.</p>
      <hr class="pagebreak" id="page-4">
      <p>Trang sau.</p>
    `);

    expect(blocks.map((block) => ({
      pageBreakBefore: block.pageBreakBefore,
      text: block.text,
    }))).toEqual([
      { pageBreakBefore: undefined, text: 'Trang trước.' },
      { pageBreakBefore: true, text: 'Trang sau.' },
    ]);
    expect(blocks.map((block) => block.text)).not.toContain('Ngắt trang');
  });

  it('carries empty wrapper pagebreak markers to the following readable block', () => {
    const blocks = extractReaderRichBlocks(`
      <p>Trang trước.</p>
      <div style="page-break-before: always"></div>
      <p>Trang sau.</p>
    `);

    expect(blocks.map((block) => ({
      pageBreakBefore: block.pageBreakBefore,
      text: block.text,
    }))).toEqual([
      { pageBreakBefore: undefined, text: 'Trang trước.' },
      { pageBreakBefore: true, text: 'Trang sau.' },
    ]);
  });

  it('splits paragraph text around inline EPUB pagebreak markers', () => {
    const blocks = extractReaderRichBlocks(`
      <p>Trang trước.<span epub:type="pagebreak" id="page-4"></span>Trang sau.</p>
    `);

    expect(blocks.map((block) => ({
      html: block.html,
      pageBreakBefore: block.pageBreakBefore,
      text: block.text,
    }))).toEqual([
      {
        html: '<p>Trang trước.</p>',
        pageBreakBefore: undefined,
        text: 'Trang trước.',
      },
      {
        html: '<p>Trang sau.</p>',
        pageBreakBefore: true,
        text: 'Trang sau.',
      },
    ]);
  });

  it('splits paragraph text around inline styled page break markers', () => {
    const blocks = extractReaderRichBlocks(`
      <p>Trang trước.<span style="page-break-before: always"></span>Trang sau.</p>
    `);

    expect(blocks.map((block) => ({
      html: block.html,
      pageBreakBefore: block.pageBreakBefore,
      text: block.text,
    }))).toEqual([
      {
        html: '<p>Trang trước.</p>',
        pageBreakBefore: undefined,
        text: 'Trang trước.',
      },
      {
        html: '<p>Trang sau.</p>',
        pageBreakBefore: true,
        text: 'Trang sau.',
      },
    ]);
  });

  it('applies EPUB stylesheet pagination hints to matching rich blocks', () => {
    const blocks = extractReaderRichBlocks(`
      <style>
        .chapter-title { break-before: page; }
        figure.plate, .keep-together { break-inside: avoid; }
        .afterword { page-break-after: always; }
      </style>
      <h2 class="chapter-title">Chương 2: Vào núi</h2>
      <figure class="plate">
        <img src="/book-assets/42/mountain.png" alt="Núi xanh">
        <figcaption>Núi xanh</figcaption>
      </figure>
      <table class="keep-together"><tr><td>Pháp bảo</td><td>Phi kiếm</td></tr></table>
      <p class="afterword">Hết phần dẫn.</p>
    `);

    expect(blocks.map((block) => ({
      pageBreakAfter: block.pageBreakAfter,
      pageBreakBefore: block.pageBreakBefore,
      pageBreakInsideAvoid: block.pageBreakInsideAvoid,
      text: block.text,
    }))).toEqual([
      {
        pageBreakAfter: undefined,
        pageBreakBefore: true,
        pageBreakInsideAvoid: undefined,
        text: 'Chương 2: Vào núi',
      },
      {
        pageBreakAfter: undefined,
        pageBreakBefore: undefined,
        pageBreakInsideAvoid: true,
        text: 'Núi xanh',
      },
      {
        pageBreakAfter: undefined,
        pageBreakBefore: undefined,
        pageBreakInsideAvoid: true,
        text: 'Pháp bảo Phi kiếm',
      },
      {
        pageBreakAfter: true,
        pageBreakBefore: undefined,
        pageBreakInsideAvoid: undefined,
        text: 'Hết phần dẫn.',
      },
    ]);
  });

  it('applies EPUB pagination hints inside media and supports stylesheet blocks', () => {
    const blocks = extractReaderRichBlocks(`
      <style>
        @media amzn-kf8 {
          figure.plate { break-inside: avoid; }
          .chapter-title { page-break-before: always; }
        }
        @supports (break-inside: avoid) {
          table.realm-list { page-break-inside: avoid; }
          .scene-end { break-after: page; }
        }
      </style>
      <h2 class="chapter-title">Chương 3: Bí cảnh</h2>
      <figure class="plate">
        <img src="/book-assets/42/realm.png" alt="Bí cảnh">
      </figure>
      <table class="realm-list"><tr><td>Cảnh giới</td><td>Kim Đan</td></tr></table>
      <p class="scene-end">Hết cảnh.</p>
    `);

    expect(blocks.map((block) => ({
      pageBreakAfter: block.pageBreakAfter,
      pageBreakBefore: block.pageBreakBefore,
      pageBreakInsideAvoid: block.pageBreakInsideAvoid,
      text: block.text,
    }))).toEqual([
      {
        pageBreakAfter: undefined,
        pageBreakBefore: true,
        pageBreakInsideAvoid: undefined,
        text: 'Chương 3: Bí cảnh',
      },
      {
        pageBreakAfter: undefined,
        pageBreakBefore: undefined,
        pageBreakInsideAvoid: true,
        text: 'Bí cảnh',
      },
      {
        pageBreakAfter: undefined,
        pageBreakBefore: undefined,
        pageBreakInsideAvoid: true,
        text: 'Cảnh giới Kim Đan',
      },
      {
        pageBreakAfter: true,
        pageBreakBefore: undefined,
        pageBreakInsideAvoid: undefined,
        text: 'Hết cảnh.',
      },
    ]);
  });

  it('applies vendor-prefixed EPUB pagination CSS rules', () => {
    const blocks = extractReaderRichBlocks(`
      <style>
        .kindle-title { -epub-page-break-before: always; }
        .plate { -webkit-column-break-inside: avoid; }
        .scene-end { -webkit-page-break-after: always; }
      </style>
      <h2 class="kindle-title">Chương 4: Cổ động</h2>
      <figure class="plate">
        <img src="/book-assets/42/drum.png" alt="Cổ động">
      </figure>
      <p class="scene-end">Màn đêm khép lại.</p>
    `);

    expect(blocks.map((block) => ({
      pageBreakAfter: block.pageBreakAfter,
      pageBreakBefore: block.pageBreakBefore,
      pageBreakInsideAvoid: block.pageBreakInsideAvoid,
      text: block.text,
    }))).toEqual([
      {
        pageBreakAfter: undefined,
        pageBreakBefore: true,
        pageBreakInsideAvoid: undefined,
        text: 'Chương 4: Cổ động',
      },
      {
        pageBreakAfter: undefined,
        pageBreakBefore: undefined,
        pageBreakInsideAvoid: true,
        text: 'Cổ động',
      },
      {
        pageBreakAfter: true,
        pageBreakBefore: undefined,
        pageBreakInsideAvoid: undefined,
        text: 'Màn đêm khép lại.',
      },
    ]);
  });

  it('slices rich text blocks without flattening inline EPUB formatting', () => {
    const html = '<p>Hàn <strong>Lập</strong> <em>khẽ</em> gật đầu.</p>';

    expect(sliceReaderRichBlockHtml(html, 'Hàn Lập khẽ gật đầu.', 4, 11)).toBe(
      '<p><strong>Lập</strong> <em>khẽ</em></p>',
    );
  });

  it('slices rich text blocks by readable text without counting ruby or hidden helpers', () => {
    const rubyHtml = '<p>Hàn <ruby>筑基<rp>(</rp><rt>Trúc Cơ</rt><rp>)</rp></ruby> thành.</p>';
    const hiddenHtml = '<p>Hàn <span hidden>ẩn một</span><strong>Lập</strong><span style="display:none">ẩn hai</span> thành.</p>';
    const ariaHiddenHtml = '<p>Hàn <strong>Lập</strong><span aria-hidden="true">Hàn Lập</span> thành.</p>';

    expect(sliceReaderRichBlockHtml(rubyHtml, 'Hàn 筑基 thành.', 0, 'Hàn 筑基'.length)).toBe(
      '<p>Hàn <ruby>筑基</ruby></p>',
    );
    expect(sliceReaderRichBlockHtml(hiddenHtml, 'Hàn Lập thành.', 0, 'Hàn Lập'.length)).toBe(
      '<p>Hàn <strong>Lập</strong></p>',
    );
    expect(sliceReaderRichBlockHtml(ariaHiddenHtml, 'Hàn Lập thành.', 0, 'Hàn Lập'.length)).toBe(
      '<p>Hàn <strong>Lập</strong></p>',
    );
  });
});
