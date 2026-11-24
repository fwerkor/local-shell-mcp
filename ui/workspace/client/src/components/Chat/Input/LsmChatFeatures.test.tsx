import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { request } from 'librechat-data-provider';
import LsmChatFeatures from './LsmChatFeatures';

jest.mock('librechat-data-provider', () => ({
  request: { get: jest.fn(), put: jest.fn() },
}));

const get = request.get as jest.Mock;
const put = request.put as jest.Mock;

beforeEach(() => {
  get.mockImplementation((url: string) => {
    if (url === '/api/lsm/mcp/servers') {
      return Promise.resolve({ servers: [
        { name: 'allowed', enabled: true, tool_count: 3 },
        { name: 'blocked', enabled: true, tool_count: 1 },
      ] });
    }
    if (url === '/api/lsm/feature-defaults' || url === '/api/lsm/preferences/chat-123') {
      return Promise.resolve({ web: true, mcp: true, memory: true, mcpServers: null });
    }
    return Promise.reject(new Error(`Unexpected request: ${url}`));
  });
  put.mockResolvedValue({});
});

function mount(conversationId: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <LsmChatFeatures conversationId={conversationId} />
    </QueryClientProvider>,
  );
}

test('selects one MCP server without globally disabling registered services', async () => {
  mount('chat-123');
  fireEvent.click(screen.getByRole('button', { name: 'Tools and features' }));
  expect(screen.getByRole('dialog', { name: 'Tools and features' })).toBeInTheDocument();
  const blocked = await screen.findByRole('checkbox', { name: 'MCP server blocked' });
  await waitFor(() => expect(blocked).not.toBeDisabled());
  fireEvent.click(blocked);
  await waitFor(() => expect(put).toHaveBeenCalledWith(
    '/api/lsm/preferences/chat-123', { mcpServers: ['allowed'] },
  ));
});

test('offers new-chat defaults without trying to save a nonexistent conversation', async () => {
  mount('new');
  fireEvent.click(screen.getByRole('button', { name: 'Tools and features' }));
  expect(screen.getByText('Defaults for new conversations')).toBeInTheDocument();
  const toggle = await screen.findByRole('checkbox', { name: 'External MCP' });
  await waitFor(() => expect(toggle).not.toBeDisabled());
  fireEvent.click(toggle);
  await waitFor(() => expect(put).toHaveBeenCalledWith('/api/lsm/feature-defaults', { mcp: false }));
});
