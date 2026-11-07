'use strict';

const express = require('express');
const mongoose = require('mongoose');
const { requireJwtAuth } = require('~/server/middleware');
const { createLsmChatPreferenceStore } = require('@librechat/data-schemas');
const { createLsmChatPreferencesHandlers } = require('@librechat/api');

const router = express.Router();
const handlers = createLsmChatPreferencesHandlers(
  createLsmChatPreferenceStore(mongoose.connection, () => mongoose.models.Conversation),
  () => ({
    controllerUrl: process.env.LSM_CONTROLLER_INTERNAL_URL,
    secret: process.env.LSM_LIBRECHAT_BRIDGE_SECRET,
  }),
);

router.use(requireJwtAuth);
router.get('/:conversationId', handlers.get);
router.put('/:conversationId', handlers.put);

module.exports = { router, loadForAgentRequest: handlers.admit };
