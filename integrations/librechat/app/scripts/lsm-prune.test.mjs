import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('..', import.meta.url));
const text = (file) => readFileSync(resolve(root, file), 'utf8');
const pkg = JSON.parse(text('package.json'));

test('preserve LSM chat, projects, agent, MCP and settings routes', () => {
  const backend = text('api/server/index.js');
  assert.ok(backend.includes("LSM_SINGLE_USER !== 'true'"));
  for (const route of ['/api/auth/lsm', '/api/lsm/controller', '/api/lsm/preferences',
    '/api/projects', '/api/agents', '/api/search', '/api/mcp', '/api/convos',
    '/api/messages', '/api/memories', '/api/files']) {
    assert.ok(backend.includes(`'${route}'`), `${route} must stay mounted`);
  }
  for (const removed of ['routes.adminAuth', 'routes.insights', 'routes.rum',
    'routes.balance', 'routes.apiKeys', 'routes.oauth', 'routes.openapi']) {
    assert.ok(!backend.includes(removed), `${removed} must not be mounted`);
  }
  assert.ok(!text('api/server/routes/index.js').includes("require('./admin/"));
  assert.ok(!existsSync(resolve(root, 'api/server/routes/admin')));
});

test('do not reintroduce standalone users, deployments or diagnostics', () => {
  for (const script of ['create-user', 'invite-user', 'delete-user', 'reset-password',
    'backend:experimental', 'update:deployed', 'redis:cluster', 'e2e:bombadil']) {
    assert.ok(!(script in pkg.scripts), `${script} is unnecessary for a single-user host`);
  }
  for (const script of ['frontend', 'backend', 'build:packages', 'check:lsm']) {
    assert.ok(script in pkg.scripts, `${script} is still required`);
  }
  assert.ok(existsSync(resolve(root, 'LICENSE')));
  assert.ok(!existsSync(resolve(root, 'api/server/socialLogins.js')));
  assert.ok(!text('api/strategies/index.js').includes('facebookStrategy'));
  assert.ok(!text('client/index.html').includes('rum/bootstrap-entry'));
  assert.ok(!text('client/src/routes/index.tsx').includes('WithRum'));
  assert.ok(text('client/index.html').includes('__lcRecoverStaleAssets'));
});

test('shipped translation resources match the language picker', () => {
  assert.ok(text('client/src/locales/i18n.ts').includes("['en', 'zh-Hans', 'zh-Hant'] as const"));
  for (const locale of ['en', 'zh-Hans', 'zh-Hant']) {
    assert.ok(existsSync(resolve(root, `client/src/locales/${locale}/translation.json`)));
  }
  assert.ok(!existsSync(resolve(root, 'client/src/locales/ja/translation.json')));
  assert.ok(!text('client/src/components/Appearance/Selectors.tsx').includes("value: 'ja-JP'"));
});


test('conversation permissions are loaded before any update and keyed by conversation', () => {
  const permissions = text('client/src/components/Chat/Input/LsmChatPermissions.tsx');
  assert.ok(permissions.includes("['lsm', 'chat-permissions', conversationId]"));
  assert.ok(permissions.includes('!query.data || query.isFetching || mutation.isLoading'));
  assert.ok(permissions.includes('if (!available || disabled || !query.data) return'));
  assert.ok(permissions.includes('client.setQueryData(preferenceKey(requestedId), saved)'));
});
