const jwt = require('jsonwebtoken');
const mongoose = require('mongoose');
const express = require('express');
const { setAuthTokens } = require('~/server/services/AuthService');

const router = express.Router();
const AUDIENCE = 'lsm-embedded-librechat';
const ISSUER = 'local-shell-mcp';

router.post('/', async (req, res) => {
  const secret = process.env.LSM_LIBRECHAT_BRIDGE_SECRET;
  if (!secret || Buffer.byteLength(secret, 'utf8') < 32) {
    return res.sendStatus(503);
  }
  let claims;
  try {
    if (typeof req.body?.ticket !== 'string' || req.body.ticket.length > 4096) {
      return res.sendStatus(401);
    }
    claims = jwt.verify(req.body.ticket, secret, {
      algorithms: ['HS256'],
      issuer: ISSUER,
      audience: AUDIENCE,
      maxAge: '60s',
      clockTolerance: 2,
    });
    if (
      !claims || typeof claims !== 'object' ||
      typeof claims.sub !== 'string' || !claims.sub || claims.sub.length > 1024 ||
      typeof claims.jti !== 'string' || claims.jti.length > 128 ||
      typeof claims.exp !== 'number'
    ) {
      return res.sendStatus(401);
    }

    // Cross-process one-use enforcement; Mongo's _id index handles concurrent logins.
    const nonces = mongoose.connection.collection('lsm_login_nonces');
    await nonces.createIndex({ expiresAt: 1 }, { expireAfterSeconds: 0 });
    await nonces.insertOne({
      _id: claims.jti,
      expiresAt: new Date(claims.exp * 1000),
    });
  } catch {
    return res.sendStatus(401);
  }

  try {
    // LSM is single-user. All valid LSM logins use one internal chat account.
    // LSM remains the sole login authority; there are no chat-user registrations.
    const email = 'workspace@local-shell-mcp.invalid';
    const User = mongoose.models.User;
    const user = await User.findOneAndUpdate(
      { email, provider: 'lsm' },
      {
        $setOnInsert: {
          username: 'lsm_workspace',
          name: 'Local Shell MCP',
          email,
          provider: 'lsm',
          emailVerified: true,
          role: 'USER',
        },
      },
      { upsert: true, new: true, runValidators: true },
    );
    const controllerUrl = process.env.LSM_CONTROLLER_INTERNAL_URL;
    if (!controllerUrl) return res.sendStatus(503);
    const response = await fetch(controllerUrl.replace(/\/$/, '') + '/api/ui/librechat/identity', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${secret}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ user_id: user._id.toString(), ticket: req.body.ticket }),
      signal: AbortSignal.timeout(10000),
    });
    if (!response.ok) return res.sendStatus(503);
    await setAuthTokens(user._id, res, null, req);
    return res.redirect(303, '/control/overview');
  } catch {
    return res.sendStatus(503);
  }
});

module.exports = router;
