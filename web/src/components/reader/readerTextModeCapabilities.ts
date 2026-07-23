import type { ReaderTextMode } from './types';

export type ReaderTextResources = {
  contentHtml: string;
  sourceText: string;
  translationText: string;
};

export type ReaderTextModeCapabilities = {
  rawAvailable: boolean;
  rawCollapsedAvailable: boolean;
  splitAvailable: boolean;
  translationAvailable: boolean;
};

/**
 * Derive the content-mode contract from one canonical chapter resource set.
 * Rich EPUB HTML is translated content even when its plain-text projection is
 * empty; source availability is intentionally independent.
 */
export function deriveReaderTextModeCapabilities(
  resources: ReaderTextResources,
): ReaderTextModeCapabilities {
  const rawAvailable = resources.sourceText.trim().length > 0;
  const translationAvailable = resources.translationText.trim().length > 0
    || resources.contentHtml.trim().length > 0;
  const parallelContentAvailable = rawAvailable && translationAvailable;
  return {
    rawAvailable,
    rawCollapsedAvailable: parallelContentAvailable,
    splitAvailable: parallelContentAvailable,
    translationAvailable,
  };
}

/**
 * Resolve a persisted/selected mode without reading storage or mutating UI
 * state. The ordering exactly preserves the Reader's established fallback:
 * prefer translation when it exists, otherwise raw, otherwise translation.
 */
export function resolveReaderTextMode(
  mode: ReaderTextMode,
  capabilities: ReaderTextModeCapabilities,
): ReaderTextMode {
  if (mode === 'raw' && !capabilities.rawAvailable) return 'translation';
  if ((mode === 'split' || mode === 'raw-collapsed') && !capabilities.splitAvailable) {
    if (capabilities.translationAvailable) return 'translation';
    if (capabilities.rawAvailable) return 'raw';
    return 'translation';
  }
  if ((mode === 'translation' || mode === 'qa-overlay')
    && !capabilities.translationAvailable
    && capabilities.rawAvailable) {
    return 'raw';
  }
  return mode;
}
