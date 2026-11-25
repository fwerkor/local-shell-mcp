import React, { createContext, useCallback, useContext, useMemo, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useToastContext } from '@librechat/client';
import { useRecoilValue } from 'recoil';
import { Constants, QueryKeys, dataService } from 'librechat-data-provider';
import type { EModelEndpoint, TConversation, TUpdateConversationRequest } from 'librechat-data-provider';
import type { ConvoGenerator } from '~/common';
import { useGetConversation, useNewConvo } from '~/hooks';
import { NotificationSeverity } from '~/common';
import { updateConvoInAllQueries } from '~/utils';
import store from '~/store';

interface ModelSelectorChatContextValue {
  endpoint?: EModelEndpoint | null;
  model?: string | null;
  spec?: string | null;
  agent_id?: string | null;
  assistant_id?: string | null;
  getConversation: () => TConversation | null;
  newConversation: ConvoGenerator;
  selectExistingConversation: (selection: Partial<TConversation>) => boolean;
}

const ModelSelectorChatContext = createContext<ModelSelectorChatContextValue | undefined>(
  undefined,
);

export function ModelSelectorChatProvider({ children }: { children: React.ReactNode }) {
  const getConversation = useGetConversation(0);
  const { setConversation } = store.useSetConversationAtom(0);
  const queryClient = useQueryClient();
  const { showToast } = useToastContext();
  const pendingSave = useRef<Promise<void>>(Promise.resolve());
  const { newConversation: nextNewConversation } = useNewConvo();

  const spec = useRecoilValue(store.conversationSpecByIndex(0));
  const model = useRecoilValue(store.conversationModelByIndex(0));
  const agent_id = useRecoilValue(store.conversationAgentIdByIndex(0));
  const endpoint = useRecoilValue(store.conversationEndpointByIndex(0));
  const assistant_id = useRecoilValue(store.conversationAssistantIdByIndex(0));

  const newConversationRef = useRef(nextNewConversation);
  newConversationRef.current = nextNewConversation;
  const newConversation = useCallback<ConvoGenerator>(
    (params) => newConversationRef.current(params),
    [],
  );

  /** A model selection belongs to the active saved conversation. Do not route it
   * through newConversation(), which turns it into an unsaved /c/new draft.
   * Serialize quick successive picks so an earlier HTTP response cannot win. */
  const selectExistingConversation = useCallback(
    (selection: Partial<TConversation>): boolean => {
      const conversationId = getConversation()?.conversationId;
      if (!conversationId || conversationId === Constants.NEW_CONVO || conversationId.startsWith('_')) {
        return false;
      }

      setConversation((previous) =>
        previous?.conversationId === conversationId ? { ...previous, ...selection } : previous,
      );
      pendingSave.current = pendingSave.current
        .catch(() => undefined)
        .then(async () => {
          const saved = await dataService.updateConversation({ conversationId, ...selection } as TUpdateConversationRequest);
          const mergeSavedSelection = (previous: TConversation) => ({
            ...previous,
            ...selection,
            updatedAt: saved.updatedAt,
          });
          queryClient.setQueryData<TConversation>([QueryKeys.conversation, conversationId], (previous) =>
            previous ? mergeSavedSelection(previous) : saved,
          );
          updateConvoInAllQueries(queryClient, conversationId, mergeSavedSelection);
        })
        .catch((error) => {
          console.error('Failed to save conversation model selection', error);
          showToast({
            message: 'Could not save conversation settings. Refreshing may restore the previous settings.',
            severity: NotificationSeverity.ERROR,
          });
        });
      return true;
    },
    [getConversation, queryClient, setConversation, showToast],
  );

  /** Context value only created when relevant conversation properties change */
  const contextValue = useMemo<ModelSelectorChatContextValue>(
    () => ({
      model,
      spec,
      agent_id,
      endpoint,
      assistant_id,
      getConversation,
      newConversation,
      selectExistingConversation,
    }),
    [endpoint, model, spec, agent_id, assistant_id, getConversation, newConversation, selectExistingConversation],
  );

  return (
    <ModelSelectorChatContext.Provider value={contextValue}>
      {children}
    </ModelSelectorChatContext.Provider>
  );
}

export function useModelSelectorChatContext() {
  const context = useContext(ModelSelectorChatContext);
  if (!context) {
    throw new Error('useModelSelectorChatContext must be used within ModelSelectorChatProvider');
  }
  return context;
}
