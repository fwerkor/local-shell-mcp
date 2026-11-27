import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { request } from 'librechat-data-provider';
import useLsmChatFeatures from '~/hooks/Plugins/useLsmChatFeatures';

jest.mock('librechat-data-provider', () => ({
  request: { get: jest.fn(), put: jest.fn() },
}));

const get = request.get as jest.Mock;
const put = request.put as jest.Mock;

beforeEach(() => {
  jest.clearAllMocks();
  const preferences = { web: true, mcp: true, memory: true, mcpServers: null };
  get.mockImplementation((url: string) => {
    if (url === '/api/lsm/mcp/servers') {
      return Promise.resolve({
        servers: [
          { name: 'allowed', enabled: true, tool_count: 3 },
          { name: 'blocked', enabled: true, tool_count: 1 },
        ],
      });
    }
    if (url === '/api/lsm/feature-defaults' || url === '/api/lsm/preferences/chat-123') {
      return Promise.resolve({ ...preferences });
    }
    return Promise.reject(new Error(`Unexpected request: ${url}`));
  });
  put.mockImplementation((_url, change) => {
    Object.assign(preferences, change);
    return Promise.resolve({ ...preferences });
  });
});

function FeatureControls({ conversationId }: { conversationId: string }) {
  const { current, registered, selected, canEdit, toggle, toggleServer, inheritServers } =
    useLsmChatFeatures(conversationId);
  return (
    <>
      <button disabled={!canEdit} onClick={inheritServers}>
        Allow all servers
      </button>
      <button disabled={!canEdit} onClick={() => toggle('web', !current?.web)}>
        Web search
      </button>
      <button disabled={!canEdit} onClick={() => toggle('memory', !current?.memory)}>
        Memory
      </button>
      {registered.map((server) => (
        <button
          key={server.name}
          disabled={!canEdit || !server.enabled}
          onClick={() =>
            toggleServer(server.name, !(selected == null || selected.includes(server.name)))
          }
        >
          MCP server {server.name}
        </button>
      ))}
    </>
  );
}

function mount(conversationId: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <FeatureControls conversationId={conversationId} />
    </QueryClientProvider>,
  );
}

test('selects one MCP server without globally disabling registered services', async () => {
  mount('chat-123');
  const blocked = await screen.findByRole('button', { name: 'MCP server blocked' });
  await waitFor(() => expect(blocked).not.toBeDisabled());
  fireEvent.click(blocked);
  await waitFor(() =>
    expect(put).toHaveBeenCalledWith('/api/lsm/preferences/chat-123', {
      mcp: true,
      mcpServers: ['allowed'],
    }),
  );
});

test('offers new-chat defaults without trying to save a nonexistent conversation', async () => {
  mount('new');
  const toggle = await screen.findByRole('button', { name: 'Allow all servers' });
  await waitFor(() => expect(toggle).not.toBeDisabled());
  fireEvent.click(toggle);
  await waitFor(() =>
    expect(put).toHaveBeenCalledWith('/api/lsm/feature-defaults', { mcp: true, mcpServers: null }),
  );
});

test.each(['new', 'new_conversation'])('saves web and memory defaults for %s', async (id) => {
  mount(id);
  const web = screen.getByRole('button', { name: 'Web search' });
  await waitFor(() => expect(web).not.toBeDisabled());
  fireEvent.click(web);
  await waitFor(() =>
    expect(put).toHaveBeenCalledWith('/api/lsm/feature-defaults', { web: false }),
  );
  const memory = screen.getByRole('button', { name: 'Memory' });
  await waitFor(() => expect(memory).not.toBeDisabled());
  fireEvent.click(memory);
  await waitFor(() =>
    expect(put).toHaveBeenCalledWith('/api/lsm/feature-defaults', { memory: false }),
  );
});

test('legacy MCP-off settings can enable exactly one server without granting the rest', async () => {
  const preferences = { web: true, mcp: false, memory: true, mcpServers: null };
  get.mockImplementation((url: string) =>
    Promise.resolve(
      url.includes('/mcp/servers')
        ? {
            servers: [
              { name: 'allowed', enabled: true, tool_count: 1 },
              { name: 'blocked', enabled: true, tool_count: 1 },
            ],
          }
        : preferences,
    ),
  );
  put.mockImplementation((_url, change) => Promise.resolve(Object.assign(preferences, change)));
  mount('chat-123');
  const allowed = await screen.findByRole('button', { name: 'MCP server allowed' });
  await waitFor(() => expect(allowed).not.toBeDisabled());
  fireEvent.click(allowed);
  await waitFor(() =>
    expect(put).toHaveBeenCalledWith('/api/lsm/preferences/chat-123', {
      mcp: true,
      mcpServers: ['allowed'],
    }),
  );
  await waitFor(() => expect(allowed).not.toBeDisabled());
  fireEvent.click(allowed);
  await waitFor(() =>
    expect(put).toHaveBeenLastCalledWith('/api/lsm/preferences/chat-123', {
      mcp: false,
      mcpServers: [],
    }),
  );
});
