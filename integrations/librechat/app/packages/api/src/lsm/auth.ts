import type { Request, Response } from 'express';

const AUDIENCE = 'lsm-embedded-librechat';
const ISSUER = 'local-shell-mcp';
type Claims = { sub: string; jti: string; exp: number };
type Store = {
  claimTicket(jti: string, expiresAt: Date): Promise<void>;
  getWorkspaceUser(): Promise<string>;
};

export function createLsmAuthHandler(deps: {
  store: Store;
  verifyTicket: (ticket: string, secret: string, options: Record<string, unknown>) => unknown;
  setAuthTokens: (userId: string, res: Response, req: Request) => Promise<unknown>;
  config: () => { secret?: string; controllerUrl?: string };
}) {
  return async (req: Request, res: Response): Promise<Response | void> => {
    const { secret, controllerUrl } = deps.config();
    if (!secret || Buffer.byteLength(secret, 'utf8') < 32) return res.sendStatus(503);
    if (typeof req.body?.ticket !== 'string' || req.body.ticket.length > 4096) {
      return res.sendStatus(401);
    }
    let claims: Claims;
    try {
      const value = deps.verifyTicket(req.body.ticket, secret, {
        algorithms: ['HS256'], issuer: ISSUER, audience: AUDIENCE,
        maxAge: '60s', clockTolerance: 2,
      });
      if (!value || typeof value !== 'object') return res.sendStatus(401);
      const decoded = value as Record<string, unknown>;
      if (typeof decoded.sub !== 'string' || !decoded.sub || decoded.sub.length > 1024 ||
          typeof decoded.jti !== 'string' || decoded.jti.length > 128 ||
          typeof decoded.exp !== 'number') return res.sendStatus(401);
      claims = decoded as Claims;
      await deps.store.claimTicket(claims.jti, new Date(claims.exp * 1000));
    } catch {
      return res.sendStatus(401);
    }
    try {
      const userId = await deps.store.getWorkspaceUser();
      if (!controllerUrl) return res.sendStatus(503);
      const response = await fetch(controllerUrl.replace(/\/$/, '') + '/api/ui/librechat/identity', {
        method: 'POST',
        headers: {
          Authorization: 'Bearer ' + secret,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ user_id: userId, ticket: req.body.ticket }),
        signal: AbortSignal.timeout(10000),
      });
      if (!response.ok) return res.sendStatus(503);
      await deps.setAuthTokens(userId, res, req);
      return res.redirect(303, '/control/overview');
    } catch {
      return res.sendStatus(503);
    }
  };
}
