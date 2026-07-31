import type {
  Book,
  ChapterApi,
  GlossaryTerm,
  Provider,
  ProviderUsage,
  QaReport,
  StyleProfile,
} from '../api/types';

export const fixtureProvider: Provider = {
  id: 'gemini',
  label: 'Live Gemini',
  base_url: 'https://generativelanguage.googleapis.com/v1beta/openai',
  model: 'gemini-live',
  api_key_env: 'GEMINI_API_KEY',
  api_key_set: true,
  temperature: 0.2,
  timeout_seconds: 60,
  supports_streaming: 1,
  supports_batch: 0,
  cost_input_per_1m: 0.1,
  cost_output_per_1m: 0.4,
  enabled: 1,
  notes: 'Loaded from backend',
};

export const fixtureMissingKeyProvider: Provider = {
  ...fixtureProvider,
  id: 'missing',
  label: 'Missing Key Provider',
  api_key_env: 'MISSING_KEY',
  api_key_set: false,
  notes: 'Missing test key',
};

export const fixtureBook: Book = {
  id: 42,
  title: 'Live Book',
  author: '',
  source: 'manual',
  source_url: '',
  created_at: '2026-06-20T00:00:00Z',
  updated_at: '2026-06-20T00:00:00Z',
};

export const fixtureChapter: ChapterApi = {
  id: 4201,
  book_id: 42,
  chapter_number: 1,
  title: 'Live Chapter',
  status: 'translated',
  source_url: '',
  raw_text_path: null,
  cleaned_text_path: '/tmp/cleaned.txt',
  translated_text_path: '/tmp/translated.txt',
  content_html_path: null,
  audio_path: null,
  translated_at: '2026-06-20T00:00:00Z',
  audio_created_at: null,
};

export const fixtureStyleProfile: StyleProfile = {
  id: 'tien_hiep',
  label: 'Tiên hiệp',
  pronoun_rules: 'ta/ngươi, đạo hữu, tiền bối',
  han_viet_level: 'high',
  preferred_terms: 'tu luyện, tu vi, cảnh giới',
  banned_modern_terms: 'tôi, bạn, ok',
  prompt_rules: 'Văn phong cổ trang tu luyện.',
  is_default: 1,
};

export const fixtureGlossaryTerm: GlossaryTerm = {
  id: 7,
  book_id: 42,
  source_term: '筑基',
  target_term: 'Trúc Cơ',
  category: 'realm',
  approved: 0,
  priority: 40,
  locked: 1,
  review_status: 'NEEDS_REVIEW',
  genre: 'tien_hiep',
  term_type: 'realm',
};

export const fixtureQaReport: QaReport = {
  book_id: 42,
  chapter_id: 4201,
  quality_score: 8.5,
  fidelity_score: 9,
  style_score: 8,
  glossary_score: 7.5,
  audiobook_score: 8,
  verdict: 'PASS',
  issues: [{ type: 'term_inconsistency', message: 'Check 筑基 usage' }],
};

export const fixtureUsage: ProviderUsage = {
  total_prompt_tokens: 0,
  total_completion_tokens: 0,
  total_tokens: 0,
  total_estimated_cost_usd: 0,
};
