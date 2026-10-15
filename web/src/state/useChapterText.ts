import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, type ApiClient } from '../api/client';
import type { Chapter } from '../api/types';
import {
  cacheReaderAssetsFromHtml,
  getCachedChapterAsync,
  hasCachedChapterAsync,
  hydrateCachedReaderAssetUrls,
  putCachedChapterAsync,
  removeCachedChapterAsync,
  readerChapterRevision,
} from './readerCache';
import { formatError, type LoadState } from './types';

export type ChapterTextPrefetchTarget = Pick<Chapter, 'book_id' | 'content_html_path' | 'id' | 'content_revision'>;

export type UseChapterTextOptions = {
  cacheOwnership?: 'external' | 'internal';
  sourceEnabled?: boolean;
};

function readerHtmlAssetBase(contentHtmlPath?: string | null): string | undefined {
  const path = contentHtmlPath?.trim() ?? '';
  if (!path) return undefined;
  if (/^https?:\/\//i.test(path) || path.startsWith('/book-assets/')) return path;
  return undefined;
}

function chapterRequestKey(chapter: ChapterTextPrefetchTarget): string {
  return `${chapter.book_id}:${chapter.id}:${readerChapterRevision(chapter)}`;
}

export function useChapterText(
  client: ApiClient,
  enabled: boolean,
  chapter: Chapter | null,
  onAuthError?: () => void,
  prefetchTargets: ChapterTextPrefetchTarget[] = [],
  { cacheOwnership = 'internal', sourceEnabled = cacheOwnership === 'internal' }: UseChapterTextOptions = {},
) {
  const chapterId = chapter?.id ?? null;
  const bookId = chapter?.book_id ?? null;
  const contentHtmlPath = chapter?.content_html_path ?? null;
  const contentRevision = chapter?.content_revision;

  const [sourceText, setSourceText] = useState('');
  const [translationText, setTranslationText] = useState('');
  const [savedTranslationText, setSavedTranslationText] = useState('');
  const [contentHtml, setContentHtml] = useState('');
  const [state, setState] = useState<LoadState>('idle');
  const [error, setError] = useState('');
  const [sourceError, setSourceError] = useState('');
  const [sourceState, setSourceState] = useState<LoadState>('idle');
  const [translatedTitle, setTranslatedTitle] = useState(chapter?.translated_title ?? '');
  const [savedTranslatedTitle, setSavedTranslatedTitle] = useState(chapter?.translated_title ?? '');
  const sourceRequestRef = useRef<{key: string; controller: AbortController; promise: Promise<void>} | null>(null);
  const sourceGenerationRef = useRef(0);
  const sourceResolvedGenerationRef = useRef(-1);
  const loadRequestIdRef = useRef(0);
  const contentRevisionRef = useRef<number | undefined>(undefined);
  const activeLoadRef = useRef<{
    controller: AbortController;
    key: string;
    promise: Promise<void>;
  } | null>(null);
  const prefetchControllersRef = useRef(new Map<string, AbortController>());

  const cacheChapter = useCallback((
    targetChapter: ChapterTextPrefetchTarget,
    text: string,
    html: string,
    sourceTextValue: string,
    revision?: number,
  ) => {
    if (!text.trim() && !html.trim()) {
      void removeCachedChapterAsync(targetChapter.book_id, targetChapter.id);
      return;
    }
    void putCachedChapterAsync({
      bookId: targetChapter.book_id,
      chapterId: targetChapter.id,
      contentRevision: readerChapterRevision({...targetChapter, content_revision: revision ?? targetChapter.content_revision}),
      html,
      sourceText: sourceTextValue,
      text,
    });
  }, []);

  const reset = useCallback(() => {
    loadRequestIdRef.current += 1;
    contentRevisionRef.current = undefined;
    sourceGenerationRef.current += 1;
    sourceRequestRef.current?.controller.abort();
    sourceRequestRef.current = null;
    setSourceError('');
    setSourceState('idle');
    setSourceText('');
    setTranslationText('');
    setSavedTranslationText('');
    setContentHtml('');
    setState('idle');
    setError('');
  }, []);

  const load = useCallback(
    async (targetChapter?: ChapterTextPrefetchTarget | null) => {
      const nextChapter = targetChapter ?? (bookId === null || chapterId === null ? null : {
        book_id: bookId,
        content_html_path: contentHtmlPath,
        content_revision: contentRevision,
        id: chapterId,
      });

      if (!enabled || !nextChapter) {
        activeLoadRef.current?.controller.abort();
        activeLoadRef.current = null;
        reset();
        return;
      }

      const requestKey = chapterRequestKey(nextChapter);
      if (activeLoadRef.current?.key === requestKey) return activeLoadRef.current.promise;
      activeLoadRef.current?.controller.abort();
      prefetchControllersRef.current.get(requestKey)?.abort();
      prefetchControllersRef.current.delete(requestKey);
      const controller = new AbortController();
      const nextHasRichContent = Boolean(nextChapter.content_html_path);
      const performLoad = async () => {
      const requestId = loadRequestIdRef.current + 1;
      loadRequestIdRef.current = requestId;
      contentRevisionRef.current = nextChapter.content_revision;
      const candidate = cacheOwnership === 'internal'
        ? await getCachedChapterAsync(nextChapter.book_id, nextChapter.id)
        : null;
      const cachedChapter = candidate && (!candidate.contentRevision || candidate.contentRevision === readerChapterRevision(nextChapter)) ? candidate : null;
      if (requestId !== loadRequestIdRef.current) return;
      if (cachedChapter) {
        if (sourceResolvedGenerationRef.current !== sourceGenerationRef.current) setSourceText(cachedChapter.sourceText);
        setTranslationText(cachedChapter.text);
        setSavedTranslationText(cachedChapter.text);
        setContentHtml(cachedChapter.html);
        setState('ready');
        if (cachedChapter.html.trim()) {
          const assetBase = readerHtmlAssetBase(nextChapter.content_html_path);
          void hydrateCachedReaderAssetUrls(
            nextChapter.book_id,
            nextChapter.id,
            cachedChapter.html,
            assetBase,
          ).then((hydratedHtml) => {
            if (requestId === loadRequestIdRef.current) setContentHtml(hydratedHtml);
          });
        }
      } else {
        setTranslationText('');
        setSavedTranslationText('');
        setContentHtml('');
        setState('loading');
      }
      setError('');

      if (typeof navigator !== 'undefined' && navigator.onLine === false) {
        if (!cachedChapter) {
          setError('Bạn đang ngoại tuyến. Nội dung đã tải sẽ được mở từ bộ nhớ offline.');
          setState('error');
        }
        return;
      }

      try {
        const translation = await client.getChapterTranslation(nextChapter.book_id, nextChapter.id, {
          signal: controller.signal,
          onContentRevision: (revision) => {
            if (requestId === loadRequestIdRef.current) contentRevisionRef.current = revision;
          },
        });
        if (requestId !== loadRequestIdRef.current) return;
        const nextTranslation = translation ?? '';
        setTranslationText(nextTranslation);
        setSavedTranslationText(nextTranslation);
        setContentHtml('');
        setState('ready');
        cacheChapter(nextChapter, nextTranslation, '', '', contentRevisionRef.current);
        let richContent = null;
        if (nextHasRichContent) {
          try {
            const response = await client.getChapterContent(nextChapter.book_id, nextChapter.id, { signal: controller.signal });
            if (requestId !== loadRequestIdRef.current) return;
            if (response?.text === nextTranslation) richContent = response;
          } catch (richError) {
            if (controller.signal.aborted || requestId !== loadRequestIdRef.current) return;
            if (richError instanceof ApiError && richError.status === 401) onAuthError?.();
            setError('Không tải được định dạng chương. Bạn vẫn có thể đọc bản dịch.');
          }
        }
        if (requestId !== loadRequestIdRef.current) return;
        setContentHtml(richContent?.html ?? '');
        cacheChapter(nextChapter, nextTranslation, richContent?.html ?? '', '', contentRevisionRef.current);
        if (richContent?.html.trim()) {
          const assetBase = readerHtmlAssetBase(nextChapter.content_html_path);
          void (async () => {
            await cacheReaderAssetsFromHtml(nextChapter.book_id, nextChapter.id, richContent.html, undefined, assetBase);
            const hydratedHtml = await hydrateCachedReaderAssetUrls(
              nextChapter.book_id,
              nextChapter.id,
              richContent.html,
              assetBase,
            );
            if (requestId === loadRequestIdRef.current) setContentHtml(hydratedHtml);
          })();
        }
      } catch (nextError) {
        if (controller.signal.aborted || (nextError instanceof DOMException && nextError.name === 'AbortError')) return;
        if (requestId !== loadRequestIdRef.current) throw nextError;
        if (nextError instanceof ApiError && nextError.status === 401) {
          onAuthError?.();
          reset();
          setError(formatError(nextError));
          setState('error');
          throw nextError;
        }
        if (cachedChapter) {
          setState('ready');
          return;
        }
        reset();
        setError(formatError(nextError));
        setState('error');
        throw nextError;
      }
      };
      const promise = performLoad();
      activeLoadRef.current = { controller, key: requestKey, promise };
      try {
        await promise;
      } finally {
        if (activeLoadRef.current?.promise === promise) activeLoadRef.current = null;
      }
    },
    [bookId, cacheChapter, cacheOwnership, chapterId, client, contentHtmlPath, contentRevision, enabled, onAuthError, reset],
  );

  const save = useCallback(
    async (nextTranslationText?: string) => {
      if (!enabled || bookId === null || chapterId === null) return;

      const textToSave = nextTranslationText ?? translationText;
      const requestId = loadRequestIdRef.current;
      const nextHtml = textToSave === savedTranslationText ? contentHtml : '';
      setError('');
      setState('loading');

      try {
        const revision = contentRevisionRef.current;
        const updatedRevision = translatedTitle !== savedTranslatedTitle
          ? await client.saveChapterTranslation(bookId, chapterId, textToSave, revision, translatedTitle.trim())
          : revision === undefined
            ? await client.saveChapterTranslation(bookId, chapterId, textToSave)
            : await client.saveChapterTranslation(bookId, chapterId, textToSave, revision);
        if (requestId !== loadRequestIdRef.current) return;
        if (updatedRevision !== undefined) contentRevisionRef.current = updatedRevision;
        setTranslationText(textToSave);
        setSavedTranslationText(textToSave);
        setSavedTranslatedTitle(translatedTitle.trim());
        setTranslatedTitle(translatedTitle.trim());
        setContentHtml(nextHtml);
        cacheChapter({ book_id: bookId, id: chapterId }, textToSave, nextHtml, sourceText, contentRevisionRef.current);
        setState('ready');
      } catch (nextError) {
        if (requestId !== loadRequestIdRef.current) return;
        setError(formatError(nextError));
        setState('error');
        throw nextError;
      }
    },
    [bookId, cacheChapter, chapterId, client, contentHtml, enabled, savedTranslatedTitle, savedTranslationText, sourceText, translatedTitle, translationText],
  );

  const loadSource = useCallback(async () => {
    if (!enabled || bookId === null || chapterId === null) return;
    const key = `${bookId}:${chapterId}:${contentRevision ?? ''}`;
    if (sourceRequestRef.current?.key === key) return sourceRequestRef.current.promise;
    sourceRequestRef.current?.controller.abort();
    const controller = new AbortController();
    const generation = ++sourceGenerationRef.current;
    setSourceText('');
    setSourceError('');
    setSourceState('loading');
    const promise = client.getChapterSource(bookId, chapterId, {signal: controller.signal}).then((source) => {
      if (generation !== sourceGenerationRef.current || controller.signal.aborted) return;
      sourceResolvedGenerationRef.current = generation;
      setSourceText(source);
      setSourceState(source ? 'ready' : 'empty');
    }).catch((nextError) => {
      if (generation !== sourceGenerationRef.current || controller.signal.aborted) return;
      if (nextError instanceof ApiError && nextError.status === 401) onAuthError?.();
      setSourceError(formatError(nextError));
      setSourceState('error');
      sourceRequestRef.current = null;
    });
    sourceRequestRef.current = {key, controller, promise};
    return promise;
  }, [bookId, chapterId, client, contentRevision, enabled, onAuthError]);

  useEffect(() => {
    setTranslatedTitle(chapter?.translated_title ?? '');
    setSavedTranslatedTitle(chapter?.translated_title ?? '');
  }, [bookId, chapterId, chapter?.translated_title]);

  useEffect(() => {
    sourceGenerationRef.current += 1;
    sourceRequestRef.current?.controller.abort();
    sourceRequestRef.current = null;
    setSourceText('');
    setSourceError('');
    setSourceState('idle');
    if (sourceEnabled) void loadSource();
  }, [bookId, chapterId, contentRevision, loadSource, sourceEnabled]);

  useEffect(() => {
    if (!enabled || bookId === null || chapterId === null) {
      activeLoadRef.current?.controller.abort();
      activeLoadRef.current = null;
      reset();
      return;
    }

    void load({ book_id: bookId, content_html_path: contentHtmlPath, content_revision: contentRevision, id: chapterId }).catch(() => {});
  }, [bookId, chapterId, contentHtmlPath, contentRevision, enabled, load, reset]);

  useEffect(() => {
    if (
      cacheOwnership === 'external'
      || !enabled
      || bookId === null
      || chapterId === null
      || prefetchTargets.length === 0
    ) return;
    const targets = prefetchTargets.filter((target) => (
      target.book_id === bookId
      && target.id !== chapterId
    ));
    if (targets.length === 0) return;

    let cancelled = false;
    const effectControllers: AbortController[] = [];
    const timeout = window.setTimeout(() => {
      void (async () => {
        const uncachedTargets: ChapterTextPrefetchTarget[] = [];
        for (const target of targets) {
          if (cancelled) return;
          if (!(await hasCachedChapterAsync(target.book_id, target.id))) {
            uncachedTargets.push(target);
          }
        }
        for (const target of uncachedTargets) {
          const requestKey = chapterRequestKey(target);
          if (prefetchControllersRef.current.has(requestKey)) continue;
          const controller = new AbortController();
          prefetchControllersRef.current.set(requestKey, controller);
          effectControllers.push(controller);
          try {
            let revision = target.content_revision;
            const [translation, richContent] = await Promise.all([
              client.getChapterTranslation(target.book_id, target.id, { signal: controller.signal, onContentRevision: (value) => { revision = value; } }),
              target.content_html_path
                ? client.getChapterContent(target.book_id, target.id, { signal: controller.signal })
                : Promise.resolve(null),
            ]);
            if (cancelled) return;
            const nextTranslation = translation ?? '';
            const html = richContent?.text === nextTranslation ? richContent.html : '';
            cacheChapter(target, nextTranslation, html, '', revision);
            if (richContent?.html.trim()) {
              void cacheReaderAssetsFromHtml(
                target.book_id,
                target.id,
                richContent.html,
                undefined,
                readerHtmlAssetBase(target.content_html_path),
              );
            }
          } catch {
            // Prefetch is opportunistic; live chapter loading remains the source of truth.
          } finally {
            if (prefetchControllersRef.current.get(requestKey) === controller) {
              prefetchControllersRef.current.delete(requestKey);
            }
          }
        }
      })();
    }, 250);

    return () => {
      cancelled = true;
      window.clearTimeout(timeout);
      effectControllers.forEach((controller) => controller.abort());
    };
  }, [bookId, cacheChapter, cacheOwnership, chapterId, client, enabled, prefetchTargets]);

  useEffect(() => () => {
    loadRequestIdRef.current += 1;
    activeLoadRef.current?.controller.abort();
    activeLoadRef.current = null;
    sourceGenerationRef.current += 1;
    sourceRequestRef.current?.controller.abort();
    prefetchControllersRef.current.forEach((controller) => controller.abort());
    prefetchControllersRef.current.clear();
  }, []);

  return {
    error,
    isDirty: translationText !== savedTranslationText || translatedTitle !== savedTranslatedTitle,
    contentHtml,
    load,
    save,
    savedTranslationText,
    setTranslationText,
    translatedTitle,
    setTranslatedTitle,
    sourceText,
    sourceState,
    sourceError,
    loadSource,
    state,
    translationText,
  };
}
