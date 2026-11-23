import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { request } from 'librechat-data-provider';
import LsmChatPermissions from './LsmChatPermissions';

jest.mock('librechat-data-provider', () => ({
  request: { get: jest.fn(), put: jest.fn() },
}));

const get = request.get as jest.Mock;

beforeEach(() => {
  get.mockImplementation((url: string) => {
    if (url === '/api/lsm/permissions/machines') {
      return Promise.resolve({ machines: [{ name: 'local', status: 'online' }] });
    }
    if (url === '/api/lsm/permissions/defaults') {
      return Promise.resolve({ machines: { local: 'none' }, effective: { local: 'none' } });
    }
    if (url === '/api/projects') return Promise.resolve({ projects: [] });
    return Promise.reject(new Error(`Unexpected request: ${url}`));
  });
});

afterEach(() => {
  document.documentElement.classList.remove('dark');
});

describe.each(['light', 'dark'])('%s theme', (theme) => {
  it('keeps the portaled permissions panel and native access controls legible', async () => {
    document.documentElement.classList.toggle('dark', theme === 'dark');
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <LsmChatPermissions conversationId="new" />
      </QueryClientProvider>,
    );

    const trigger = screen.getByRole('button', { name: 'Permissions' });
    expect(trigger).toHaveClass('text-text-primary');
    fireEvent.click(trigger);

    const dialog = screen.getByRole('dialog', { name: 'Machine and conversation permissions' });
    expect(dialog.parentElement).toBe(document.body);
    expect(dialog).toHaveClass('lsm-permissions-dialog', 'bg-surface-primary', 'text-text-primary');
    expect(screen.getByRole('button', { name: 'Global' })).toHaveAttribute('aria-pressed', 'true');

    const select = await screen.findByRole('combobox', { name: 'local machine access' });
    await waitFor(() => expect(select).not.toBeDisabled());
    expect(select).toHaveClass('bg-surface-primary', 'text-text-primary');
    expect(select).toHaveValue('none');
    expect(screen.getByText('(controller host)')).toHaveClass('text-text-secondary');
  });
});
