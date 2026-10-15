import type { Chapter, GlossaryTermUpdate } from '../api/types';
import type { AppWorkflowOptions } from './appWorkflow';
import { isAuthError } from './appWorkflow';
import { formatError } from './types';
import type { useGlossary } from './useGlossary';
import type { useLibrary } from './useLibrary';
import type { useLibraryCatalog } from './useLibraryCatalog';
import type { useProviders } from './useProviders';
import type { NormalizedQaIssue } from './useQa';
import type { useReaderChapterData } from './useReaderChapterData';
import type { useStyleProfiles } from './useStyleProfiles';

export function useWorkbenchActions({ setBackendError, handleJobError, expireSession,
  chapterText, selectedChapter, library, providersState, styleState, glossaryState,
  rawBacklogChapters, loadRawBacklog }:
  Pick<AppWorkflowOptions, 'setBackendError' | 'handleJobError' | 'expireSession'> &
  Pick<ReturnType<typeof useLibraryCatalog>, 'rawBacklogChapters' | 'loadRawBacklog'> & {
    chapterText: ReturnType<typeof useReaderChapterData>['text'];
    selectedChapter: Chapter | null;
    library: ReturnType<typeof useLibrary>;
    providersState: ReturnType<typeof useProviders>;
    styleState: ReturnType<typeof useStyleProfiles>;
    glossaryState: ReturnType<typeof useGlossary>;
  }) {
  function handleApplyQaFix(issue: NormalizedQaIssue): void {
    const suggestedFix = issue.suggestedFix?.trim();
    if (!suggestedFix) return;

    const segment = issue.segment?.trim();
    chapterText.setTranslationText((current) => {
      if (segment && current.includes(segment)) {
        return current.replace(segment, suggestedFix);
      }

      return current ? `${current}\n\n${suggestedFix}` : suggestedFix;
    });
  }

  async function handleSearchTm(query: string): Promise<void> {
    setBackendError('');
    try {
      await glossaryState.searchTranslationMemory(query);
    } catch (error) {
      handleJobError(error, 'TM search failed');
    }
  }

  async function handleStyleProfileChange(styleProfileId: string): Promise<void> {
    styleState.setSelectedStyleProfileId(styleProfileId);
    setBackendError('');

    try {
      await styleState.setDefaultProfile(styleProfileId);
    } catch (error) {
      if (isAuthError(error)) {
        expireSession();
      } else {
        setBackendError(`Style profile update failed: ${formatError(error)}`);
      }
    }
  }

  async function handleGlossaryTermUpdate(termId: number, updates: GlossaryTermUpdate): Promise<void> {
    setBackendError('');

    try {
      await glossaryState.updateTerm(termId, updates);
    } catch (error) {
      handleJobError(error, 'Glossary update failed');
    }
  }

  async function handleGlossaryLockToggle(termId: number, locked: boolean): Promise<void> {
    setBackendError('');

    try {
      await glossaryState.toggleLock(termId, locked);
    } catch (error) {
      handleJobError(error, 'Glossary lock update failed');
    }
  }

  async function handleGlossaryApprove(termId: number): Promise<void> {
    setBackendError('');

    try {
      await glossaryState.approveTerm(termId);
    } catch (error) {
      handleJobError(error, 'Glossary approve failed');
    }
  }

  async function handleGlossaryReject(termId: number): Promise<void> {
    setBackendError('');

    try {
      await glossaryState.rejectTerm(termId);
    } catch (error) {
      handleJobError(error, 'Glossary reject failed');
    }
  }

  async function handleGlossarySaveAndApprove(
    termId: number,
    updates: GlossaryTermUpdate,
    locked: boolean,
  ): Promise<void> {
    setBackendError('');

    try {
      await glossaryState.saveAndApproveTerm(termId, updates, locked);
    } catch (error) {
      handleJobError(error, 'Glossary review failed');
    }
  }

  async function handleTestProvider(providerId: string): Promise<void> {
    setBackendError('');

    try {
      await providersState.testProvider(providerId);
    } catch (error) {
      handleJobError(error, 'Provider test failed');
    }
  }

  async function handleSaveProviderKey(providerId: string, apiKey: string): Promise<void> {
    setBackendError('');

    try {
      await providersState.saveProviderKey(providerId, apiKey);
    } catch (error) {
      handleJobError(error, 'Provider key save failed');
      throw error;
    }
  }

  async function handleSaveTranslation(text: string): Promise<void> {
    if (!selectedChapter) return;

    setBackendError('');
    try {
      await chapterText.save(text);
      await library.refreshChapters(selectedChapter.book_id);
      if (rawBacklogChapters.state !== 'idle') {
        await loadRawBacklog();
      }
    } catch (error) {
      handleJobError(error, 'Save translation failed');
    }
  }

  return {
    handleApplyQaFix, handleSearchTm, handleStyleProfileChange, handleGlossaryTermUpdate,
    handleGlossaryLockToggle, handleGlossaryApprove, handleGlossaryReject,
    handleGlossarySaveAndApprove, handleTestProvider, handleSaveProviderKey, handleSaveTranslation,
  };
}
