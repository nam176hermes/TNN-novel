import { describe, expect, it } from 'vitest';
import type { ReaderTextMode } from './types';
import {
  deriveReaderTextModeCapabilities,
  resolveReaderTextMode,
} from './readerTextModeCapabilities';

const allModes: ReaderTextMode[] = ['translation', 'raw', 'split', 'raw-collapsed', 'qa-overlay'];

describe('readerTextModeCapabilities', () => {
  it('keeps every mode available when the chapter has source and translation', () => {
    const capabilities = deriveReaderTextModeCapabilities({
      contentHtml: '',
      sourceText: '原文。',
      translationText: 'Bản dịch.',
    });

    expect(capabilities).toEqual({
      rawAvailable: true,
      rawCollapsedAvailable: true,
      splitAvailable: true,
      translationAvailable: true,
    });
    expect(allModes.map((mode) => resolveReaderTextMode(mode, capabilities))).toEqual(allModes);
  });

  it('falls translation-dependent modes back to raw for a source-only chapter', () => {
    const capabilities = deriveReaderTextModeCapabilities({
      contentHtml: '   ',
      sourceText: '原文。',
      translationText: '\n',
    });

    expect(capabilities).toEqual({
      rawAvailable: true,
      rawCollapsedAvailable: false,
      splitAvailable: false,
      translationAvailable: false,
    });
    expect(allModes.map((mode) => resolveReaderTextMode(mode, capabilities))).toEqual([
      'raw',
      'raw',
      'raw',
      'raw',
      'raw',
    ]);
  });

  it('falls source-dependent modes back to translation for a translation-only chapter', () => {
    const capabilities = deriveReaderTextModeCapabilities({
      contentHtml: '',
      sourceText: '',
      translationText: 'Bản dịch.',
    });

    expect(capabilities).toEqual({
      rawAvailable: false,
      rawCollapsedAvailable: false,
      splitAvailable: false,
      translationAvailable: true,
    });
    expect(allModes.map((mode) => resolveReaderTextMode(mode, capabilities))).toEqual([
      'translation',
      'translation',
      'translation',
      'translation',
      'qa-overlay',
    ]);
  });

  it('treats rich HTML as translated content without duplicating source capability', () => {
    const capabilities = deriveReaderTextModeCapabilities({
      contentHtml: '<p>Bản dịch EPUB.</p>',
      sourceText: '',
      translationText: '',
    });

    expect(capabilities.translationAvailable).toBe(true);
    expect(capabilities.rawAvailable).toBe(false);
    expect(resolveReaderTextMode('split', capabilities)).toBe('translation');
  });

  it('preserves the existing empty-chapter fallback contract', () => {
    const capabilities = deriveReaderTextModeCapabilities({
      contentHtml: '',
      sourceText: ' ',
      translationText: '\n',
    });

    expect(capabilities).toEqual({
      rawAvailable: false,
      rawCollapsedAvailable: false,
      splitAvailable: false,
      translationAvailable: false,
    });
    expect(resolveReaderTextMode('raw', capabilities)).toBe('translation');
    expect(resolveReaderTextMode('split', capabilities)).toBe('translation');
    expect(resolveReaderTextMode('raw-collapsed', capabilities)).toBe('translation');
    expect(resolveReaderTextMode('translation', capabilities)).toBe('translation');
    expect(resolveReaderTextMode('qa-overlay', capabilities)).toBe('qa-overlay');
  });
});
