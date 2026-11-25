import { fireEvent, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { FormProvider, useForm, useWatch } from 'react-hook-form';
import { request } from 'librechat-data-provider';
import LsmExternalMcpServers from './LsmExternalMcpServers';

jest.mock('librechat-data-provider', () => ({ request: { get: jest.fn() } }));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));

function Form({ legacy = false }: { legacy?: boolean }) {
  const methods = useForm<{ mcp_servers?: string[] | null }>({
    defaultValues: { mcp_servers: legacy ? undefined : null },
  });
  const value = useWatch({ control: methods.control, name: 'mcp_servers' });
  return (
    <FormProvider {...methods}>
      <LsmExternalMcpServers />
      <output data-testid="policy">{JSON.stringify(value)}</output>
    </FormProvider>
  );
}

test('server toggles persist an agent allowlist and never enable globally disabled servers', async () => {
  (request.get as jest.Mock).mockResolvedValue({
    servers: [
      { name: 'snowluma', enabled: true, transport: 'stdio', tool_count: 10 },
      { name: 'other', enabled: true, transport: 'stdio', tool_count: 2 },
      { name: 'disabled', enabled: false, transport: 'stdio', tool_count: 1 },
    ],
  });
  const query = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={query}><Form /></QueryClientProvider>);
  const first = await screen.findByRole('checkbox', { name: 'snowluma' });
  const other = screen.getByRole('checkbox', { name: 'other' });
  const disabled = screen.getByRole('checkbox', { name: 'disabled' });
  expect(first).toBeChecked();
  expect(disabled).toBeDisabled();
  fireEvent.click(first);
  expect(screen.getByTestId('policy')).toHaveTextContent('["other"]');
  fireEvent.click(other);
  expect(screen.getByTestId('policy')).toHaveTextContent('[]');
  fireEvent.click(first);
  expect(screen.getByTestId('policy')).toHaveTextContent('["snowluma"]');
  fireEvent.click(screen.getByText('com_lsm_external_mcp_inherit'));
  expect(screen.getByTestId('policy')).toHaveTextContent('null');
  expect(other).toBeChecked();
});

test('legacy agents can explicitly allow all servers without selecting a subset first', async () => {
  (request.get as jest.Mock).mockResolvedValue({
    servers: [{ name: 'snowluma', enabled: true, transport: 'stdio', tool_count: 10 }],
  });
  const query = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={query}><Form legacy /></QueryClientProvider>);
  await screen.findByRole('checkbox', { name: 'snowluma' });
  fireEvent.click(screen.getByText('com_lsm_external_mcp_inherit'));
  expect(screen.getByTestId('policy')).toHaveTextContent('null');
});
