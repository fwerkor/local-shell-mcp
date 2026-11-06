import type { AppConfig, IConversation, IUser } from '@librechat/data-schemas';
import { Constants, Tools } from 'librechat-data-provider';
import type { RequestBody, ServerRequest } from '~/types';

/**
 * Runtime-only state required to initialize and execute an Agent run.
 *
 * This context deliberately contains no transport objects. Ingress adapters
 * may derive it from HTTP, while future execution hosts can rehydrate it from
 * an authenticated principal and deployment configuration.
 */
export type LsmChatPreferences = { web: boolean; lsm: boolean; memory: boolean };

/** Limit saved and ephemeral agents to the server-authorized conversation tools. */
export function filterLsmChatTools(
  tools: string[] | undefined,
  permissions: LsmChatPreferences | undefined,
): string[] | undefined {
  if (!permissions || !tools) return tools;
  const { web, lsm, memory } = permissions;
  return tools.filter((name) => {
    if (name === Tools.execute_code || name === Tools.file_search) return false;
    if (!web && name === Tools.web_search) return false;
    if (!memory && name === Tools.memory) return false;
    if (name.includes(Constants.mcp_delimiter)) {
      return lsm && name.endsWith(`${Constants.mcp_delimiter}LSM`);
    }
    return true;
  });
}

export interface AgentExecutionContext {
  /** Effective server-authorized capabilities for this specific conversation. */
  lsmChatPrefs?: LsmChatPreferences;
  user?: IUser;
  appConfig?: AppConfig;
  requestBody: RequestBody;
  /** Server-captured logical turn start time used by prompt variables. */
  turnStartedAt: number;
  /** Server-captured conversation creation time retained as historical metadata. */
  conversationCreatedAt?: string;
  /** Conversation already resolved by ingress. Presence distinguishes "not read" from absent. */
  resolvedConversation?: Partial<IConversation> | null;
}

/** Creates the transport-free context at the existing HTTP adapter seam. */
export function createAgentExecutionContext({
  user,
  appConfig,
  requestBody,
  turnStartedAt = Date.now(),
  conversationCreatedAt,
  resolvedConversation,
  hasResolvedConversation = false,
  lsmChatPrefs,
}: {
  user?: IUser;
  appConfig?: AppConfig;
  requestBody: RequestBody;
  turnStartedAt?: number;
  conversationCreatedAt?: string;
  resolvedConversation?: Partial<IConversation> | null;
  hasResolvedConversation?: boolean;
  lsmChatPrefs?: LsmChatPreferences;
}): AgentExecutionContext {
  const context: AgentExecutionContext = {
    user,
    appConfig,
    requestBody,
    turnStartedAt,
    conversationCreatedAt,
    ...(lsmChatPrefs && { lsmChatPrefs }),
  };
  if (hasResolvedConversation) {
    context.resolvedConversation = resolvedConversation ?? null;
  }
  return context;
}

/** Temporary adapter for request-backed Agent entry points. */
export function createRequestAgentExecutionContext(
  req: ServerRequest,
  requestBody: RequestBody = req.body ?? {},
): AgentExecutionContext {
  const turnStartedAt = req.turnStartedAt ?? Date.now();
  req.turnStartedAt = turnStartedAt;
  return createAgentExecutionContext({
    user: req.user,
    appConfig: req.config,
    requestBody,
    turnStartedAt,
    lsmChatPrefs: (req as ServerRequest & { lsmChatPrefs?: LsmChatPreferences }).lsmChatPrefs,
    conversationCreatedAt: req.conversationCreatedAt,
    resolvedConversation: req.resolvedConversation,
    hasResolvedConversation: Object.prototype.hasOwnProperty.call(req, 'resolvedConversation'),
  });
}
