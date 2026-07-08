import { describe, expect, it } from 'vitest';
import * as readerLocation from './readerLocation';
import {
  absoluteCharOffsetForParagraph,
  bookProgressPercent,
  countWords,
  estimateReadingMinutes,
  fallbackParagraphPages,
  pageIndexForParagraph,
  pageForParagraph,
  paginateParagraphsByViewport,
  paragraphLocation,
  readerTextLocationFromViewportAnchor,
  readingStatsForText,
  textOffsetFromPointInNode,
  textOffsetWithinNode,
  wordsRemainingForProgress,
} from './readerLocation';

describe('readerLocation', () => {
  it('maps an absolute character offset to paragraph location', () => {
    expect(paragraphLocation([{ index: 0, paragraph: 'abc' }], 0)).toEqual({
      paragraphIndex: 0,
      charOffset: 0,
      absoluteCharOffset: 0,
    });

    expect(paragraphLocation([
      { index: 0, paragraph: 'abc' },
      { index: 1, paragraph: 'defg' },
    ], 6)).toEqual({
      paragraphIndex: 1,
      charOffset: 1,
      absoluteCharOffset: 6,
    });
  });

  it('snaps absolute offsets inside paragraph separators to the next readable character', () => {
    expect(paragraphLocation([
      { index: 0, paragraph: 'abc' },
      { index: 1, paragraph: 'defg' },
    ], 4)).toEqual({
      paragraphIndex: 1,
      charOffset: 0,
      absoluteCharOffset: 5,
    });
  });

  it('calculates absolute offsets from paragraph and character position', () => {
    expect(absoluteCharOffsetForParagraph(['abc', 'defg'], 1, 2)).toBe(7);
    expect(absoluteCharOffsetForParagraph(['abc', 'defg'], 1, 99)).toBe(9);
    expect(absoluteCharOffsetForParagraph(['abc'], -1, 1)).toBe(0);
  });

  it('does not double count aria-hidden mirror text when rich HTML has readable text', () => {
    const root = document.createElement('div');
    root.innerHTML = '<span>Hàn Lập</span><span aria-hidden="true">Hàn Lập</span>';

    expect(readerLocation.textLength(root)).toBe('Hàn Lập'.length);
    expect(readerLocation.textNodeAtOffset(root, 'Hàn '.length)?.node.textContent).toBe('Hàn Lập');
  });

  it('does not count CSS-hidden EPUB helper text in exact reader offsets', () => {
    const root = document.createElement('div');
    root.innerHTML = [
      '<span>Hàn </span>',
      '<span hidden>ẩn một</span>',
      '<span style="display: none">ẩn hai</span>',
      '<span style="visibility: hidden">ẩn ba</span>',
      '<strong>Lập</strong>',
    ].join('');

    expect(readerLocation.textLength(root)).toBe('Hàn Lập'.length);
    expect(readerLocation.textNodeAtOffset(root, 'Hàn L'.length)?.node.textContent).toBe('Lập');
  });

  it('does not count stylesheet-hidden EPUB helper text in exact reader offsets', () => {
    const style = document.createElement('style');
    const root = document.createElement('p');
    style.textContent = '.reader-hidden-helper { display: none; } .reader-collapsed-helper { visibility: collapse; }';
    root.innerHTML = [
      'Hàn ',
      '<span class="reader-hidden-helper">ẩn một</span>',
      '<strong>Lập</strong>',
      '<span class="reader-collapsed-helper">ẩn hai</span>',
    ].join('');
    document.head.append(style);
    document.body.append(root);

    const strongText = root.querySelector('strong')?.firstChild;
    try {
      expect(readerLocation.textLength(root)).toBe('Hàn Lập'.length);
      expect(readerLocation.textNodeAtOffset(root, 'Hàn L'.length)?.node.textContent).toBe('Lập');
      expect(textOffsetWithinNode(root, strongText as Text, 1)).toBe('Hàn '.length + 1);
    } finally {
      root.remove();
      style.remove();
    }
  });

  it('does not count EPUB ruby annotation text in exact reader offsets', () => {
    const root = document.createElement('p');
    root.innerHTML = 'Hàn <ruby>筑基<rp>(</rp><rt>Trúc Cơ</rt><rp>)</rp></ruby> thành.';
    const annotationText = root.querySelector('rt')?.firstChild;

    expect(readerLocation.textLength(root)).toBe('Hàn 筑基 thành.'.length);
    expect(readerLocation.textNodeAtOffset(root, 'Hàn 筑'.length)?.node.textContent).toBe('筑基');
    expect(textOffsetWithinNode(root, annotationText as Text, 3)).toBe('Hàn 筑基'.length);
  });

  it('counts rich HTML line breaks as readable character offsets', () => {
    const root = document.createElement('p');
    root.innerHTML = 'Hàn<br>Lập';
    const secondLineText = root.childNodes[2];

    expect(readerLocation.textLength(root)).toBe('Hàn Lập'.length);
    expect(readerLocation.textNodeAtOffset(root, 'Hàn '.length)?.node.textContent).toBe('Lập');
    expect(textOffsetWithinNode(root, secondLineText, 1)).toBe('Hàn L'.length);
  });

  it('keeps aria-hidden mirror text when it is the only readable anchor', () => {
    const root = document.createElement('div');
    root.innerHTML = '<img alt=""><span aria-hidden="true">Bản đồ Thanh Vân</span>';

    expect(readerLocation.textLength(root)).toBe('Bản đồ Thanh Vân'.length);
    expect(readerLocation.textNodeAtOffset(root, 4)?.node.textContent).toBe('Bản đồ Thanh Vân');
  });

  it('measures exact text offsets inside nested inline reader DOM', () => {
    const paragraph = document.createElement('p');
    paragraph.innerHTML = 'Hàn <strong>Lập</strong> <em>khẽ</em> gật đầu.';

    const strongText = paragraph.querySelector('strong')?.firstChild;
    expect(strongText).toBeInstanceOf(Text);
    expect(textOffsetWithinNode(paragraph, strongText as Text, 2)).toBe('Hàn '.length + 2);

    const emphasis = paragraph.querySelector('em');
    expect(emphasis).toBeInstanceOf(HTMLElement);
    expect(textOffsetWithinNode(paragraph, emphasis as HTMLElement, 1)).toBe('Hàn Lập '.length + 'khẽ'.length);
  });

  it('resolves scroll progress from the exact viewport caret inside rich text', () => {
    const container = document.createElement('main');
    const firstBlock = document.createElement('div');
    const secondBlock = document.createElement('div');
    const paragraph = document.createElement('p');
    const blocks = ['Mở đầu', 'Hàn Lập khẽ gật đầu.'];
    const strongText = document.createTextNode('Lập');
    const strong = document.createElement('strong');

    firstBlock.className = 'reader-paragraph-block';
    firstBlock.dataset.paragraphIndex = '0';
    firstBlock.innerHTML = '<p class="reader-paragraph-text">Mở đầu</p>';
    secondBlock.className = 'reader-paragraph-block';
    secondBlock.dataset.paragraphIndex = '1';
    paragraph.className = 'reader-paragraph-text';
    paragraph.append('Hàn ');
    strong.append(strongText);
    paragraph.append(strong, ' khẽ gật đầu.');
    secondBlock.append(paragraph);
    container.append(firstBlock, secondBlock);
    document.body.appendChild(container);

    const rect = (top: number, bottom: number, left = 0, right = 320) => ({
      bottom,
      height: bottom - top,
      left,
      right,
      top,
      width: right - left,
      x: left,
      y: top,
      toJSON: () => ({}),
    }) as DOMRect;
    Object.defineProperty(container, 'getBoundingClientRect', { configurable: true, value: () => rect(100, 600) });
    Object.defineProperty(firstBlock, 'getBoundingClientRect', { configurable: true, value: () => rect(0, 80) });
    Object.defineProperty(secondBlock, 'getBoundingClientRect', { configurable: true, value: () => rect(100, 220) });
    Object.defineProperty(paragraph, 'getBoundingClientRect', { configurable: true, value: () => rect(104, 210, 24, 300) });
    Object.defineProperty(document, 'caretPositionFromPoint', {
      configurable: true,
      value: () => ({ offsetNode: strongText, offset: 2 }),
    });

    try {
      expect(readerTextLocationFromViewportAnchor(container, blocks)).toEqual({
        absoluteCharOffset: 'Mở đầu\n\nHàn Lậ'.length,
        charOffset: 'Hàn Lậ'.length,
        paragraphIndex: 1,
      });
    } finally {
      Reflect.deleteProperty(document, 'caretPositionFromPoint');
      container.remove();
    }
  });

  it('adds visible page slice offsets to exact viewport caret locations', () => {
    const container = document.createElement('main');
    const block = document.createElement('div');
    const paragraph = document.createElement('p');
    const visibleText = 'phần đang hiện trên trang';
    const blocks = ['x'.repeat(300) + visibleText + ' phần sau trang'];
    const visibleTextNode = document.createTextNode(visibleText);

    block.className = 'reader-paragraph-block';
    block.dataset.paragraphIndex = '0';
    block.dataset.charStart = '300';
    block.dataset.charEnd = String(300 + visibleText.length);
    paragraph.className = 'reader-paragraph-text';
    paragraph.append(visibleTextNode);
    block.append(paragraph);
    container.append(block);
    document.body.appendChild(container);

    const rect = (top: number, bottom: number, left = 0, right = 320) => ({
      bottom,
      height: bottom - top,
      left,
      right,
      top,
      width: right - left,
      x: left,
      y: top,
      toJSON: () => ({}),
    }) as DOMRect;
    Object.defineProperty(container, 'getBoundingClientRect', { configurable: true, value: () => rect(100, 600) });
    Object.defineProperty(block, 'getBoundingClientRect', { configurable: true, value: () => rect(100, 220) });
    Object.defineProperty(paragraph, 'getBoundingClientRect', { configurable: true, value: () => rect(104, 210, 24, 300) });
    Object.defineProperty(document, 'caretPositionFromPoint', {
      configurable: true,
      value: () => ({ offsetNode: visibleTextNode, offset: 12 }),
    });

    try {
      expect(readerTextLocationFromViewportAnchor(container, blocks)).toEqual({
        absoluteCharOffset: 312,
        charOffset: 312,
        paragraphIndex: 0,
      });
    } finally {
      Reflect.deleteProperty(document, 'caretPositionFromPoint');
      container.remove();
    }
  });

  it('ignores native caret ranges from a different reader block than the viewport anchor', () => {
    const container = document.createElement('main');
    const previousBlock = document.createElement('div');
    const previousParagraph = document.createElement('p');
    const nextBlock = document.createElement('div');
    const nextParagraph = document.createElement('p');
    const previousText = document.createTextNode('Đoạn trước đã qua.');
    const blocks = ['Đoạn trước đã qua.', 'Đoạn đang đọc.'];

    previousBlock.className = 'reader-paragraph-block';
    previousBlock.dataset.paragraphIndex = '0';
    previousParagraph.className = 'reader-paragraph-text';
    previousParagraph.append(previousText);
    previousBlock.append(previousParagraph);
    nextBlock.className = 'reader-paragraph-block';
    nextBlock.dataset.paragraphIndex = '1';
    nextParagraph.className = 'reader-paragraph-text';
    nextParagraph.textContent = blocks[1];
    nextBlock.append(nextParagraph);
    container.append(previousBlock, nextBlock);
    document.body.appendChild(container);

    const rect = (top: number, bottom: number, left = 0, right = 320) => ({
      bottom,
      height: bottom - top,
      left,
      right,
      top,
      width: right - left,
      x: left,
      y: top,
      toJSON: () => ({}),
    }) as DOMRect;
    const originalGetClientRects = Range.prototype.getClientRects;
    const originalGetBoundingClientRect = Range.prototype.getBoundingClientRect;
    const originalGetComputedStyle = window.getComputedStyle;
    Object.defineProperty(container, 'getBoundingClientRect', { configurable: true, value: () => rect(100, 600) });
    Object.defineProperty(previousBlock, 'getBoundingClientRect', { configurable: true, value: () => rect(0, 90) });
    Object.defineProperty(previousParagraph, 'getBoundingClientRect', { configurable: true, value: () => rect(8, 80, 24, 300) });
    Object.defineProperty(nextBlock, 'getBoundingClientRect', { configurable: true, value: () => rect(110, 210) });
    Object.defineProperty(nextParagraph, 'getBoundingClientRect', { configurable: true, value: () => rect(114, 190, 24, 300) });
    Object.defineProperty(nextParagraph, 'clientWidth', { configurable: true, value: 276 });
    Object.defineProperty(document, 'caretPositionFromPoint', {
      configurable: true,
      value: () => ({ offsetNode: previousText, offset: previousText.length }),
    });
    Object.defineProperty(Range.prototype, 'getClientRects', {
      configurable: true,
      value: () => [] as unknown as DOMRectList,
    });
    Object.defineProperty(Range.prototype, 'getBoundingClientRect', {
      configurable: true,
      value: () => rect(0, 0),
    });
    Object.defineProperty(window, 'getComputedStyle', {
      configurable: true,
      value: () => ({
        fontSize: '20px',
        lineHeight: '20px',
        paddingLeft: '0px',
        paddingRight: '0px',
      }) as CSSStyleDeclaration,
    });

    try {
      expect(readerTextLocationFromViewportAnchor(container, blocks, { anchorOffsetPx: 16 })).toEqual({
        absoluteCharOffset: `${blocks[0]}\n\n`.length,
        charOffset: 0,
        paragraphIndex: 1,
      });
    } finally {
      Reflect.deleteProperty(document, 'caretPositionFromPoint');
      Object.defineProperty(Range.prototype, 'getClientRects', {
        configurable: true,
        value: originalGetClientRects,
      });
      Object.defineProperty(Range.prototype, 'getBoundingClientRect', {
        configurable: true,
        value: originalGetBoundingClientRect,
      });
      Object.defineProperty(window, 'getComputedStyle', {
        configurable: true,
        value: originalGetComputedStyle,
      });
      container.remove();
    }
  });

  it('uses the next readable text block when the viewport anchor lands on image-only rich content', () => {
    const container = document.createElement('main');
    const firstBlock = document.createElement('div');
    const imageBlock = document.createElement('div');
    const imageWrapper = document.createElement('div');
    const image = document.createElement('img');
    const nextBlock = document.createElement('div');
    const nextParagraph = document.createElement('p');
    const blocks = ['Mở đầu', '', 'Sau bản đồ'];

    firstBlock.className = 'reader-paragraph-block';
    firstBlock.dataset.paragraphIndex = '0';
    firstBlock.innerHTML = '<p class="reader-paragraph-text">Mở đầu</p>';
    imageBlock.className = 'reader-paragraph-block reader-rich-block';
    imageBlock.dataset.paragraphIndex = '1';
    imageBlock.dataset.richKind = 'image';
    imageWrapper.className = 'reader-paragraph-text';
    image.src = '/book-assets/42/map.png';
    imageWrapper.append(image);
    imageBlock.append(imageWrapper);
    nextBlock.className = 'reader-paragraph-block';
    nextBlock.dataset.paragraphIndex = '2';
    nextParagraph.className = 'reader-paragraph-text';
    nextParagraph.textContent = 'Sau bản đồ';
    nextBlock.append(nextParagraph);
    container.append(firstBlock, imageBlock, nextBlock);
    document.body.appendChild(container);

    const rect = (top: number, bottom: number, left = 0, right = 320) => ({
      bottom,
      height: bottom - top,
      left,
      right,
      top,
      width: right - left,
      x: left,
      y: top,
      toJSON: () => ({}),
    }) as DOMRect;
    Object.defineProperty(container, 'getBoundingClientRect', { configurable: true, value: () => rect(100, 600) });
    Object.defineProperty(firstBlock, 'getBoundingClientRect', { configurable: true, value: () => rect(0, 80) });
    Object.defineProperty(imageBlock, 'getBoundingClientRect', { configurable: true, value: () => rect(100, 220) });
    Object.defineProperty(imageWrapper, 'getBoundingClientRect', { configurable: true, value: () => rect(100, 220, 24, 300) });
    Object.defineProperty(nextBlock, 'getBoundingClientRect', { configurable: true, value: () => rect(240, 320) });
    Object.defineProperty(nextParagraph, 'getBoundingClientRect', { configurable: true, value: () => rect(244, 300, 24, 300) });

    try {
      expect(readerTextLocationFromViewportAnchor(container, blocks, { anchorOffsetPx: 120 })).toEqual({
        absoluteCharOffset: 'Mở đầu\n\n\n\n'.length,
        charOffset: 0,
        paragraphIndex: 2,
      });
    } finally {
      container.remove();
    }
  });

  it('uses the next readable block when the previous block only touches the viewport edge', () => {
    const container = document.createElement('main');
    const previousBlock = document.createElement('div');
    const previousParagraph = document.createElement('p');
    const nextBlock = document.createElement('div');
    const nextParagraph = document.createElement('p');
    const blocks = ['Đoạn vừa khuất.', 'Đoạn đang hiện.'];

    previousBlock.className = 'reader-paragraph-block';
    previousBlock.dataset.paragraphIndex = '0';
    previousParagraph.className = 'reader-paragraph-text';
    previousParagraph.textContent = blocks[0];
    previousBlock.append(previousParagraph);
    nextBlock.className = 'reader-paragraph-block';
    nextBlock.dataset.paragraphIndex = '1';
    nextParagraph.className = 'reader-paragraph-text';
    nextParagraph.textContent = blocks[1];
    nextBlock.append(nextParagraph);
    container.append(previousBlock, nextBlock);
    document.body.appendChild(container);

    const rect = (top: number, bottom: number, left = 0, right = 320) => ({
      bottom,
      height: bottom - top,
      left,
      right,
      top,
      width: right - left,
      x: left,
      y: top,
      toJSON: () => ({}),
    }) as DOMRect;
    Object.defineProperty(container, 'getBoundingClientRect', { configurable: true, value: () => rect(200, 600) });
    Object.defineProperty(previousBlock, 'getBoundingClientRect', { configurable: true, value: () => rect(120, 200) });
    Object.defineProperty(previousParagraph, 'getBoundingClientRect', { configurable: true, value: () => rect(128, 196, 24, 300) });
    Object.defineProperty(nextBlock, 'getBoundingClientRect', { configurable: true, value: () => rect(224, 304) });
    Object.defineProperty(nextParagraph, 'getBoundingClientRect', { configurable: true, value: () => rect(232, 292, 24, 300) });

    try {
      expect(readerTextLocationFromViewportAnchor(container, blocks)).toEqual({
        absoluteCharOffset: `${blocks[0]}\n\n`.length,
        charOffset: 0,
        paragraphIndex: 1,
      });
    } finally {
      container.remove();
    }
  });

  it('uses the next readable block when the viewport anchor lands in the gap between paragraphs', () => {
    const container = document.createElement('main');
    const previousBlock = document.createElement('div');
    const previousParagraph = document.createElement('p');
    const nextBlock = document.createElement('div');
    const nextParagraph = document.createElement('p');
    const blocks = ['Đoạn trước.', 'Đoạn kế tiếp.'];

    previousBlock.className = 'reader-paragraph-block';
    previousBlock.dataset.paragraphIndex = '0';
    previousParagraph.className = 'reader-paragraph-text';
    previousParagraph.textContent = blocks[0];
    previousBlock.append(previousParagraph);
    nextBlock.className = 'reader-paragraph-block';
    nextBlock.dataset.paragraphIndex = '1';
    nextParagraph.className = 'reader-paragraph-text';
    nextParagraph.textContent = blocks[1];
    nextBlock.append(nextParagraph);
    container.append(previousBlock, nextBlock);
    document.body.appendChild(container);

    const rect = (top: number, bottom: number, left = 0, right = 320) => ({
      bottom,
      height: bottom - top,
      left,
      right,
      top,
      width: right - left,
      x: left,
      y: top,
      toJSON: () => ({}),
    }) as DOMRect;
    Object.defineProperty(container, 'getBoundingClientRect', { configurable: true, value: () => rect(100, 600) });
    Object.defineProperty(previousBlock, 'getBoundingClientRect', { configurable: true, value: () => rect(80, 108) });
    Object.defineProperty(previousParagraph, 'getBoundingClientRect', { configurable: true, value: () => rect(84, 104, 24, 300) });
    Object.defineProperty(nextBlock, 'getBoundingClientRect', { configurable: true, value: () => rect(132, 212) });
    Object.defineProperty(nextParagraph, 'getBoundingClientRect', { configurable: true, value: () => rect(136, 196, 24, 300) });

    try {
      expect(readerTextLocationFromViewportAnchor(container, blocks)).toEqual({
        absoluteCharOffset: `${blocks[0]}\n\n`.length,
        charOffset: 0,
        paragraphIndex: 1,
      });
    } finally {
      container.remove();
    }
  });

  it('finds exact text offsets from measured character range rectangles', () => {
    const paragraph = document.createElement('p');
    paragraph.textContent = 'abcdef';
    document.body.appendChild(paragraph);
    const originalGetClientRects = Range.prototype.getClientRects;
    const originalGetBoundingClientRect = Range.prototype.getBoundingClientRect;
    Object.defineProperty(Range.prototype, 'getClientRects', {
      configurable: true,
      value(this: Range) {
        const left = this.startOffset * 10;
        return [{
          bottom: 20,
          height: 20,
          left,
          right: left + 1,
          top: 0,
          width: 1,
          x: left,
          y: 0,
          toJSON: () => ({}),
        }] as unknown as DOMRectList;
      },
    });
    Object.defineProperty(Range.prototype, 'getBoundingClientRect', {
      configurable: true,
      value(this: Range) {
        const left = this.startOffset * 10;
        return {
          bottom: 20,
          height: 20,
          left,
          right: left + 1,
          top: 0,
          width: 1,
          x: left,
          y: 0,
          toJSON: () => ({}),
        } as DOMRect;
      },
    });

    try {
      expect(textOffsetFromPointInNode(paragraph, 26, 12)).toBe(3);
    } finally {
      Object.defineProperty(Range.prototype, 'getClientRects', {
        configurable: true,
        value: originalGetClientRects,
      });
      Object.defineProperty(Range.prototype, 'getBoundingClientRect', {
        configurable: true,
        value: originalGetBoundingClientRect,
      });
      paragraph.remove();
    }
  });

  it('prefers native caret positions over geometry estimates for text offsets', () => {
    const paragraph = document.createElement('p');
    const text = document.createTextNode('abcdefghijklmnopqrstuvwxyz');
    paragraph.append(text);
    document.body.appendChild(paragraph);
    const originalCaretPositionFromPoint = (document as Document & {
      caretPositionFromPoint?: (x: number, y: number) => { offsetNode: Node; offset: number } | null;
    }).caretPositionFromPoint;
    const originalGetClientRects = Range.prototype.getClientRects;
    const originalGetBoundingClientRect = Range.prototype.getBoundingClientRect;
    const originalGetComputedStyle = window.getComputedStyle;

    Object.defineProperty(document, 'caretPositionFromPoint', {
      configurable: true,
      value: () => ({ offsetNode: text, offset: 5 }),
    });
    Object.defineProperty(paragraph, 'getBoundingClientRect', {
      configurable: true,
      value: () => ({
        bottom: 120,
        height: 100,
        left: 20,
        right: 220,
        top: 20,
        width: 200,
        x: 20,
        y: 20,
        toJSON: () => ({}),
      }) as DOMRect,
    });
    Object.defineProperty(paragraph, 'clientWidth', { configurable: true, value: 200 });
    Object.defineProperty(Range.prototype, 'getClientRects', {
      configurable: true,
      value: () => [] as unknown as DOMRectList,
    });
    Object.defineProperty(Range.prototype, 'getBoundingClientRect', {
      configurable: true,
      value: () => ({
        bottom: 0,
        height: 0,
        left: 0,
        right: 0,
        top: 0,
        width: 0,
        x: 0,
        y: 0,
        toJSON: () => ({}),
      }) as DOMRect,
    });
    Object.defineProperty(window, 'getComputedStyle', {
      configurable: true,
      value: () => ({
        fontSize: '20px',
        lineHeight: '20px',
        paddingLeft: '0px',
        paddingRight: '0px',
      }) as CSSStyleDeclaration,
    });

    try {
      expect(textOffsetFromPointInNode(paragraph, 190, 32)).toBe(5);
    } finally {
      if (originalCaretPositionFromPoint) {
        Object.defineProperty(document, 'caretPositionFromPoint', {
          configurable: true,
          value: originalCaretPositionFromPoint,
        });
      } else {
        Reflect.deleteProperty(document, 'caretPositionFromPoint');
      }
      Object.defineProperty(Range.prototype, 'getClientRects', {
        configurable: true,
        value: originalGetClientRects,
      });
      Object.defineProperty(Range.prototype, 'getBoundingClientRect', {
        configurable: true,
        value: originalGetBoundingClientRect,
      });
      Object.defineProperty(window, 'getComputedStyle', {
        configurable: true,
        value: originalGetComputedStyle,
      });
      paragraph.remove();
    }
  });

  it('finds text offsets far from the start of a wrapped line', () => {
    const paragraph = document.createElement('p');
    paragraph.textContent = 'x'.repeat(600);
    document.body.appendChild(paragraph);
    const originalGetClientRects = Range.prototype.getClientRects;
    const originalGetBoundingClientRect = Range.prototype.getBoundingClientRect;
    const lineSize = 240;
    const lineHeight = 20;
    Object.defineProperty(Range.prototype, 'getClientRects', {
      configurable: true,
      value(this: Range) {
        const line = Math.floor(this.startOffset / lineSize);
        const column = this.startOffset % lineSize;
        const left = column * 10;
        const top = line * lineHeight;
        return [{
          bottom: top + lineHeight,
          height: lineHeight,
          left,
          right: left + 1,
          top,
          width: 1,
          x: left,
          y: top,
          toJSON: () => ({}),
        }] as unknown as DOMRectList;
      },
    });
    Object.defineProperty(Range.prototype, 'getBoundingClientRect', {
      configurable: true,
      value(this: Range) {
        const line = Math.floor(this.startOffset / lineSize);
        const column = this.startOffset % lineSize;
        const left = column * 10;
        const top = line * lineHeight;
        return {
          bottom: top + lineHeight,
          height: lineHeight,
          left,
          right: left + 1,
          top,
          width: 1,
          x: left,
          y: top,
          toJSON: () => ({}),
        } as DOMRect;
      },
    });

    try {
      expect(textOffsetFromPointInNode(paragraph, 1900, 32)).toBe(430);
    } finally {
      Object.defineProperty(Range.prototype, 'getClientRects', {
        configurable: true,
        value: originalGetClientRects,
      });
      Object.defineProperty(Range.prototype, 'getBoundingClientRect', {
        configurable: true,
        value: originalGetBoundingClientRect,
      });
      paragraph.remove();
    }
  });

  it('estimates text offsets from element geometry when browser range rectangles are unavailable', () => {
    const paragraph = document.createElement('p');
    paragraph.textContent = 'x'.repeat(120);
    document.body.appendChild(paragraph);
    const originalGetClientRects = Range.prototype.getClientRects;
    const originalGetBoundingClientRect = Range.prototype.getBoundingClientRect;
    const originalGetComputedStyle = window.getComputedStyle;

    Object.defineProperty(paragraph, 'getBoundingClientRect', {
      configurable: true,
      value: () => ({
        bottom: 140,
        height: 120,
        left: 20,
        right: 220,
        top: 20,
        width: 200,
        x: 20,
        y: 20,
        toJSON: () => ({}),
      }) as DOMRect,
    });
    Object.defineProperty(paragraph, 'clientWidth', { configurable: true, value: 200 });
    Object.defineProperty(Range.prototype, 'getClientRects', {
      configurable: true,
      value: () => [] as unknown as DOMRectList,
    });
    Object.defineProperty(Range.prototype, 'getBoundingClientRect', {
      configurable: true,
      value: () => ({
        bottom: 0,
        height: 0,
        left: 0,
        right: 0,
        top: 0,
        width: 0,
        x: 0,
        y: 0,
        toJSON: () => ({}),
      }) as DOMRect,
    });
    Object.defineProperty(window, 'getComputedStyle', {
      configurable: true,
      value: () => ({
        fontSize: '20px',
        lineHeight: '20px',
        paddingLeft: '0px',
        paddingRight: '0px',
      }) as CSSStyleDeclaration,
    });

    try {
      expect(textOffsetFromPointInNode(paragraph, 120, 72)).toBe(50);
    } finally {
      Object.defineProperty(Range.prototype, 'getClientRects', {
        configurable: true,
        value: originalGetClientRects,
      });
      Object.defineProperty(Range.prototype, 'getBoundingClientRect', {
        configurable: true,
        value: originalGetBoundingClientRect,
      });
      Object.defineProperty(window, 'getComputedStyle', {
        configurable: true,
        value: originalGetComputedStyle,
      });
      paragraph.remove();
    }
  });

  it('calculates whole-book progress from zero-based chapter index and chapter percent', () => {
    expect(bookProgressPercent({ chapterIndex: 1, chapterCount: 10, chapterPercent: 50 })).toBe(15);
    expect(bookProgressPercent({ chapterIndex: 0, chapterCount: 10, chapterPercent: 50 })).toBe(5);
    expect(bookProgressPercent({ chapterIndex: 9, chapterCount: 10, chapterPercent: 100 })).toBe(100);
  });

  it('counts words across Vietnamese and Chinese text', () => {
    expect(countWords('Hàn Lập khẽ gật đầu.')).toBe(5);
    expect(countWords('筑基成功')).toBe(4);
    expect(countWords('Hàn Lập 筑基 thành công.')).toBe(6);
  });

  it('estimates reading minutes and page index defensively', () => {
    expect(estimateReadingMinutes(0)).toBe(0);
    expect(estimateReadingMinutes(321, 320)).toBe(2);
    expect(pageForParagraph(7, 4)).toBe(1);
    expect(pageForParagraph(-1, 4)).toBe(0);
    expect(pageForParagraph(7, 0)).toBe(0);
  });

  it('builds fallback pages and maps paragraphs back to their page', () => {
    const pages = fallbackParagraphPages(9, 4);

    expect(pages).toEqual([
      { startIndex: 0, endIndex: 4 },
      { startIndex: 4, endIndex: 8 },
      { startIndex: 8, endIndex: 9 },
    ]);
    expect(pageIndexForParagraph(6, pages)).toBe(1);
    expect(pageIndexForParagraph(99, pages, 2)).toBe(2);
  });

  it('honors rich EPUB page-break and standalone hints in fallback pagination', () => {
    expect(fallbackParagraphPages(6, 4, [
      {},
      { pageBreakBefore: true },
      {},
      { pageBreakAfter: true },
      { preferStandalone: true },
      {},
    ])).toEqual([
      { startIndex: 0, endIndex: 1 },
      { startIndex: 1, endIndex: 4 },
      { startIndex: 4, endIndex: 5 },
      { startIndex: 5, endIndex: 6 },
    ]);
  });

  it('maps a paragraph character offset back to a split page', () => {
    const pages = [
      { startIndex: 0, endIndex: 1, startChar: 0, endChar: 300 },
      { startIndex: 0, endIndex: 1, startChar: 300, endChar: 600 },
      { startIndex: 0, endIndex: 1, startChar: 600, endChar: 900 },
    ];

    expect((pageIndexForParagraph as unknown as (
      paragraphIndex: number,
      pagesArg: Array<{ endChar: number; endIndex: number; startChar: number; startIndex: number }>,
      fallbackPageIndex: number,
      charOffset: number,
    ) => number)(0, pages, 0, 350)).toBe(1);
  });

  it('uses the saved fallback page to disambiguate split-page character boundaries', () => {
    const pages = [
      { startIndex: 0, endIndex: 1, startChar: 0, endChar: 300 },
      { startIndex: 0, endIndex: 1, startChar: 300, endChar: 600 },
      { startIndex: 0, endIndex: 1, startChar: 600, endChar: 900 },
    ];

    expect((pageIndexForParagraph as unknown as (
      paragraphIndex: number,
      pagesArg: Array<{ endChar: number; endIndex: number; startChar: number; startIndex: number }>,
      fallbackPageIndex: number,
      charOffset: number,
    ) => number)(0, pages, 0, 300)).toBe(0);
    expect((pageIndexForParagraph as unknown as (
      paragraphIndex: number,
      pagesArg: Array<{ endChar: number; endIndex: number; startChar: number; startIndex: number }>,
      fallbackPageIndex: number,
      charOffset: number,
    ) => number)(0, pages, 1, 300)).toBe(1);
  });

  it('paginates measured paragraphs by actual viewport height', () => {
    expect(paginateParagraphsByViewport([
      { index: 0, top: 0, bottom: 120 },
      { index: 1, top: 132, bottom: 250 },
      { index: 2, top: 262, bottom: 430 },
      { index: 3, top: 442, bottom: 520 },
    ], 300)).toEqual([
      { startIndex: 0, endIndex: 2 },
      { startIndex: 2, endIndex: 4 },
    ]);
  });

  it('keeps large rich media blocks on standalone pages', () => {
    expect(paginateParagraphsByViewport([
      { index: 0, top: 0, bottom: 120 },
      { index: 1, top: 132, bottom: 360, preferStandalone: true },
      { index: 2, top: 372, bottom: 460 },
    ], 500)).toEqual([
      { startIndex: 0, endIndex: 1 },
      { startIndex: 1, endIndex: 2 },
      { startIndex: 2, endIndex: 3 },
    ]);
  });

  it('honors explicit page break hints from EPUB rich blocks', () => {
    expect(paginateParagraphsByViewport([
      { index: 0, top: 0, bottom: 90 },
      { index: 1, top: 100, bottom: 190, pageBreakBefore: true },
      { index: 2, top: 200, bottom: 290, pageBreakAfter: true },
      { index: 3, top: 300, bottom: 390 },
    ], 500)).toEqual([
      { startIndex: 0, endIndex: 1 },
      { startIndex: 1, endIndex: 3 },
      { startIndex: 3, endIndex: 4 },
    ]);
  });

  it('splits oversized measured text blocks into character-ranged pages', () => {
    expect(paginateParagraphsByViewport([
      { index: 0, top: 0, bottom: 900, charLength: 900 },
      { index: 1, top: 912, bottom: 1000, charLength: 88 },
    ], 300)).toEqual([
      { startIndex: 0, endIndex: 1, startChar: 0, endChar: 300 },
      { startIndex: 0, endIndex: 1, startChar: 300, endChar: 600 },
      { startIndex: 0, endIndex: 1, startChar: 600, endChar: 900 },
      { startIndex: 1, endIndex: 2 },
    ]);
  });

  it('uses measured character page breaks for oversized rich text blocks', () => {
    expect(paginateParagraphsByViewport([
      { index: 0, top: 0, bottom: 900, charLength: 900, pageBreakOffsets: [180, 420] },
    ], 300)).toEqual([
      { startIndex: 0, endIndex: 1, startChar: 0, endChar: 180 },
      { startIndex: 0, endIndex: 1, startChar: 180, endChar: 420 },
      { startIndex: 0, endIndex: 1, startChar: 420, endChar: 900 },
    ]);
  });

  it('splits oversized keep-together text blocks when they cannot fit the viewport', () => {
    expect(paginateParagraphsByViewport([
      { index: 0, top: 0, bottom: 120, charLength: 120 },
      {
        index: 1,
        top: 132,
        bottom: 1032,
        charLength: 900,
        pageBreakOffsets: [240, 520],
        preferStandalone: true,
      },
      { index: 2, top: 1044, bottom: 1120, charLength: 76 },
    ], 300)).toEqual([
      { startIndex: 0, endIndex: 1 },
      { startIndex: 1, endIndex: 2, startChar: 0, endChar: 240 },
      { startIndex: 1, endIndex: 2, startChar: 240, endChar: 520 },
      { startIndex: 1, endIndex: 2, startChar: 520, endChar: 900 },
      { startIndex: 2, endIndex: 3 },
    ]);
  });

  it('keeps oversized unsplittable rich media blocks on one standalone page', () => {
    expect(paginateParagraphsByViewport([
      { index: 0, top: 0, bottom: 120, charLength: 120 },
      {
        canSplit: false,
        charLength: 240,
        index: 1,
        preferStandalone: true,
        top: 132,
        bottom: 1032,
      },
      { index: 2, top: 1044, bottom: 1120, charLength: 76 },
    ], 300)).toEqual([
      { startIndex: 0, endIndex: 1 },
      { startIndex: 1, endIndex: 2 },
      { startIndex: 2, endIndex: 3 },
    ]);
  });

  it('measures character page breaks from rendered range rectangles', () => {
    const paragraph = document.createElement('p');
    paragraph.textContent = 'abcdefghijklmnopqrstuvwx';
    document.body.appendChild(paragraph);
    const originalGetClientRects = Range.prototype.getClientRects;
    const originalGetBoundingClientRect = Range.prototype.getBoundingClientRect;
    const lineSize = 8;
    const lineHeight = 40;

    Object.defineProperty(paragraph, 'getBoundingClientRect', {
      configurable: true,
      value: () => ({
        bottom: 120,
        height: 120,
        left: 20,
        right: 220,
        top: 0,
        width: 200,
        x: 20,
        y: 0,
        toJSON: () => ({}),
      }) as DOMRect,
    });
    Object.defineProperty(Range.prototype, 'getClientRects', {
      configurable: true,
      value(this: Range) {
        const line = Math.floor(this.startOffset / lineSize);
        const column = this.startOffset % lineSize;
        const left = 20 + column * 10;
        const top = line * lineHeight;
        return [{
          bottom: top + lineHeight,
          height: lineHeight,
          left,
          right: left + 1,
          top,
          width: 1,
          x: left,
          y: top,
          toJSON: () => ({}),
        }] as unknown as DOMRectList;
      },
    });
    Object.defineProperty(Range.prototype, 'getBoundingClientRect', {
      configurable: true,
      value(this: Range) {
        const line = Math.floor(this.startOffset / lineSize);
        const column = this.startOffset % lineSize;
        const left = 20 + column * 10;
        const top = line * lineHeight;
        return {
          bottom: top + lineHeight,
          height: lineHeight,
          left,
          right: left + 1,
          top,
          width: 1,
          x: left,
          y: top,
          toJSON: () => ({}),
        } as DOMRect;
      },
    });

    try {
      const helper = (readerLocation as {
        pageBreakOffsetsForViewportSlices?: (root: Node, viewportHeight: number) => number[];
      }).pageBreakOffsetsForViewportSlices;
      expect(helper?.(paragraph, 40)).toEqual([8, 16]);
    } finally {
      Object.defineProperty(Range.prototype, 'getClientRects', {
        configurable: true,
        value: originalGetClientRects,
      });
      Object.defineProperty(Range.prototype, 'getBoundingClientRect', {
        configurable: true,
        value: originalGetBoundingClientRect,
      });
      paragraph.remove();
    }
  });

  it('calculates words and time remaining from chapter progress', () => {
    expect(wordsRemainingForProgress(1000, 52)).toBe(480);
    expect(wordsRemainingForProgress(1000, 100)).toBe(0);
    expect(wordsRemainingForProgress(1000, -10)).toBe(1000);
    expect(readingStatsForText('một hai ba bốn', 50, 2)).toEqual({
      estimatedMinutes: 2,
      estimatedMinutesRemaining: 1,
      remainingWords: 2,
      totalWords: 4,
    });
  });
});
