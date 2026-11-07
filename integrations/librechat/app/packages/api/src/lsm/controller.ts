import { Readable } from 'node:stream';
import type { Request, Response } from 'express';

type AuthenticatedRequest = Request & { user?: { id?: string; _id?: string; provider?: string } };

const SAFE_PATH = /^(?:nested-mcp|bootstrap|dashboard|machines|files(?:\/(?:preview|content|download-ticket|download\/[a-zA-Z0-9_-]+|upload|(?:mkdir|touch|rename|copy|move|delete|write)))?|gui\/(?:windows|frame|action)|librechat\/upload|terminals(?:\/(?:read|start|send|resize|kill))?|logical-sessions(?:\/(?:detail|start|finish|cancel|delete))?|audit(?:\/detail)?|remotes(?:\/(?:rename|reset|revoke))?|settings\/(?:view|save|restart))$/;
const MAX_BODY = 32 * 1024 * 1024;

export const isAllowedLsmControllerPath = (value: string, method: string): boolean => {
  if (typeof value !== 'string' || value.length > 256 ||
      !SAFE_PATH.test(value) || !['GET', 'POST', 'HEAD'].includes(method)) return false;
  if (method === 'HEAD') return /^files\/download\//.test(value);
  if (method === 'POST') {
    return /^(?:nested-mcp|files\/(?:download-ticket|upload|mkdir|touch|rename|copy|move|delete|write)|librechat\/upload|gui\/action|terminals\/(?:start|send|resize|kill)|logical-sessions\/(?:start|finish|cancel|delete)|remotes(?:\/(?:rename|reset|revoke))?|settings\/(?:save|restart))$/.test(value);
  }
  return !/^(?:files\/(?:download-ticket|upload|mkdir|touch|rename|copy|move|delete|write)|librechat\/upload|gui\/action|terminals\/(?:start|send|resize|kill)|logical-sessions\/(?:start|finish|cancel|delete)|remotes\/(?:rename|reset|revoke)|settings\/(?:save|restart))$/.test(value);
};

/** Strict browser-origin check for configuration mutations. */
export const isLsmSettingsOriginAllowed = (
  origin: string | undefined,
  host: string | undefined,
  fetchSite: string | undefined,
): boolean => {
  if (!origin || !host || (fetchSite && fetchSite !== 'same-origin')) return false;
  try {
    const url = new URL(origin);
    return ['https:', 'http:'].includes(url.protocol) &&
      url.host.toLowerCase() === host.toLowerCase() &&
      !url.username && !url.password && url.pathname === '/' && !url.search && !url.hash;
  } catch {
    return false;
  }
};

export const makeLsmControllerProxy = (configuration: () => { base?: string; secret?: string }): ((req: Request, res: Response) => Promise<void | Response>) => async (req: Request, res: Response): Promise<void | Response> => {
  const { base, secret } = configuration();
  const userId = String((req as AuthenticatedRequest).user?.id || (req as AuthenticatedRequest).user?._id || '');
  const path = req.path.replace(/^\//, '');
  if (!base || !secret || Buffer.byteLength(secret, 'utf8') < 32) return res.sendStatus(503);
  if ((req as AuthenticatedRequest).user?.provider !== 'lsm' || !/^[a-f\d]{24}$/i.test(userId)) return res.sendStatus(403);
  if (!isAllowedLsmControllerPath(path, req.method)) return res.sendStatus(404);
  if (req.method === 'POST' && /^settings\/(?:save|restart)$/.test(path) &&
      !isLsmSettingsOriginAllowed(
        req.get('origin'), req.get('host'), req.get('sec-fetch-site'),
      )) return res.sendStatus(403);

  // URL is constructed from an administrator-controlled service origin and
  // an allowlisted relative route only. Reject redirects and unknown routes.
  const target = base.replace(/\/$/, '') + '/api/ui/' + path +
    (req.originalUrl.includes('?') ? req.originalUrl.slice(req.originalUrl.indexOf('?')) : '');
  const headers: Record<string, string> = {
    Authorization: 'Bearer ' + secret,
    'X-LSM-Chat-User-Id': userId,
  };
  let body: Buffer | string | undefined;
  if (req.method === 'POST') {
    if (Buffer.isBuffer(req.body)) {
      body = req.body;
      headers['Content-Type'] = 'application/octet-stream';
    } else {
      body = JSON.stringify(req.body ?? {});
      headers['Content-Type'] = 'application/json';
    }
    if (Buffer.byteLength(body) > MAX_BODY) return res.sendStatus(413);
  }

  try {
    const upstream = await fetch(target, {
      method: req.method,
      headers,
      body: body as RequestInit['body'],
      redirect: 'error',
      signal: AbortSignal.timeout(60000),
    });
    res.status(upstream.status);
    res.set('Cache-Control', 'no-store');
    for (const header of [
      'content-type', 'content-disposition', 'content-length',
      'x-lsm-gui-window-x', 'x-lsm-gui-window-y',
      'x-lsm-gui-window-width', 'x-lsm-gui-window-height',
      'x-lsm-gui-backend', 'x-lsm-gui-observation-id',
      'x-lsm-gui-observation-ttl-s', 'x-lsm-gui-coordinate-input',
    ]) {
      const value = upstream.headers.get(header);
      if (value) res.set(header, value);
    }
    if (req.method === 'HEAD' || !upstream.body) return res.end();
    Readable.fromWeb(upstream.body as never).on('error', () => res.destroy()).pipe(res);
  } catch {
    if (!res.headersSent) return res.status(502).json({ error: 'LSM Controller unavailable' });
    res.destroy();
  }
};
