const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const Module = require('node:module');
const test = require('node:test');

const originalLoad = Module._load;
const fakeVscode = {
  window: {
    createOutputChannel: () => ({ append() {}, appendLine() {}, show() {}, dispose() {} }),
    showInformationMessage: async () => undefined,
    showWarningMessage: async () => undefined,
    showErrorMessage: async () => undefined,
    showTextDocument: async () => undefined,
  },
  workspace: {
    workspaceFolders: undefined,
    getConfiguration: () => ({ get: (_key, defaultValue) => defaultValue }),
    openTextDocument: async () => ({}),
  },
  commands: { registerCommand: () => ({ dispose() {} }) },
  env: { clipboard: { writeText: async () => undefined } },
  Uri: { joinPath: (...parts) => parts.join('/') },
};
Module._load = function(request, parent, isMain) {
  if (request === 'vscode') return fakeVscode;
  return originalLoad.call(this, request, parent, isMain);
};
const extension = require('../out/extension.js');
Module._load = originalLoad;

class FakeChild extends EventEmitter {
  constructor({ pid = 123, exitCode = null, signalCode = null } = {}) {
    super();
    this.pid = pid;
    this.exitCode = exitCode;
    this.signalCode = signalCode;
    this.killCalls = [];
  }
  kill(signal) {
    this.killCalls.push(signal);
    return true;
  }
}

test('URL and environment helpers normalize user configuration', () => {
  const config = {
    executablePath: 'local-shell-mcp', host: '127.0.0.1', port: 9000,
    workspaceRoot: '/workspace', authMode: 'oauth', publicBaseUrl: '',
    oauthAdminPin: '', allowFullContainer: false, extraEnv: {},
  };
  assert.equal(extension.normalizeBaseUrl(' https://example.test/// '), 'https://example.test');
  assert.equal(extension.localBaseUrl(config), 'http://127.0.0.1:9000');
  assert.equal(extension.mcpBaseUrl(config), 'http://127.0.0.1:9000');
  assert.equal(extension.mcpUrl(config), 'http://127.0.0.1:9000/mcp');
  config.publicBaseUrl = 'https://public.test';
  assert.equal(extension.mcpUrl(config), 'https://public.test/mcp');
  assert.deepEqual(extension.stringifyExtraEnv({ A: 1, B: false, C: null, D: undefined, '': 'x' }), { A: '1', B: 'false' });
});

test('waitForExit handles already-exited, emitted, and timed-out processes', async () => {
  assert.equal(await extension.waitForExit(new FakeChild({ exitCode: 0 }), 1), true);
  const emitted = new FakeChild();
  setImmediate(() => emitted.emit('exit', 0, null));
  assert.equal(await extension.waitForExit(emitted, 100), true);
  assert.equal(await extension.waitForExit(new FakeChild(), 1), false);
});

test('signalPosixProcessTree uses process group and falls back safely', () => {
  const child = new FakeChild({ pid: 42 });
  const calls = [];
  extension.signalPosixProcessTree(child, 'SIGTERM', (pid, signal) => {
    calls.push([pid, signal]);
    return true;
  });
  assert.deepEqual(calls, [[-42, 'SIGTERM']]);
  extension.signalPosixProcessTree(child, 'SIGKILL', () => { throw new Error('no group'); });
  assert.deepEqual(child.killCalls, ['SIGKILL']);
  const noPid = new FakeChild({ pid: null });
  extension.signalPosixProcessTree(noPid, 'SIGTERM', () => true);
  assert.deepEqual(noPid.killCalls, ['SIGTERM']);
});

test('POSIX stop escalates from SIGTERM to SIGKILL only when needed', async () => {
  const child = new FakeChild();
  const signals = [];
  const waits = [];
  await extension.stopProcessTree(
    child,
    'linux',
    () => { throw new Error('unused'); },
    async (_proc, timeout) => { waits.push(timeout); return waits.length === 2; },
    (_proc, signal) => signals.push(signal),
  );
  assert.deepEqual(signals, ['SIGTERM', 'SIGKILL']);
  assert.deepEqual(waits, [2000, 1000]);

  const graceful = new FakeChild();
  const gracefulSignals = [];
  await extension.stopProcessTree(
    graceful,
    'darwin',
    () => { throw new Error('unused'); },
    async () => true,
    (_proc, signal) => gracefulSignals.push(signal),
  );
  assert.deepEqual(gracefulSignals, ['SIGTERM']);
});

test('Windows stop uses taskkill and falls back to child.kill on error', async () => {
  const child = new FakeChild({ pid: 77 });
  const waits = [];
  let invocation;
  await extension.stopProcessTree(
    child,
    'win32',
    ((file, args, callback) => {
      invocation = [file, args];
      callback(new Error('taskkill unavailable'), '', '');
      return {};
    }),
    async (_proc, timeout) => { waits.push(timeout); return true; },
  );
  assert.deepEqual(invocation, ['taskkill', ['/PID', '77', '/T', '/F']]);
  assert.deepEqual(child.killCalls, [undefined]);
  assert.deepEqual(waits, [2000]);
});

test('already exited process is a no-op', async () => {
  const child = new FakeChild({ exitCode: 0 });
  let invoked = false;
  await extension.stopProcessTree(child, 'linux', () => { invoked = true; }, async () => { invoked = true; return true; });
  assert.equal(invoked, false);
});
