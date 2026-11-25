import type { TConversation } from 'librechat-data-provider';
import { useLocalize } from '~/hooks';

export type Sampling = NonNullable<TConversation['lsmSampling']>;
export type SamplingDraft = Record<keyof Sampling, string>;
export const samplingFields = [
  { key: 'temperature', label: 'com_endpoint_temperature', min: 0, max: 2, step: 'any' },
  { key: 'top_p', label: 'com_endpoint_top_p', min: 0, max: 1, step: 'any' },
  { key: 'max_tokens', label: 'com_endpoint_max_output_tokens', min: 1, max: 2000000, step: 1 },
] as const;

export function samplingDraft(value?: Sampling): SamplingDraft {
  return {
    temperature: value?.temperature == null ? '' : String(value.temperature),
    top_p: value?.top_p == null ? '' : String(value.top_p),
    max_tokens: value?.max_tokens == null ? '' : String(value.max_tokens),
  };
}

export function parseSampling(draft: SamplingDraft): Sampling {
  const result: Sampling = {};
  for (const { key, min, max, step } of samplingFields) {
    if (!draft[key].trim()) continue;
    const value = Number(draft[key]);
    if (!Number.isFinite(value) || value < min || value > max || (step === 1 && !Number.isInteger(value))) {
      throw new Error('Invalid sampling parameter');
    }
    result[key] = value;
  }
  return result;
}

export default function SamplingFields({ value, onChange, prefix = '' }: {
  value: SamplingDraft;
  onChange: (value: SamplingDraft) => void;
  prefix?: string;
}) {
  const localize = useLocalize();
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      {samplingFields.map(({ key, label, min, max, step }) => (
        <label key={key} className="flex min-w-0 flex-col gap-1 text-sm text-text-primary">
          {localize(label)}
          <input
            className="w-full rounded-lg border border-border-medium bg-surface-primary px-3 py-2 text-sm text-text-primary"
            type="number"
            min={min}
            max={max}
            step={step}
            placeholder={localize('com_ui_default')}
            aria-label={prefix ? prefix + ' ' + localize(label) : localize(label)}
            value={value[key]}
            onChange={(event) => onChange({ ...value, [key]: event.target.value })}
          />
        </label>
      ))}
    </div>
  );
}
