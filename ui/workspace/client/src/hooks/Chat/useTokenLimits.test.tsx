import { renderHook } from '@testing-library/react';
import type { TConversation } from 'librechat-data-provider';
import useTokenLimits from './useTokenLimits';

let mockAgent:
  | { provider: string; model: string; model_parameters?: Record<string, number> }
  | undefined;
let mockServerLimit: number | undefined;

jest.mock('~/data-provider', () => ({
  useGetStartupConfig: () => ({ data: undefined }),
  useTokenConfigQuery: () => ({ data: { Channel: { model: { context: 128000 } } } }),
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
    const conversation = { endpoint: 'Channel', model: 'model' } as TConversation;
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
    const conversation = { endpoint: 'agents', agent_id: 'agent' } as TConversation;
    const { result } = renderHook(() => useTokenLimits(conversation));
    expect(result.current.maxContextTokens).toBe(4096);
  });
});
