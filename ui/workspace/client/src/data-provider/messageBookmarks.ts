import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { request } from 'librechat-data-provider';

export type MessageBookmark = {
  messageId: string;
  conversationId: string;
  conversationTitle: string;
  title: string;
  preview: string;
  role: string;
  createdAt: string;
};

const key = ['messageBookmarks'];
const url = '/api/message-bookmarks';

export function useMessageBookmarks<T = MessageBookmark[]>(
  enabled = true,
  select?: (items: MessageBookmark[]) => T,
) {
  return useQuery<MessageBookmark[], Error, T>(key, () => request.get(url), {
    enabled,
    select,
    staleTime: 30_000,
  });
}

export function useChangeMessageBookmark() {
  const client = useQueryClient();
  return useMutation<
    MessageBookmark | { deleted: boolean },
    Error,
    { messageId: string; remove?: boolean; title?: string }
  >(
    ({ messageId, remove, title }) =>
      remove
        ? request.delete(`${url}/${encodeURIComponent(messageId)}`)
        : request.put(`${url}/${encodeURIComponent(messageId)}`, { title }),
    {
      onSuccess: (result, { messageId }) => {
        client.setQueryData<MessageBookmark[]>(key, (previous) => {
          const items = previous ?? [];
          if ('deleted' in result) {
            return items.filter((item) => item.messageId !== messageId);
          }
          return [result, ...items.filter((item) => item.messageId !== messageId)].sort(
            (a, b) =>
              b.createdAt.localeCompare(a.createdAt) || a.messageId.localeCompare(b.messageId),
          );
        });
        void client.invalidateQueries(key);
      },
    },
  );
}
