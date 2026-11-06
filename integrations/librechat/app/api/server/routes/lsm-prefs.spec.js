jest.mock('~/server/middleware', () => ({ requireJwtAuth: (_req, _res, next) => next() }));
const { loadForAgentRequest } = require('./lsm-prefs');

describe('LSM chat-level admission', () => {
  it('keeps the LSM and web tools enabled for a new chat', async () => {
    const req = {
      method: 'POST', path: '/chat', user: { id: 'user' },
      body: { conversationId: 'new', ephemeralAgent: {
        mcp: ['untrusted'], web_search: false, execute_code: true, file_search: true,
      } },
    };
    const next = jest.fn();
    await loadForAgentRequest(req, {}, next);
    expect(next).toHaveBeenCalledTimes(1);
    expect(req.body.ephemeralAgent).toMatchObject({
      mcp: ['LSM'], web_search: true, execute_code: false, file_search: false,
    });
  });

  it('does not interfere with abort or queued-turn control requests', async () => {
    for (const path of ['/chat/abort', '/chat/queued-turns', '/chat/steer/arm']) {
      const req = { method: 'POST', path, body: { conversationId: 'unsaved' } };
      const next = jest.fn();
      await loadForAgentRequest(req, {}, next);
      expect(next).toHaveBeenCalledTimes(1);
      expect(req.lsmChatPrefs).toBeUndefined();
    }
  });
});
