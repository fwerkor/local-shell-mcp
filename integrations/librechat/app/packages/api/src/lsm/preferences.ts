import type { Request, Response, NextFunction } from 'express';

type Preferences = { web: boolean; lsm: boolean; mcp: boolean; memory: boolean };
type Store = {
  isOwner(userId: string, conversationId: string): Promise<boolean>;
  read(userId: string, conversationId: string): Promise<Partial<Preferences> | null>;
  save(userId: string, conversationId: string, prefs: Preferences): Promise<number>;
};
type UserRequest = Request & { user?: { id?: string } };
const DEFAULTS: Readonly<Preferences> = { web: true, lsm: true, mcp: true, memory: true };

function validConversationId(value: unknown): value is string {
  return typeof value === 'string' && /^[a-zA-Z0-9_-]{1,180}$/.test(value);
}

function normalizePreferences(source: Record<string, unknown>): Preferences {
  const output: Preferences = { ...DEFAULTS };
  for (const key of Object.keys(DEFAULTS) as (keyof Preferences)[]) {
    if (!Object.prototype.hasOwnProperty.call(source, key)) continue;
    if (typeof source[key] !== 'boolean') throw new TypeError('Invalid chat preference');
    output[key] = source[key] as boolean;
  }
  if (!output.web) output.lsm = false;
  if (output.lsm) output.web = true;
  return output;
}

function isChatGeneration(path: string, method: string): boolean {
  // /chat/:endpoint is the browser's normal generation route. These are
  // not generation requests and must never be modified by chat admission.
  return method === 'POST' && (path === '/chat' ||
    /^\/chat\/(?!abort$|queued-turns$|queue$|steer$|stream$)[a-zA-Z0-9_-]+$/.test(path));
}

type Handler = (req: UserRequest, res: Response, next: NextFunction) => Promise<void | Response>;
export function createLsmChatPreferencesHandlers(
  store: Store,
  config: () => { controllerUrl?: string; secret?: string },
): { get: Handler; put: Handler; admit: Handler } {
  const get = async (userId: string, conversationId: string): Promise<Preferences> => {
    const stored = await store.read(userId, conversationId);
    return stored ? normalizePreferences(stored) : { ...DEFAULTS };
  };
  const sync = async (userId: string, conversationId: string, prefs: Preferences, revision: number) => {
    const { controllerUrl, secret } = config();
    if (!controllerUrl || !secret || Buffer.byteLength(secret, 'utf8') < 32) {
      throw new Error('LSM authorization service is unavailable');
    }
    const response = await fetch(controllerUrl.replace(/\/$/, '') + '/api/ui/librechat/policy', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + secret },
      body: JSON.stringify({
        user_id: userId, conversation_id: conversationId,
        lsm: prefs.lsm, mcp: prefs.mcp, revision,
      }),
      signal: AbortSignal.timeout(10000),
    });
    if (!response.ok) throw new Error('LSM authorization update failed');
  };

  const check = async (req: UserRequest, res: Response): Promise<{ userId: string; conversationId: string } | null> => {
    const conversationId = req.params.conversationId;
    if (!validConversationId(conversationId)) {
      res.sendStatus(400);
      return null;
    }
    const userId = String(req.user?.id || '');
    if (!userId || !(await store.isOwner(userId, conversationId))) {
      res.sendStatus(404);
      return null;
    }
    return { userId, conversationId };
  };

  return {
    get: async (req: UserRequest, res: Response, next: NextFunction): Promise<void | Response> => {
      try {
        const subject = await check(req, res);
        if (subject) res.json(await get(subject.userId, subject.conversationId));
      } catch (error) { next(error); }
    },
    put: async (req: UserRequest, res: Response, next: NextFunction): Promise<void | Response> => {
      try {
        const subject = await check(req, res);
        if (!subject) return;
        let prefs: Preferences;
        try {
          prefs = normalizePreferences(req.body || {});
        } catch {
          res.sendStatus(400);
          return;
        }
        try {
          const revision = await store.save(subject.userId, subject.conversationId, prefs);
          await sync(subject.userId, subject.conversationId, prefs, revision);
          res.json(prefs);
        } catch {
          res.status(503).json({ error: 'Chat permission sync failed; retry before using this conversation' });
        }
      } catch (error) { next(error); }
    },
    admit: async (req: UserRequest, res: Response, next: NextFunction): Promise<void | Response> => {
      try {
        if (!isChatGeneration(req.path, req.method)) return next();
        const conversationId = req.body?.conversationId;
        let prefs: Preferences;
        if (!conversationId || conversationId === 'new') {
          prefs = { ...DEFAULTS };
        } else {
          if (!validConversationId(conversationId)) return res.sendStatus(400);
          const userId = String(req.user?.id || '');
          if (!userId || !(await store.isOwner(userId, conversationId))) return res.sendStatus(404);
          prefs = await get(userId, conversationId);
        }
        (req as UserRequest & { lsmChatPrefs?: Preferences }).lsmChatPrefs = prefs;
        if (req.body?.ephemeralAgent) {
          const agent = req.body.ephemeralAgent as Record<string, unknown>;
          const selected = Array.isArray(agent.mcp) ? agent.mcp : [];
          agent.mcp = (prefs.lsm || prefs.mcp) ? ['LSM'] :
            selected.filter((name) => name !== 'LSM');
          agent.web_search = prefs.web;
          agent.memory = prefs.memory && agent.memory === true;
          agent.execute_code = false;
          agent.file_search = false;
        }
        next();
      } catch (error) { next(error); }
    },
  };
}
