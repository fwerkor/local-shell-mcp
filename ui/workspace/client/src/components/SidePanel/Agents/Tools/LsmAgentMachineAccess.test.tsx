import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { FormProvider, useForm, useFormContext } from 'react-hook-form';
import { request } from 'librechat-data-provider';
import LsmAgentMachineAccess from './LsmAgentMachineAccess';

jest.mock('librechat-data-provider', () => ({ request: { get: jest.fn() } }));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));

function Form({ legacy }: { legacy: boolean }) {
  const methods = useForm({
    defaultValues: { machine_permissions: legacy ? undefined : {}, tools: ['run_shell'] },
  });
  return (
    <FormProvider {...methods}>
      <LsmAgentMachineAccess />
      <Value />
    </FormProvider>
  );
}

function Value() {
  const { watch } = useFormContext();
  return <output data-testid="policy">{JSON.stringify(watch('machine_permissions'))}</output>;
}

function mount(legacy: boolean) {
  const query = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={query}><Form legacy={legacy} /></QueryClientProvider>);
}

beforeEach(() => {
  (request.get as jest.Mock).mockResolvedValue({ machines: [{ name: 'local', status: 'online' }] });
});

test('legacy tool grants are visible and cannot silently become machine grants', async () => {
  mount(true);
  expect(await screen.findByText('com_lsm_agent_machine_legacy')).toBeInTheDocument();
  expect(screen.getByLabelText('local machine access')).toBeDisabled();
  fireEvent.click(screen.getByText('com_lsm_agent_machine_revoke'));
  await waitFor(() => expect(screen.getByTestId('policy')).toHaveTextContent('{"local":"none"}'));
  expect(screen.getByLabelText('local machine access')).not.toBeDisabled();
});

test('new agents use the fully allowed machine default', async () => {
  mount(false);
  const picker = await screen.findByLabelText('local machine access');
  expect(picker).toHaveValue('write');
  expect(screen.queryByText('com_lsm_agent_machine_legacy')).not.toBeInTheDocument();
});

test('local is present and first even if an older server omits it', async () => {
  (request.get as jest.Mock).mockResolvedValue({ machines: [{ name: 'aia1', status: 'online' }] });
  mount(false);
  await screen.findByLabelText('aia1 machine access');
  const pickers = screen.getAllByRole('combobox');
  expect(pickers[0]).toHaveAccessibleName('local machine access');
  fireEvent.change(pickers[0], { target: { value: 'none' } });
  expect(screen.getByTestId('policy')).toHaveTextContent('{"local":"none"}');
});
