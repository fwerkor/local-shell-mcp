const { isAllowedPath } = require('./lsm-controller');

describe('LSM controller proxy allowlist', () => {
  test.each([
    ['dashboard', 'GET'],
    ['nested-mcp', 'GET'],
    ['nested-mcp', 'POST'],
    ['files', 'GET'],
    ['files/preview', 'GET'],
    ['files/download-ticket', 'POST'],
    ['files/download/abc_123', 'HEAD'],
    ['files/upload', 'POST'],
    ['files/mkdir', 'POST'],
    ['files/touch', 'POST'],
    ['librechat/upload', 'POST'],
    ['gui/frame', 'GET'],
    ['gui/action', 'POST'],
    ['terminals/send', 'POST'],
    ['logical-sessions/detail', 'GET'],
    ['remotes/rename', 'POST'],
    ['audit/detail', 'GET'],
  ])('accepts %s %s', (path, method) => {
    expect(isAllowedPath(path, method)).toBe(true);
  });

  test.each([
    ['auth', 'GET'],
    ['librechat/identity', 'POST'],
    ['librechat/policy', 'POST'],
    ['librechat/upload', 'GET'],
    ['files/upload', 'GET'],
    ['files/download/abc', 'POST'],
    ['../auth', 'GET'],
    ['files/%2e%2e/auth', 'GET'],
    ['files/../../mcp', 'GET'],
    ['mcp', 'POST'],
    ['nested-mcp', 'PUT'],
    ['terminals/kill', 'GET'],
    ['remotes', 'DELETE'],
  ])('rejects %s %s', (path, method) => {
    expect(isAllowedPath(path, method)).toBe(false);
  });
});
