'use strict';

const express = require('express');
const jwt = require('jsonwebtoken');
const mongoose = require('mongoose');
const { setAuthTokens } = require('~/server/services/AuthService');
const { createLsmAuthStore } = require('@librechat/data-schemas');
const { createLsmAuthHandler } = require('@librechat/api');

const router = express.Router();
router.post('/', createLsmAuthHandler({
  store: createLsmAuthStore(mongoose.connection, () => mongoose.models.User),
  verifyTicket: jwt.verify,
  setAuthTokens: (id, res, req) => setAuthTokens(new mongoose.Types.ObjectId(id), res, null, req),
  config: () => ({
    secret: process.env.LSM_LIBRECHAT_BRIDGE_SECRET,
    controllerUrl: process.env.LSM_CONTROLLER_INTERNAL_URL,
  }),
}));

module.exports = router;
