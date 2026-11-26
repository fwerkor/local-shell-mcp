import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RecoilRoot } from 'recoil';
import { dataService, QueryKeys, StepEvents, Tools } from 'librechat-data-provider';
import type { ReactNode } from 'react';
import type { EventSubmission, MemoriesResponse, TAttachment } from 'librechat-data-provider';
import useAttachmentHandler from '~/hooks/SSE/useAttachmentHandler';
import useStepHandler from '~/hooks/SSE/useStepHandler';
import { useMemoriesQuery } from './queries';

jest.mock('librechat-data-provider', () => {
  const actual = jest.requireActual('librechat-data-provider');
  return { ...actual, dataService: { ...actual.dataService, getMemories: jest.fn() } };
});

const empty: MemoriesResponse = {
  memories: [],
  totalTokens: 0,
  tokenLimit: 100,
  usagePercentage: 0,
};
const saved: MemoriesResponse = {
  ...empty,
  memories: [
    {
      _id: 'stored-id',
      key: 'style',
      value: 'Concise answers',
      tokenCount: 3,
      updated_at: '2026-11-26',
    },
  ],
  totalTokens: 3,
  usagePercentage: 3,
};

const submission = { messages: [], userMessage: { messageId: 'user' } } as unknown as EventSubmission;

describe('memory list freshness', () => {
  const getMemories = jest.mocked(dataService.getMemories);
  let client: QueryClient;
  let serverData: MemoriesResponse;

  beforeEach(() => {
    client = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity } },
    });
    serverData = empty;
    getMemories.mockImplementation(async () => serverData);
  });

  afterEach(() => client.clear());

  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <RecoilRoot>{children}</RecoilRoot>
      </QueryClientProvider>
    );
  }

  it('refetches a fresh cached list when the menu is reopened', async () => {
    const first = renderHook(() => useMemoriesQuery(), { wrapper: Wrapper });
    await waitFor(() => expect(first.result.current.data).toEqual(empty));
    first.unmount();

    serverData = saved;
    const reopened = renderHook(() => useMemoriesQuery(), { wrapper: Wrapper });
    await waitFor(() => expect(reopened.result.current.data).toEqual(saved));
  });

  it('reloads the authoritative list for memory attachments, including replayed events', async () => {
    const { result } = renderHook(
      () => ({ query: useMemoriesQuery(), attachment: useAttachmentHandler(client) }),
      { wrapper: Wrapper },
    );
    await waitFor(() => expect(result.current.query.data).toEqual(empty));

    serverData = saved;
    const replay = () =>
      result.current.attachment({
        data: {
          type: Tools.memory,
          messageId: 'response',
          conversationId: 'conversation',
          memory: { type: 'update', key: 'style', value: 'Stale replayed value' },
        } as TAttachment,
        submission,
      });

    act(replay);
    await waitFor(() => expect(result.current.query.data).toEqual(saved));

    serverData = empty;
    act(replay);
    await waitFor(() => expect(result.current.query.data).toEqual(empty));
  });

  it('invalidates on inline memory completion even when the run step is not cached', async () => {
    const refresh = jest.fn(() => void client.invalidateQueries([QueryKeys.memories]));
    const { result } = renderHook(
      () => ({
        query: useMemoriesQuery(),
        steps: useStepHandler({
          setMessages: jest.fn(),
          getMessages: () => [],
          announcePolite: jest.fn(),
          lastAnnouncementTimeRef: { current: 0 },
          onMemoryChange: refresh,
        }),
      }),
      { wrapper: Wrapper },
    );
    await waitFor(() => expect(result.current.query.data).toEqual(empty));
    const warn = jest.spyOn(console, 'warn').mockImplementation(() => {});
    serverData = saved;
    act(() => {
      result.current.steps.stepHandler(
        {
          event: StepEvents.ON_RUN_STEP_COMPLETED,
          data: {
            result: {
              id: 'step',
              index: 0,
              tool_call: {
                name: 'set_memory',
                artifact: { memory: { type: 'update', key: 'style' } },
              } as NonNullable<import('librechat-data-provider').Agents.ToolEndEvent['tool_call']>,
            },
          },
        },
        submission,
      );
    });
    expect(refresh).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(result.current.query.data).toEqual(saved));
    warn.mockRestore();
  });
});
