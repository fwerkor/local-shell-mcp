import type { ServerRequest } from '~/types';
import { createAgentExecutionContext, createRequestAgentExecutionContext, denyProviderWebSearch, filterLsmChatTools } from './runtime';

describe('createRequestAgentExecutionContext', () => {
  afterEach(() => jest.restoreAllMocks());

  it('captures one server timestamp and reuses it across request-backed initialization', () => {
    const now = jest.spyOn(Date, 'now').mockReturnValueOnce(1000).mockReturnValueOnce(2000);
    const req = { body: {} } as ServerRequest;

    const first = createRequestAgentExecutionContext(req);
    const second = createRequestAgentExecutionContext(req);

    expect(first.turnStartedAt).toBe(1000);
    expect(second.turnStartedAt).toBe(1000);
    expect(req.turnStartedAt).toBe(1000);
    expect(now).toHaveBeenCalledTimes(1);
  });

  it('captures server time when a request-free caller omits the turn start', () => {
    const now = jest.spyOn(Date, 'now').mockReturnValue(3000);

    const context = createAgentExecutionContext({ requestBody: {} });

    expect(context.turnStartedAt).toBe(3000);
    expect(now).toHaveBeenCalledTimes(1);
  });
});


describe('LSM per-conversation saved Agent policies', () => {
  const candidates = [
    'web_search',
    'memory',
    'mcp_all_mcp_LSM',
    'run_shell_mcp_LSM',
    'fetch_mcp_Other',
    'mcp_all_mcp_Other',
    'ask_user_question',
    'execute_code',
    'file_search',
  ];
  it('filters saved-Agent capabilities even if they were enabled in an earlier chat', () => {
    expect(filterLsmChatTools(candidates, { web: false, lsm: false, mcp: false, memory: false })).toEqual([
      'ask_user_question',
    ]);
  });

  it('retains Ask User and LSM when the conversation explicitly permits both', () => {
    expect(filterLsmChatTools(candidates, { web: true, lsm: true, memory: true })).toEqual([
      'web_search', 'memory', 'mcp_all_mcp_LSM', 'run_shell_mcp_LSM', 'ask_user_question',
    ]);
  });

  it('exposes only the nested MCP gateway when LSM native access is off', () => {
    expect(filterLsmChatTools(candidates, { web: true, lsm: false, mcp: true, memory: false })).toEqual([
      'web_search', 'ask_user_question', 'mcp_tool_search_mcp_LSM',
      'mcp_tool_inspect_mcp_LSM', 'mcp_tool_call_mcp_LSM',
    ]);
  });

  it('disables nested MCP independently of LSM native tools', () => {
    expect(filterLsmChatTools(candidates, { web: true, lsm: true, mcp: false, memory: false })).toEqual([
      'web_search', 'mcp_all_mcp_LSM', 'run_shell_mcp_LSM', 'ask_user_question',
    ]);
  });

  it('does not modify standalone LibreChat deployments', () => {
    expect(filterLsmChatTools(candidates, undefined)).toBe(candidates);
  });

  it('propagates per-conversation permissions into the tool initializer', () => {
    const prefs = { web: false, lsm: false, mcp: false, memory: false };
    const runtime = createAgentExecutionContext({ requestBody: {}, lsmChatPrefs: prefs });
    expect(runtime.lsmChatPrefs).toBe(prefs);
  });
});

describe('provider-native web search denial', () => {
  it('blocks Google and OpenRouter native search when the conversation disables web', async () => {
    const resolveGrant = jest.fn().mockResolvedValue(true);
    expect(await denyProviderWebSearch({
      builtInSearch: true,
      conversationWebAllowed: false,
      resolveGrant,
    })).toBe(true);
    expect(resolveGrant).not.toHaveBeenCalled();
  });

  it('also blocks provider-native search when the role denies permission', async () => {
    expect(await denyProviderWebSearch({
      builtInSearch: true,
      conversationWebAllowed: true,
      resolveGrant: async () => false,
    })).toBe(true);
  });

  it('allows a role-granted provider search unless the conversation denies it', async () => {
    const resolveGrant = jest.fn().mockResolvedValue(true);
    expect(await denyProviderWebSearch({
      builtInSearch: true,
      conversationWebAllowed: true,
      resolveGrant,
    })).toBe(false);
    expect(await denyProviderWebSearch({
      builtInSearch: false,
      conversationWebAllowed: false,
      resolveGrant,
    })).toBe(false);
    expect(resolveGrant).toHaveBeenCalledTimes(1);
  });
});
