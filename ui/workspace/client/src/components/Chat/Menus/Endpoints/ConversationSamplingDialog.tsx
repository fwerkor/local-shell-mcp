import { useId, useState } from 'react';
import { Button, OGDialog, OGDialogTemplate } from '@librechat/client';
import { getConfigDefaults, getEndpointField, isParamEndpoint, isAgentsEndpoint } from 'librechat-data-provider';
import type { TConversation, TEndpointsConfig } from 'librechat-data-provider';
import { useUserKeyQuery } from 'librechat-data-provider/react-query';
import { useMenuContext } from '@ariakit/react';
import { SlidersHorizontal } from 'lucide-react';
import { useGetStartupConfig } from '~/data-provider';
import { useModelSelectorChatContext } from './ModelSelectorChatContext';
import store from '~/store';
import SamplingFields, { parseSampling, samplingDraft } from '~/components/Endpoints/SamplingFields';
import { useLocalize } from '~/hooks';

export default function ConversationSamplingDialog({ conversation, onClose, onSave }: {
  conversation: TConversation;
  onClose: () => void;
  onSave: (sampling: NonNullable<TConversation['lsmSampling']>) => void;
}) {
  const localize = useLocalize();
  const [draft, setDraft] = useState(() => samplingDraft(conversation.lsmSampling));
  const formId = useId();
  return (
    <OGDialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <OGDialogTemplate
        title={localize('com_ui_model_parameters')}
        description={localize('com_ui_conversation_sampling_description')}
        className="max-w-xl"
        main={
          <form id={formId} onSubmit={(event) => {
            event.preventDefault();
            onSave(parseSampling(draft));
            onClose();
          }}>
            <SamplingFields value={draft} onChange={setDraft} />
          </form>
        }
        leftButtons={<Button variant="outline" type="button" onClick={() => setDraft(samplingDraft())}>
          {localize('com_ui_reset')}
        </Button>}
        buttons={<Button variant="submit" form={formId} type="submit">{localize('com_ui_save')}</Button>}
      />
    </OGDialog>
  );
}

function SamplingAction({ onClick }: { onClick: () => void }) {
  const localize = useLocalize();
  const menu = useMenuContext();
  return (
    <button
      type="button"
      data-testid="model-selector-parameters"
      aria-label={localize('com_ui_model_parameters')}
      title={localize('com_ui_model_parameters')}
      className="flex size-9 shrink-0 items-center justify-center rounded-lg text-text-secondary hover:bg-surface-hover hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-text-primary"
      onClick={() => { menu?.hide(); onClick(); }}
    >
      <SlidersHorizontal className="size-4" aria-hidden="true" />
    </button>
  );
}

export function useConversationSampling(endpointsConfig: TEndpointsConfig) {
  const { endpoint: currentEndpoint, model, getConversation, selectExistingConversation } = useModelSelectorChatContext();
  const { setConversation } = store.useSetConversationAtom(0);
  const { data: startupConfig } = useGetStartupConfig();
  const endpoint = currentEndpoint ?? '';
  const { data: keyExpiry } = useUserKeyQuery(endpoint);
  const [snapshot, setSnapshot] = useState<TConversation | null>(null);
  const enabled = (startupConfig?.interface ?? getConfigDefaults().interface)?.parameters === true &&
    Boolean(model) && !isAgentsEndpoint(endpoint) &&
    isParamEndpoint(endpoint, getEndpointField(endpointsConfig, endpoint, 'type')) &&
    (!endpointsConfig?.[endpoint]?.userProvide || Boolean(keyExpiry?.expiresAt));
  return {
    action: enabled && <SamplingAction onClick={() => setSnapshot(getConversation())} />,
    dialog: enabled && snapshot && snapshot.model === model && snapshot.endpoint === endpoint && (
      <ConversationSamplingDialog
        conversation={snapshot}
        onClose={() => setSnapshot(null)}
        onSave={(lsmSampling) => {
          if (getConversation()?.conversationId !== snapshot.conversationId) return;
          if (!selectExistingConversation({ lsmSampling })) {
            setConversation((previous) => previous ? { ...previous, lsmSampling } : previous);
          }
        }}
      />
    ),
  };
}
