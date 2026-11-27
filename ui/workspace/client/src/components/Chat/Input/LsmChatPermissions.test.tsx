import { useState } from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { request } from 'librechat-data-provider';
import LsmChatPermissions, { useDraftMachinePermissions } from './LsmChatPermissions';
import { changeLanguageSafely } from '~/locales/i18n';

jest.mock('librechat-data-provider', () => ({
  request: { get: jest.fn(), put: jest.fn() },
}));

const get = request.get as jest.Mock;
const put = request.put as jest.Mock;

function Harness({ conversationId, projectId }: { conversationId: string; projectId?: string }) {
  const [open, setOpen] = useState(false);
  const draft = useDraftMachinePermissions(conversationId, projectId);
  return (
    <>
      <button onClick={() => setOpen(!open)}>Manage</button>
      {open && (
        <LsmChatPermissions conversationId={conversationId} projectId={projectId} draft={draft} />
      )}
    </>
  );
}

function mount(conversationId: string, projectId?: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={client}>
      <Harness conversationId={conversationId} projectId={projectId} />
    </QueryClientProvider>,
  );
  return { ...view, client };
}

beforeEach(async () => {
  await changeLanguageSafely('zh-Hans');
  get.mockReset();
  put.mockReset();
  put.mockImplementation((_url: string, payload: unknown) => Promise.resolve(payload));
  get.mockImplementation((url: string) => {
    if (url === '/api/lsm/approval/chat-1') {
      return Promise.resolve({ mode: 'inherit', effective: 'automatic' });
    }
    if (url === '/api/lsm/permissions/machines') {
      return Promise.resolve({
        machines: [
          { name: 'local', status: 'online' },
          { name: 'worker1', status: 'offline' },
        ],
      });
    }
    if (url === '/api/lsm/permissions/defaults') {
      return Promise.resolve({
        machines: {},
        effective: { local: 'write', worker1: 'write' },
      });
    }
    if (url === '/api/lsm/permissions/projects/project-1') {
      return Promise.resolve({
        machines: { worker1: 'write' },
        effective: { local: 'write', worker1: 'write' },
      });
    }
    if (url === '/api/projects')
      return Promise.resolve({ projects: [{ id: 'project-1', name: 'Project A' }] });
    if (url === '/api/lsm/preferences/chat-1') {
      return Promise.resolve({
        machines: { local: 'write' },
        effective: { local: 'write', worker1: 'write' },
        projectId: 'project-1',
        web: true,
        mcp: false,
        memory: true,
        lsm: true,
      });
    }
    return Promise.reject(new Error(`Unexpected request: ${url}`));
  });
});

afterEach(async () => {
  await changeLanguageSafely('en');
  document.documentElement.classList.remove('dark');
});

describe.each(['light', 'dark'])('%s theme', (theme) => {
  it('exposes all scopes and visually distinct machine choices in the shared panel', async () => {
    document.documentElement.classList.toggle('dark', theme === 'dark');
    mount('new');
    fireEvent.click(screen.getByRole('button', { name: 'Manage' }));
    expect(screen.getByRole('region', { name: '工具权限' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '当前会话' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    fireEvent.click(screen.getByRole('button', { name: '全局默认' }));

    const write = await screen.findByRole('button', { name: 'local 读写' });
    await waitFor(() => expect(write).not.toBeDisabled());
    expect(write).toHaveAttribute('aria-pressed', 'true');
    expect(screen.queryByRole('button', { name: 'local 继承' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '全部恢复继承' })).not.toBeInTheDocument();
    expect(screen.getByText('本机')).toHaveClass('text-text-secondary');
    fireEvent.click(screen.getByRole('button', { name: 'local 只读' }));
    await waitFor(() =>
      expect(put).toHaveBeenCalledWith('/api/lsm/permissions/defaults', {
        machines: { local: 'read' },
      }),
    );

    fireEvent.click(screen.getByRole('button', { name: 'Manage' }));
    expect(screen.queryByRole('region', { name: '工具权限' })).not.toBeInTheDocument();
  });
});

it('can edit project defaults independently when starting a project chat', async () => {
  mount('new', 'project-1');
  fireEvent.click(screen.getByRole('button', { name: 'Manage' }));
  expect(screen.getByRole('button', { name: '当前会话' })).toHaveAttribute('aria-pressed', 'true');
  fireEvent.click(screen.getByRole('button', { name: '项目默认' }));
  await screen.findByRole('button', { name: 'worker1 读写' });
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'worker1 读写' })).toHaveAttribute(
      'aria-pressed',
      'true',
    ),
  );
  expect(screen.getByText('继承 · 读写 · 全局默认')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'local 继承' })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'worker1 继承' })).not.toBeDisabled(),
  );
  fireEvent.click(screen.getByRole('button', { name: 'worker1 继承' }));
  await waitFor(() =>
    expect(put).toHaveBeenCalledWith('/api/lsm/permissions/projects/project-1', { machines: {} }),
  );
});

it('shows inherited machine access in a saved chat and leaves token scopes untouched', async () => {
  mount('chat-1');
  fireEvent.click(screen.getByRole('button', { name: 'Manage' }));
  expect(screen.getByRole('button', { name: '当前会话' })).toHaveAttribute('aria-pressed', 'true');
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'worker1 继承' })).toHaveAttribute(
      'aria-pressed',
      'true',
    ),
  );
  await screen.findByText('继承 · 读写 · 项目默认');
  expect(screen.getByRole('button', { name: 'worker1 读写' })).toHaveAttribute(
    'aria-pressed',
    'false',
  );
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'local 继承' })).not.toBeDisabled(),
  );

  fireEvent.click(screen.getByRole('button', { name: 'local 继承' }));
  await waitFor(() =>
    expect(put).toHaveBeenCalledWith('/api/lsm/preferences/chat-1', {
      machines: {},
    }),
  );
  expect(put.mock.calls[0][1]).not.toHaveProperty('scopes');
  expect(put.mock.calls[0][1]).not.toHaveProperty('token');
});

it('renders permissions in the selected non-Chinese language', async () => {
  await changeLanguageSafely('en');
  mount('new');
  fireEvent.click(screen.getByRole('button', { name: 'Manage' }));
  expect(screen.getByRole('button', { name: 'Global defaults' })).toBeInTheDocument();
  expect(await screen.findByRole('button', { name: 'local Read/write' })).toBeInTheDocument();
});

it('keeps new-chat machine overrides local to the draft without changing defaults', async () => {
  const { client } = mount('new', 'project-1');
  fireEvent.click(screen.getByRole('button', { name: 'Manage' }));
  const read = await screen.findByRole('button', { name: 'local 只读' });
  await waitFor(() => expect(read).not.toBeDisabled());
  fireEvent.click(read);
  expect(client.getQueryData(['lsm', 'draft-machine-permissions', 0, 'project-1'])).toEqual({
    local: 'read',
  });
  expect(put).not.toHaveBeenCalled();
  const reset = screen.getByRole('button', { name: 'local 继承' });
  await waitFor(() => expect(reset).not.toBeDisabled());
  fireEvent.click(reset);
  await waitFor(() =>
    expect(client.getQueryData(['lsm', 'draft-machine-permissions', 0, 'project-1'])).toEqual({}),
  );
});

it('preserves draft permissions when the tool dialog closes and reopens', async () => {
  const { client } = mount('new', 'project-1');
  const trigger = screen.getByRole('button', { name: 'Manage' });
  fireEvent.click(trigger);
  const read = await screen.findByRole('button', { name: 'local 只读' });
  await waitFor(() => expect(read).not.toBeDisabled());
  fireEvent.click(read);
  fireEvent.click(trigger);
  expect(client.getQueryData(['lsm', 'draft-machine-permissions', 0, 'project-1'])).toEqual({
    local: 'read',
  });
  fireEvent.click(trigger);
  expect(await screen.findByRole('button', { name: 'local 只读' })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  expect(put).not.toHaveBeenCalled();
});

it('can explicitly choose the same permission as the inherited value and reset every draft override', async () => {
  const { client } = mount('new', 'project-1');
  fireEvent.click(screen.getByRole('button', { name: 'Manage' }));
  const key = ['lsm', 'draft-machine-permissions', 0, 'project-1'];
  const write = await screen.findByRole('button', { name: 'local 读写' });
  await waitFor(() => expect(write).not.toBeDisabled());
  expect(write).toHaveAttribute('aria-pressed', 'false');
  fireEvent.click(write);
  await waitFor(() => expect(write).toHaveAttribute('aria-pressed', 'true'));
  fireEvent.click(screen.getByRole('button', { name: 'worker1 无' }));
  expect(client.getQueryData(key)).toEqual({ local: 'write', worker1: 'none' });
  const reset = screen.getByRole('button', { name: '全部恢复继承' });
  await waitFor(() => expect(reset).not.toBeDisabled());
  fireEvent.click(reset);
  expect(client.getQueryData(key)).toEqual({});
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'local 继承' })).toHaveAttribute(
      'aria-pressed',
      'true',
    ),
  );
  expect(screen.getByRole('button', { name: 'worker1 继承' })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  expect(put).not.toHaveBeenCalled();
});

it('resets all saved overrides in the current scope only', async () => {
  mount('chat-1');
  fireEvent.click(screen.getByRole('button', { name: 'Manage' }));
  const reset = screen.getByRole('button', { name: '全部恢复继承' });
  await waitFor(() => expect(reset).not.toBeDisabled());
  fireEvent.click(reset);
  await waitFor(() =>
    expect(put).toHaveBeenCalledWith('/api/lsm/preferences/chat-1', {
      machines: {},
    }),
  );
  fireEvent.click(screen.getByRole('button', { name: '项目默认' }));
  await waitFor(() => expect(reset).not.toBeDisabled());
  fireEvent.click(reset);
  await waitFor(() =>
    expect(put).toHaveBeenCalledWith('/api/lsm/permissions/projects/project-1', {
      machines: {},
    }),
  );
});
