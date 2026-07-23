import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { RefObject } from 'react';

export type WindowedListOptions = {
  count: number;
  estimateSize: number;
  initialIndex?: number;
  minimumCount?: number;
  overscan?: number;
  resetKey: string;
};

type WindowedListResult = {
  containerRef: RefObject<HTMLDivElement | null>;
  endIndex: number;
  isWindowed: boolean;
  onScroll(): void;
  paddingBottom: number;
  paddingTop: number;
  scrollToIndex(index: number, align?: 'auto' | 'center'): void;
  startIndex: number;
};

/**
 * Small dependency-free windowing primitive for the two operator-owned long
 * lists. Items remain in normal document flow, so variable-height glossary
 * cards and TOC previews can grow without overlapping adjacent content.
 */
export function useWindowedList({
  count,
  estimateSize,
  initialIndex = 0,
  minimumCount = 60,
  overscan = 5,
  resetKey,
}: WindowedListOptions): WindowedListResult {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const isWindowed = count > minimumCount;
  const fallbackViewportSize = estimateSize * 10;
  const [scrollTop, setScrollTop] = useState(() => (
    isWindowed ? Math.max(0, initialIndex * estimateSize - fallbackViewportSize / 2) : 0
  ));
  const [viewportSize, setViewportSize] = useState(fallbackViewportSize);

  const readViewport = useCallback(() => {
    const node = containerRef.current;
    if (!node) return;
    setViewportSize(node.clientHeight || fallbackViewportSize);
    setScrollTop(node.scrollTop);
  }, [fallbackViewportSize]);

  useLayoutEffect(() => {
    const node = containerRef.current;
    const nextTop = isWindowed
      ? Math.max(0, initialIndex * estimateSize - (node?.clientHeight || fallbackViewportSize) / 2)
      : 0;
    if (node) node.scrollTop = nextTop;
    setScrollTop(nextTop);
    readViewport();
  }, [estimateSize, fallbackViewportSize, initialIndex, isWindowed, readViewport, resetKey]);

  useEffect(() => {
    const node = containerRef.current;
    if (!node || typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(readViewport);
    observer.observe(node);
    return () => observer.disconnect();
  }, [readViewport]);

  const { endIndex, paddingBottom, paddingTop, startIndex } = useMemo(() => {
    if (!isWindowed) {
      return { endIndex: count, paddingBottom: 0, paddingTop: 0, startIndex: 0 };
    }
    const start = Math.max(0, Math.floor(scrollTop / estimateSize) - overscan);
    const end = Math.min(
      count,
      Math.ceil((scrollTop + viewportSize) / estimateSize) + overscan,
    );
    return {
      endIndex: end,
      paddingBottom: Math.max(0, (count - end) * estimateSize),
      paddingTop: start * estimateSize,
      startIndex: start,
    };
  }, [count, estimateSize, isWindowed, overscan, scrollTop, viewportSize]);

  const scrollToIndex = useCallback((index: number, align: 'auto' | 'center' = 'auto') => {
    if (!isWindowed || count === 0) return;
    const boundedIndex = Math.max(0, Math.min(count - 1, index));
    const node = containerRef.current;
    const currentViewport = node?.clientHeight || viewportSize || fallbackViewportSize;
    const itemTop = boundedIndex * estimateSize;
    const itemBottom = itemTop + estimateSize;
    let nextTop = node?.scrollTop ?? scrollTop;
    if (align === 'center') {
      nextTop = Math.max(0, itemTop - currentViewport / 2 + estimateSize / 2);
    } else if (itemTop < nextTop) {
      nextTop = itemTop;
    } else if (itemBottom > nextTop + currentViewport) {
      nextTop = itemBottom - currentViewport;
    }
    if (node) node.scrollTop = nextTop;
    setScrollTop(nextTop);
  }, [count, estimateSize, fallbackViewportSize, isWindowed, scrollTop, viewportSize]);

  return {
    containerRef,
    endIndex,
    isWindowed,
    onScroll: readViewport,
    paddingBottom,
    paddingTop,
    scrollToIndex,
    startIndex,
  };
}
