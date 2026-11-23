import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { request } from 'librechat-data-provider';
import LsmChatPermissions from './LsmChatPermissions';

jest.mock('librechat-data-provider', () => ({
  request: { get: jest.fn(), put: jest.fn() },
}));

const get = request.get as jest.Mock;
const put = request.put as jest.Mock;

function mount(conversationId: string, projectId?: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <LsmChatPermissions conversationId={conversationId} projectId={projectId} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  get.mockReset();
  put.mockReset();
  put.mockImplementation((_url: string, payload: unknown) => Promise.resolve(payload));
  get.mockImplementation((url: string) => {
    if (url === '/api/lsm/permissions/machines') {
      return Promise.resolve({ machines: [
        { name: 'local', status: 'online' }, { name: 'worker1', status: 'offline' },
      ] });
    }
    if (url === '/api/lsm/permissions/defaults') {
      return Promise.resolve({
        machines: { local: 'read', worker1: 'none' },
        effective: { local: 'read', worker1: 'none' },
      });
    }
    if (url === '/api/lsm/permissions/projects/project-1') {
      return Promise.resolve({
        machines: { worker1: 'write' },
        effective: { local: 'read', worker1: 'write' },
      });
    }
    if (url === '/api/projects') return Promise.resolve({ projects: [{ id: 'project-1', name: 'Project A' }] });
    if (url === '/api/lsm/preferences/chat-1') {
      return Promise.resolve({
        machines: { local: 'write' }, effective: { local: 'write', worker1: 'write' },
        projectId: 'project-1', web: true, mcp: false, memory: true, lsm: true,
      });
    }
    return Promise.reject(new Error(`Unexpected request: ${url}`));
  });
});

afterEach(() => {
  document.documentElement.classList.remove('dark');
});

describe.each(['light', 'dark'])('%s theme', (theme) => {
  it('uses a compact accessible popup and visually distinct machine choices', async () => {
    document.documentElement.classList.toggle('dark', theme === 'dark');
    mount('new');
    const trigger = screen.getByRole('button', { name: '工具权限' });
    expect(trigger).toHaveClass('text-text-secondary');
    fireEvent.click(trigger);

    const dialog = screen.getByRole('dialog', { name: '工具权限' });
    expect(dialog.parentElement).toBe(document.body);
    expect(dialog).toHaveClass('lsm-permissions-dialog', 'bg-surface-primary', 'text-text-primary');
    expect(screen.getByRole('button', { name: '实例默认' })).toHaveAttribute('aria-pressed', 'true');

    const read = await screen.findByRole('button', { name: 'local 只读' });
    await waitFor(() => expect(read).not.toBeDisabled());
    expect(read).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText('本机')).toHaveClass('text-text-secondary');
    fireEvent.click(screen.getByRole('button', { name: 'local 读写' }));
    await waitFor(() => expect(put).toHaveBeenCalledWith('/api/lsm/permissions/defaults', {
      machines: { local: 'write', worker1: 'none' },
    }));

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});

it('opens on the current project defaults when starting a project chat', async () => {
  mount('new', 'project-1');
  fireEvent.click(screen.getByRole('button', { name: '工具权限' }));
  expect(screen.getByRole('button', { name: '项目默认' })).toHaveAttribute('aria-pressed', 'true');
  await screen.findByRole('button', { name: 'worker1 读写' });
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'worker1 读写' })).toHaveAttribute('aria-pressed', 'true'),
  );
  expect(screen.getByText('继承 · 只读')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'worker1 恢复继承' }));
  await waitFor(() => expect(put).toHaveBeenCalledWith(
    '/api/lsm/permissions/projects/project-1', { machines: {} },
  ));
});

it('shows inherited machine access in a saved chat and leaves token scopes untouched', async () => {
  mount('chat-1');
  fireEvent.click(screen.getByRole('button', { name: '工具权限' }));
  expect(screen.getByRole('button', { name: '当前会话' })).toHaveAttribute('aria-pressed', 'true');
  await waitFor(() => expect(screen.getByRole('button', { name: 'worker1 读写' }))
    .toHaveAttribute('aria-pressed', 'true'));
  expect(screen.getByText('继承 · 读写')).toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: 'local 恢复继承' }));
  await waitFor(() => expect(put).toHaveBeenCalledWith('/api/lsm/preferences/chat-1', {
    machines: {}, web: true, mcp: false, memory: true,
  }));
  expect(put.mock.calls[0][1]).not.toHaveProperty('scopes');
  expect(put.mock.calls[0][1]).not.toHaveProperty('token');
});
