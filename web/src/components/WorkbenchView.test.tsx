import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Chapter, CostEstimate, StyleProfile, TranslationPreset } from '../api/types';
import WorkbenchView from './WorkbenchView';

const chapter: Chapter = {
  id: 11,
  book_id: 1,
  chapter_number: 3,
  title: 'Sơn biên tiểu thôn',
  status: 'translated',
  audio_path: '',
};

const styleProfiles: StyleProfile[] = [
  {
    id: 'tien_hiep',
    label: 'Tiên hiệp',
    pronoun_rules: 'ta/ngươi',
    han_viet_level: 'high',
    preferred_terms: 'tu vi',
    banned_modern_terms: 'tôi, bạn',
    prompt_rules: 'cổ trang',
    is_default: 1,
  },
];

const translationPresets: TranslationPreset[] = [
  {
    id: 'fast_draft',
    label: 'Nhanh',
    description: 'Dịch nháp nhanh, bỏ polish và QA.',
  },
  {
    id: 'cheapest',
    label: 'Rẻ nhất',
    description: 'Model rẻ/free',
  },
  {
    id: 'balanced',
    label: 'Cân bằng',
    description: 'Dịch rẻ, polish tốt hơn',
  },
  {
    id: 'quality_high',
    label: 'Chất lượng cao',
    description: 'QA và rewrite lỗi',
  },
];

const estimate: CostEstimate = {
  provider_id: 'openai',
  model: 'gpt-4.1-mini',
  chapter_count: 1,
  estimated_input_tokens: 1200,
  estimated_output_tokens: 1500,
  estimated_cost_usd: 0.004321,
  within_budget: true,
};

function buildWorkbenchProps(overrides: Partial<Parameters<typeof WorkbenchView>[0]> = {}) {
  return {
    activeJob: null,
    assistPanel: <aside aria-label="Assist test panel">Assist panel content</aside>,
    chapter,
    contentHtml: '',
    estimate,
    estimateDisabledReason: '',
    isDirty: true,
    onEstimate: vi.fn(),
    onSave: vi.fn(),
    onDeleteChapter: vi.fn(),
    onDeleteTranslation: vi.fn(),
    onPresetChange: vi.fn(),
    onStyleProfileChange: vi.fn(),
    onTranslate: vi.fn(),
    onTranslationChange: vi.fn(),
    onViewModeChange: vi.fn(),
    selectedPresetId: 'balanced',
    selectedStyleProfileId: 'tien_hiep',
    sourceState: 'ready' as const,
    sourceText: '他点点头。',
    styleProfiles,
    translationPresets,
    translateDisabledReason: '',
    translationText: 'Hắn khẽ gật đầu.',
    viewMode: 'edit' as const,
    ...overrides,
  };
}

function renderWorkbench(overrides: Partial<Parameters<typeof WorkbenchView>[0]> = {}) {
  const props = buildWorkbenchProps(overrides);

  render(<WorkbenchView {...props} />);

  return props;
}

describe('WorkbenchView', () => {
  afterEach(() => {
    cleanup();
  });

  it('renders selected chapter editor content and saves through Lưu', async () => {
    const props = renderWorkbench();

    expect(screen.getByRole('heading', { name: 'Sơn biên tiểu thôn' })).toBeInTheDocument();
    expect(screen.getByText('Bản gốc tiếng Trung')).toBeInTheDocument();
    expect(screen.getByLabelText('Bản dịch tiếng Việt')).toHaveValue('Hắn khẽ gật đầu.');

    await userEvent.click(screen.getByRole('button', { name: 'Lưu' }));

    expect(props.onSave).toHaveBeenCalledOnce();
  });

  it('renders assist panel beside the editor when a chapter exists', () => {
    renderWorkbench();

    expect(screen.getByText('Bản gốc tiếng Trung')).toBeInTheDocument();
    expect(screen.getByRole('complementary', { name: 'Assist test panel' })).toBeInTheDocument();
    expect(screen.getByText('Assist panel content')).toBeInTheDocument();
  });

  it('keeps inline illustrations in a read-only preview outside the translation textarea', () => {
    renderWorkbench({
      contentHtml: '<p>Kiếm khí nổi lên.</p><img src="/book-assets/1/sword.png" alt="Kiếm quang"/>',
      translationText: 'Kiếm khí nổi lên.',
    });

    expect(screen.getByLabelText('Bản dịch tiếng Việt')).toHaveValue('Kiếm khí nổi lên.');
    const preview = screen.getByRole('article', { name: 'Minh họa trong chương' });
    expect(preview).toHaveTextContent('Kiếm khí nổi lên.');
    expect(screen.getByRole('img', { name: 'Kiếm quang' })).toHaveAttribute('src', '/book-assets/1/sword.png');
  });

  it('switches mobile workbench panels between editor and assist', async () => {
    renderWorkbench();
    const workbench = screen.getByRole('region', { name: 'Workbench' });

    expect(workbench).toHaveAttribute('data-mobile-section', 'editor');
    await userEvent.click(screen.getByRole('tab', { name: 'Trợ lý' }));
    expect(workbench).toHaveAttribute('data-mobile-section', 'assist');
    await userEvent.click(screen.getByRole('tab', { name: 'Editor' }));
    expect(workbench).toHaveAttribute('data-mobile-section', 'editor');
  });

  it('disables Dịch with a visible preset workflow reason', () => {
    renderWorkbench({
      translateDisabledReason: 'Chưa chọn preset',
    });

    expect(screen.getByText('Chưa chọn preset')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Dịch' })).toBeDisabled();
  });

  it('lets the operator choose a translation preset instead of a raw model', async () => {
    const props = renderWorkbench();

    expect(screen.queryByLabelText('Model')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Preset dịch')).toHaveValue('balanced');

    await userEvent.selectOptions(screen.getByLabelText('Preset dịch'), 'quality_high');

    expect(props.onPresetChange).toHaveBeenCalledWith('quality_high');
  });

  it('shows the provider flow for the selected translation preset', () => {
    renderWorkbench();

    expect(screen.getByText('Cân bằng: DeepSeek dịch -> Gemini polish -> DeepSeek QA')).toBeInTheDocument();
  });

  it('shows the fast draft provider flow when selected', () => {
    renderWorkbench({ selectedPresetId: 'fast_draft' });

    expect(screen.getByText('Nhanh: DeepSeek dịch nháp -> rule engine local')).toBeInTheDocument();
  });

  it('exposes separate delete actions for translation and chapter', async () => {
    const props = renderWorkbench({
      onDeleteChapter: vi.fn(),
      onDeleteTranslation: vi.fn(),
    });

    await userEvent.click(screen.getByRole('button', { name: 'Xóa bản dịch' }));
    await userEvent.click(screen.getByRole('button', { name: 'Xóa chương' }));

    expect(props.onDeleteTranslation).toHaveBeenCalledOnce();
    expect(props.onDeleteChapter).toHaveBeenCalledOnce();
  });

  it('switches from edit mode to a clean Vietnamese reader mode', async () => {
    function Harness() {
      const [viewMode, setViewMode] = useState<'edit' | 'reader'>('edit');
      return (
        <WorkbenchView
          {...buildWorkbenchProps()}
          assistPanel={<aside aria-label="Assist test panel">Assist panel content</aside>}
          onViewModeChange={setViewMode}
          contentHtml="<p>Hắn khẽ gật đầu.</p><img src=&quot;/book-assets/1/sword.png&quot; alt=&quot;Kiếm&quot;/><p>Lục ca, ta cảm tạ huynh.</p>"
          translationText={'Hắn khẽ gật đầu.\n\nLục ca, ta cảm tạ huynh.'}
          viewMode={viewMode}
        />
      );
    }

    render(<Harness />);

    expect(screen.getByText('Bản gốc tiếng Trung')).toBeInTheDocument();
    expect(screen.getByLabelText('Bản dịch tiếng Việt')).toBeInTheDocument();
    expect(screen.getByRole('complementary', { name: 'Assist test panel' })).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Đọc' }));

    const workbench = screen.getByRole('region', { name: 'Workbench' });
    expect(workbench).toHaveAttribute('data-view-mode', 'reader');
    expect(screen.queryByText('Bản gốc tiếng Trung')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Bản dịch tiếng Việt')).not.toBeInTheDocument();
    expect(screen.queryByRole('complementary', { name: 'Assist test panel' })).not.toBeInTheDocument();
    expect(screen.getByRole('article', { name: 'Bản đọc tiếng Việt' })).toHaveTextContent('Lục ca, ta cảm tạ huynh.');
    expect(screen.getByRole('img', { name: 'Kiếm' })).toHaveAttribute('src', '/book-assets/1/sword.png');
  });

  it('shows the Vietnamese no-chapter empty state', () => {
    renderWorkbench({
      chapter: null,
      dashboard: {
        activeJobCount: 2,
        activities: [{ id: 'a1', label: 'Job retry started', timestampLabel: '3 phút trước' }],
        progressPercent: 64,
        rawBookCount: 4,
        rawChapterCount: 17,
        systemItems: [
          { label: 'API Server', ok: true, statusLabel: 'Hoạt động' },
          { label: 'Dịch vụ dịch', ok: true, statusLabel: 'Gemini' },
        ],
        translatedChapterCount: 128,
      },
      estimate: null,
      estimateDisabledReason: 'Chưa chọn chương',
      isDirty: false,
      sourceText: '',
      translationText: '',
      translateDisabledReason: 'Chưa chọn chương',
    });

    expect(screen.getByRole('heading', { name: 'Chưa chọn chương' })).toBeInTheDocument();
    expect(screen.getByText('Chọn một chương trong danh sách bên trái để bắt đầu biên tập bản dịch.')).toBeInTheDocument();
    expect(screen.queryByRole('complementary', { name: 'Assist test panel' })).not.toBeInTheDocument();
  });

  it('uses live dashboard data and routes dashboard actions from the empty workbench', async () => {
    const onOpenJobs = vi.fn();
    const onOpenStatus = vi.fn();
    renderWorkbench({
      chapter: null,
      dashboard: {
        activeJobCount: 2,
        activities: [{ id: 'a1', label: 'Job retry started', timestampLabel: '3 phút trước' }],
        progressPercent: 64,
        rawBookCount: 4,
        rawChapterCount: 17,
        systemItems: [
          { label: 'API Server', ok: true, statusLabel: 'Hoạt động' },
          { label: 'Dịch vụ dịch', ok: false, statusLabel: 'Chưa chọn' },
        ],
        translatedChapterCount: 128,
      },
      estimate: null,
      estimateDisabledReason: 'Chưa chọn chương',
      isDirty: false,
      onOpenJobs,
      onOpenStatus,
      sourceText: '',
      translationText: '',
      translateDisabledReason: 'Chưa chọn chương',
    });

    expect(screen.getByText('17')).toBeInTheDocument();
    expect(screen.getByText('4 truyện · Dữ liệu hiện tại')).toBeInTheDocument();
    expect(screen.getByText('128')).toBeInTheDocument();
    expect(screen.getByText('64%')).toBeInTheDocument();
    expect(screen.getByText('Job retry started')).toBeInTheDocument();
    expect(screen.getByText('Chưa chọn')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Xem tất cả hoạt động' }));
    await userEvent.click(screen.getByRole('button', { name: 'Xem chi tiết hệ thống' }));

    expect(onOpenJobs).toHaveBeenCalledOnce();
    expect(onOpenStatus).toHaveBeenCalledOnce();
  });
});
