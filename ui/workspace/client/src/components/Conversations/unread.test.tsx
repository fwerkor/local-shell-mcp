import React from 'react';
import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { request } from 'librechat-data-provider';
import { useConversationReadReceipt, unreadMarker, notifyConversationCompletion } from './unread';

jest.mock('librechat-data-provider', () => ({
  apiBaseUrl: () => '',
  request: { get: jest.fn(), post: jest.fn() },
}));

const get = jest.mocked(request.get);
const post = jest.mocked(request.post);

it('acknowledges the opened chat and new completions but not a manual unread mark', async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  let unread: Record<string, string> = { a: 'run:old', b: 'run:background' };
  get.mockImplementation(async () => ({ unread: { ...unread } }) as never);
  post.mockImplementation(async (_url, body) => {
    if (unread[body.conversationId] === body.expected) {
      delete unread[body.conversationId];
    }
    return {};
  });
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const { rerender, unmount } = renderHook(({ id }) => useConversationReadReceipt(id, true), {
    wrapper,
    initialProps: { id: 'a' },
  });
  await waitFor(() => expect(unread.a).toBeUndefined());
  expect(unread.b).toBe('run:background');

  async function publish(id: string, marker: string) {
    unread[id] = marker;
    await act(async () => {
      await client.invalidateQueries(['lsm-conversation-unread']);
    });
  }

  unread.a = 'run:sse';
  await act(async () => {
    notifyConversationCompletion('a', 'run:sse');
  });
  await waitFor(() => expect(unread.a).toBeUndefined());
  await publish('a', 'run:new');
  await waitFor(() => expect(unread.a).toBeUndefined());
  await publish('a', 'manual:explicit');
  expect(unread.a).toBe('manual:explicit');
  rerender({ id: 'b' });
  await waitFor(() => expect(unread.b).toBeUndefined());
  expect(unread.a).toBe('manual:explicit');
  rerender({ id: 'a' });
  await waitFor(() => expect(unread.a).toBeUndefined());
  unmount();
  client.clear();
});

it('does not interpret inherited object properties as unread markers', () => {
  expect(unreadMarker({ unread: {} }, 'constructor')).toBeUndefined();
});
