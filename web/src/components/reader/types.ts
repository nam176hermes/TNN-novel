export type ReaderTheme = 'light' | 'dark' | 'sepia' | 'eink';
export type ReaderWidth = 'narrow' | 'medium' | 'wide';
export type ReaderFontFamily = 'serif' | 'sans';
export type ReaderMode = 'scroll' | 'paginated';
export type ReaderTextMode = 'translation' | 'raw' | 'split' | 'raw-collapsed' | 'qa-overlay';

export type ReaderSettings = {
  characterSpacing: number;
  fontFamily: ReaderFontFamily;
  fontSize: number;
  fontWeight: number;
  fullscreen: boolean;
  lineHeight: number;
  marginScale: number;
  paragraphSpacing: number;
  readingMode: ReaderMode;
  instantMode: boolean;
  theme: ReaderTheme;
  width: ReaderWidth;
};

export type ReaderSelectionState = {
  anchor: { left: number; top: number };
  charEnd: number;
  charStart: number;
  contextAfter: string;
  contextBefore: string;
  paragraphIndex: number;
  text: string;
};
