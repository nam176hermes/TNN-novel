import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { RefObject } from 'react';

export type WindowedListOptions = {
  count: number;
  estimateSize: number;
  initialIndex?: number;
  measureItems?: boolean;
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
  measureItems = false,
  minimumCount = 60,
  overscan = 5,
  resetKey,
}: WindowedListOptions): WindowedListResult {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const isWindowed = count > minimumCount;
  const fallbackViewportSize = estimateSize * 10;
  const [measuredSize, setMeasuredSize] = useState<number | null>(null);
  const itemSize = measuredSize ?? estimateSize;
  const [scrollTop, setScrollTop] = useState(() => (
    isWindowed ? Math.max(0, initialIndex * itemSize - fallbackViewportSize / 2) : 0
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
      ? Math.max(0, initialIndex * itemSize - (node?.clientHeight || fallbackViewportSize) / 2)
      : 0;
    if (node) node.scrollTop = nextTop;
    setScrollTop(nextTop);
    readViewport();
  }, [fallbackViewportSize, initialIndex, isWindowed, itemSize, readViewport, resetKey]);

  useLayoutEffect(() => {
    if (!isWindowed || !measureItems) return;
    const node = containerRef.current;
    if (!node) return;
    const sizes = Array.from(node.querySelectorAll<HTMLElement>('[data-virtual-index]'))
      .map((element) => element.getBoundingClientRect().height)
      .filter((size) => Number.isFinite(size) && size > 0);
    if (sizes.length === 0) return;
    const observedAverage = sizes.reduce((total, size) => total + size, 0) / sizes.length;
    const averageSize = measuredSize === null
      ? observedAverage
      : measuredSize * 0.75 + observedAverage * 0.25;
    if (Math.abs(averageSize - itemSize) < 4) return;
    const previousSize = itemSize;
    const nextTop = previousSize > 0 ? (node.scrollTop / previousSize) * averageSize : node.scrollTop;
    node.scrollTop = nextTop;
    setScrollTop(nextTop);
    setMeasuredSize(averageSize);
  }, [isWindowed, itemSize, measureItems, measuredSize, resetKey, scrollTop]);

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
    const start = Math.max(0, Math.floor(scrollTop / itemSize) - overscan);
    const end = Math.min(
      count,
      Math.ceil((scrollTop + viewportSize) / itemSize) + overscan,
    );
    return {
      endIndex: end,
      paddingBottom: Math.max(0, (count - end) * itemSize),
      paddingTop: start * itemSize,
      startIndex: start,
    };
  }, [count, isWindowed, itemSize, overscan, scrollTop, viewportSize]);

  const scrollToIndex = useCallback((index: number, align: 'auto' | 'center' = 'auto') => {
    if (!isWindowed || count === 0) return;
    const boundedIndex = Math.max(0, Math.min(count - 1, index));
    const node = containerRef.current;
    const currentViewport = node?.clientHeight || viewportSize || fallbackViewportSize;
    const itemTop = boundedIndex * itemSize;
    const itemBottom = itemTop + itemSize;
    let nextTop = node?.scrollTop ?? scrollTop;
    if (align === 'center') {
      nextTop = Math.max(0, itemTop - currentViewport / 2 + itemSize / 2);
    } else if (itemTop < nextTop) {
      nextTop = itemTop;
    } else if (itemBottom > nextTop + currentViewport) {
      nextTop = itemBottom - currentViewport;
    }
    if (node) node.scrollTop = nextTop;
    setScrollTop(nextTop);
  }, [count, fallbackViewportSize, isWindowed, itemSize, scrollTop, viewportSize]);

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
