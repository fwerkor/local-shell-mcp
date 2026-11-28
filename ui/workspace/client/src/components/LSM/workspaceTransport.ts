export type WorkspaceConnection = { ui_path: string; auth_mode: string };

export function workspaceSocket(connection: WorkspaceConnection, token: string | undefined,
  channel: 'shell' | 'desktop', parameters: Record<string, string>) {
  const url = new URL(connection.ui_path.replace(/\/$/, '') + '/ws/' + channel, window.location.origin);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  for (const [key, value] of Object.entries(parameters)) url.searchParams.set(key, value);
  const protocols = ['lsm-ui'];
  if (connection.auth_mode !== 'none' && token) {
    const bytes = new TextEncoder().encode(token);
    protocols.push('bearer.' + btoa(Array.from(bytes, b => String.fromCharCode(b)).join(''))
      .replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, ''));
  }
  return new WebSocket(url, protocols);
}
