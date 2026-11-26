import { useCallback, useEffect, useRef, useState } from 'react';
import { atom, useAtom } from 'jotai';
import { useQuery } from '@tanstack/react-query';
import { useToastContext } from '@librechat/client';
import {
  Constants,
  dataService,
  isCompactedLeaf,
  isAssistantsEndpoint,
} from 'librechat-data-provider';
import useLocalize from '~/hooks/useLocalize';
import { useLatestMessage } from '~/hooks/Messages/useLatestMessage';
import { useChatContext } from '~/Providers';

/** Conversation whose compaction this client submitted and is still streaming. */
export const compactingConversationAtom = atom<string | null>(null);

/**
 * An Assistants thread lives on the provider, so a summary inserted into the
 * local history would compact nothing. Callers hide the action there.
 */
export const supportsCompaction = (endpoint?: string | null): boolean =>
  !isAssistantsEndpoint(endpoint);

/**
 * Manual context compaction. Submits a summarize-only turn hung off the
 * branch's leaf through the ordinary chat pipeline: the summary streams into
 * a response placeholder under the leaf, exactly like the automatic detour's,
 * and is persisted as the boundary every later turn starts from.
 */
export default function useCompactConversation() {
  const { ask, index, conversation, isSubmitting } = useChatContext();
  const latestMessage = useLatestMessage(index);
  const localize = useLocalize();
  const { showToast } = useToastContext();
  const [requesting, setRequesting] = useState(false);
  const [live, setLive] = useState<{
    conversationId: string;
    receipt: Awaited<ReturnType<typeof dataService.requestLiveCompaction>>;
  } | null>(null);
  const [compactingConversation, setCompactingConversation] = useAtom(compactingConversationAtom);

  const conversationId = conversation?.conversationId;
  const hasConversation =
    conversationId != null &&
    conversationId !== Constants.NEW_CONVO &&
    conversationId !== Constants.PENDING_CONVO;
  const livePending = live != null && live.conversationId === conversationId;
  const liveStatus = useQuery(
    ['lsm-live-compaction', live?.receipt.runId, live?.receipt.requestId],
    () => dataService.getLiveCompactionStatus(live!.receipt),
    { enabled: livePending, refetchInterval: 2000, retry: 2, staleTime: 0 },
  );
  useEffect(() => {
    if (
      !livePending ||
      (!liveStatus.isError && (liveStatus.data == null || liveStatus.data.status === 'pending'))
    ) {
      return;
    }
    const success = !liveStatus.isError && liveStatus.data?.status === 'complete';
    showToast({
      message: success
        ? localize('com_ui_context_compacted_by_you')
        : localize('com_ui_failed_subject', { 0: localize('com_ui_context_compact') }),
      status: success ? 'success' : 'error',
    });
    setLive(null);
  }, [livePending, liveStatus.data, liveStatus.isError, localize, showToast]);
  const isCompacting =
    requesting || livePending || (isSubmitting && compactingConversation === conversationId);
  const canCompact =
    hasConversation &&
    !isCompacting &&
    (isSubmitting ||
      (latestMessage != null &&
        latestMessage.parentMessageId != null &&
        !isCompactedLeaf(latestMessage)));

  /** The marker lives from the submission until the turn it started settles:
   *  cleared on the submitting → idle edge, or on a mount that finds the
   *  chat already idle (the turn finished while this view was away), never
   *  on the idle render that precedes the submit. */
  const wasSubmitting = useRef(isSubmitting);
  const mounted = useRef(false);
  useEffect(() => {
    const settled = wasSubmitting.current && !isSubmitting;
    const mountedIdle = !mounted.current && !isSubmitting;
    mounted.current = true;
    wasSubmitting.current = isSubmitting;
    if ((settled || mountedIdle) && compactingConversation != null) {
      setCompactingConversation(null);
    }
  }, [isSubmitting, compactingConversation, setCompactingConversation]);

  const compact = useCallback(() => {
    if (!canCompact || conversationId == null) {
      return;
    }
    if (isSubmitting) {
      setRequesting(true);
      void dataService
        .requestLiveCompaction(conversationId)
        .then(
          (receipt) => setLive({ conversationId, receipt }),
          () =>
            showToast({
              message: localize('com_ui_failed_subject', { 0: localize('com_ui_context_compact') }),
              status: 'error',
            }),
        )
        .finally(() => setRequesting(false));
      return;
    }
    if (latestMessage == null) {
      return;
    }
    setCompactingConversation(conversationId);
    /** The leaf is both the placeholder's parent and the server-side anchor
     *  (`parentMessageId` is what the controller compacts up to). */
    const accepted = ask(
      {
        text: '',
        conversationId,
        messageId: latestMessage.messageId,
        parentMessageId: latestMessage.messageId,
      },
      { compact: true },
    );
    if (accepted === false) {
      setCompactingConversation(null);
    }
  }, [
    ask,
    canCompact,
    conversationId,
    isSubmitting,
    latestMessage,
    localize,
    setCompactingConversation,
    showToast,
  ]);

  return { compact, canCompact, isCompacting };
}
