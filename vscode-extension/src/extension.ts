import * as cp from 'child_process';
import * as crypto from 'crypto';
import * as http from 'http';
import * as https from 'https';
import * as vscode from 'vscode';

let output: vscode.OutputChannel;
let serverProcess: cp.ChildProcessWithoutNullStreams | undefined;

function stopProcessTree(proc: cp.ChildProcessWithoutNullStreams): Promise<void> {
  return new Promise((resolve) => {
    if (proc.exitCode !== null || proc.signalCode !== null) {
      resolve();
      return;
    }
    if (process.platform === 'win32' && proc.pid) {
      cp.execFile('taskkill', ['/PID', String(proc.pid), '/T', '/F'], (error) => {
        if (error) {
          proc.kill();
        }
        resolve();
      });
      return;
    }
    proc.kill();
    resolve();
  });
}

interface ExtensionConfig {
  executablePath: string;
  host: string;
  port: number;
  workspaceRoot: string;
  authMode: 'oauth' | 'none';
  publicBaseUrl: string;
  oauthAdminPin: string;
  allowFullContainer: boolean;
  extraEnv: Record<string, unknown>;
}

function getOutput(): vscode.OutputChannel {
  if (!output) {
    output = vscode.window.createOutputChannel('local-shell-mcp');
  }
  return output;
}

function firstWorkspaceFolder(): string | undefined {
  return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
}

function getConfig(): ExtensionConfig {
  const cfg = vscode.workspace.getConfiguration('local-shell-mcp');
  const workspaceRoot = cfg.get<string>('workspaceRoot')?.trim() || firstWorkspaceFolder() || process.cwd();
  const authMode = cfg.get<'oauth' | 'none'>('authMode', 'oauth');

  return {
    executablePath: cfg.get<string>('executablePath', 'local-shell-mcp').trim() || 'local-shell-mcp',
    host: cfg.get<string>('host', '127.0.0.1').trim() || '127.0.0.1',
    port: cfg.get<number>('port', 8765),
    workspaceRoot,
    authMode,
    publicBaseUrl: normalizeBaseUrl(cfg.get<string>('publicBaseUrl', '')),
    oauthAdminPin: cfg.get<string>('oauthAdminPin', ''),
    allowFullContainer: cfg.get<boolean>('allowFullContainer', false),
    extraEnv: cfg.get<Record<string, unknown>>('extraEnv', {}) ?? {},
  };
}

function normalizeBaseUrl(value: string): string {
  return value.trim().replace(/\/+$/, '');
}

function localBaseUrl(config: ExtensionConfig): string {
  return `http://${config.host}:${config.port}`;
}

function mcpBaseUrl(config: ExtensionConfig): string {
  return config.publicBaseUrl || localBaseUrl(config);
}

function mcpUrl(config: ExtensionConfig): string {
  return `${mcpBaseUrl(config)}/mcp`;
}

async function getOrCreateJwtSecret(context: vscode.ExtensionContext): Promise<string> {
  const key = 'local-shell-mcp.oauthJwtSecret';
  const existing = context.globalState.get<string>(key);
  if (existing) {
    return existing;
  }
  const generated = crypto.randomBytes(32).toString('hex');
  await context.globalState.update(key, generated);
  return generated;
}

function stringifyExtraEnv(extraEnv: Record<string, unknown>): Record<string, string> {
  const env: Record<string, string> = {};
  for (const [key, value] of Object.entries(extraEnv)) {
    if (!key || value === undefined || value === null) {
      continue;
    }
    env[key] = String(value);
  }
  return env;
}

async function buildEnvironment(context: vscode.ExtensionContext, config: ExtensionConfig): Promise<NodeJS.ProcessEnv> {
  const env: NodeJS.ProcessEnv = {
    ...process.env,
    ...stringifyExtraEnv(config.extraEnv),
    LOCAL_SHELL_MCP_HOST: config.host,
    LOCAL_SHELL_MCP_PORT: String(config.port),
    LOCAL_SHELL_MCP_MODE: 'mcp',
    LOCAL_SHELL_MCP_WORKSPACE_ROOT: config.workspaceRoot,
    LOCAL_SHELL_MCP_AUTH_MODE: config.authMode,
    LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER: config.allowFullContainer ? 'true' : 'false',
  };

  if (config.publicBaseUrl) {
    env.LOCAL_SHELL_MCP_PUBLIC_BASE_URL = config.publicBaseUrl;
  }
  if (config.oauthAdminPin) {
    env.LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN = config.oauthAdminPin;
  }
  if (config.authMode === 'oauth' && !env.LOCAL_SHELL_MCP_OAUTH_JWT_SECRET) {
    env.LOCAL_SHELL_MCP_OAUTH_JWT_SECRET = await getOrCreateJwtSecret(context);
  }
  return env;
}

function requestJson(url: string, timeoutMs = 2500): Promise<{ ok: boolean; statusCode: number; body: string }> {
  return new Promise((resolve) => {
    const client = url.startsWith('https:') ? https : http;
    const req = client.get(url, { timeout: timeoutMs }, (res) => {
      const chunks: Buffer[] = [];
      res.on('data', (chunk: Buffer) => chunks.push(chunk));
      res.on('end', () => {
        const statusCode = res.statusCode ?? 0;
        resolve({
          ok: statusCode >= 200 && statusCode < 300,
          statusCode,
          body: Buffer.concat(chunks).toString('utf8'),
        });
      });
    });
    req.on('timeout', () => {
      req.destroy();
      resolve({ ok: false, statusCode: 0, body: 'timeout' });
    });
    req.on('error', (error: Error) => {
      resolve({ ok: false, statusCode: 0, body: error.message });
    });
  });
}

async function waitForHealth(config: ExtensionConfig): Promise<boolean> {
  const healthUrl = `${localBaseUrl(config)}/healthz`;
  for (let i = 0; i < 20; i += 1) {
    const result = await requestJson(healthUrl, 1000);
    if (result.ok) {
      return true;
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  return false;
}

async function startServer(context: vscode.ExtensionContext): Promise<void> {
  if (serverProcess) {
    vscode.window.showInformationMessage('local-shell-mcp is already running from this VS Code window.');
    return;
  }

  const config = getConfig();
  const channel = getOutput();
  channel.show(true);
  channel.appendLine(`Starting local-shell-mcp for workspace: ${config.workspaceRoot}`);
  channel.appendLine(`MCP URL: ${mcpUrl(config)}`);

  const env = await buildEnvironment(context, config);
  const child = cp.spawn(config.executablePath, ['--mode', 'mcp'], {
    cwd: config.workspaceRoot,
    env,
    shell: process.platform === 'win32',
  });

  serverProcess = child;
  child.stdout.on('data', (data: Buffer) => channel.append(data.toString()));
  child.stderr.on('data', (data: Buffer) => channel.append(data.toString()));
  child.on('error', (error: Error) => {
    serverProcess = undefined;
    channel.appendLine(`Failed to start local-shell-mcp: ${error.message}`);
    vscode.window.showErrorMessage(`Failed to start local-shell-mcp: ${error.message}`);
  });
  child.on('exit', (code: number | null, signal: NodeJS.Signals | null) => {
    serverProcess = undefined;
    channel.appendLine(`local-shell-mcp exited with code=${code ?? 'null'} signal=${signal ?? 'null'}`);
  });

  const healthy = await waitForHealth(config);
  if (healthy) {
    vscode.window.showInformationMessage(`local-shell-mcp is running at ${mcpUrl(config)}`);
  } else {
    vscode.window.showWarningMessage('local-shell-mcp process started, but /healthz did not respond yet. See the local-shell-mcp output channel.');
  }
}

async function stopServer(): Promise<void> {
  if (!serverProcess) {
    vscode.window.showInformationMessage('No local-shell-mcp process is running from this VS Code window.');
    return;
  }
  const proc = serverProcess;
  serverProcess = undefined;
  await stopProcessTree(proc);
  vscode.window.showInformationMessage('local-shell-mcp stop requested.');
}

async function restartServer(context: vscode.ExtensionContext): Promise<void> {
  if (serverProcess) {
    await stopServer();
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  await startServer(context);
}

async function showStatus(): Promise<void> {
  const config = getConfig();
  const healthUrl = `${localBaseUrl(config)}/healthz`;
  const readyUrl = `${localBaseUrl(config)}/readyz`;
  const health = await requestJson(healthUrl);
  const ready = await requestJson(readyUrl);
  const owned = serverProcess ? 'yes' : 'no';

  if (health.ok) {
    vscode.window.showInformationMessage(`local-shell-mcp is reachable. MCP URL: ${mcpUrl(config)}. Started by this window: ${owned}.`);
  } else {
    vscode.window.showWarningMessage(`local-shell-mcp is not reachable at ${healthUrl}: ${health.body}. Started by this window: ${owned}.`);
  }

  const channel = getOutput();
  channel.appendLine('--- Status check ---');
  channel.appendLine(`healthz ${health.statusCode}: ${health.body}`);
  channel.appendLine(`readyz ${ready.statusCode}: ${ready.body}`);
}

async function copyMcpUrl(): Promise<void> {
  const url = mcpUrl(getConfig());
  await vscode.env.clipboard.writeText(url);
  vscode.window.showInformationMessage(`Copied MCP URL: ${url}`);
}

async function copySetupPrompt(): Promise<void> {
  const config = getConfig();
  const prompt = [
    'Use local-shell-mcp as the execution environment for this VS Code workspace.',
    '',
    `MCP URL: ${mcpUrl(config)}`,
    `Workspace root: ${config.workspaceRoot}`,
    '',
    'When inspecting, editing, testing, committing, pushing, or releasing code, use the local-shell-mcp tools instead of asking me to run shell commands manually.',
    'Keep changes scoped to this workspace unless I explicitly request broader access.',
    'Before pushing, run the relevant tests and a secret scan when available.',
  ].join('\n');
  await vscode.env.clipboard.writeText(prompt);
  vscode.window.showInformationMessage('Copied local-shell-mcp ChatGPT setup prompt.');
}

async function openGuide(context: vscode.ExtensionContext): Promise<void> {
  const guideUri = vscode.Uri.joinPath(context.extensionUri, 'GUIDE.md');
  const document = await vscode.workspace.openTextDocument(guideUri);
  await vscode.window.showTextDocument(document, { preview: true });
}

export function activate(context: vscode.ExtensionContext): void {
  output = vscode.window.createOutputChannel('local-shell-mcp');

  context.subscriptions.push(
    output,
    vscode.commands.registerCommand('local-shell-mcp.startServer', () => startServer(context)),
    vscode.commands.registerCommand('local-shell-mcp.stopServer', stopServer),
    vscode.commands.registerCommand('local-shell-mcp.restartServer', () => restartServer(context)),
    vscode.commands.registerCommand('local-shell-mcp.showStatus', showStatus),
    vscode.commands.registerCommand('local-shell-mcp.copyMcpUrl', copyMcpUrl),
    vscode.commands.registerCommand('local-shell-mcp.copySetupPrompt', copySetupPrompt),
    vscode.commands.registerCommand('local-shell-mcp.openGuide', () => openGuide(context)),
  );
}

export async function deactivate(): Promise<void> {
  const proc = serverProcess;
  serverProcess = undefined;
  if (proc) {
    await stopProcessTree(proc);
  }
}
