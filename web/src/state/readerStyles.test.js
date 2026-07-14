import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { readStyleSources } from '../test/readStyleSources';

const readerStyles = readStyleSources(resolve(__dirname, '../styles.css'));

describe('reader paginated rich media styles', () => {
  it('constrains rich images and complex EPUB blocks to the paginated viewport', () => {
    expect(readerStyles).toContain('.reader-page-content[data-reading-mode="paginated"] .reader-rich-block img');
    expect(readerStyles).toContain('max-height: min(58dvh, calc(100dvh - 240px), 620px);');
    expect(readerStyles).toContain('.reader-page-content[data-reading-mode="paginated"] .reader-rich-block :is(table, pre)');
    expect(readerStyles).toContain('max-height: min(52dvh, calc(100dvh - 280px), 560px);');
  });
});
