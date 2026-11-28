import { renderHook } from '@testing-library/react';
import { EModelEndpoint } from 'librechat-data-provider';
import type { TConversation } from 'librechat-data-provider';
import useTokenLimits from './useTokenLimits';

let mockAgent:
  | { provider: string; model: string; model_parameters?: Record<string, number> }
  | undefined;
let mockServerLimit: number | undefined;

jest.mock('~/data-provider', () => ({
  useGetStartupConfig: () => ({ data: undefined }),
  useTokenConfigQuery: () => ({
    data: { openAI: { model: { context: 128000 } }, Channel: { model: { context: 128000 } } },
  }),
  useGetAgentByIdQuery: () => ({ data: mockAgent }),
  useGetEndpointsQuery: () => ({ data: { agents: { maxContextTokens: mockServerLimit } } }),
}));
jest.mock('~/utils', () => ({ getModelSpec: () => undefined }));

describe('effective context window', () => {
  beforeEach(() => {
    mockAgent = undefined;
    mockServerLimit = 8192;
  });

  it('uses the server override instead of the catalog window', () => {
    const conversation = {
      endpoint: EModelEndpoint.openAI,
      model: 'model',
      conversationId: 'test',
      title: 'Test',
      createdAt: '',
      updatedAt: '',
    } satisfies TConversation;
    const { result, rerender } = renderHook(() => useTokenLimits(conversation));
    expect(result.current.maxContextTokens).toBe(8192);
    mockServerLimit = undefined;
    rerender();
    expect(result.current.maxContextTokens).toBe(128000);
  });

  it('prefers an explicit agent limit over the server override', () => {
    mockAgent = {
      provider: 'Channel',
      model: 'model',
      model_parameters: { max_context_tokens: 4096 },
    };
    const conversation = {
      endpoint: EModelEndpoint.agents,
      agent_id: 'agent',
      conversationId: 'test',
      title: 'Test',
      createdAt: '',
      updatedAt: '',
    } satisfies TConversation;
    const { result } = renderHook(() => useTokenLimits(conversation));
    expect(result.current.maxContextTokens).toBe(4096);
  });
});
