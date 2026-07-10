import { describe, expect, it } from 'vitest';
import { buildReaderProgressTextAnchor, resolveReaderProgressTextAnchor } from './readerProgressAnchor';

describe('readerProgressAnchor', () => {
  it('restores the same character when text was inserted before the saved location', () => {
    const originalBlocks = [
      'Lục ca khẽ gật đầu.',
      'Nàng thu kiếm, chậm rãi bước qua thềm đá.',
      'Gió đêm lặng xuống.',
    ];
    const shiftedBlocks = [
      'Đoạn mới được biên tập thêm ở đầu chương.',
      ...originalBlocks,
    ];
    const charOffset = 'Nàng thu kiếm, '.length;
    const anchor = buildReaderProgressTextAnchor(originalBlocks, 1, charOffset);

    expect(resolveReaderProgressTextAnchor(shiftedBlocks, {
      absoluteCharOffset: originalBlocks[0].length + 2 + charOffset,
      anchor,
      charOffset,
      paragraphIndex: 1,
    })).toEqual({
      absoluteCharOffset: shiftedBlocks[0].length + 2 + originalBlocks[0].length + 2 + charOffset,
      charOffset,
      paragraphIndex: 2,
    });
  });

  it('falls back to the saved absolute offset when the text anchor is unavailable', () => {
    expect(resolveReaderProgressTextAnchor(['Một', 'Hai'], {
      absoluteCharOffset: 5,
      charOffset: 0,
      paragraphIndex: 1,
    })).toEqual({
      absoluteCharOffset: 5,
      charOffset: 0,
      paragraphIndex: 1,
    });
  });

  it('prefers matching text context over a stale absolute offset when repeated text exists', () => {
    const shiftedBlocks = [
      'Hàn Lập ngồi xuống bên suối.',
      'Một đoạn mới chen vào khiến offset cũ trỏ nhầm.',
      'Lục ca nói Hàn Lập khẽ gật đầu rồi bước qua thềm đá.',
    ];
    const targetCharOffset = 'Lục ca nói '.length;
    const targetAbsoluteOffset = shiftedBlocks[0].length + 2 + shiftedBlocks[1].length + 2 + targetCharOffset;

    expect(resolveReaderProgressTextAnchor(shiftedBlocks, {
      absoluteCharOffset: 0,
      anchor: {
        offset: 0,
        prefix: 'Lục ca nói ',
        suffix: ' khẽ gật đầu',
        text: 'Hàn Lập',
        version: 1,
      },
      charOffset: 0,
      paragraphIndex: 0,
    })).toEqual({
      absoluteCharOffset: targetAbsoluteOffset,
      charOffset: targetCharOffset,
      paragraphIndex: 2,
    });
  });
});
