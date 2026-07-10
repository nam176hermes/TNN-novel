import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import CostEstimateDialog from './CostEstimateDialog';

describe('CostEstimateDialog', () => {
  it('blocks over-budget jobs until user confirms override', () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();

    render(
      <CostEstimateDialog
        estimate={{
          provider_id: 'gemini',
          model: 'gemini-2.5-flash-lite',
          chapter_count: 10,
          estimated_input_tokens: 10000,
          estimated_output_tokens: 12000,
          estimated_cost_usd: 0.02,
          within_budget: false,
        }}
        onCancel={onCancel}
        onConfirm={onConfirm}
      />,
    );

    expect(screen.getByText('Estimated cost: $0.020000')).toBeInTheDocument();
    expect(screen.getByText('Over budget')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Confirm override' }));

    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onCancel).not.toHaveBeenCalled();
  });

  it('starts within-budget jobs directly', () => {
    render(
      <CostEstimateDialog
        estimate={{
          provider_id: 'deepseek',
          model: 'deepseek-v4-flash',
          chapter_count: 2,
          estimated_input_tokens: 3200,
          estimated_output_tokens: 4100,
          estimated_cost_usd: 0.001596,
          within_budget: true,
        }}
        onCancel={() => undefined}
        onConfirm={() => undefined}
      />,
    );

    expect(screen.getByText('Within budget')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Start job' })).toBeInTheDocument();
  });
});
