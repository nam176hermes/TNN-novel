import { useCallback, useState, type RefObject } from 'react';
import { getCurrentParagraphIndex, paragraphTextElement, textOffsetWithinNode } from '../../state/readerLocation';
import type { ReaderSelectionState } from './types';

function elementFromSelectionNode(node: Node | null): Element | null {
  if (!node) return null;
  return node.nodeType === Node.ELEMENT_NODE ? node as Element : node.parentElement;
}

function paragraphIndexFromSelectionNode(node: Node | null): number | null {
  const element = elementFromSelectionNode(node);
  const block = element?.closest<HTMLElement>('.reader-paragraph-block[data-paragraph-index]');
  const rawIndex = block?.dataset.paragraphIndex;
  if (rawIndex == null) return null;
  const index = Number(rawIndex);
  return Number.isInteger(index) && index >= 0 ? index : null;
}

function selectionParagraphBlock(container: HTMLElement | null, node: Node | null): HTMLElement | null {
  if (!container) return null;
  const element = elementFromSelectionNode(node);
  const block = element?.closest<HTMLElement>('.reader-paragraph-block[data-paragraph-index]');
  return block && container.contains(block) ? block : null;
}

function paragraphTextElementFromBlock(block: HTMLElement | null): HTMLElement | null {
  if (!block) return null;
  return block.querySelector<HTMLElement>('.reader-paragraph-text') ?? block;
}

function charStartOffsetFromBlock(block: HTMLElement | null): number {
  const value = Number(block?.dataset.charStart);
  return Number.isInteger(value) && value >= 0 ? value : 0;
}

function selectionAnchorFromRect(rect: DOMRect): { left: number; top: number } {
  const fallbackLeft = Math.round(window.innerWidth / 2);
  const fallbackTop = 120;
  const rectLeft = Number.isFinite(rect.left) ? rect.left : fallbackLeft;
  const rectTop = Number.isFinite(rect.top) ? rect.top : fallbackTop;
  const rectWidth = Number.isFinite(rect.width) ? rect.width : 0;
  const maxLeft = Math.max(16, window.innerWidth - 16);
  const maxTop = Math.max(16, window.innerHeight - 92);
  return {
    left: Math.round(Math.min(maxLeft, Math.max(16, rectLeft + rectWidth / 2))),
    top: Math.round(Math.min(maxTop, Math.max(16, rectTop - 72))),
  };
}

export function useReaderSelection(readerMainRef: RefObject<HTMLElement | null>, progressTextBlocks: string[]) {
  const [readerSelection, setReaderSelection] = useState<ReaderSelectionState | null>(null);
  function clearReaderSelection(): void {
    window.getSelection()?.removeAllRanges();
    setReaderSelection(null);
  }

  function captureReaderSelection(): void {
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed || selection.rangeCount === 0) {
      setReaderSelection(null);
      return;
    }

    const text = selection.toString().trim().slice(0, 2000);
    if (!text) {
      setReaderSelection(null);
      return;
    }

    const range = selection.getRangeAt(0);
    if (!readerMainRef.current?.contains(range.commonAncestorContainer)) {
      setReaderSelection(null);
      return;
    }

    const selectionBlock = selectionParagraphBlock(readerMainRef.current, range.startContainer)
      ?? selectionParagraphBlock(readerMainRef.current, range.commonAncestorContainer)
      ?? selectionParagraphBlock(readerMainRef.current, selection.anchorNode)
      ?? selectionParagraphBlock(readerMainRef.current, selection.focusNode);
    const paragraphIndex = paragraphIndexFromSelectionNode(selectionBlock)
      ?? paragraphIndexFromSelectionNode(range.commonAncestorContainer)
      ?? paragraphIndexFromSelectionNode(selection.anchorNode)
      ?? paragraphIndexFromSelectionNode(selection.focusNode)
      ?? getCurrentParagraphIndex(readerMainRef.current)
      ?? 0;
    const paragraphText = progressTextBlocks[paragraphIndex] ?? text;
    const paragraphElement = paragraphTextElementFromBlock(selectionBlock)
      ?? paragraphTextElement(readerMainRef.current, paragraphIndex);
    const rangeStart = paragraphElement
      ? textOffsetWithinNode(paragraphElement, range.startContainer, range.startOffset)
      : null;
    const rangeEnd = paragraphElement
      ? textOffsetWithinNode(paragraphElement, range.endContainer, range.endOffset)
      : null;
    const rangeBaseOffset = charStartOffsetFromBlock(selectionBlock);
    const fallbackStart = Math.max(0, paragraphText.indexOf(text));
    const charStart = rangeStart !== null ? rangeBaseOffset + rangeStart : fallbackStart;
    const charEnd = rangeEnd !== null ? rangeBaseOffset + rangeEnd : charStart + text.length;
    setReaderSelection({
      anchor: selectionAnchorFromRect(range.getBoundingClientRect()),
      charEnd,
      charStart,
      contextAfter: progressTextBlocks[paragraphIndex + 1] ?? '',
      contextBefore: progressTextBlocks[paragraphIndex - 1] ?? '',
      paragraphIndex,
      text,
    });
  }

  return {
    readerSelection, captureReaderSelection, clearReaderSelection,
    dismissReaderSelection: useCallback(() => setReaderSelection(null), []),
  };
}
