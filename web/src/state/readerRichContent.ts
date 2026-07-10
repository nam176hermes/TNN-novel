export type ReaderRichBlock = {
  html: string;
  index: number;
  kind: 'text' | 'image' | 'html' | 'structure';
  pageBreakAfter?: boolean;
  pageBreakBefore?: boolean;
  pageBreakInsideAvoid?: boolean;
  text: string;
};

type NormalizedRichBlockElement = {
  element: Element;
  pageBreakAfter?: boolean;
  pageBreakBefore?: boolean;
  pageBreakInsideAvoid?: boolean;
};

type ReaderStylesheetPaginationRule = {
  pageBreakAfter?: boolean;
  pageBreakBefore?: boolean;
  pageBreakInsideAvoid?: boolean;
  selector: string;
};

type ReaderStylesheetHiddenRule = {
  selector: string;
};

type StructuredTextOptions = {
  includeAriaHidden?: boolean;
};

const leafBlockSelector = [
  'blockquote',
  'audio',
  'aside',
  'dl',
  'figure',
  'h1',
  'h2',
  'h3',
  'h4',
  'h5',
  'h6',
  'hr',
  'img',
  'math',
  'ol',
  'p',
  'picture',
  'pre',
  'svg',
  'table',
  'ul',
  'video',
].join(',');

const wrapperBlockSelector = [
  'article',
  'aside',
  'div',
  'section',
].join(',');

const nonReadingSelector = 'script,style,noscript,template';
const rubyAnnotationSelector = 'rt,rp';

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function hasElementAncestor(node: Node, root: Node, predicate: (element: Element) => boolean): boolean {
  let current: Node | null = node.nodeType === Node.ELEMENT_NODE ? node : node.parentNode;
  while (current) {
    if (current !== root && current.nodeType === Node.ELEMENT_NODE && predicate(current as Element)) return true;
    if (current === root) return false;
    current = current.parentNode;
  }
  return false;
}

function textPositionAtOffset(root: Node, offset: number): { node: Text; offset: number } | null {
  const documentRef = root.ownerDocument ?? document;
  const ownerWindow = documentRef.defaultView;
  const textFilter = ownerWindow?.NodeFilter?.SHOW_TEXT ?? 4;
  const walker = documentRef.createTreeWalker(root, textFilter);
  let cursor = 0;
  let current = walker.nextNode();
  let lastTextNode: Text | null = null;

  while (current) {
    const textNode = current as Text;
    const excluded = hasElementAncestor(
      textNode,
      root,
      (element) => isCssHiddenElement(element) || isAriaHiddenElement(element) || element.matches(rubyAnnotationSelector),
    );
    if (excluded) {
      current = walker.nextNode();
      continue;
    }
    lastTextNode = textNode;
    const length = textNode.textContent?.length ?? 0;
    if (offset <= cursor + length) {
      return {
        node: textNode,
        offset: Math.min(length, Math.max(0, offset - cursor)),
      };
    }
    cursor += length;
    current = walker.nextNode();
  }

  return lastTextNode ? { node: lastTextNode, offset: lastTextNode.textContent?.length ?? 0 } : null;
}

function copyElementShell(element: Element): Element {
  return element.cloneNode(false) as Element;
}

function normalizedText(value: string | null | undefined): string {
  return (value ?? '').replace(/\s+/g, ' ').trim();
}

function joinReadableTextParts(parts: string[]): string {
  let output = '';
  for (const part of parts.map(normalizedText).filter(Boolean)) {
    if (!output) {
      output = part;
    } else if (/^[,.;:!?，。！？；：)\]}]/u.test(part) || /[([{]$/u.test(output.trim())) {
      output += part;
    } else {
      output += ` ${part}`;
    }
  }
  return normalizedText(output);
}

function visibleDomText(node: Node, options: StructuredTextOptions = {}): string {
  if (node.nodeType === Node.TEXT_NODE) return node.textContent ?? '';
  if (node.nodeType !== Node.ELEMENT_NODE) return '';

  const element = node as Element;
  if (element.matches(nonReadingSelector) || isCssHiddenElement(element)) return '';
  if (element.matches(rubyAnnotationSelector)) return '';
  if (!options.includeAriaHidden && isAriaHiddenElement(element)) return '';
  return joinReadableTextParts(Array.from(element.childNodes).map((child) => visibleDomText(child, options)));
}

function normalizedPageBreakToken(value: string | null | undefined): string {
  return (value ?? '').toLowerCase().replace(/[_\s]+/g, '-');
}

function stripNonReadingHtml(value: string): string {
  return value.replace(/<(script|style|noscript|template)\b[^>]*>[\s\S]*?<\/\1>/gi, ' ');
}

function isCssHiddenElement(node: Node): boolean {
  if (node.nodeType !== Node.ELEMENT_NODE) return false;
  const element = node as HTMLElement;
  const inlineStyle = element.style;
  const display = inlineStyle?.display?.toLowerCase() ?? '';
  const visibility = inlineStyle?.visibility?.toLowerCase() ?? '';
  return element.hasAttribute('hidden')
    || display === 'none'
    || visibility === 'hidden'
    || visibility === 'collapse';
}

function isAriaHiddenElement(node: Node): boolean {
  return node.nodeType === Node.ELEMENT_NODE
    && (node as Element).getAttribute('aria-hidden')?.toLowerCase() === 'true';
}

function removeCssHiddenElements(root: Element): void {
  Array.from(root.querySelectorAll('*'))
    .filter(isCssHiddenElement)
    .forEach((element) => element.remove());
}

function removeRubyAnnotationElements(root: Element): void {
  root.querySelectorAll(rubyAnnotationSelector).forEach((element) => element.remove());
}

function removeStylesheetHiddenElements(root: Element, stylesheetRules: ReaderStylesheetHiddenRule[]): void {
  if (stylesheetRules.length === 0) return;
  Array.from(root.querySelectorAll('*'))
    .filter((element) => stylesheetRules.some((rule) => selectorMatches(element, rule.selector)))
    .forEach((element) => element.remove());
}

function removeRedundantAriaHiddenElements(root: Element): void {
  if (!normalizedText(structuredText(root, { includeAriaHidden: false }))) return;
  Array.from(root.querySelectorAll('*'))
    .filter(isAriaHiddenElement)
    .forEach((element) => element.remove());
}

function pageBreakTokenSource(element: Element): string {
  return [
    element.getAttribute('class'),
    element.getAttribute('id'),
    element.getAttribute('epub:type'),
    element.getAttribute('role'),
    element.getAttribute('data-type'),
    element.getAttribute('data-break'),
    element.getAttribute('data-page-break'),
    element.getAttribute('data-pagebreak'),
    element.hasAttribute('data-break-before') ? 'data-break-before' : '',
    element.getAttribute('data-break-before'),
    element.hasAttribute('data-page-break-before') ? 'data-page-break-before' : '',
    element.getAttribute('data-page-break-before'),
    element.hasAttribute('data-break-after') ? 'data-break-after' : '',
    element.getAttribute('data-break-after'),
    element.hasAttribute('data-page-break-after') ? 'data-page-break-after' : '',
    element.getAttribute('data-page-break-after'),
  ].map(normalizedPageBreakToken).join(' ');
}

function pageBreakDataDirectionSource(element: Element): string {
  return [
    element.getAttribute('data-break'),
    element.getAttribute('data-page-break'),
    element.getAttribute('data-pagebreak'),
  ].map(normalizedPageBreakToken).join(' ');
}

function hasExplicitPageBreakAfterToken(element: Element): boolean {
  const value = pageBreakTokenSource(element);
  return /\b(?:page-?break|break)-(?:after|right|left|recto|verso)\b/.test(value)
    || /\b(?:after|right|left|recto|verso)-(?:page-?break|break)\b/.test(value)
    || /\b(?:after|right|left|recto|verso)\b/.test(pageBreakDataDirectionSource(element));
}

function hasExplicitPageBreakBeforeToken(element: Element): boolean {
  const value = pageBreakTokenSource(element);
  const dataDirection = pageBreakDataDirectionSource(element);
  if (/\b(?:before|after|right|left|recto|verso)\b/.test(dataDirection)) {
    return /\bbefore\b/.test(dataDirection);
  }
  if (/\b(?:page-?break|break)-(?:before|after|right|left|recto|verso)\b/.test(value)) {
    return /\b(?:page-?break|break)-before\b/.test(value);
  }
  if (/\b(?:before|after|right|left|recto|verso)-(?:page-?break|break)\b/.test(value)) {
    return /\bbefore-(?:page-?break|break)\b/.test(value);
  }
  return /\b(?:chapter-)?(?:epub-)?(?:mbp-)?page-?break\b/.test(value)
    || /\bpagebreak\b/.test(value);
}

function hasExplicitPageBreakToken(element: Element): boolean {
  const value = [
    element.getAttribute('class'),
    element.getAttribute('id'),
    element.getAttribute('epub:type'),
    element.getAttribute('role'),
    element.getAttribute('data-type'),
    element.getAttribute('data-break'),
    element.getAttribute('data-page-break'),
    element.getAttribute('data-pagebreak'),
  ].map(normalizedPageBreakToken).join(' ');
  return /\b(?:chapter-)?(?:epub-)?(?:mbp-)?page-?break\b/.test(value)
    || /\bpagebreak\b/.test(value);
}

function hasInlinePageBreakMarker(element: Element, stylesheetRules: ReaderStylesheetPaginationRule[] = []): boolean {
  const style = element.getAttribute('style');
  const stylesheetHints = stylesheetPageBreakHints(element, stylesheetRules);
  return hasExplicitPageBreakToken(element)
    || stylesheetHints.pageBreakBefore
    || stylesheetHints.pageBreakAfter
    || styleHasPageBreak(style, 'before')
    || styleHasPageBreak(style, 'after');
}

function hasBreakInsideAvoidToken(element: Element): boolean {
  const dataBreakInside = normalizedPageBreakToken(element.getAttribute('data-break-inside'));
  const dataPageBreakInside = normalizedPageBreakToken(element.getAttribute('data-page-break-inside'));
  if ([dataBreakInside, dataPageBreakInside].some((value) => value === 'avoid' || value.startsWith('avoid-'))) {
    return true;
  }

  const booleanAvoidHints = [
    element.getAttribute('data-avoid-break'),
    element.getAttribute('data-avoid-page-break'),
    element.getAttribute('data-keep-together'),
    element.getAttribute('data-no-break'),
  ].map(normalizedPageBreakToken);
  if (booleanAvoidHints.some((value) => value === 'true' || value === '1' || value === 'yes' || value === 'avoid')) {
    return true;
  }

  const value = [
    element.getAttribute('class'),
    element.getAttribute('id'),
    element.getAttribute('epub:type'),
    element.getAttribute('role'),
    element.getAttribute('data-type'),
    element.getAttribute('data-avoid-break'),
    element.getAttribute('data-avoid-page-break'),
    element.getAttribute('data-break-inside'),
    element.getAttribute('data-keep-together'),
    element.getAttribute('data-no-break'),
    element.getAttribute('data-page-break-inside'),
  ].map(normalizedPageBreakToken).join(' ');
  return /\b(?:break-inside|page-break-inside|pagebreak-inside)-avoid\b/.test(value)
    || /\b(?:avoid-break|keep-together|no-break|nobreak)\b/.test(value);
}

function isSemanticKeepTogetherBlock(element: Element): boolean {
  if (element.matches('aside')) return true;
  const value = [
    element.getAttribute('class'),
    element.getAttribute('id'),
    element.getAttribute('epub:type'),
    element.getAttribute('role'),
    element.getAttribute('data-type'),
  ].map(normalizedPageBreakToken).join(' ');
  return /\b(?:doc-)?(?:footnote|endnote|rearnote)\b/.test(value)
    || /\b(?:sidebar|annotation|note)\b/.test(value);
}

function styleValue(style: string, property: string): string {
  const escapedProperty = property.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const pattern = new RegExp(`(?:^|;)\\s*${escapedProperty}\\s*:\\s*([^;]+)`, 'i');
  return normalizedPageBreakToken(pattern.exec(style)?.[1]);
}

function styleHasPageBreak(style: string | null | undefined, direction: 'after' | 'before'): boolean {
  const source = style ?? '';
  const properties = direction === 'before'
    ? ['break-before', 'page-break-before', '-epub-page-break-before', '-webkit-break-before', '-webkit-page-break-before']
    : ['break-after', 'page-break-after', '-epub-page-break-after', '-webkit-break-after', '-webkit-page-break-after'];
  return properties.some((property) => {
    const value = styleValue(source, property);
    return ['always', 'left', 'page', 'recto', 'right', 'verso'].includes(value);
  });
}

function styleHasBreakInsideAvoid(style: string | null | undefined): boolean {
  const source = style ?? '';
  return ['break-inside', 'page-break-inside', 'column-break-inside', '-webkit-column-break-inside']
    .some((property) => {
      const value = styleValue(source, property);
      return value === 'avoid' || value.startsWith('avoid-');
    });
}

function splitCssSelectors(selectorText: string): string[] {
  return selectorText
    .split(',')
    .map((selector) => selector.trim())
    .filter(Boolean);
}

function extractStylesheetPaginationRules(html: string): ReaderStylesheetPaginationRule[] {
  const rules: ReaderStylesheetPaginationRule[] = [];
  const styleBlockPattern = /<style\b[^>]*>([\s\S]*?)<\/style>/gi;
  let styleBlock = styleBlockPattern.exec(html);

  while (styleBlock) {
    const stylesheet = styleBlock[1].replace(/\/\*[\s\S]*?\*\//g, ' ');
    const rulePattern = /([^{}@]+)\{([^{}]+)\}/g;
    let cssRule = rulePattern.exec(stylesheet);
    while (cssRule) {
      const declarations = cssRule[2];
      const pageBreakAfter = styleHasPageBreak(declarations, 'after') ? true : undefined;
      const pageBreakBefore = styleHasPageBreak(declarations, 'before') ? true : undefined;
      const pageBreakInsideAvoid = styleHasBreakInsideAvoid(declarations) ? true : undefined;
      if (pageBreakAfter || pageBreakBefore || pageBreakInsideAvoid) {
        for (const selector of splitCssSelectors(cssRule[1])) {
          rules.push({
            pageBreakAfter,
            pageBreakBefore,
            pageBreakInsideAvoid,
            selector,
          });
        }
      }
      cssRule = rulePattern.exec(stylesheet);
    }
    styleBlock = styleBlockPattern.exec(html);
  }

  return rules;
}

function styleHasHiddenContent(style: string | null | undefined): boolean {
  const source = style ?? '';
  const display = styleValue(source, 'display');
  const visibility = styleValue(source, 'visibility');
  return display === 'none'
    || visibility === 'hidden'
    || visibility === 'collapse';
}

function extractStylesheetHiddenRules(html: string): ReaderStylesheetHiddenRule[] {
  const rules: ReaderStylesheetHiddenRule[] = [];
  const styleBlockPattern = /<style\b[^>]*>([\s\S]*?)<\/style>/gi;
  let styleBlock = styleBlockPattern.exec(html);

  while (styleBlock) {
    const stylesheet = styleBlock[1].replace(/\/\*[\s\S]*?\*\//g, ' ');
    const rulePattern = /([^{}@]+)\{([^{}]+)\}/g;
    let cssRule = rulePattern.exec(stylesheet);
    while (cssRule) {
      if (styleHasHiddenContent(cssRule[2])) {
        for (const selector of splitCssSelectors(cssRule[1])) {
          rules.push({ selector });
        }
      }
      cssRule = rulePattern.exec(stylesheet);
    }
    styleBlock = styleBlockPattern.exec(html);
  }

  return rules;
}

function selectorMatches(element: Element, selector: string): boolean {
  try {
    return element.matches(selector);
  } catch {
    return false;
  }
}

function stylesheetPageBreakHints(
  element: Element,
  stylesheetRules: ReaderStylesheetPaginationRule[],
): Pick<ReaderRichBlock, 'pageBreakAfter' | 'pageBreakBefore' | 'pageBreakInsideAvoid'> {
  const hints: Pick<ReaderRichBlock, 'pageBreakAfter' | 'pageBreakBefore' | 'pageBreakInsideAvoid'> = {};
  for (const rule of stylesheetRules) {
    if (!selectorMatches(element, rule.selector)) continue;
    if (rule.pageBreakAfter) hints.pageBreakAfter = true;
    if (rule.pageBreakBefore) hints.pageBreakBefore = true;
    if (rule.pageBreakInsideAvoid) hints.pageBreakInsideAvoid = true;
  }
  return hints;
}

function elementPageBreakHints(
  element: Element,
  stylesheetRules: ReaderStylesheetPaginationRule[] = [],
): Pick<ReaderRichBlock, 'pageBreakAfter' | 'pageBreakBefore' | 'pageBreakInsideAvoid'> {
  const style = element.getAttribute('style');
  const tokenBreakBefore = hasExplicitPageBreakBeforeToken(element);
  const tokenBreakAfter = hasExplicitPageBreakAfterToken(element);
  const isHorizontalRule = element.matches('hr');
  const stylesheetHints = stylesheetPageBreakHints(element, stylesheetRules);
  return {
    pageBreakAfter: styleHasPageBreak(style, 'after') || tokenBreakAfter || isHorizontalRule || stylesheetHints.pageBreakAfter ? true : undefined,
    pageBreakBefore: styleHasPageBreak(style, 'before') || tokenBreakBefore || stylesheetHints.pageBreakBefore ? true : undefined,
    pageBreakInsideAvoid: (
      styleHasBreakInsideAvoid(style)
      || hasBreakInsideAvoidToken(element)
      || isSemanticKeepTogetherBlock(element)
      || stylesheetHints.pageBreakInsideAvoid
    ) ? true : undefined,
  };
}

export function htmlTextContent(value: string): string {
  const html = value.trim();
  if (!html) return '';

  const readableHtml = stripNonReadingHtml(html);
  if (typeof DOMParser !== 'undefined') {
    const hiddenRules = extractStylesheetHiddenRules(html);
    const documentRef = new DOMParser().parseFromString(readableHtml, 'text/html');
    documentRef.querySelectorAll(nonReadingSelector).forEach((element) => element.remove());
    removeCssHiddenElements(documentRef.body);
    removeStylesheetHiddenElements(documentRef.body, hiddenRules);
    removeRubyAnnotationElements(documentRef.body);
    const textWithoutAriaHidden = normalizedText(visibleDomText(documentRef.body, { includeAriaHidden: false }));
    if (textWithoutAriaHidden) return textWithoutAriaHidden;
    return normalizedText(visibleDomText(documentRef.body, { includeAriaHidden: true }));
  }

  return normalizedText(
    readableHtml
      .replace(/<(?:script|style|noscript|template)\b[^>]*>.*?<\/(?:script|style|noscript|template)>/gis, ' ')
      .replace(/<(?:rt|rp)\b[^>]*>.*?<\/(?:rt|rp)>/gis, ' ')
      .replace(/<[^>]+>/g, ' ')
      .replace(/&nbsp;/gi, ' '),
  );
}

export function richBlockNeedsTextMirror(block: Pick<ReaderRichBlock, 'html' | 'text'>): boolean {
  return Boolean(block.text.trim()) && !htmlTextContent(block.html);
}

function structuredText(node: Node, options: StructuredTextOptions = {}): string {
  if (node.nodeType === Node.TEXT_NODE) return node.textContent ?? '';
  if (node.nodeType !== Node.ELEMENT_NODE) return '';

  const element = node as Element;
  if (element.matches(nonReadingSelector) || isCssHiddenElement(element)) return '';
  if (element.matches(rubyAnnotationSelector)) return '';
  if (!options.includeAriaHidden && isAriaHiddenElement(element)) return '';
  const label = elementLabel(element, options);
  if (label && element.matches('audio,img,math,picture,svg,video')) return label;
  return joinReadableTextParts(Array.from(element.childNodes).map((child) => structuredText(child, options)));
}

function elementLabel(element: Element, options: StructuredTextOptions = {}): string {
  const explicitLabel = normalizedText(
    element.getAttribute('aria-label')
      || element.getAttribute('alt')
      || element.getAttribute('title')
      || '',
  );
  if (explicitLabel) return explicitLabel;

  const image = element.matches('img') ? element : element.querySelector('img');
  if (image instanceof HTMLImageElement) {
    const imageLabel = normalizedText(image.alt || image.getAttribute('title') || '');
    if (imageLabel) return imageLabel;
  }

  const titleElement = element.querySelector('title,figcaption');
  const titleText = normalizedText(titleElement ? structuredText(titleElement, options) : '');
  if (titleText) return titleText;

  return '';
}

function fallbackMediaText(element: Element): string {
  if (element.matches('audio') || element.querySelector('audio')) return 'Âm thanh';
  if (element.matches('video') || element.querySelector('video')) return 'Video';
  if (element.matches('math') || element.querySelector('math')) return 'Công thức';
  if (element.matches('img,picture,svg') || element.querySelector('img,picture,svg')) return 'Hình ảnh';
  if (element.matches('hr')) return 'Ngắt trang';
  return '';
}

function elementKind(element: Element): ReaderRichBlock['kind'] {
  if (element.matches('img,picture,svg') || element.querySelector('img')) return 'image';
  if (element.matches('aside,audio,dl,figure,hr,math,ol,pre,table,ul,video')) return 'structure';
  if (element.matches('p,blockquote,h1,h2,h3,h4,h5,h6')) return 'text';
  return 'html';
}

function blockText(element: Element): string {
  const label = elementLabel(element);
  if (label && element.matches('audio,img,math,picture,svg,video')) return label;
  if (element.matches('figure')) {
    const captionElement = element.querySelector('figcaption');
    const captionText = normalizedText(captionElement ? structuredText(captionElement) : '');
    if (captionText) return captionText;
    const image = element.querySelector('img');
    const imageText = image instanceof HTMLImageElement ? normalizedText(image.alt) : '';
    const readableText = normalizedText(structuredText(element));
    const ariaHiddenFallbackText = normalizedText(structuredText(element, { includeAriaHidden: true }));
    return imageText || label || readableText || ariaHiddenFallbackText || fallbackMediaText(element);
  }
  const text = normalizedText(structuredText(element));
  if (text) return text;
  const ariaHiddenFallbackText = normalizedText(structuredText(element, { includeAriaHidden: true }));
  return label || ariaHiddenFallbackText || fallbackMediaText(element);
}

function textBlockElement(parent: Element, text: string): Element {
  const paragraph = parent.ownerDocument.createElement('p');
  paragraph.textContent = text;
  return paragraph;
}

function isInlineRunNode(node: Node): boolean {
  if (node.nodeType === Node.TEXT_NODE) return Boolean(normalizedText(node.textContent));
  if (node.nodeType !== Node.ELEMENT_NODE) return false;
  const element = node as Element;
  if (element.matches(nonReadingSelector) || isCssHiddenElement(element)) return false;
  return (
    !element.matches(leafBlockSelector)
    && !element.matches(wrapperBlockSelector)
    && !element.querySelector(leafBlockSelector)
    && Boolean(normalizedText(structuredText(element)))
  );
}

function inlineRunTextElement(parent: Element, nodes: Node[]): Element | null {
  const paragraph = parent.ownerDocument.createElement('p');

  function appendSeparator(nextText: string): void {
    const currentText = paragraph.textContent ?? '';
    if (!currentText.trim()) return;
    if (/^[,.;:!?，。！？；：)\]}]/u.test(nextText)) return;
    if (/[([{]$/u.test(currentText.trim())) return;
    paragraph.append(' ');
  }

  for (const node of nodes) {
    const text = normalizedText(structuredText(node));
    if (!text) continue;
    appendSeparator(text);
    if (node.nodeType === Node.TEXT_NODE) {
      paragraph.append(text);
    } else {
      paragraph.append(node.cloneNode(true));
    }
  }

  return paragraph.textContent?.trim() ? paragraph : null;
}

function applyWrapperPageBreakHints(
  blocks: NormalizedRichBlockElement[],
  hints: Pick<ReaderRichBlock, 'pageBreakAfter' | 'pageBreakBefore' | 'pageBreakInsideAvoid'>,
): NormalizedRichBlockElement[] {
  if (blocks.length === 0) return blocks;
  const normalizedBlocks = [...blocks];
  if (hints.pageBreakBefore) {
    normalizedBlocks[0] = { ...normalizedBlocks[0], pageBreakBefore: true };
  }
  if (hints.pageBreakAfter) {
    const lastIndex = normalizedBlocks.length - 1;
    normalizedBlocks[lastIndex] = { ...normalizedBlocks[lastIndex], pageBreakAfter: true };
  }
  if (hints.pageBreakInsideAvoid) {
    return normalizedBlocks.map((block) => ({ ...block, pageBreakInsideAvoid: true }));
  }
  return normalizedBlocks;
}

function splitTextLeafElementByPageBreakMarkers(
  element: Element,
  hints: Pick<ReaderRichBlock, 'pageBreakAfter' | 'pageBreakBefore' | 'pageBreakInsideAvoid'>,
  stylesheetRules: ReaderStylesheetPaginationRule[],
): NormalizedRichBlockElement[] | null {
  if (!element.matches('p,blockquote,h1,h2,h3,h4,h5,h6')) return null;
  const markers = Array.from(element.querySelectorAll('*'))
    .filter((marker) => hasInlinePageBreakMarker(marker, stylesheetRules));
  if (markers.length === 0) return null;

  const blocks: NormalizedRichBlockElement[] = [];
  let previousMarker: Element | null = null;
  let pendingPageBreakBefore = Boolean(hints.pageBreakBefore);

  function appendRange(range: Range): void {
    const wrapper = copyElementShell(element);
    wrapper.append(range.cloneContents());
    if (!normalizedText(wrapper.textContent)) return;
    blocks.push({
      element: wrapper,
      pageBreakBefore: pendingPageBreakBefore ? true : undefined,
      pageBreakInsideAvoid: hints.pageBreakInsideAvoid,
    });
    pendingPageBreakBefore = false;
  }

  for (const marker of markers) {
    const range = element.ownerDocument.createRange();
    if (previousMarker) {
      range.setStartAfter(previousMarker);
    } else {
      range.setStart(element, 0);
    }
    range.setEndBefore(marker);
    appendRange(range);
    pendingPageBreakBefore = true;
    previousMarker = marker;
  }

  const range = element.ownerDocument.createRange();
  if (previousMarker) {
    range.setStartAfter(previousMarker);
  } else {
    range.setStart(element, 0);
  }
  range.setEnd(element, element.childNodes.length);
  appendRange(range);

  if (blocks.length === 0) return [];
  if (hints.pageBreakAfter || pendingPageBreakBefore) {
    const lastIndex = blocks.length - 1;
    blocks[lastIndex] = { ...blocks[lastIndex], pageBreakAfter: true };
  }
  return blocks;
}

function normalizeChildBlockElements(
  parent: Element,
  nodes: Node[],
  stylesheetRules: ReaderStylesheetPaginationRule[] = [],
): NormalizedRichBlockElement[] {
  const blocks: NormalizedRichBlockElement[] = [];
  let inlineRun: Node[] = [];
  let pendingPageBreakBefore = false;

  function appendBlock(block: NormalizedRichBlockElement): void {
    if (pendingPageBreakBefore) {
      blocks.push({ ...block, pageBreakBefore: true });
      pendingPageBreakBefore = false;
      return;
    }
    blocks.push(block);
  }

  function appendBlocks(nextBlocks: NormalizedRichBlockElement[]): void {
    for (const block of nextBlocks) appendBlock(block);
  }

  function flushInlineRun(): void {
    const element = inlineRunTextElement(parent, inlineRun);
    if (element) appendBlock({ element });
    inlineRun = [];
  }

  for (const node of nodes) {
    if (isInlineRunNode(node)) {
      inlineRun.push(node);
      continue;
    }

    if (node.nodeType === Node.TEXT_NODE) {
      continue;
    }

    flushInlineRun();
    if (node.nodeType === Node.ELEMENT_NODE) {
      const element = node as Element;
      const normalizedBlocks = normalizeBlockElement(element, stylesheetRules);
      if (normalizedBlocks.length > 0) {
        appendBlocks(normalizedBlocks);
      } else {
        const hints = elementPageBreakHints(element, stylesheetRules);
        if (hints.pageBreakBefore || hints.pageBreakAfter) {
          pendingPageBreakBefore = true;
        }
      }
    }
  }

  flushInlineRun();
  if (pendingPageBreakBefore && blocks.length > 0) {
    const lastIndex = blocks.length - 1;
    blocks[lastIndex] = { ...blocks[lastIndex], pageBreakAfter: true };
  }
  return blocks;
}

function normalizeBlockElement(
  element: Element,
  stylesheetRules: ReaderStylesheetPaginationRule[] = [],
): NormalizedRichBlockElement[] {
  if (element.matches(nonReadingSelector) || isCssHiddenElement(element)) return [];
  if (element.matches('hr') && hasExplicitPageBreakToken(element)) return [];
  const hints = elementPageBreakHints(element, stylesheetRules);
  const splitBlocks = splitTextLeafElementByPageBreakMarkers(element, hints, stylesheetRules);
  if (splitBlocks) return splitBlocks;
  if (element.matches(leafBlockSelector)) return [{ element, ...hints }];

  const childBlocks = normalizeChildBlockElements(element, Array.from(element.childNodes), stylesheetRules);
  if (childBlocks.length > 0) return applyWrapperPageBreakHints(childBlocks, hints);

  if (
    element.matches(wrapperBlockSelector)
    && (hints.pageBreakBefore || hints.pageBreakAfter)
    && !normalizedText(structuredText(element))
    && !element.querySelector('audio,img,math,picture,svg,video')
  ) {
    return [];
  }

  if (element.matches(wrapperBlockSelector) || element.querySelector('img')) return [{ element, ...hints }];
  return [];
}

export function extractReaderRichBlocks(contentHtml: string): ReaderRichBlock[] {
  const html = contentHtml.trim();
  if (!html) return [];
  const stylesheetRules = extractStylesheetPaginationRules(html);
  const stylesheetHiddenRules = extractStylesheetHiddenRules(html);
  const readableHtml = stripNonReadingHtml(html).trim();
  if (!readableHtml) return [];

  if (typeof DOMParser === 'undefined') {
    return [{
      html: readableHtml,
      index: 0,
      kind: /<img\b/i.test(readableHtml) ? 'image' : 'html',
      text: normalizedText(readableHtml.replace(/<[^>]+>/g, ' ')),
    }];
  }

  const documentRef = new DOMParser().parseFromString(readableHtml, 'text/html');
  removeCssHiddenElements(documentRef.body);
  removeStylesheetHiddenElements(documentRef.body, stylesheetHiddenRules);
  const blocks: Array<Omit<ReaderRichBlock, 'index'>> = [];

  for (const block of normalizeChildBlockElements(documentRef.body, Array.from(documentRef.body.childNodes), stylesheetRules)) {
    removeRedundantAriaHiddenElements(block.element);
    const richText = blockText(block.element);
    if (!richText && !block.element.querySelector('img') && !block.element.matches('img,hr')) continue;
    blocks.push({
      html: block.element.outerHTML,
      kind: elementKind(block.element),
      pageBreakAfter: block.pageBreakAfter,
      pageBreakBefore: block.pageBreakBefore,
      pageBreakInsideAvoid: block.pageBreakInsideAvoid,
      text: richText,
    });
  }

  if (blocks.length === 0) {
    const text = normalizedText(structuredText(documentRef.body) || structuredText(documentRef.body, { includeAriaHidden: true }));
    return text ? [{ html: `<p>${escapeHtml(text)}</p>`, index: 0, kind: 'text', text }] : [];
  }

  return blocks.map((block, index) => ({ ...block, index }));
}

export function sliceReaderRichBlockHtml(
  html: string,
  fallbackText: string,
  startChar: number,
  endChar: number,
): string {
  const safeStart = Math.max(0, Math.round(startChar));
  const safeEnd = Math.max(safeStart, Math.round(endChar));
  const fallbackSlice = fallbackText.slice(safeStart, safeEnd);
  const fallbackHtml = `<p>${escapeHtml(fallbackSlice)}</p>`;

  if (!fallbackSlice || typeof DOMParser === 'undefined') return fallbackHtml;

  const documentRef = new DOMParser().parseFromString(html, 'text/html');
  const sourceElement = documentRef.body.firstElementChild;
  if (!sourceElement) return fallbackHtml;
  removeRedundantAriaHiddenElements(sourceElement);

  const start = textPositionAtOffset(sourceElement, safeStart);
  const end = textPositionAtOffset(sourceElement, safeEnd);
  if (!start || !end) return fallbackHtml;

  try {
    const range = documentRef.createRange();
    range.setStart(start.node, start.offset);
    range.setEnd(end.node, end.offset);
    const fragment = range.cloneContents();
    const wrapper = copyElementShell(sourceElement);
    wrapper.append(fragment);
    removeCssHiddenElements(wrapper);
    removeRedundantAriaHiddenElements(wrapper);
    removeRubyAnnotationElements(wrapper);
    return wrapper.textContent?.trim() ? wrapper.outerHTML : fallbackHtml;
  } catch {
    return fallbackHtml;
  }
}
