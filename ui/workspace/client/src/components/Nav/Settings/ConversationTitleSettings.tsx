import { useRecoilState } from 'recoil';
import { useGetModelsQuery } from 'librechat-data-provider/react-query';
import { useLocalize } from '~/hooks';
import { atomWithServerPreference } from '~/store/utils';

const modeAtom = atomWithServerPreference<string>('conversationTitleMode', 'once');
const modelAtom = atomWithServerPreference<string>('conversationTitleModel', '');

export default function ConversationTitleSettings() {
  const localize = useLocalize();
  const [mode, setMode] = useRecoilState(modeAtom);
  const [model, setModel] = useRecoilState(modelAtom);
  const { data } = useGetModelsQuery();
  const models = Object.entries(data ?? {}).flatMap(([channel, ids]) =>
    channel === 'agents'
      ? []
      : ids.map((id) => ({ value: JSON.stringify([channel, id]), label: `${channel} / ${id}` })),
  );
  const selectClass =
    'max-w-[60%] rounded-lg border border-border-medium bg-surface-primary px-2 py-2 text-sm text-text-primary';
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <label htmlFor="conversation-title-mode">{localize('com_lsm_title_mode')}</label>
        <select
          id="conversation-title-mode"
          className={selectClass}
          value={mode}
          onChange={(event) => setMode(event.target.value)}
        >
          <option value="off">{localize('com_lsm_title_off')}</option>
          <option value="once">{localize('com_lsm_title_once')}</option>
          <option value="every">{localize('com_lsm_title_every')}</option>
        </select>
      </div>
      {mode !== 'off' && (
        <div className="flex items-center justify-between gap-3">
          <label htmlFor="conversation-title-model">{localize('com_lsm_title_model')}</label>
          <select
            id="conversation-title-model"
            className={selectClass}
            value={model}
            onChange={(event) => setModel(event.target.value)}
          >
            <option value="">{localize('com_lsm_title_original_model')}</option>
            {model && !models.some((item) => item.value === model) && (
              <option value={model}>{model}</option>
            )}
            {models.map((item) => (
              <option key={item.value} value={item.value}>{item.label}</option>
            ))}
          </select>
        </div>
      )}
      <p className="text-xs text-text-secondary">{localize('com_lsm_title_timing')}</p>
    </div>
  );
}
