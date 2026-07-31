import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { GlossaryTerm, TmSearchResult } from '../api/types';
import AssistPanel from './AssistPanel';

const relevantTerms: GlossaryTerm[] = [
  {
    id: 7,
    book_id: 42,
    source_term: '筑基',
    target_term: 'Trúc Cơ',
    approved: 0,
    priority: 40,
    locked: 1,
    genre: 'tien_hiep',
    term_type: 'realm',
  },
];

const tmResults: TmSearchResult[] = [
  {
    source_text: '他开始筑基。',
    translation_text: 'Hắn bắt đầu Trúc Cơ.',
    match_score: 92,
  },
];

describe('AssistPanel', () => {
  afterEach(() => {
    cleanup();
  });

  it('shows pending glossary count and relevant source/target terms', () => {
    render(
      <AssistPanel
        activeJob={null}
        glossaryError=""
        pendingGlossaryCount={2}
        qaIssues={[]}
        qaState="empty"
        relevantTerms={relevantTerms}
        tmError=""
        tmResults={[]}
        tmState="idle"
        onRunQa={vi.fn()}
        onApplyQaFix={vi.fn()}
        onSearchTm={vi.fn()}
      />,
    );

    expect(screen.getByRole('heading', { name: 'Trợ lý dịch' })).toBeInTheDocument();
    expect(screen.getByText('2 thuật ngữ chờ duyệt')).toBeInTheDocument();
    expect(screen.getByText('筑基')).toBeInTheDocument();
    expect(screen.getByText('Trúc Cơ')).toBeInTheDocument();
  });

  it('displays QA empty state and issues when present', () => {
    render(
      <AssistPanel
        activeJob={null}
        glossaryError=""
        pendingGlossaryCount={0}
        qaIssues={[{ type: 'term_inconsistency', message: 'Check 筑基 usage' }]}
        qaState="ready"
        relevantTerms={[]}
        tmError=""
        tmResults={[]}
        tmState="idle"
        onRunQa={vi.fn()}
        onApplyQaFix={vi.fn()}
        onSearchTm={vi.fn()}
      />,
    );

    expect(screen.getByRole('button', { name: 'Chạy QA' })).toBeInTheDocument();
    expect(screen.getByText('term_inconsistency')).toBeInTheDocument();
    expect(screen.getByText('Check 筑基 usage')).toBeInTheDocument();
  });

  it('renders actionable QA issue details and applies the suggested fix', async () => {
    const onApplyQaFix = vi.fn();

    render(
      <AssistPanel
        activeJob={null}
        glossaryError=""
        pendingGlossaryCount={0}
        qaIssues={[
          {
            type: 'pronoun_modern',
            message: 'Xưng hô hiện đại trong thoại cổ trang',
            segment: 'tôi cảm ơn anh',
            reason: 'Không dùng tôi/anh khi gọi Lục ca',
            suggestedFix: 'ta cảm tạ huynh',
          },
        ]}
        qaState="ready"
        relevantTerms={[]}
        tmError=""
        tmResults={[]}
        tmState="idle"
        onRunQa={vi.fn()}
        onApplyQaFix={onApplyQaFix}
        onSearchTm={vi.fn()}
      />,
    );

    expect(screen.getByText('Đoạn lỗi')).toBeInTheDocument();
    expect(screen.getByText('tôi cảm ơn anh')).toBeInTheDocument();
    expect(screen.getByText('Lý do')).toBeInTheDocument();
    expect(screen.getByText('Không dùng tôi/anh khi gọi Lục ca')).toBeInTheDocument();
    expect(screen.getByText('Gợi ý sửa')).toBeInTheDocument();
    expect(screen.getByText('ta cảm tạ huynh')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Apply fix pronoun_modern' }));

    expect(onApplyQaFix).toHaveBeenCalledWith({
      type: 'pronoun_modern',
      message: 'Xưng hô hiện đại trong thoại cổ trang',
      segment: 'tôi cảm ơn anh',
      reason: 'Không dùng tôi/anh khi gọi Lục ca',
      suggestedFix: 'ta cảm tạ huynh',
    });
  });

  it('shows deterministic chapter QA summary and escaped glossary violations', () => {
    render(
      <AssistPanel
        activeJob={null}
        glossaryError=""
        pendingGlossaryCount={0}
        qaIssues={[]}
        qaReport={{
          book_id: 42,
          chapter_id: 4201,
          quality_score: 4,
          overall_status: 'WARNING',
          chinese_leakage_count: 2,
          length_ratio: 0.31,
          missing_paragraph_warning: true,
          repetition_warning: true,
          name_consistency_status: 'PASS',
          term_consistency_status: 'FAIL',
          glossary_violations: [
            {
              source_term: '灵石',
              expected: 'linh thạch',
              message: '<img src=x onerror=alert(1)> phải dùng linh thạch',
            },
          ],
        }}
        qaState="ready"
        relevantTerms={[]}
        tmError=""
        tmResults={[]}
        tmState="idle"
        onRunQa={vi.fn()}
        onApplyQaFix={vi.fn()}
        onSearchTm={vi.fn()}
      />,
    );

    expect(screen.getByText('Trạng thái')).toBeInTheDocument();
    expect(screen.getByText('WARNING')).toBeInTheDocument();
    expect(screen.getByText('Rò chữ Trung')).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();
    expect(screen.getByText('Tỷ lệ dài/ngắn')).toBeInTheDocument();
    expect(screen.getByText('0.31')).toBeInTheDocument();
    expect(screen.getByText('Vi phạm thuật ngữ khóa')).toBeInTheDocument();
    expect(screen.getByText('灵石 -> linh thạch')).toBeInTheDocument();
    expect(screen.getByText('<img src=x onerror=alert(1)> phải dùng linh thạch')).toBeInTheDocument();
    expect(document.querySelector('img[src="x"]')).toBeNull();
  });

  it('submits TM search only from the form and renders real hook results', async () => {
    const onSearchTm = vi.fn();

    render(
      <AssistPanel
        activeJob={null}
        glossaryError=""
        pendingGlossaryCount={0}
        qaIssues={[]}
        qaState="empty"
        relevantTerms={[]}
        tmError=""
        tmResults={tmResults}
        tmState="ready"
        onRunQa={vi.fn()}
        onApplyQaFix={vi.fn()}
        onSearchTm={onSearchTm}
      />,
    );

    const input = screen.getByLabelText('Tìm TM');
    await userEvent.type(input, '他开始筑基。');

    expect(onSearchTm).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole('button', { name: 'Tìm TM' }));

    expect(onSearchTm).toHaveBeenCalledWith('他开始筑基。');
    expect(screen.getByText('TM 92%')).toBeInTheDocument();
    expect(screen.getByText('Hắn bắt đầu Trúc Cơ.')).toBeInTheDocument();
  });
});
