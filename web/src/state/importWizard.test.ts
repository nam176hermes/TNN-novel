import { describe, expect, it } from 'vitest';
import {
  buildImportPreview,
  cleanImportedText,
  detectImportChapters,
  detectImportContentKind,
} from './importWizard';

describe('importWizard helpers', () => {
  it('detects Chinese and Vietnamese chapter headings with stable chapter metadata', () => {
    const chapters = detectImportChapters(
      '第十章 蛰伏\n天色已晚。\n\nChương 11: Gió nổi\nBản dịch tiếng Việt.',
    );

    expect(chapters).toEqual([
      expect.objectContaining({ chapterNumber: 10, title: '蛰伏', startLine: 0 }),
      expect.objectContaining({ chapterNumber: 11, title: 'Gió nổi', startLine: 3 }),
    ]);
  });

  it('falls back to one manually editable chapter when no heading is detected', () => {
    const chapters = detectImportChapters('Một đoạn văn không có heading rõ ràng.');

    expect(chapters).toHaveLength(1);
    expect(chapters[0]).toMatchObject({
      chapterNumber: 1,
      title: 'Toàn bộ nội dung',
      detection: 'fallback',
    });
  });

  it('classifies raw Chinese, Vietnamese translation, both, and unknown content', () => {
    expect(detectImportContentKind('第十章 蛰伏\n天色已晚。')).toBe('raw');
    expect(detectImportContentKind('Chương 10\nTrời đã tối, hắn bước vào thành.')).toBe('translated');
    expect(detectImportContentKind('第十章 蛰伏\n天色已晚。\n\nBản dịch: Trời đã tối.')).toBe('both');
    expect(detectImportContentKind('... --- ...')).toBe('unknown');
  });

  it('cleans obvious ads, watermarks, and spacing without deleting body text', () => {
    const cleaned = cleanImportedText('  Đọc truyện tại 69shu.com\n\nNội dung chính.\r\n\r\n\r\nNguồn: qidian.com  ');

    expect(cleaned).toBe('Nội dung chính.');
  });

  it('builds preview warnings for duplicate chapters, short content, and language mismatch', () => {
    const preview = buildImportPreview({
      text: 'Chương 1\nXin chào.\n\nChương 1\nXin chào.',
      selectedKind: 'raw',
      existingChapters: [{ chapter_number: 1, title: 'Cũ' }],
    });

    expect(preview.chapterCount).toBe(2);
    expect(preview.duplicateChapterNumbers).toEqual([1]);
    expect(preview.warnings.map((warning) => warning.type)).toEqual(
      expect.arrayContaining(['duplicate_chapter', 'too_short', 'language_mismatch']),
    );
  });

  it('handles many detected chapters without collapsing metadata', () => {
    const text = Array.from({ length: 120 }, (_, index) => `第${index + 1}章 标题${index + 1}\n少年继续前行。`).join('\n\n');
    const preview = buildImportPreview({ text, selectedKind: 'raw' });

    expect(preview.chapterCount).toBe(120);
    expect(preview.firstTitle).toBe('标题1');
    expect(preview.lastTitle).toBe('标题120');
    expect(preview.warnings.map((warning) => warning.type)).not.toContain('long_single_chapter');
  });

  it('warns before committing an extremely long single chapter', () => {
    const preview = buildImportPreview({
      text: 'Không có heading rõ ràng.\n' + 'Nội dung rất dài. '.repeat(6000),
      selectedKind: 'translated',
    });

    expect(preview.chapterCount).toBe(1);
    expect(preview.warnings.map((warning) => warning.type)).toContain('long_single_chapter');
  });
});
