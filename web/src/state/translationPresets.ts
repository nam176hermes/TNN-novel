import type { TranslationPreset } from '../api/types';

export const translationPresets: TranslationPreset[] = [
  {
    id: 'fast_draft',
    label: 'Nhanh',
    description: 'Dịch nháp nhanh bằng một model, bỏ polish và QA.',
    chunk_size: 3500,
  },
  {
    id: 'cheapest',
    label: 'Rẻ nhất',
    description: 'Dịch, polish và QA bằng model rẻ/free.',
  },
  {
    id: 'balanced',
    label: 'Cân bằng',
    description: 'Dịch rẻ, polish bằng model ổn định hơn, QA riêng.',
  },
  {
    id: 'quality_high',
    label: 'Chất lượng cao',
    description: 'QA và rewrite các đoạn lỗi.',
  },
];

export const defaultTranslationPresetId = 'balanced';
