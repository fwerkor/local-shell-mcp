import { fireEvent, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { FormProvider, useForm } from 'react-hook-form';
import { request } from 'librechat-data-provider';
import type { AgentForm } from '~/common';
import LsmExternalMcpServers, { useSelectedExternalMcpServers } from './LsmExternalMcpServers';
import {
  ExternalMcpSummary,
  MachineAccessSummary,
  summarizeMachineAccess,
  useMachineAccessSummary,
} from './LsmToolSummary';

jest.mock('librechat-data-provider', () => ({ request: { get: jest.fn() } }));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));

const manage = jest.fn();

function Summary() {
  const servers = useSelectedExternalMcpServers();
  const machines = useMachineAccessSummary();
  return (
    <ul>
      {servers.map((server) => (
        <ExternalMcpSummary key={server.name} server={server} onManage={manage} />
      ))}
      {machines && <MachineAccessSummary summary={machines} onManage={manage} />}
    </ul>
  );
}

function Form() {
  const methods = useForm<AgentForm>({
    defaultValues: {
      mcp_servers: null,
      machine_default_permission: 'none',
      machine_permissions: {},
    },
  });
  return (
    <FormProvider {...methods}>
      <Summary />
      <LsmExternalMcpServers />
      <button
        type="button"
        onClick={() => methods.setValue('machine_permissions', { local: 'read' })}
      >
        grant
      </button>
      <button type="button" onClick={() => methods.setValue('machine_permissions', {})}>
        revoke
      </button>
    </FormProvider>
  );
}

test('machine summary hides denied and legacy policies, and counts only overrides', () => {
  expect(summarizeMachineAccess(undefined, undefined)).toBeNull();
  expect(summarizeMachineAccess({ local: 'none' }, 'none')).toBeNull();
  expect(summarizeMachineAccess({ local: 'read', a: 'write', b: 'none' }, 'none')).toEqual({
    defaultAccess: 'none',
    overrides: { read: 1, write: 1, none: 0 },
  });
  expect(summarizeMachineAccess({ local: 'none', a: 'write' }, undefined)).toEqual({
    defaultAccess: 'write',
    overrides: { read: 0, write: 0, none: 1 },
  });
});

test('summary follows external MCP and machine policy changes without reopening the editor', async () => {
  (request.get as jest.Mock).mockResolvedValue({
    servers: [
      { name: 'snowluma', enabled: true, transport: 'stdio', tool_count: 10 },
      { name: 'disabled', enabled: false, transport: 'stdio', tool_count: 1 },
    ],
  });
  const query = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={query}>
      <Form />
    </QueryClientProvider>,
  );
  const mcp = await screen.findByRole('button', { name: 'snowluma — com_ui_manage' });
  expect(mcp).toHaveTextContent('MCP · 10');
  expect(
    screen.queryByRole('button', { name: 'disabled — com_ui_manage' }),
  ).not.toBeInTheDocument();
  fireEvent.click(mcp);
  expect(manage).toHaveBeenCalled();
  fireEvent.click(screen.getByRole('checkbox', { name: 'snowluma' }));
  expect(
    screen.queryByRole('button', { name: 'snowluma — com_ui_manage' }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('checkbox', { name: 'snowluma' }));
  expect(screen.getByRole('button', { name: 'snowluma — com_ui_manage' })).toBeInTheDocument();
  const machineName = 'com_lsm_agent_machine_access — com_ui_manage';
  expect(screen.queryByRole('button', { name: machineName })).not.toBeInTheDocument();
  fireEvent.click(screen.getByText('grant'));
  expect(screen.getByRole('button', { name: machineName })).toHaveTextContent(
    '1 com_lsm_agent_machine_read',
  );
  fireEvent.click(screen.getByText('revoke'));
  expect(screen.queryByRole('button', { name: machineName })).not.toBeInTheDocument();
});
