'use strict';

// Legacy Express routes only register middleware. Controller proxy policy and
// transport live in the TypeScript API workspace.
const express = require('express');
const { requireJwtAuth } = require('~/server/middleware');
const { makeLsmControllerProxy, isAllowedLsmControllerPath } = require('@librechat/api');

const router = express.Router();
router.use(requireJwtAuth);
router.use(express.raw({ type: 'application/octet-stream', limit: 32 * 1024 * 1024 }));
router.use(makeLsmControllerProxy(() => ({
  base: process.env.LSM_CONTROLLER_INTERNAL_URL,
  secret: process.env.LSM_LIBRECHAT_BRIDGE_SECRET,
})));

module.exports = { router, isAllowedPath: isAllowedLsmControllerPath };
