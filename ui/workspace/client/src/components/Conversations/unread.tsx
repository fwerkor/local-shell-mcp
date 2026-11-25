import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { apiBaseUrl, request } from 'librechat-data-provider';

type UnreadSnapshot = { unread: Record<string, string> };
const key = ['lsm-conversation-unread'];
const endpoint = () => apiBaseUrl() + '/api/convos/unread';
const fetchUnread = () => request.get<UnreadSnapshot>(endpoint());

export function unreadMarker(snapshot: UnreadSnapshot | undefined, id: string | null) {
  return id && snapshot && Object.prototype.hasOwnProperty.call(snapshot.unread, id)
    ? snapshot.unread[id]
    : undefined;
}

export function useUnreadQuery(enabled: boolean) {
  return useQuery({
    queryKey: key,
    queryFn: fetchUnread,
    enabled,
    staleTime: 1000,
    refetchInterval: 3000,
    refetchOnWindowFocus: 'always',
    retry: false,
  });
}

export function useSetUnread() {
  const client = useQueryClient();
  return useCallback(
    async (conversationId: string, unread: boolean, expected?: string) => {
      await request.post(endpoint(), { conversationId, unread, expected });
      await client.invalidateQueries(key);
    },
    [client],
  );
}

type UnreadContextValue = {
  snapshot?: UnreadSnapshot;
  setUnread: (id: string, unread: boolean, expected?: string) => Promise<void>;
};

const UnreadContext = createContext<UnreadContextValue>({
  setUnread: async () => {},
});

export const UnreadProvider = UnreadContext.Provider;

export function useConversationUnread(id: string | null) {
  const { snapshot, setUnread } = useContext(UnreadContext);
  return { marker: unreadMarker(snapshot, id), setUnread };
}

/** A manual mark made while viewing a chat stays until the next visit. */
export function shouldAcknowledge(marker: string | undefined, previous: string | undefined) {
  return marker !== previous && marker?.startsWith('run:') === true;
}

const completionEvent = 'lsm:conversation-completion';

export function notifyConversationCompletion(conversationId: string, marker: string) {
  window.dispatchEvent(new CustomEvent(completionEvent, { detail: { conversationId, marker } }));
}

export function useConversationReadReceipt(conversationId: string, enabled: boolean) {
  const client = useQueryClient();
  const setUnread = useSetUnread();
  const { data } = useUnreadQuery(enabled);
  const [visible, setVisible] = useState(() => document.visibilityState !== 'hidden');
  useEffect(() => {
    const onVisibility = () => setVisible(document.visibilityState !== 'hidden');
    document.addEventListener('visibilitychange', onVisibility);
    return () => document.removeEventListener('visibilitychange', onVisibility);
  }, []);
  const active = enabled && visible && !!conversationId && conversationId !== 'new';
  const marker = unreadMarker(data, conversationId);
  const previous = useRef<{ id: string; marker?: string }>();

  useEffect(() => {
    if (!active) {
      return;
    }
    const onCompletion = (event: Event) => {
      const { conversationId: id, marker } = (
        event as CustomEvent<{
          conversationId: string;
          marker: string;
        }>
      ).detail;
      if (
        id === conversationId &&
        marker.startsWith('run:') &&
        document.visibilityState !== 'hidden'
      ) {
        void setUnread(id, false, marker).catch(() => {});
      }
    };
    window.addEventListener(completionEvent, onCompletion);
    return () => window.removeEventListener(completionEvent, onCompletion);
  }, [active, conversationId, setUnread]);

  useEffect(() => {
    if (!active) {
      return;
    }
    let cancelled = false;
    // Fetch a fresh snapshot on entry/return, not a stale list-cache value.
    client
      .fetchQuery({ queryKey: key, queryFn: fetchUnread, staleTime: 0 })
      .then((snapshot) => {
        const current = unreadMarker(snapshot, conversationId);
        if (!cancelled && current) {
          return setUnread(conversationId, false, current);
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [active, conversationId, client, setUnread]);

  useEffect(() => {
    const old = previous.current;
    previous.current = { id: conversationId, marker };
    if (active && old?.id === conversationId && shouldAcknowledge(marker, old.marker)) {
      void setUnread(conversationId, false, marker).catch(() => {});
    }
  }, [active, conversationId, marker, setUnread]);
}
