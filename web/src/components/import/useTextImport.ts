import { useMemo, useState, type ChangeEvent } from 'react';
import type { EbookDuplicateStrategy, JobStartResponse, WizardTextImportResult } from '../../api/types';
import { detectImportMetadata, type DetectedImportMetadata } from '../../state/importMetadata';
import { buildImportPreview, detectImportContentKind, type DetectedImportChapter, type ImportContentKind } from '../../state/importWizard';
import { errorMessage, formatBytes } from './importLabels';
import type { FinalImportAction, ImportMode, ImportPanelProps } from './types';

const MAX_BROWSER_TEXT_UPLOAD_BYTES = 5 * 1024 * 1024;
const TEXT_IMPORT_SUFFIXES = new Set(['.txt', '.md', '.markdown', '.html', '.htm']);
const TEXT_IMPORT_MIME_TYPES = new Set(['', 'text/plain', 'text/markdown', 'text/html']);
function textByteLength(value: string): number {
  return new TextEncoder().encode(value).length;
}

function hasUnsupportedEncodingMarkers(value: string): boolean {
  const replacementCount = value.match(/\uFFFD/g)?.length ?? 0;
  if (replacementCount === 0) return false;
  return replacementCount > Math.max(4, value.length * 0.01);
}

function isSupportedTextImportFile(file: File): boolean {
  const lowered = file.name.toLowerCase();
  const dotIndex = lowered.lastIndexOf('.');
  const suffix = dotIndex >= 0 ? lowered.slice(dotIndex) : '';
  return TEXT_IMPORT_SUFFIXES.has(suffix) && TEXT_IMPORT_MIME_TYPES.has(file.type);
}

export function useTextImport({ mode, books = [], chapters = [], targetBookId, duplicateStrategy,
  onImportWizardText, onCreateTranslationJob, onCreateTtsJob, onJobCreated }: Pick<ImportPanelProps,
  'books' | 'chapters' | 'onImportWizardText' | 'onCreateTranslationJob' | 'onCreateTtsJob'> & {
  mode: ImportMode;
  duplicateStrategy: EbookDuplicateStrategy;
  targetBookId: string;
  onJobCreated(job: JobStartResponse | null): void;
}) {
  const [title, setTitle] = useState('');
  const [chapterNumber, setChapterNumber] = useState('1');
  const [chapterTitle, setChapterTitle] = useState('');
  const [text, setText] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [titleDirty, setTitleDirty] = useState(false);
  const [chapterNumberDirty, setChapterNumberDirty] = useState(false);
  const [chapterTitleDirty, setChapterTitleDirty] = useState(false);
  const [fileText, setFileText] = useState('');
  const [contentKind, setContentKind] = useState<ImportContentKind>('unknown');
  const [finalAction, setFinalAction] = useState<FinalImportAction>('open');
  const [overwriteConfirmed, setOverwriteConfirmed] = useState(false);
  const [chapterEdits, setChapterEdits] = useState<Record<number, { chapterNumber?: string; title?: string }>>({});
  const [lastWizardResult, setLastWizardResult] = useState<WizardTextImportResult | null>(null);
  const [wizardError, setWizardError] = useState('');
  const parsedChapterNumber = Number.parseInt(chapterNumber, 10);
  const importFields = {
    title,
    chapter_number: Number.isNaN(parsedChapterNumber) ? 1 : parsedChapterNumber,
    chapter_title: chapterTitle,
  };
  const textDraft = mode === 'file' ? fileText : text;
  const selectedTargetBookId = targetBookId ? Number.parseInt(targetBookId, 10) : null;
  const inferredTargetBook = !selectedTargetBookId && title.trim()
    ? books.find((book) => book.title.trim().toLowerCase() === title.trim().toLowerCase())
    : null;
  const effectiveTargetBookId = selectedTargetBookId ?? inferredTargetBook?.id ?? null;
  const existingChaptersForTarget = useMemo(
    () => (
      effectiveTargetBookId
        ? chapters.filter((chapter) => chapter.book_id === effectiveTargetBookId)
        : []
    ),
    [chapters, effectiveTargetBookId],
  );
  const textPreview = useMemo(
    () => (
      textDraft.trim()
        ? buildImportPreview({
          text: textDraft,
          selectedKind: contentKind,
          existingChapters: existingChaptersForTarget,
        })
        : null
    ),
    [contentKind, existingChaptersForTarget, textDraft],
  );
  function parsedTargetBookId(value = targetBookId): number | null {
    return value ? Number.parseInt(value, 10) : null;
  }

  function applyDetectedMetadata(metadata: DetectedImportMetadata): void {
    if (metadata.title) {
      setTitle((current) => (!titleDirty ? metadata.title : current));
    }
    if (metadata.chapterNumber !== null) {
      setChapterNumber((current) => {
        return !chapterNumberDirty ? String(metadata.chapterNumber) : current;
      });
    }
    if (metadata.chapterTitle) {
      setChapterTitle((current) => (!chapterTitleDirty ? metadata.chapterTitle : current));
    }
  }

  function detectFromSource(nextText: string, filename = ''): void {
    applyDetectedMetadata(
      detectImportMetadata({
        title: titleDirty ? title : '',
        chapterNumber: chapterNumberDirty && !Number.isNaN(parsedChapterNumber) ? parsedChapterNumber : null,
        chapterTitle: chapterTitleDirty ? chapterTitle : '',
        text: nextText,
        filename,
      }),
    );
  }

  function updateDetectedContentKind(nextText: string): void {
    const detected = detectImportContentKind(nextText);
    if (detected !== 'unknown') {
      setContentKind((current) => (current === 'unknown' ? detected : current));
    }
  }

  function handleTitleChange(event: ChangeEvent<HTMLInputElement>): void {
    setTitleDirty(true);
    setTitle(event.target.value);
  }

  function handleChapterNumberChange(event: ChangeEvent<HTMLInputElement>): void {
    setChapterNumberDirty(true);
    setChapterNumber(event.target.value);
  }

  function handleChapterTitleChange(event: ChangeEvent<HTMLInputElement>): void {
    setChapterTitleDirty(true);
    setChapterTitle(event.target.value);
  }

  function handleTextChange(event: ChangeEvent<HTMLTextAreaElement>): void {
    const nextText = event.target.value;
    if (textByteLength(nextText) > MAX_BROWSER_TEXT_UPLOAD_BYTES) {
      setWizardError(`Pasted text is too large (${formatBytes(textByteLength(nextText))}). Split it into smaller imports or use server-side import.`);
      return;
    }
    setText(nextText);
    detectFromSource(nextText);
    updateDetectedContentKind(nextText);
    setLastWizardResult(null);
    onJobCreated(null);
    setWizardError('');
  }

  async function handleFileChange(event: ChangeEvent<HTMLInputElement>): Promise<void> {
    const nextFile = event.target.files?.[0] ?? null;
    setFile(nextFile);
    setFileText('');
    setLastWizardResult(null);
    onJobCreated(null);
    setWizardError('');
    if (!nextFile) return;
    if (onImportWizardText && !isSupportedTextImportFile(nextFile)) {
      setFile(null);
      setWizardError('Unsupported TXT import file type. Use TXT, Markdown, HTML, or the Ebook flow for EPUB/AZW3/MOBI/PRC.');
      return;
    }
    if (onImportWizardText && nextFile.size > MAX_BROWSER_TEXT_UPLOAD_BYTES) {
      setFile(null);
      setWizardError(`TXT file is too large (${formatBytes(nextFile.size)}). Use a smaller text file or server-side ebook import.`);
      return;
    }

    try {
      const nextText = await nextFile.text();
      if (onImportWizardText && hasUnsupportedEncodingMarkers(nextText)) {
        setFile(null);
        setWizardError('Encoding không được hỗ trợ hoặc file bị lỗi. Hãy lưu lại file dưới dạng UTF-8 rồi thử lại.');
        return;
      }
      if (onImportWizardText && !nextText.trim()) {
        setFile(null);
        setWizardError('File is empty.');
        return;
      }
      setFileText(nextText);
      detectFromSource(nextText, nextFile.name);
      updateDetectedContentKind(nextText);
    } catch {
      detectFromSource('', nextFile.name);
      setWizardError('Không đọc được file này trong trình duyệt. Hãy kiểm tra encoding hoặc dùng Server inbox nếu file lớn.');
    }
  }

  function handleChapterEdit(index: number, field: 'chapterNumber' | 'title', value: string): void {
    setChapterEdits((current) => ({
      ...current,
      [index]: {
        ...current[index],
        [field]: value,
      },
    }));
  }

  function reviewedChapter(chapter: DetectedImportChapter, index: number) {
    const edit = chapterEdits[index] ?? {};
    const editedNumber = Number.parseInt(edit.chapterNumber ?? '', 10);
    return {
      chapter_number: Number.isFinite(editedNumber) && editedNumber > 0 ? editedNumber : chapter.chapterNumber,
      chapter_title: (edit.title ?? chapter.title).trim() || `Chương ${chapter.chapterNumber}`,
      text: chapter.text,
    };
  }

  async function submitWizardText(sourceType: 'paste' | 'txt'): Promise<void> {
    if (!onImportWizardText || !textPreview) return;
    setWizardError('');
    setLastWizardResult(null);
    onJobCreated(null);
    try {
      const result = await onImportWizardText({
        title: title.trim(),
        target_book_id: parsedTargetBookId() ?? undefined,
        content_kind: contentKind,
        duplicate_strategy: duplicateStrategy,
        source_type: sourceType,
        chapters: textPreview.chapters.map((chapter, index) => reviewedChapter(chapter, index)),
      }, { finalAction });
      const resolvedResult = result ?? null;
      setLastWizardResult(resolvedResult);
      if (!resolvedResult) return;

      if (finalAction === 'translate' && onCreateTranslationJob && resolvedResult.chapter_ids.length > 0) {
        const job = await onCreateTranslationJob(resolvedResult.book_id, resolvedResult.chapter_ids);
        onJobCreated(job ?? null);
      } else if (finalAction === 'tts' && onCreateTtsJob && resolvedResult.chapter_ids.length > 0) {
        const job = await onCreateTtsJob(resolvedResult.book_id, resolvedResult.chapter_ids);
        onJobCreated(job ?? null);
      }
    } catch (error) {
      setWizardError(errorMessage(error));
    }
  }

  return {
    title, chapterNumber, chapterTitle, text, file, fileText, contentKind, finalAction,
    overwriteConfirmed, lastWizardResult, wizardError, importFields, textPreview,
    handleTitleChange, handleChapterNumberChange, handleChapterTitleChange, handleTextChange,
    handleFileChange, handleChapterEdit, submitWizardText, setContentKind,
    setFinalAction, setOverwriteConfirmed,
    clearWizardResult: () => setLastWizardResult(null),
    applyPreviewTitle: (previewTitle: string) => { if (!titleDirty && previewTitle) setTitle(previewTitle); },
  };
}
