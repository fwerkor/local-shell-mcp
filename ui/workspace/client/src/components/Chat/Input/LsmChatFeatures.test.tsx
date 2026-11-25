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
  const { current, registered, canEdit, toggle, toggleServer } = useLsmChatFeatures(conversationId);
  return (
    <>
      <button disabled={!canEdit} onClick={() => toggle('mcp', !current?.mcp)}>
        External MCP
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
          disabled={!canEdit || !current?.mcp}
          onClick={() => toggleServer(server.name, false)}
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
    expect(put).toHaveBeenCalledWith('/api/lsm/preferences/chat-123', { mcpServers: ['allowed'] }),
  );
});

test('offers new-chat defaults without trying to save a nonexistent conversation', async () => {
  mount('new');
  const toggle = await screen.findByRole('button', { name: 'External MCP' });
  await waitFor(() => expect(toggle).not.toBeDisabled());
  fireEvent.click(toggle);
  await waitFor(() =>
    expect(put).toHaveBeenCalledWith('/api/lsm/feature-defaults', { mcp: false }),
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
