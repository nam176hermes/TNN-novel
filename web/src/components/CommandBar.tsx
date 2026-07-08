import { ChevronRight, FileX, Trash2 } from 'lucide-react';
import type { CostEstimate, JobStatus, StyleProfile, TranslationPreset } from '../api/types';

export type CommandBarProps = {
  activeJob: JobStatus | null;
  estimate: CostEstimate | null;
  estimateDisabledReason: string;
  isDirty: boolean;
  selectedPresetId: string;
  selectedStyleProfileId: string;
  styleProfiles: StyleProfile[];
  translationPresets: TranslationPreset[];
  translateDisabledReason: string;
  onEstimate(): void;
  onDeleteChapter(): void;
  onDeleteTranslation(): void;
  onPresetChange(presetId: string): void;
  onStyleProfileChange(styleProfileId: string): void;
  onTranslate(): void;
};

function formatCost(estimate: CostEstimate | null): string {
  if (!estimate) return 'Chưa ước tính';
  return `Chi phí: $${estimate.estimated_cost_usd.toFixed(4)}`;
}

const PRESET_PROVIDER_FLOWS: Record<string, string> = {
  fast_draft: 'DeepSeek dịch nháp -> rule engine local',
  balanced: 'DeepSeek dịch -> Gemini polish -> DeepSeek QA',
  cheapest: 'Gemini dịch -> Gemini polish -> DeepSeek QA',
  quality_high: 'DeepSeek dịch -> Gemini polish -> DeepSeek QA -> Gemini rewrite',
};

function formatPresetProviderFlow(selectedPresetId: string, translationPresets: TranslationPreset[]): string {
  const preset = translationPresets.find((item) => item.id === selectedPresetId);
  const presetLabel = preset?.label ?? selectedPresetId;
  const providerFlow = PRESET_PROVIDER_FLOWS[selectedPresetId] ?? 'provider theo cấu hình backend';

  return `${presetLabel}: ${providerFlow}`;
}

export default function CommandBar({
  activeJob,
  estimate,
  estimateDisabledReason,
  isDirty,
  selectedPresetId,
  selectedStyleProfileId,
  styleProfiles,
  translationPresets,
  translateDisabledReason,
  onEstimate,
  onDeleteChapter,
  onDeleteTranslation,
  onPresetChange,
  onStyleProfileChange,
  onTranslate,
}: CommandBarProps) {
  const estimateDisabled = estimateDisabledReason.length > 0;
  const translateDisabled = translateDisabledReason.length > 0;
  const presetProviderFlow = formatPresetProviderFlow(selectedPresetId, translationPresets);
  const selectedPreset = translationPresets.find((preset) => preset.id === selectedPresetId);

  return (
    <section aria-label="Thanh lệnh" className="command-bar">
      <div className="command-bar-heading">
        <span>Preset dịch</span>
        <ChevronRight aria-hidden="true" size={15} />
      </div>
      <div className="command-bar-controls">
        <label>
          <span>Preset dịch</span>
          <select
            disabled={translationPresets.length === 0}
            onChange={(event) => onPresetChange(event.target.value)}
            value={selectedPresetId}
          >
            {translationPresets.length === 0 ? <option value="">Chưa có preset</option> : null}
            {translationPresets.map((preset) => (
              <option key={preset.id} value={preset.id}>
                {preset.label}
              </option>
            ))}
          </select>
        </label>

        <label>
          <span>Thể loại/văn phong</span>
          <select
            disabled={styleProfiles.length === 0}
            onChange={(event) => onStyleProfileChange(event.target.value)}
            value={selectedStyleProfileId}
          >
            {styleProfiles.length === 0 ? <option value="">Chưa có profile</option> : null}
            {styleProfiles.map((profile) => (
              <option key={profile.id} value={profile.id}>
                {profile.label}
              </option>
            ))}
          </select>
        </label>

        <div className="command-run-control">
          <span>Ước tính</span>
          <div className="command-run-actions">
            <button className="primary-action command-translate-button" disabled={translateDisabled} onClick={onTranslate} type="button">
              Dịch
            </button>
            <button className="secondary-action command-estimate-button" disabled={estimateDisabled} onClick={onEstimate} type="button">
              Ước tính
            </button>
          </div>
        </div>
      </div>

      <div className="command-bar-actions">
        <button className="secondary-action" onClick={onDeleteTranslation} type="button">
          <FileX aria-hidden="true" size={16} />
          Xóa bản dịch
        </button>
        <button className="danger-action" onClick={onDeleteChapter} type="button">
          <Trash2 aria-hidden="true" size={16} />
          Xóa chương
        </button>
      </div>

      <div className="command-bar-status" aria-live="polite">
        <span className="command-bar-provider-flow">{presetProviderFlow}</span>
        {selectedPreset?.chunk_size ? <span>Chunk {selectedPreset.chunk_size} ký tự</span> : null}
        <span>{formatCost(estimate)}</span>
        <span>{isDirty ? 'Chưa lưu' : 'Đã lưu'}</span>
        {estimateDisabledReason ? <span>{estimateDisabledReason}</span> : null}
        {translateDisabledReason ? <span>{translateDisabledReason}</span> : null}
      </div>
    </section>
  );
}
