import { useCallback, useEffect, useState } from 'react';
import type {
  SourceAdapterCandidate,
  SourceAdapterCandidateList,
  SourceCapability,
  SourceCatalogHealthResult,
  SourceCatalogQuery
} from '../api/types';
import type { WorkflowView } from '../components/WorkflowShell';
import { isAuthError, type AppWorkflowOptions } from './appWorkflow';
import { formatError, type LoadState } from './types';

export function useSourceManagement({ session, expireSession, activeView }:
  Pick<AppWorkflowOptions, 'session' | 'expireSession'> & { activeView: WorkflowView }) {
  const [sourceCapabilities, setSourceCapabilities] = useState<SourceCapability[]>([]);
  const [sourceCapabilitiesState, setSourceCapabilitiesState] = useState<LoadState>('idle');
  const [sourceCapabilitiesError, setSourceCapabilitiesError] = useState('');
  const loadSourceCapabilities = useCallback(async (): Promise<void> => {
    if (!session.isAuthenticated || sourceCapabilitiesState === 'loading') return;

    setSourceCapabilitiesError('');
    setSourceCapabilitiesState('loading');
    try {
      const sources = await session.client.getImportSources();
      setSourceCapabilities(sources);
      setSourceCapabilitiesState(sources.length > 0 ? 'ready' : 'empty');
    } catch (error) {
      if (isAuthError(error)) {
        expireSession();
        return;
      }
      setSourceCapabilitiesError(formatError(error));
      setSourceCapabilitiesState('error');
    }
  }, [expireSession, session.client, session.isAuthenticated, sourceCapabilitiesState]);

  const loadSourceCatalog = useCallback(
    (params: SourceCatalogQuery) => session.client.getSourceCatalog(params),
    [session.client],
  );

  const checkSourceCatalogEntry = useCallback(
    (entryId: string): Promise<SourceCatalogHealthResult> => session.client.checkSourceCatalogEntry(entryId),
    [session.client],
  );

  const loadSourceAdapterCandidates = useCallback(
    (): Promise<SourceAdapterCandidateList> => session.client.getSourceAdapterCandidates(),
    [session.client],
  );

  const createSourceAdapterCandidate = useCallback(
    (entryId: string): Promise<SourceAdapterCandidate> => session.client.createSourceAdapterCandidate(entryId),
    [session.client],
  );

  const importManagedSources = useCallback(
    (entryIds: string[]) => session.client.importManagedSources(entryIds),
    [session.client],
  );

  const testManagedSource = useCallback(
    (sourceId: string) => session.client.testManagedSource(sourceId),
    [session.client],
  );

  const verifyManagedSource = useCallback(
    (sourceId: string) => session.client.verifyManagedSource(sourceId),
    [session.client],
  );

  const setManagedSourceStatus = useCallback(
    (sourceId: string, status: 'BROKEN' | 'BLOCKED' | 'NEEDS_REVIEW') => session.client.setManagedSourceStatus(sourceId, status),
    [session.client],
  );

  useEffect(() => {
    if (activeView !== 'sources' || sourceCapabilitiesState !== 'idle') return;
    void loadSourceCapabilities();
  }, [activeView, loadSourceCapabilities, sourceCapabilitiesState]);

  return {
    sourceCapabilities, sourceCapabilitiesState, sourceCapabilitiesError, loadSourceCapabilities,
    loadSourceCatalog, checkSourceCatalogEntry, loadSourceAdapterCandidates, createSourceAdapterCandidate,
    importManagedSources, testManagedSource, verifyManagedSource, setManagedSourceStatus,
  };
}
