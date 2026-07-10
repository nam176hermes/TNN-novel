import { describe, expect, it } from 'vitest';
import { detectImportMetadata } from './importMetadata';

describe('detectImportMetadata', () => {
  it('parses large Chinese chapter numbers', () => {
    expect(
      detectImportMetadata({
        text: '《凡人修仙传》\n第一百二十三章 云涌\n张铁睁开双眼。',
      }),
    ).toMatchObject({
      title: '凡人修仙传',
      chapterNumber: 123,
      chapterTitle: '云涌',
    });
  });
});
