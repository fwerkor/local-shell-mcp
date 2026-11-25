import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { request } from 'librechat-data-provider';
import ApprovalModeSetting, { ApprovalModeSelect } from './ApprovalModeSetting';

jest.mock('librechat-data-provider', () => ({
  request: { get: jest.fn(), put: jest.fn() },
}));
jest.mock('~/hooks/useLocalize', () => ({
  __esModule: true,
  default: () => (key: string) => key,
}));

const get = request.get as jest.Mock;
const put = request.put as jest.Mock;

function mount(conversationId?: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ApprovalModeSetting conversationId={conversationId} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  get.mockReset();
  put.mockReset();
});

it('loads and saves the server default with no inherit option', async () => {
  let mode = 'automatic';
  get.mockImplementation(async () => ({ mode, effective: mode }));
  put.mockImplementation(async (_url, body) => {
    mode = body.mode;
    return { mode, effective: mode };
  });
  mount();
  const select = screen.getByRole('combobox', { name: 'com_ui_tool_approval_mode' });
  await waitFor(() => expect(select).toBeEnabled());
  expect(select).toHaveValue('automatic');
  expect(screen.queryByRole('option', { name: 'com_ui_tool_approval_inherit' })).not.toBeInTheDocument();
  fireEvent.change(select, { target: { value: 'dangerous' } });
  await waitFor(() => expect(put).toHaveBeenCalledWith('/api/lsm/approval', { mode: 'dangerous' }));
  await waitFor(() => expect(select).toHaveValue('dangerous'));
});

it('supports explicit conversation overrides and restoring inheritance', async () => {
  let mode = 'all';
  get.mockImplementation(async () => ({ mode, effective: mode === 'inherit' ? 'dangerous' : mode }));
  put.mockImplementation(async (_url, body) => {
    mode = body.mode;
    return { mode, effective: 'dangerous' };
  });
  mount('chat-123');
  const select = screen.getByRole('combobox');
  await waitFor(() => expect(select).toHaveValue('all'));
  fireEvent.change(select, { target: { value: 'inherit' } });
  await waitFor(() => expect(put).toHaveBeenCalledWith('/api/lsm/approval/chat-123', { mode: 'inherit' }));
  await waitFor(() => expect(select).toHaveValue('inherit'));
  expect(screen.getByRole('option', { name: 'com_ui_tool_approval_inherit (com_ui_tool_approval_dangerous)' })).toBeInTheDocument();
});

it('supports form-owned Agent overrides', () => {
  const onChange = jest.fn();
  render(<ApprovalModeSelect value="inherit" inherit onChange={onChange} />);
  fireEvent.change(screen.getByRole('combobox'), { target: { value: 'all' } });
  expect(onChange).toHaveBeenCalledWith('all');
});

it('does not show an unsaved approval mode on failure', async () => {
  get.mockResolvedValue({ mode: 'automatic', effective: 'automatic' });
  put.mockRejectedValue(new Error('Network failed'));
  mount();
  const select = screen.getByRole('combobox');
  await waitFor(() => expect(select).toBeEnabled());
  fireEvent.change(select, { target: { value: 'all' } });
  await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
  expect(select).toHaveValue('automatic');
});
