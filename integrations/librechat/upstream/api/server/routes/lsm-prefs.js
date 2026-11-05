const express = require('express');
const mongoose = require('mongoose');
const { requireJwtAuth } = require('~/server/middleware');

const router = express.Router();
const DEFAULTS = Object.freeze({ web: true, lsm: true, memory: true });
const collection = () => mongoose.connection.collection('lsm_chat_preferences');

const conversationIdIsValid = (id) =>
  typeof id === 'string' && id.length > 0 && id.length <= 180 &&
  /^[a-zA-Z0-9_-]+$/.test(id);

const normalized = (source) => {
  const output = { ...DEFAULTS };
  for (const field of Object.keys(DEFAULTS)) {
    if (Object.hasOwn(source, field)) {
      if (typeof source[field] !== 'boolean') throw new TypeError('Invalid chat preference');
      output[field] = source[field];
    }
  }
  if (!output.web) output.lsm = false;
  if (output.lsm) output.web = true;
  return output;
};

const ownerCheck = async (userId, conversationId) => {
  return !!(await mongoose.models.Conversation.exists({
    conversationId, user: userId,
  }));
};

const getPreferences = async (userId, conversationId) => {
  const stored = await collection().findOne({ userId, conversationId });
  return stored ? normalized(stored) : { ...DEFAULTS };
};

const syncToolPolicy = async (userId, conversationId, enabled) => {
  const controllerUrl = process.env.LSM_CONTROLLER_INTERNAL_URL;
  const secret = process.env.LSM_LIBRECHAT_BRIDGE_SECRET;
  if (!controllerUrl || !secret || Buffer.byteLength(secret, 'utf8') < 32) {
    throw new Error('LSM authorization service is unavailable');
  }
  const response = await fetch(controllerUrl.replace(/\/$/, '') + '/api/ui/librechat/policy', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${secret}`,
    },
    body: JSON.stringify({ user_id: userId, conversation_id: conversationId, lsm: enabled }),
    signal: AbortSignal.timeout(10000),
  });
  if (!response.ok) throw new Error('LSM authorization update failed');
};

router.use(requireJwtAuth);

router.get('/:conversationId', async (req, res) => {
  const { conversationId } = req.params;
  if (!conversationIdIsValid(conversationId)) return res.sendStatus(400);
  if (!(await ownerCheck(req.user.id, conversationId))) return res.sendStatus(404);
  return res.json(await getPreferences(req.user.id, conversationId));
});

router.put('/:conversationId', async (req, res) => {
  const { conversationId } = req.params;
  if (!conversationIdIsValid(conversationId)) return res.sendStatus(400);
  if (!(await ownerCheck(req.user.id, conversationId))) return res.sendStatus(404);
  let prefs;
  try {
    prefs = normalized(req.body || {});
  } catch {
    return res.sendStatus(400);
  }
  try {
    // Fail closed while reconciling: disable first, write Mongo, then enable
    // only after the durable chat preference has committed.
    await syncToolPolicy(req.user.id, conversationId, false);
    await collection().createIndex({ userId: 1, conversationId: 1 }, { unique: true });
    await collection().updateOne(
      { userId: req.user.id, conversationId },
      { $set: { ...prefs }, $setOnInsert: { userId: req.user.id, conversationId } },
      { upsert: true },
    );
    if (prefs.lsm) await syncToolPolicy(req.user.id, conversationId, true);
    return res.json(prefs);
  } catch {
    return res.status(503).json({ error: 'Chat permission update failed; LSM tools remain disabled until retry' });
  }
});

const loadForAgentRequest = async (req, res, next) => {
  try {
    if (req.method !== 'POST' || !req.path.startsWith('/chat')) return next();
    const conversationId = req.body?.conversationId;
    if (!conversationId || conversationId === 'new') {
      req.lsmChatPrefs = { ...DEFAULTS };
    } else {
      if (!conversationIdIsValid(conversationId)) return res.sendStatus(400);
      if (!(await ownerCheck(req.user.id, conversationId))) return res.sendStatus(404);
      req.lsmChatPrefs = await getPreferences(req.user.id, conversationId);
    }
    // An ephemeral Agent can only use the configured LSM server. Native
    // orchestration tools (Ask User, subagents, handoff) remain unaffected.
    if (req.body?.ephemeralAgent) {
      const agent = req.body.ephemeralAgent;
      const selected = Array.isArray(agent.mcp) ? agent.mcp : [];
      agent.mcp = req.lsmChatPrefs.lsm ? ['LSM'] : selected.filter((name) => name !== 'LSM');
      agent.web_search = req.lsmChatPrefs.web;
      agent.memory = req.lsmChatPrefs.memory && agent.memory === true;
      agent.execute_code = false;
      agent.file_search = false;
    }
    next();
  } catch (error) {
    next(error);
  }
};

module.exports = { router, loadForAgentRequest };
