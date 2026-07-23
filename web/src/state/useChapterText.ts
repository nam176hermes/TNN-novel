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
} from './readerCache';
import { formatError, type LoadState } from './types';

export type ChapterTextPrefetchTarget = Pick<Chapter, 'book_id' | 'content_html_path' | 'id'>;

export type UseChapterTextOptions = {
  cacheOwnership?: 'external' | 'internal';
};

function readerHtmlAssetBase(contentHtmlPath?: string | null): string | undefined {
  const path = contentHtmlPath?.trim() ?? '';
  if (!path) return undefined;
  if (/^https?:\/\//i.test(path) || path.startsWith('/book-assets/')) return path;
  return undefined;
}

function chapterRequestKey(chapter: ChapterTextPrefetchTarget): string {
  return `${chapter.book_id}:${chapter.id}:${chapter.content_html_path?.trim() ?? ''}`;
}

export function useChapterText(
  client: ApiClient,
  enabled: boolean,
  chapter: Chapter | null,
  onAuthError?: () => void,
  prefetchTargets: ChapterTextPrefetchTarget[] = [],
  { cacheOwnership = 'internal' }: UseChapterTextOptions = {},
) {
  const chapterId = chapter?.id ?? null;
  const bookId = chapter?.book_id ?? null;
  const contentHtmlPath = chapter?.content_html_path ?? null;

  const [sourceText, setSourceText] = useState('');
  const [translationText, setTranslationText] = useState('');
  const [savedTranslationText, setSavedTranslationText] = useState('');
  const [contentHtml, setContentHtml] = useState('');
  const [state, setState] = useState<LoadState>('idle');
  const [error, setError] = useState('');
  const loadRequestIdRef = useRef(0);
  const activeLoadRef = useRef<{
    controller: AbortController;
    key: string;
    promise: Promise<void>;
  } | null>(null);
  const prefetchControllersRef = useRef(new Map<string, AbortController>());

  const cacheChapter = useCallback((
    targetChapter: { book_id: number; id: number },
    text: string,
    html: string,
    sourceTextValue: string,
  ) => {
    if (!text.trim() && !html.trim()) {
      void removeCachedChapterAsync(targetChapter.book_id, targetChapter.id);
      return;
    }
    void putCachedChapterAsync({
      bookId: targetChapter.book_id,
      chapterId: targetChapter.id,
      html,
      sourceText: sourceTextValue,
      text,
    });
  }, []);

  const reset = useCallback(() => {
    loadRequestIdRef.current += 1;
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
      const cachedChapter = cacheOwnership === 'internal'
        ? await getCachedChapterAsync(nextChapter.book_id, nextChapter.id)
        : null;
      if (requestId !== loadRequestIdRef.current) return;
      if (cachedChapter) {
        setSourceText(cachedChapter.sourceText);
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
        setSourceText('');
        setTranslationText('');
        setSavedTranslationText('');
        setContentHtml('');
        setState('loading');
      }
      setError('');

      try {
        const [source, translation] = await Promise.all([
          client.getChapterSource(nextChapter.book_id, nextChapter.id, { signal: controller.signal }),
          client.getChapterTranslation(nextChapter.book_id, nextChapter.id, { signal: controller.signal }),
        ]);
        const richContent = nextHasRichContent
          ? await client.getChapterContent(nextChapter.book_id, nextChapter.id, { signal: controller.signal })
          : null;
        if (requestId !== loadRequestIdRef.current) return;
        const nextTranslation = richContent?.text ?? translation ?? '';

        setSourceText(source);
        setTranslationText(nextTranslation);
        setSavedTranslationText(nextTranslation);
        setContentHtml(richContent?.html ?? '');
        setState('ready');
        cacheChapter(nextChapter, nextTranslation, richContent?.html ?? '', source);
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
    [bookId, cacheChapter, cacheOwnership, chapterId, client, contentHtmlPath, enabled, onAuthError, reset],
  );

  const save = useCallback(
    async (nextTranslationText?: string) => {
      if (!enabled || bookId === null || chapterId === null) return;

      const textToSave = nextTranslationText ?? translationText;
      setError('');
      setState('loading');

      try {
        await client.saveChapterTranslation(bookId, chapterId, textToSave);
        setTranslationText(textToSave);
        setSavedTranslationText(textToSave);
        setContentHtml('');
        cacheChapter({ book_id: bookId, id: chapterId }, textToSave, '', sourceText);
        setState('ready');
      } catch (nextError) {
        setError(formatError(nextError));
        setState('error');
        throw nextError;
      }
    },
    [bookId, cacheChapter, chapterId, client, enabled, sourceText, translationText],
  );

  useEffect(() => {
    if (!enabled || bookId === null || chapterId === null) {
      activeLoadRef.current?.controller.abort();
      activeLoadRef.current = null;
      reset();
      return;
    }

    void load({ book_id: bookId, content_html_path: contentHtmlPath, id: chapterId }).catch(() => {});
  }, [bookId, chapterId, contentHtmlPath, enabled, load, reset]);

  useEffect(() => {
    if (!enabled || bookId === null || chapterId === null || prefetchTargets.length === 0) return;
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
            const [translation, richContent] = await Promise.all([
              client.getChapterTranslation(target.book_id, target.id, { signal: controller.signal }),
              target.content_html_path
                ? client.getChapterContent(target.book_id, target.id, { signal: controller.signal })
                : Promise.resolve(null),
            ]);
            if (cancelled) return;
            const nextTranslation = richContent?.text ?? translation ?? '';
            cacheChapter(target, nextTranslation, richContent?.html ?? '', '');
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
  }, [bookId, cacheChapter, chapterId, client, enabled, prefetchTargets]);

  useEffect(() => () => {
    loadRequestIdRef.current += 1;
    activeLoadRef.current?.controller.abort();
    activeLoadRef.current = null;
    prefetchControllersRef.current.forEach((controller) => controller.abort());
    prefetchControllersRef.current.clear();
  }, []);

  return {
    error,
    isDirty: translationText !== savedTranslationText,
    contentHtml,
    load,
    save,
    savedTranslationText,
    setTranslationText,
    sourceText,
    state,
    translationText,
  };
}
