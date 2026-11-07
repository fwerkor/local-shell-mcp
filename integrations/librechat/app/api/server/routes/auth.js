'use strict';

const express = require('express');
const { requireJwtAuth } = require('~/server/middleware');
const { refreshController } = require('~/server/controllers/AuthController');
const { logoutController } = require('~/server/controllers/auth/LogoutController');

// Local Shell MCP is the only sign-in authority. LibreChat retains only its
// private session refresh and logout; it cannot create or authenticate users.
const router = express.Router();
router.post('/refresh', refreshController);
router.post('/logout', requireJwtAuth, logoutController);

module.exports = router;
