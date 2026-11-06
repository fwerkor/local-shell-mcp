'use strict';

const express = require('express');
const { Readable } = require('node:stream');
const { requireJwtAuth } = require('~/server/middleware');

const router = express.Router();
const SAFE_PATH = /^(?:bootstrap|dashboard|machines|files(?:\/(?:preview|content|download-ticket|download\/[a-zA-Z0-9_-]+|upload|(?:mkdir|touch|rename|copy|move|delete|write)))?|gui\/(?:windows|frame|action)|librechat\/upload|terminals(?:\/(?:read|start|send|resize|kill))?|logical-sessions(?:\/(?:detail|start|finish|cancel|delete))?|audit(?:\/detail)?|remotes(?:\/(?:rename|reset|revoke))?)$/;
const MAX_BODY = 32 * 1024 * 1024;

const isAllowedPath = (value, method) => {
  if (typeof value !== 'string' || value.length > 256 ||
      !SAFE_PATH.test(value) || !['GET', 'POST', 'HEAD'].includes(method)) return false;
  if (method === 'HEAD') return /^files\/download\//.test(value);
  if (method === 'POST') {
    return /^(?:files\/(?:download-ticket|upload|mkdir|touch|rename|copy|move|delete|write)|librechat\/upload|gui\/action|terminals\/(?:start|send|resize|kill)|logical-sessions\/(?:start|finish|cancel|delete)|remotes(?:\/(?:rename|reset|revoke))?)$/.test(value);
  }
  return !/^(?:files\/(?:download-ticket|upload|mkdir|touch|rename|copy|move|delete|write)|librechat\/upload|gui\/action|terminals\/(?:start|send|resize|kill)|logical-sessions\/(?:start|finish|cancel|delete)|remotes\/(?:rename|reset|revoke))$/.test(value);
};

router.use(requireJwtAuth);
// A dedicated raw parser is needed for Controller file upload; normal JSON
// requests have already been parsed by the parent Express app.
router.use(express.raw({ type: 'application/octet-stream', limit: MAX_BODY }));

router.use(async (req, res) => {
  const base = process.env.LSM_CONTROLLER_INTERNAL_URL;
  const secret = process.env.LSM_LIBRECHAT_BRIDGE_SECRET;
  const userId = String(req.user?.id || req.user?._id || '');
  const path = req.path.replace(/^\//, '');
  if (!base || !secret || Buffer.byteLength(secret, 'utf8') < 32) return res.sendStatus(503);
  if (req.user?.provider !== 'lsm' || !/^[a-f\d]{24}$/i.test(userId)) return res.sendStatus(403);
  if (!isAllowedPath(path, req.method)) return res.sendStatus(404);

  // URL is constructed from an administrator-controlled service origin and
  // an allowlisted relative route only. Reject redirects and unknown routes.
  const target = base.replace(/\/$/, '') + '/api/ui/' + path +
    (req.originalUrl.includes('?') ? req.originalUrl.slice(req.originalUrl.indexOf('?')) : '');
  const headers = {
    Authorization: 'Bearer ' + secret,
    'X-LSM-Chat-User-Id': userId,
  };
  let body;
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
      body,
      redirect: 'error',
      signal: AbortSignal.timeout(60000),
    });
    res.status(upstream.status);
    res.set('Cache-Control', 'no-store');
    for (const header of ['content-type', 'content-disposition', 'content-length']) {
      const value = upstream.headers.get(header);
      if (value) res.set(header, value);
    }
    if (req.method === 'HEAD' || !upstream.body) return res.end();
    Readable.fromWeb(upstream.body).on('error', () => res.destroy()).pipe(res);
  } catch {
    if (!res.headersSent) return res.status(502).json({ error: 'LSM Controller unavailable' });
    res.destroy();
  }
});

module.exports = { router, isAllowedPath };
