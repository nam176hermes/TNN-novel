import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Chapter, CostEstimate, GlossaryTerm, JobStatus, Provider, StyleProfile } from '../api/types';
import type { QualityMode } from './ProviderCostPanel';
import TranslatorWorkbench from './TranslatorWorkbench';
import type { QualityIssue } from './QualityPanel';

const chapter: Chapter = {
  id: 11,
  book_id: 1,
  chapter_number: 3,
  title: 'Sơn biên tiểu thôn',
  status: 'translated',
  audio_path: '',
  qa_score: 8.2,
  qa_verdict: 'pass',
  qa_issue_count: 9,
  top_issues: ['Do not show chapter summary QA fallback'],
};

const providers: Provider[] = [
  {
    id: 'openai',
    label: 'OpenAI',
    base_url: 'https://api.openai.com/v1',
    model: 'gpt-4.1-mini',
    api_key_env: 'OPENAI_API_KEY',
    api_key_set: true,
    temperature: 0.4,
    timeout_seconds: 60,
    supports_streaming: 1,
    supports_batch: 0,
    cost_input_per_1m: 0.4,
    cost_output_per_1m: 1.6,
    enabled: 1,
    notes: '',
  },
  {
    id: 'missing',
    label: 'Missing Key Provider',
    base_url: 'https://example.test',
    model: 'novel-model',
    api_key_env: 'MISSING_KEY',
    api_key_set: false,
    temperature: 0.4,
    timeout_seconds: 60,
    supports_streaming: 0,
    supports_batch: 0,
    cost_input_per_1m: 0.1,
    cost_output_per_1m: 0.2,
    enabled: 1,
    notes: '',
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

const activeJob: JobStatus = {
  job_id: 'job-1',
  status: 'running',
  progress: 1,
  total: 3,
  message: 'Translating chapter',
};

const qaIssues: QualityIssue[] = [{ type: 'glossary', message: 'Check 灵石' }];

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
  {
    id: 'kiem_hiep',
    label: 'Kiếm hiệp',
    pronoun_rules: 'tại hạ/các hạ',
    han_viet_level: 'balanced',
    preferred_terms: 'giang hồ',
    banned_modern_terms: 'team',
    prompt_rules: 'võ hiệp',
    is_default: 0,
  },
];

const glossaryTerms: GlossaryTerm[] = [
  {
    id: 7,
    book_id: 1,
    source_term: '筑基',
    target_term: 'Trúc Cơ',
    locked: 1,
    genre: 'tien_hiep',
    term_type: 'realm',
    priority: 40,
  },
];

function renderWorkbench(overrides: Partial<Parameters<typeof TranslatorWorkbench>[0]> = {}) {
  const props = {
    activeJob,
    chapter,
    estimate,
    onEstimate: vi.fn(),
    onModeChange: vi.fn(),
    onProviderChange: vi.fn(),
    onRunQa: vi.fn(),
    onSaveTranslation: vi.fn(),
    onGlossaryTermLockToggle: vi.fn(),
    onGlossaryTermUpdate: vi.fn(),
    onTranslate: vi.fn(),
    onTranslationChange: vi.fn(),
    onStyleProfileChange: vi.fn(),
    providers,
    glossaryTerms,
    glossaryPendingCount: 1,
    qaIssues,
    savedTranslationText: 'Hắn gật đầu.',
    selectedMode: 'balanced' as QualityMode,
    selectedProviderId: 'openai',
    selectedStyleProfileId: 'tien_hiep',
    sourceText: '他点点头。',
    styleProfiles,
    translationText: 'Hắn khẽ gật đầu.',
    ...overrides,
  };

  render(<TranslatorWorkbench {...props} />);

  return props;
}

describe('TranslatorWorkbench', () => {
  afterEach(() => {
    cleanup();
  });

  it('renders the selected chapter title and status', () => {
    renderWorkbench();

    expect(screen.getByRole('heading', { name: 'Sơn biên tiểu thôn' })).toBeInTheDocument();
    expect(screen.getByText('translated')).toBeInTheDocument();
    expect(screen.getByText('Chapter 3')).toBeInTheDocument();
  });

  it('wires provider estimate and translate controls', async () => {
    const props = renderWorkbench({ activeJob: null });

    expect(screen.getByText('Estimated cost: $0.0043')).toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText('Provider'), 'missing');
    await userEvent.selectOptions(screen.getByLabelText('Quality mode'), 'careful');
    await userEvent.selectOptions(screen.getByLabelText('Style profile'), 'kiem_hiep');
    await userEvent.click(screen.getByRole('button', { name: 'Estimate' }));
    await userEvent.click(screen.getByRole('button', { name: 'Translate' }));

    expect(props.onProviderChange).toHaveBeenCalledWith('missing');
    expect(props.onModeChange).toHaveBeenCalledWith('careful');
    expect(props.onStyleProfileChange).toHaveBeenCalledWith('kiem_hiep');
    expect(props.onEstimate).toHaveBeenCalledOnce();
    expect(props.onTranslate).toHaveBeenCalledOnce();
  });

  it('disables translate when the selected provider is missing a key', () => {
    renderWorkbench({ activeJob: null, selectedProviderId: 'missing' });

    expect(screen.getByText('Key missing')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Translate' })).toBeDisabled();
  });

  it('wires editor save callback', async () => {
    const props = renderWorkbench();

    await userEvent.click(screen.getByRole('button', { name: 'Save' }));

    expect(props.onSaveTranslation).toHaveBeenCalledWith('Hắn khẽ gật đầu.');
  });

  it('wires editor copy callback', async () => {
    const props = renderWorkbench({ onCopyTranslation: vi.fn() });

    await userEvent.click(screen.getByRole('button', { name: 'Copy' }));

    expect(props.onCopyTranslation).toHaveBeenCalledOnce();
  });

  it('disables the editor while chapter text is loading', () => {
    renderWorkbench({ textLoading: true });

    expect(screen.getByLabelText('Vietnamese translation')).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
  });

  it('wires the QA action', async () => {
    const props = renderWorkbench();

    await userEvent.click(screen.getByRole('button', { name: 'Run QA' }));

    expect(props.onRunQa).toHaveBeenCalledOnce();
  });

  it('renders QA detail scores from the saved report', () => {
    renderWorkbench({
      qaScore: 8.5,
      qaVerdict: 'PASS',
      qaDetails: {
        fidelity: 9,
        style: 8,
        glossary: 7.5,
        audiobook: 8,
      },
    });

    expect(screen.getByText('8.5')).toBeInTheDocument();
    expect(screen.getByText('PASS')).toBeInTheDocument();
    expect(screen.getByText('Fidelity')).toBeInTheDocument();
    expect(screen.getByText('9')).toBeInTheDocument();
    expect(screen.getByText('Style')).toBeInTheDocument();
    expect(screen.getByText('Glossary')).toBeInTheDocument();
    expect(screen.getByText('Audiobook')).toBeInTheDocument();
  });

  it('renders deterministic chapter QA status and glossary violations', () => {
    renderWorkbench({
      qaScore: 3,
      qaVerdict: 'FAIL',
      qaDetails: {
        fidelity: 3,
        style: 6,
        glossary: 4,
      },
      qaOverallStatus: 'FAIL',
      qaChineseLeakageCount: 2,
      qaLengthRatio: 0.31,
      qaMissingParagraphWarning: true,
      qaRepetitionWarning: true,
      qaGlossaryViolations: [
        {
          source_term: '灵石',
          expected: 'linh thạch',
          message: '<img src=x onerror=alert(1)> phải dùng linh thạch',
        },
      ],
    });

    expect(screen.getAllByText('FAIL').length).toBeGreaterThan(0);
    expect(screen.getByText('Chinese leakage')).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();
    expect(screen.getByText('Length ratio')).toBeInTheDocument();
    expect(screen.getByText('0.31')).toBeInTheDocument();
    expect(screen.getByText('Missing paragraphs')).toBeInTheDocument();
    expect(screen.getByText('Repeated text')).toBeInTheDocument();
    expect(screen.getByText('灵石 -> linh thạch')).toBeInTheDocument();
    expect(screen.getByText('<img src=x onerror=alert(1)> phải dùng linh thạch')).toBeInTheDocument();
    expect(document.querySelector('img[src="x"]')).toBeNull();
  });

  it('does not derive QA panel content from chapter summary fields', () => {
    renderWorkbench({
      qaDetails: undefined,
      qaIssues: [],
      qaScore: undefined,
      qaVerdict: undefined,
    });

    expect(screen.getByText('No QA')).toBeInTheDocument();
    expect(screen.queryByText('8.2')).not.toBeInTheDocument();
    expect(screen.queryByText('pass')).not.toBeInTheDocument();
    expect(screen.queryByText('Do not show chapter summary QA fallback')).not.toBeInTheDocument();
  });

  it('uses glossary pending count from glossary state, not chapter QA count', () => {
    renderWorkbench({ glossaryPendingCount: 2 });

    expect(screen.getByText('2 pending terms')).toBeInTheDocument();
    expect(screen.queryByText('9 pending terms')).not.toBeInTheDocument();
  });

  it('renders an empty state without a selected chapter', () => {
    renderWorkbench({
      activeJob: null,
      chapter: null,
      estimate: null,
      qaIssues: [],
      savedTranslationText: null,
      sourceText: '',
      translationText: '',
    });

    expect(screen.getByText('Select a chapter to review.')).toBeInTheDocument();
    expect(screen.queryByLabelText('Chapter editor')).not.toBeInTheDocument();
  });
});
